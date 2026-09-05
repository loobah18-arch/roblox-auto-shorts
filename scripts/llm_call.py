#!/usr/bin/env python3
"""
Free LLM caller with a provider/mo chain + retry (all $0).

The user's OpenRouter key has ~no credit, so we call FREE tiers of providers whose
keys are already in the repo secrets:  Groq → Google Gemini → OpenRouter :free.
Whichever returns a 2xx first wins; 429s are retried down the chain.

Only reads keys from the environment (never from files).
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

UA = "whop-producer/1.0"

GROQ_MODELS = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "llama-3.2-3b-preview"]
GEMINI_MODELS = ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-flash-latest"]
OPENROUTER_FREE = [
    "google/gemma-4-26b-a4b-it:free",
    "z-ai/glm-5.2:free",
    "minimax/minimax-m3:free",
    "thinkingmachines/inkling:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "liquid/lfm-2.5-2.6b:free",
]


def _post_json(url: str, headers: dict, payload: dict, timeout: int = 90):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"User-Agent": UA, "Content-Type": "application/json", **headers},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def _call_groq(key: str, model: str, system: str, user: str, max_tokens: int, json_mode: bool):
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.4,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    raw = _post_json("https://api.groq.com/openai/v1/chat/completions",
                     {"Authorization": f"Bearer {key}"}, body)
    return raw


def _call_gemini(key: str, model: str, system: str, user: str, max_tokens: int, json_mode: bool):
    body = {
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "systemInstruction": {"parts": [{"text": system}]},
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.4},
    }
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    raw = _post_json(url + f"?key={key}", {}, body, timeout=120)
    data = json.loads(raw)
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"gemini unexpected shape: {str(data)[:300]}")


def _call_openrouter(key: str, model: str, system: str, user: str, max_tokens: int, json_mode: bool):
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.4,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    raw = _post_json("https://openrouter.ai/api/v1/chat/completions",
                     {"Authorization": f"Bearer {key}"}, body, timeout=120)
    return raw


def _parse_response(provider: str, raw: str, model: str) -> str:
    """Return the assistant text from a raw provider response body."""
    if provider == "gemini":
        return raw.rstrip()  # _call_gemini already unwrapped
    data = json.loads(raw)
    return data["choices"][0]["message"]["content"]


def call_llm(system: str, user: str, *, json_mode: bool = True, max_tokens: int = 2048):
    """
    Call free LLMs down the chain until one succeeds.
    Returns {"ok": bool, "text": str|None, "provider": str|None, "model": str|None,
             "error": str|None, "attempts": [(provider, model, status)]}
    """
    attempts: list[tuple[str, str, str]] = []

    groq_key = os.environ.get("GROQ_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    or_key = os.environ.get("OPENROUTER_API_KEY")

    for provider, key, models, caller in (
        ("groq", groq_key, GROQ_MODELS, _call_groq),
        ("gemini", gemini_key, GEMINI_MODELS, _call_gemini),
        ("openrouter:free", or_key, OPENROUTER_FREE, _call_openrouter),
    ):
        if not key:
            attempts.append((provider, "-", "no key in env"))
            continue
        for model in models:
            try:
                raw = caller(key, model, system, user, max_tokens, json_mode)
                text = _parse_response(provider, raw, model)
                attempts.append((provider, model, "ok"))
                return {"ok": True, "text": text, "provider": provider,
                        "model": model, "error": None, "attempts": attempts}
            except urllib.error.HTTPError as e:
                status = f"HTTP {e.code}"
                if e.code == 429:  # rate limited → next provider/model
                    attempts.append((provider, model, status))
                    time.sleep(0.6)
                    continue
                attempts.append((provider, model, status))
            except Exception as e:  # network / parse
                attempts.append((provider, model, f"{type(e).__name__}: {e}"))
                time.sleep(0.4)
        # give the next provider a moment to breathe
        time.sleep(0.5)

    return {"ok": False, "text": None, "provider": None, "model": None,
            "error": "all free providers failed", "attempts": attempts}


if __name__ == "__main__":
    res = call_llm("Reply with exactly {\"ok\":true}.", "test")
    print(json.dumps(res, indent=2)[:1200])
    sys.exit(0 if res["ok"] else 1)