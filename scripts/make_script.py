#!/usr/bin/env python3
"""
Generate a compliance-checked storyboard script for a campaign.

Pipeline: make_script.py
  1. Build the prompt from the full campaign brief + structured rules.
  2. Call a free model down the chain (Groq → Gemini → OpenRouter:free).
  3. Immediately run validate_compliance.py checks on the JSON.
  4. If it fails, feed every failing check back and retry (self-healing, up to
     --max-attempts). Only a PASSING script is written to disk.

Output JSON (script.json):
  {
    "title": "...", "format_name": "...", "persona": "...",
    "slides": [{"n":1,"text":"...","visual":"text-card|lifestyle-photo|product-photo|retail-shot|notes-app|persona-selfie","notes":"..."}],
    "caption": "...", "hashtags": ["..."], "retail_line": "..."
  }

Usage:
    python3 scripts/make_script.py --dir tracker/campaigns/goli --persona "tired mom"
"""
import argparse
import json
import os
import re
import sys
import time

import llm_call
import validate_compliance

PLATFORM_ROOT = "youtube"  # the producer only targets YouTube (bhaloo ji)

DEFAULT_PERSONAS = [
    "tired mom who shops at Target",
    "skeptical wellness girl doing research",
    "gym guy who adds a daily habit",
    "burnt-out office worker",
    "broke college student trying something cheap",
    "quiet self-improvement guy",
]


def extract_json(text: str):
    if not text:
        return None
    text = text.strip()
    # strip code fences
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # find first balanced {...}
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                cand = text[start:i + 1]
                try:
                    return json.loads(cand)
                except json.JSONDecodeError:
                    # tolerate a single trailing comma
                    try:
                        return json.loads(re.sub(r",\s*([}\]])", r"\1", cand))
                    except json.JSONDecodeError:
                        return None
    return None


