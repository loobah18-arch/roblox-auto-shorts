#!/usr/bin/env python3
"""
Shared LLM client for the Bhaloo Ji engine (Gemini -> Groq -> OpenRouter -> NVIDIA NIM).

Every failure is logged with the provider, model, HTTP status and the start of the
response body, so a dead model or exhausted quota is visible in the Actions log
instead of silently falling through to template text.

Model IDs were checked against the providers' docs/model lists in Nov 2026:
  * Gemini: gemini-2.0-flash is gone; gemini-2.5-flash is deprecated (routes to
    gemini-3.5-flash-lite from 2026-12-01) so it is tried last. The current flash /
    flash-lite models come first, and the key's own ListModels answer decides which of
    them are actually tried.
  * Groq: openai/gpt-oss-120b (free tier, 8K TPM), llama-3.3-70b-versatile (now
    enterprise-only on many keys), plus whatever the key's /models lists.
  * OpenRouter / NVIDIA NIM: picked from their live model lists.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

UA = "bhaloo-ji-engine/2.0"
DEFAULT_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "180"))

GEMINI_PREFERRED = [
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-2.5-flash",  # deprecated: reroutes to 3.5-flash-lite from 2026-12-01, kept last
]
GROQ_VISION_PREFERRED = ["meta-llama/llama-4-scout-17b-16e-instruct", "meta-llama/llama-4-maverick-17b-128e-instruct"]
GROQ_PREFERRED = ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]
OPENROUTER_PREFERRED = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3.5-super-vl:free",
    "google/gemma-4-26b-a4b-it:free",
    "inclusionai/ling-3.2-flash:free",
    "nvidia/nemotron-3.5-lightning:free",
]
NVIDIA_PREFERRED = [
    "mistralai/mistral-large-4-1t-a52b",
    "moonshotai/kimi-k3.1-pro",
    "nvidia/nemotron-3-ultra-550b-a55b",
    "google/gemma-4-31b-it",
    "z-ai/glm-5.3-flash",
    "meta/llama-3.3-70b-instruct",
]

_MODEL_CACHE: dict[str, list[str]] = {}
_DEAD: set[str] = set()  # provider:model pairs that answered 404/400-not-found this run


def log(msg: str) -> None:
    print(f"[anime_llm] {msg}", flush=True)


class LLMHTTPError(Exception):
    def __init__(self, status: int, body: str, retry_after: float | None = None):
        super().__init__(f"HTTP {status}: {body[:400]}")
        self.status = status
        self.body = body
        self.retry_after = retry_after


def _http_json(url: str, payload: dict | None, headers: dict, timeout: float) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **headers},
                                 method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        ra = None
        try:
            ra = float(e.headers.get("retry-after")) if e.headers and e.headers.get("retry-after") else None
        except Exception:
            ra = None
        if ra is None:
            m = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', body) or re.search(r"try again in (\d+(?:\.\d+)?)s", body)
            if m:
                ra = float(m.group(1))
        raise LLMHTTPError(e.code, body, ra)


def _list_models(provider: str, key: str) -> list[str]:
    if provider in _MODEL_CACHE:
        return _MODEL_CACHE[provider]
    ids: list[str] = []
    try:
        if provider == "gemini":
            res = _http_json(f"https://generativelanguage.googleapis.com/v1beta/models?pageSize=200&key={key}", None, {}, 30)
            ids = [m["name"].split("/", 1)[-1] for m in res.get("models", [])
                   if "generateContent" in (m.get("supportedGenerationMethods") or [])]
        elif provider == "groq":
            res = _http_json("https://api.groq.com/openai/v1/models", None, {"Authorization": f"Bearer {key}"}, 30)
            ids = [m["id"] for m in res.get("data", [])]
        elif provider == "openrouter":
            res = _http_json("https://openrouter.ai/api/v1/models", None, {"Authorization": f"Bearer {key}"}, 30)
            ids = [m["id"] for m in res.get("data", [])]
        elif provider == "nvidia":
            res = _http_json("https://integrate.api.nvidia.com/v1/models", None, {"Authorization": f"Bearer {key}"}, 30)
            ids = [m["id"] for m in res.get("data", [])]
        log(f"{provider}: key lists {len(ids)} models")
    except LLMHTTPError as e:
        log(f"{provider}: model list failed (HTTP {e.status}): {e.body[:300]}")
    except Exception as e:
        log(f"{provider}: model list failed: {e!r}")
    _MODEL_CACHE[provider] = ids
    return ids


def _ordered(provider: str, key: str, preferred: list[str], extra_filter=None) -> list[str]:
    avail = _list_models(provider, key)
    if not avail:
        return list(preferred)  # list call failed: just try the preferred IDs
    out = [m for m in preferred if m in avail]
    if extra_filter:
        out += [m for m in avail if m not in out and extra_filter(m)][:2]
    return out


def _gemini(key: str, model: str, system: str, prompt: str, json_mode: bool, temperature: float, max_tokens: int,
            timeout: float, image_b64: str | None = None) -> str:
    parts: list[dict] = [{"text": prompt}]
    if image_b64:
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": image_b64}})
    cfg: dict = {"temperature": temperature, "maxOutputTokens": max_tokens}
    if json_mode:
        cfg["responseMimeType"] = "application/json"
    payload = {"contents": [{"role": "user", "parts": parts}], "generationConfig": cfg}
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    res = _http_json(url, payload, {"Content-Type": "application/json"}, timeout)
    cands = res.get("candidates") or []
    if not cands:
        raise ValueError(f"no candidates (promptFeedback={json.dumps(res.get('promptFeedback'))[:300]})")
    c0 = cands[0]
    text = "".join(p.get("text", "") for p in (c0.get("content") or {}).get("parts", []) if not p.get("thought"))
    if not text.strip():
        raise ValueError(f"empty text (finishReason={c0.get('finishReason')})")
    if c0.get("finishReason") not in (None, "STOP"):
        log(f"gemini {model}: finishReason={c0.get('finishReason')} (text kept, validator decides)")
    return text


def _openai_compat(base: str, key: str, model: str, system: str, prompt: str, json_mode: bool, temperature: float,
                   max_tokens: int, timeout: float, image_b64: str | None = None, extra_headers: dict | None = None) -> str:
    user_content: object = prompt
    if image_b64:
        user_content = [{"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}]
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user_content}]
    payload: dict = {"model": model, "messages": msgs, "temperature": temperature, "max_tokens": max_tokens}
    if json_mode and not image_b64 and "api.groq.com" in base:
        payload["response_format"] = {"type": "json_object"}
    if "gpt-oss" in model and "api.groq.com" in base:
        payload["reasoning_effort"] = "low"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", **(extra_headers or {})}
    res = _http_json(f"{base}/chat/completions", payload, headers, timeout)
    if res.get("error"):
        raise ValueError(f"error in body: {json.dumps(res['error'])[:300]}")
    msg = (res.get("choices") or [{}])[0].get("message") or {}
    text = msg.get("content") or ""
    if isinstance(text, list):
        text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
    text = re.sub(r"(?s)<think>.*?</think>", "", text).strip()
    if not text:
        raise ValueError(f"empty reply (finish_reason={(res.get('choices') or [{}])[0].get('finish_reason')})")
    return text


def provider_chain(vision: bool = False) -> list[tuple[str, str, object]]:
    """Returns [(provider, model, callable(system, prompt, json_mode, temperature, max_tokens, timeout, image_b64))]."""
    chain: list[tuple[str, str, object]] = []
    gk = os.environ.get("GEMINI_API_KEY", "").strip()
    qk = os.environ.get("GROQ_API_KEY", "").strip()
    ok = os.environ.get("OPENROUTER_API_KEY", "").strip()
    nk = os.environ.get("NVIDIA_API_KEY", "").strip()

    if gk:
        for m in _ordered("gemini", gk, GEMINI_PREFERRED, extra_filter=lambda x: "flash" in x and not re.search(r"tts|image|live|audio|embed|transcribe", x)):
            chain.append(("gemini", m, lambda s, p, j, t, mt, to, img, _m=m: _gemini(gk, _m, s, p, j, t, mt, to, img)))
    if qk:
        for m in _ordered("groq", qk, GROQ_VISION_PREFERRED if vision else GROQ_PREFERRED):
            chain.append(("groq", m, lambda s, p, j, t, mt, to, img, _m=m: _openai_compat(
                "https://api.groq.com/openai/v1", qk, _m, s, p, j, t, min(mt, 16000), to, img)))
    if ok:
        pref = OPENROUTER_PREFERRED if not vision else ["nvidia/nemotron-3.5-super-vl:free", "google/gemma-4-31b-it:free", "google/gemma-4-26b-a4b-it:free"]
        for m in _ordered("openrouter", ok, pref):
            chain.append(("openrouter", m, lambda s, p, j, t, mt, to, img, _m=m: _openai_compat(
                "https://openrouter.ai/api/v1", ok, _m, s, p, j, t, mt, to, img,
                {"HTTP-Referer": "https://github.com/loobah18-arch/roblox-auto-shorts", "X-Title": "Bhaloo Ji Anime Recap"})))
    if nk:
        pref = NVIDIA_PREFERRED if not vision else ["nvidia/nemotron-3.5-super-vl-120b-a12b", "google/gemma-4-31b-it"]
        for m in _ordered("nvidia", nk, pref):
            chain.append(("nvidia", m, lambda s, p, j, t, mt, to, img, _m=m: _openai_compat(
                "https://integrate.api.nvidia.com/v1", nk, _m, s, p, j, t, min(mt, 16000), to, img)))
    return chain


def complete(prompt: str, system: str = "", json_mode: bool = False, temperature: float = 0.6,
             max_tokens: int = 16000, timeout: float | None = None, validator=None, image_b64: str | None = None,
             vision: bool = False, max_429_wait: float = 90.0, label: str = "") -> tuple[str, str] | None:
    """
    Try every provider/model in order. `validator(text)` may raise ValueError to reject an answer
    (the next model is then tried; the rejection is logged). Returns (text, "provider:model") or None.
    """
    timeout = timeout or DEFAULT_TIMEOUT
    chain = provider_chain(vision=vision or bool(image_b64))
    if not chain:
        log(f"{label}: no LLM API keys in the environment")
        return None
    for provider, model, fn in chain:
        tag = f"{provider}:{model}"
        if tag in _DEAD:
            continue
        for attempt in range(3):
            t0 = time.time()
            try:
                text = fn(system, prompt, json_mode, temperature, max_tokens, timeout, image_b64)
                if validator is not None:
                    validator(text)
                log(f"{label}: {tag} OK in {time.time() - t0:.1f}s ({len(text)} chars)")
                return text, tag
            except LLMHTTPError as e:
                log(f"{label}: {tag} HTTP {e.status} after {time.time() - t0:.1f}s: {e.body[:500]}")
                if e.status == 429 and attempt < 2:
                    wait = e.retry_after if e.retry_after is not None else 20.0 * (attempt + 1)
                    if wait <= max_429_wait:
                        log(f"{label}: {tag} rate-limited, retrying in {wait:.0f}s")
                        time.sleep(wait + 1)
                        continue
                if e.status in (500, 502, 503, 504) and attempt < 1:
                    time.sleep(8)
                    continue
                if e.status in (400, 403, 404) and re.search(r"not found|not supported|does not exist|decommission|deprecat|no longer|permission|not available|model_not", e.body, re.I):
                    _DEAD.add(tag)
                break
            except ValueError as e:
                log(f"{label}: {tag} rejected after {time.time() - t0:.1f}s: {e}")
                if attempt < 1 and validator is not None:
                    continue  # one more sample from the same model
                break
            except Exception as e:
                log(f"{label}: {tag} failed after {time.time() - t0:.1f}s: {e!r}")
                break
    log(f"{label}: every LLM provider failed")
    return None


def extract_json(text: str):
    """Parse a JSON object/array from an LLM answer (strips code fences and leading prose)."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```\s*$", "", t)
    try:
        return json.loads(t)
    except Exception:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        s = t.find(open_c)
        e = t.rfind(close_c)
        if s != -1 and e > s:
            try:
                return json.loads(t[s:e + 1])
            except Exception:
                continue
    raise ValueError("answer is not valid JSON")
