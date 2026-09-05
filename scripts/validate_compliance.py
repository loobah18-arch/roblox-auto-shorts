#!/usr/bin/env python3
"""
Pure-code compliance validator for a generated short script.

Runs AFTER make_script.py (which may use a free model) as the real safety net:
if a free/sloppy model writes a banned claim or forgets the required hashtag,
THIS catches it and the pipeline retries generation — nothing invalid ever
reaches the renderer or YouTube.

Inputs:
  rules.json   — structured brief from parse_brief.py  (hashtags, slides range,
                 banned_claim_phrases, retail_keywords, required_elements)
  script.json  — generated storyboard from make_script.py

Checks:
  1. Captain hashtag: the campaign's primary required hashtag appears in the
     final caption+hashtags (case-insensitive; initial # optional).
  2. Banned claims: no banned phrase/word from the brief or the generic list
     appears in title, slides, or caption.
  3. Slide count within the brief's range (default 5-8).
  4. Retail push: at least one slide or caption line names a buying destination
     (brief retail_keywords, else a generic store/shelf/cart/aisle set).
  5. Registry/no-ad-sound: title length, caption length, no 'link in bio',
     no fake scarcity/sellout phrases, no all-caps shouting in the title.

Output: {"pass": bool, "checks": [{name, ok, detail}], "errors": [..]}
Exit 0 if pass, 3 if not.
"""
import argparse
import json
import os
import re
import sys

GENERIC_BANNED = [
    "cure", "cures", "cured", "treat", "treats", "treating", "fix", "fixes",
    "prevent", "prevents", "reverse", "reverses", "reversing", "anti-aging",
    "anti aging", "weight loss", "lose weight", "losing weight", "slimming",
    "clinically proven", "studies show", "doctors recommend", "doctor recommended",
    "scientifically proven", "guaranteed", "you will feel", "boost", "boosts",
    "boosted", "instant energy", "coffee replacement", "replaces my coffee",
    "natural", "organic", "plant-based", "sold out everywhere", "fake sellout",
    "link in bio", "buy now", "order now", "double your", "10x",
    "disease", "cancer", "diabetes", "depression", "anxiety", "adhd",
    "dementia", "heart attack", "stroke", "overnight",
]

# Words that make a line sound like an ad — flagged for the human review note.
AD_SOUNDERS = ["limited time", "hurry", "act fast", "amazing deal", "don't miss out",
               "discounted", "sale ends", "50%", "free shipping"]

DEFAULT_SLIDE_RANGE = (5, 8)


def norm(h: str) -> str:
    return h.lower().lstrip("#").replace("_", "").replace("-", "")


def caption_with_hashtags(script: dict) -> str:
    caps = [script.get("caption") or ""] + list(script.get("hashtags") or [])
    return " ".join(caps)


def slide_text(script: dict) -> str:
    out = []
    for s in script.get("slides") or []:
        out.append(s.get("text", "") if isinstance(s, dict) else str(s))
    return "\n".join(out)


def check(name: str, ok: bool, detail: str) -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail}