def build_prompt(detail, rules, brief_text, persona):
    caps = [t for t in rules.get("hashtags") or [] if t]
    banned = (rules.get("banned_claim_phrases") or [])[:40]
    required = (rules.get("required_elements") or [])[:8]
    brief = brief_text[:14000]  # fit small free-model contexts

    user = f"""You write slideshow storyboard scripts for Whop Content Rewards campaigns. Target platform: {PLATFORM_ROOT} (9:16 YouTube Short).

CAMPAIGN: {detail.get('title','')}
MATERIAL LINKS: {' '.join(detail.get('reference_links') or [])}
RULES — hashtags: {', '.join('#'+c for c in caps)}
SLIDES: {rules.get('slides_min',5)} to {rules.get('slides_max',8)} slides, ~3 words-to-short-phrase on-screen text each.
PAYOUT: ${rules.get('rate_per_1k_usd',0.0)}/1K, max ${rules.get('payout_max_usd','?')}/post.
REQUIRED ELEMENTS: {required}
BANNED CLAIMS: {banned}
RETAIL KEYWORDS: {rules.get('retail_keywords') or ['store','shelf','cart']}

FULL CAMPAIGN BRIEF (the source of truth — follow it exactly):
=== BRIEF START ===
{brief}
=== BRIEF END ===

You are creating this for PERSONA: "{persona}".

OUTPUT: JSON only, no markdown fence, no prose. Schema:
{{
  "title": "short Youtube title <=100 chars, human, not ad-like",
  "format_name": "which brief format/lane you followed",
  "persona": "{persona}",
  "slides": [
    {{"n":1, "text":"on-screen words (<=8 words)", "visual":"text-card|lifestyle-photo|product-photo|retail-shot|notes-app|persona-selfie", "notes":"1 clause of staging/production direction"}}
  ],
  "caption": "the post caption WITHOUT hashtags — short, human, ends with one comment question",
  "hashtags": ["{caps[0] if caps else 'FILM'} and up to 2 extra allowed by brief"],
  "retail_line": "one line naming where people buy it (e.g. 'got mine at Target')"
}}

HARD RULES:
- 5-8 slides. Slide 1 is a hook card. On persona pages product appears late (slide >=5). Last slide is a soft closer + one comment question.
- Text must be short and low-case-y, like a person talking, never an ad.
- Lip-stick to the brief's exact claims. NEVER use any BANNED CLAIM. Never pretend to be a doctor, never health-claim, never weight-loss, never 'boost/natural/organic/etc' unless the brief explicitly allows.
- NEVER write "link in bio", "check my bio", "comment below", "follow me", or any invitation to click an external link — it is an AUTOMATIC rejection every time.
- MUST name the campaign brand / where people get it (retail_line or a slide/caption naming the brand like 'FundingPips' or 'got mine at Target'): you will not be paid if the destination is missing.
- If the brief lists REQUIRED overlay text or REQUIRED caption wording, include that exact wording (or close to it) verbatim in the relevant slide/caption.
- caption excludes hashtags; we append them separately. In slides, if captions/hashtag-like '#word' appear, that's fine only if the brief requires it."""
    return user


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", required=True, help="campaign dir with detail.json, brief.txt, rules.json")
    ap.add_argument("--output", default="script.json")
    ap.add_argument("--persona", default="", help="override persona (auto-rotates otherwise)")
    ap.add_argument("--max-attempts", type=int, default=3)
    args = ap.parse_args()

    detail = json.load(open(os.path.join(args.dir, "detail.json"), encoding="utf-8"))
    brief = open(os.path.join(args.dir, "brief.txt"), encoding="utf-8").read()
    rules = json.load(open(os.path.join(args.dir, "rules.json"), encoding="utf-8"))

    persona = args.persona or DEFAULT_PERSONAS[ int(time.time() // 86400) % len(DEFAULT_PERSONAS) ]

    user = build_prompt(detail, rules, brief, persona)
    system = ("You are a disciplined content creator assistant. You ALWAYS output only valid JSON "
              "matching the requested schema. You follow campaign briefs exactly and never produce "
              "banned claims, fake sellouts, or ad-speak.")

    attempts_log = []
    for attempt in range(1, args.max_attempts + 1):
        if attempt > 1:
            prev = attempts_log[-1]
            extra = ("Fix EXACTLY these compliance failures in the previous draft: "
                     + json.dumps(prev.get("errors", ["unspecified"]))
                     + ". Return the corrected full JSON only.")
        else:
            extra = ""
        full_user = user + (("\n\n" + extra) if extra else "")

        res = llm_call.call_llm(system, full_user, json_mode=True)
        if not res["ok"]:
            print(f"[warn] attempt {attempt}: no free LLM responded: {res['error']}", file=sys.stderr)
            attempts_log.append({"provider": None, "errors": [res["error"]]})
            continue

        script = extract_json(res["text"])
        # free models often return a bare JSON array or scalar — treat any non-object
        # as a failed attempt (a list would crash script.get() below instead of retrying)
        if not isinstance(script, dict):
            print(f"[warn] attempt {attempt}: model returned non-object JSON", file=sys.stderr)
            attempts_log.append({"provider": res["provider"], "model": res["model"],
                                 "errors": ["response was not a JSON object"]})
            continue

        # normalize slides to dicts — tolerate any JSON shape (array, object, null)
        raw_slides = script.get("slides")
        if raw_slides is None:
            raw_slides = []
        elif not isinstance(raw_slides, list):
            raw_slides = []

        slides = []
        for s in raw_slides:
            if isinstance(s, str):
                s = {"text": s, "visual": "text-card"}
            elif not isinstance(s, dict):
                continue  # skip null, number, etc.
            slides.append({**s, "n": len(slides) + 1})
        script["slides"] = slides

        verdict = validate_compliance.validate(rules, script)
        if verdict["pass"]:
            script["_meta"] = {
                "provider": res["provider"], "model": res["model"],
                "attempt": attempt, "persona": persona,
                "checks": verdict["checks"],
            }
            os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(script, f, indent=2, ensure_ascii=False)
            print(f"PASS on attempt {attempt} via {res['provider']}/{res['model']} -> {args.output}")
            return 0
        else:
            print(f"[warn] attempt {attempt}: compliance failed: {verdict['errors']}", file=sys.stderr)
            attempts_log.append({"provider": res["provider"], "model": res["model"],
                                 "errors": verdict["errors"]})

    # exhausted attempts
    attempts_path = os.path.splitext(args.output)[0] + ".attempts.json"
    with open(attempts_path, "w", encoding="utf-8") as f:
        json.dump({"persona": persona, "attempts": attempts_log}, f, indent=2)
    print(f"FAILED after {args.max_attempts} attempts. See script.attempts.json", file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())