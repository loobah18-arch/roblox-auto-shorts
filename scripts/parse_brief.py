#!/usr/bin/env python3
"""
Turn a raw campaign brief.txt into structured rules.json.

Whop campaign briefs are all written in natural language with a slightly
different layout per brand, but they consistently include:
  - required hashtags (#GOLINAD)
  - target platforms (TikTok / Instagram / YouTube)
  - slide/script counts ("5 to 8 slides")
  - rate and payout caps ($1/1K, $400 max)
  - a "MUST" / "every post" list of required elements
  - a banned-claims list ("never say this" / "you will not get paid if")
  - format skeletons for the actual creator asset

This parser is deliberately GENERIC and defensive: it never fails the pipeline.
Everything it can't parse confidently is left to make_script.py, which feeds the
full brief text to the model, and the real safety net is validate_compliance.py
(pure-code, runs after generation).

Usage:
    python3 scripts/parse_brief.py --brief tracker/campaigns/goli/brief.txt --output tracker/campaigns/goli/rules.json
"""
import argparse
import json
import os
import re
import sys

# A generic, conservative claim list used when the brief doesn't spell one out.
# These are the categories whop briefs most commonly reject post-clipping.
GENERIC_BANNED = [
    "cure", "cured", "cures", "treat", "treats", "treating", "fix", "fixes",
    "prevent", "prevents", "reverse", "reverses", "reversing", "anti-aging",
    "anti aging", "weight loss", "lose weight", "losing weight", "slim",
    "boost", "boosted", "boost your", "energy shot", "coffee replacement",
    "clinically proven", "studies show", "doctors recommend", "scientifically",
    "natural", "organic", "plant-based", "guaranteed", "you will feel",
    "not supposed to fix", "disease", "cancer", "diabetes", "depression",
    "adhd", "dementia", "anxiety", "heart attack", "stroke",
    "link in bio", "buy now", "10x", "double your", "overnight",
    "fake sellout", "sold out everywhere",
]


def harvest(text: str) -> dict:
    rules: dict = {}

    # ---- hashtags ----
    tags = re.findall(r'(?<![\w#])(?:#)([A-Za-z0-9_]{2,})', text)
    rules["hashtags"] = sorted(set(tag.lstrip("#") for tag in tags))

    # ---- platforms ----
    low = text.lower()
    found = []
    for p in ["tiktok", "instagram", "youtube", "facebook", "twitter", "snapchat", "pinterest"]:
        if re.search(r'\b' + p + r'\b', low):
            found.append(p)
    rules["platforms"] = found

    # ---- slide / post count ("5 to 8 slides", "5-8")
    m = re.search(r'([0-9]{1,2})\s*(?:to|-)\s*([0-9]{1,2})\s*(?:slides|slideshows|videos|posts)', low)
    if m:
        rules["slides_min"], rules["slides_max"] = int(m.group(1)), int(m.group(2))

    # ---- rate per 1K ----
    rate = None
    for pat in [r'\$([0-9]+(?:\.[0-9]+)?)\s*(?:/|per)\s*1k',
                r'\$([0-9]+(?:\.[0-9]+)?)\s*per\s*1000',
                r'\$([0-9]+(?:\.[0-9]+)?)\s*cpm\b']:
        mm = re.search(pat, low)
        if mm:
            rate = float(mm.group(1))
            break
    if rate is not None:
        rules["rate_per_1k_usd"] = rate

    # ---- payout cap ("$400 max per clip", "max payout $400") ----
    m = re.search(r'\$([0-9]+(?:\.[0-9]+)?)\s*(?:max|cap)', low)
    if not m:
        m = re.search(r'(?:max|cap)\s*(?:per clip|payout)?\s*\$?([0-9]+(?:\.[0-9]+)?)', low)
    if m:
        rules["payout_max_usd"] = float(m.group(1))

    # ---- required elements: lines with MUST / REQUIRED / no exceptions / every post ----
    required = []
    seen = set()
    for m in re.finditer(r'([^.\n]{1,200}?(?:must|required|no exceptions|every post|will not get paid)[^.\n]{1,200}?)', text, re.I):
        s = re.sub(r'\s+', " ", m.group(0)).strip()
        if 12 <= len(s) <= 220 and s not in seen:
            seen.add(s)
            required.append(s)
    rules["required_elements"] = required[:40]

    # ---- banned claim lines: text after marker words like "never say"/"you will not get paid"/"❌" ----
    banned = get_banned_block(text)

    # merge with generic list conservatively
    merged = list(dict.fromkeys(banned + GENERIC_BANNED))
    rules["banned_claim_phrases"] = merged

    # ---- format names: "FORMAT 1" section headers and the like ----
    formats = re.findall(r'(?i)(format|lane|recipe)\s*[0-9A-F]*:?\s*([A-Za-z][A-Za-z ._-]{3,50})', text)
    rules["format_names"] = [f[1].strip() for f in formats[:12]]

    # ---- retail push keywords (brand/store/shelf talk) ----
    rules["retail_keywords"] = harvest_retail(text)

    return rules


def harvest_retail(text):
    """Collect the retail-destination words a brief wants pushed (Target, Walmart,
    Amazon, 'store', 'aisle', 'cart', …). Used by the compliance validator to make
    sure the generated script actually names the buying destination."""
    words = set()
    low = text.lower()
    # known retail brands
    for known in ("Target", "Amazon", "Walmart", "Costco", "Walgreens", "CVS",
                  "Target.com", "Amazon.com"):
        if known.lower() in low:
            words.add(known)
    # retail context words
    for kw in ("store", "shelf", "aisle", "cart", "checkout", "got mine at",
               "buy it at", "in store", "where to buy", "retail push", "red bag"):
        if kw in low:
            words.add(kw)
    return [w for w in words][:20]


def get_banned_block(text: str):
    """Collect ban-zone lines. Whop briefs denote them inconsistently."""
    banned = []
    markers = ["you will not get paid", "never say", "do not", "can't say",
               "not allowed", "❌", "✖"]
    # Split on newlines first (works regardless of punctuation quirks).
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for i, line in enumerate(lines):
        low = line.lower()
        if any(mk in low for mk in markers):
            # take the line and up to the next 4 clean lines as the ban sentence
            chunk = [line]
            for nxt in lines[i + 1:i + 5]:
                if len(nxt) < 200 and nxt and not re.match(r'^[0-9]+[.)]', nxt):
                    if any(mk in nxt.lower() for mk in ["never say", "do not", "not allowed", "required", "must"]):
                        break
                    chunk.append(nxt)
                else:
                    break
            sentence = re.sub(r'\s+', " ", " ".join(chunk)).strip().strip("•-* ")
            if 4 <= len(sentence) <= 220:
                banned.append(sentence)
    return banned


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--brief", required=True, help="path to brief.txt")
    ap.add_argument("--output", required=True, help="path to write rules.json")
    args = ap.parse_args()

    text = open(args.brief, encoding="utf-8", errors="ignore").read()
    rules = harvest(text)
    # Always keep full text alongside for the model step / human audit.
    rules["brief_chars"] = len(text)

    out_dir = os.path.dirname(args.output) or "."
    os.makedirs(out_dir, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(rules, f, indent=2, ensure_ascii=False)
    print(json.dumps(rules, indent=2, ensure_ascii=False)[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main())