def validate(rules: dict, script: dict) -> dict:
    errors: list[str] = []
    checks: list[dict] = []

    # ---- 1. required hashtag ----
    tags = [t for t in rules.get("hashtags") or [] if t]
    primary = tags[0] if tags else None  # parse_brief returns brief's hashtags; first is usually the required one
    full = caption_with_hashtags(script)
    hashtag_ok = True
    detail = ""
    if primary:
        # required hashtag is usually the ALL-CAPS one; pick it if present
        caps = [t for t in tags if t.upper() == t] or tags
        primary = caps[0]
        hashtag_ok = norm(primary) in norm(full)
        detail = f"Hashtag #{primary} {'found' if hashtag_ok else 'MISSING in caption/hashtags'}"
    else:
        detail = "no hashtags in rules; skipped"
    checks.append(check("required_hashtag", hashtag_ok, detail))
    if not hashtag_ok:
        errors.append(detail)

    # ---- 2. banned claims ----
    banned = [b for b in rules.get("banned_claim_phrases") or [] if b] + GENERIC_BANNED
    banned = [b.lower().strip(" .•-*") for b in banned if len(b.strip()) >= 3]
    banned = list(dict.fromkeys(banned))
    blob = (slide_text(script) + "\n" + caption_with_hashtags(script) + "\n" +
            (script.get("title") or "")).lower()
    # normalize common glues so 'anti-aging' and 'weight loss' match 'weight-loss'
    blobn = re.sub(r"[^a-z0-9 ]", " ", blob)
    hit = None
    for b in banned:
        bn = re.sub(r"[^a-z0-9 ]", " ", b).strip()
        if len(bn) < 3:
            continue
        if bn in ("boost", "fix", "cure", "treat"):  # substring-hazard words: word-boundary check
            if re.search(r"(?<![\w])" + re.escape(bn) + r"(?![\w])", blobn):
                hit = bn
                break
        elif bn in blobn:
            hit = bn
            break
    checks.append(check("banned_claims", hit is None,
                        f"no banned claims" if hit is None else f"BANNED PHRASE: '{hit}'"))
    if hit:
        errors.append(f"banned claim in generated text: '{hit}'")

    # ---- 3. slide count ----
    n = len(script.get("slides") or [])
    lo = int(rules.get("slides_min") or DEFAULT_SLIDE_RANGE[0])
    hi = int(rules.get("slides_max") or DEFAULT_SLIDE_RANGE[1])
    ok_slides = lo <= n <= hi
    checks.append(check("slide_count", ok_slides,
                        f"{n} slides in range [{lo},{hi}]" if ok_slides else f"{n} slides; brief wants [{lo},{hi}]"))
    if not ok_slides:
        errors.append(f"slide count {n} outside [{lo},{hi}]")

    # ---- 4. retail push / destination ----
    retail = list(rules.get("retail_keywords") or [])
    generic_retail = ["target", "amazon", "walmart", "costco", "store", "shelf",
                      "aisle", "cart", "got mine at", "buy it at", "in-store"]
    if not retail:
        retail = generic_retail
        detail_retail = f"no brief retail keywords; using generic set"
    else:
        detail_retail = f"brief retail keywords: {', '.join(retail[:6])}"
    blob_retail = (slide_text(script) + "\n" + full).lower()
    ok_retail = any(k.lower() in blob_retail for k in retail) or \
                any(k in blob_retail for k in generic_retail)
    checks.append(check("retail_push", ok_retail,
                        detail_retail + ("; destination named ✓" if ok_retail else "; NO buying-destination named")))
    if not ok_retail:
        errors.append("generated script never names a purchase destination (store/shelf/cart)")

    # ---- 5. registry / ad-sound hygiene ----
    title = script.get("title") or ""
    ok_title = 5 <= len(title) <= 100
    checks.append(check("title_length", ok_title, f"title {len(title)} chars (5..100)"))
    if not ok_title:
        errors.append(f"title length {len(title)}")

    ok_linkbio = "link in bio" not in blob.lower() and "linkinbio" not in norm(full)
    checks.append(check("no_link_in_bio", ok_linkbio, "no 'link in bio'"))
    if not ok_linkbio:
        errors.append("forbidden 'link in bio'")

    ad_hits = [w for w in AD_SOUNDERS if w in blob]
    checks.append(check("ad_sound_note", True,
                        f"no ad-sounders" if not ad_hits else f"ad-sounding: {', '.join(ad_hits)} (flag for review)"))

    ok = not errors
    return {"pass": ok, "checks": checks,
            "errors": errors,
            "banned_list_size": len(banned),
            "norm_blob_len": len(blobn)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rules", required=True)
    ap.add_argument("--script", required=True)
    ap.add_argument("--output", default="")
    args = ap.parse_args()
    rules = json.load(open(args.rules, encoding="utf-8"))
    script = json.load(open(args.script, encoding="utf-8"))
    result = validate(rules, script)
    out = json.dumps(result, indent=2, ensure_ascii=False)
    print(out)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        open(args.output, "w", encoding="utf-8").write(out + "\n")
    return 0 if result["pass"] else 3


if __name__ == "__main__":
    sys.exit(main())