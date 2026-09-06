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

# Phrases that make an extracted "requirement/format/ban" useless for downstream
# LLM prompt or the compliance validator. Heuristics below drop anything that
# reads like strategy prose rather than an actual rule.
NOISE = [
    "just inspiration", "you are encouraged", "rough format ideas", "run it again",
    "rerun your winner", "do not reinvent", "strongest one", "ship this first",
    "proven videos", "start with the", "in the campaign", "s - they are",
    "s:", "main goal", "not supposed to fix", "general very rough",
    "learn from them", "how to do it", "not the point", "open gemini",
]
GENERIC_RETAIL = ["store", "shelf", "aisle", "cart", "got mine at", "in store",
                  "buy it at", "where to buy", "checkout", "retail push", "red bag"]


def harvest_formats(text: str) -> list[str]:
    """Extract real format/lane titles. Whop briefs list them as:
      FORMAT 1
      I Didn't Know How Bad It Was   ← title
      The strongest one.              ← comment (skip)
    """
    formats: list[str] = []
    seen: set[str] = set()
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # — "LANE X — Title. Subtitle." pattern —
    for line in lines:
        m = re.match(r'(?:LANE|RECIPE)\s*[A-Z0-9]*?\s*[—:\-]\s*(.+)$', line, re.I)
        if not m:
            continue
        # take first clause before a period or long comma
        title = re.split(r'[.](?:\s|$)|[;]\s', m.group(1))[0].strip().rstrip('.,').strip()
        tkey = title.lower()
        if len(title.split()) < 2 or not title[0].isupper():
            continue
        if tkey in seen or any(n in tkey for n in NOISE):
            continue
        seen.add(tkey)
        formats.append(title)

    # — "FORMAT IDEAS: A, B, C" header —
    for line in lines:
        m = re.match(r'^FORMAT\s+IDEAS?\s*[:.]\s*(.+)$', line, re.I)
        if m:
            ideas = [a.strip() for a in re.split(r'[,/]', m.group(1)) if a.strip()]
            for idea in ideas:
                title = re.split(r'[.!?]', idea, maxsplit=1)[0].strip().rstrip('.').strip()
                if not title or len(title) < 3:
                    continue
                if any(n in title.lower() for n in NOISE):
                    continue
                tkey = title.lower()
                if tkey not in seen:
                    seen.add(tkey)
                    formats.append(title)

    # — "FORMAT N" on its own line → next non-empty line is the title —
    for i, line in enumerate(lines):
        if not re.match(r'^FORMAT\s+\d+$', line, re.I):
            continue
        for nxt in lines[i + 1: i + 3]:
            # skip sub-comments ("The strongest one. Ship this first.")
            if re.match(r'^(?:the\s|\d|we|ship|proven|start|run|great|funny|target)', nxt, re.I):
                continue
            t = nxt.split('.')[0].strip().rstrip(',').strip()
            if len(t) < 3 or len(t) > 65 or not t[0].isupper():
                continue
            tkey = t.lower()
            if tkey in seen or any(n in tkey for n in NOISE):
                continue
            seen.add(tkey)
            formats.append(t)
            break

    return formats[:10]


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
    # Preserve the brief's first-mentioned order (the required hashtag is usually
    # the one listed first) instead of sorting — the compliance validator relies
    # on tags[0] being the required tag.
    tags = re.findall(r'(?<![\w#])(?:#)([A-Za-z0-9_]{2,})', text)
    rules["hashtags"] = list(dict.fromkeys(tag.lstrip("#") for tag in tags))

    # ---- platforms ----
    # Only trust EXPLICIT platform directives ("post to:", "platform:", "upload to:"),
    # not passing mentions inside strategy prose ("clean eats pages on Pinterest").
    # The authoritative source is detail.json["platforms"] (merged in main()).
    low = text.lower()
    found = []
    known = ["tiktok", "instagram", "youtube", "facebook", "twitter", "snapchat",
             "pinterest", "threads"]
    directive = re.compile(
        r'(?:post\s*(?:to|on|at)|upload\s*(?:to|on)|publish\s*(?:on|to)|'
        r'submit\s*(?:to|on)|platforms?\s*(?:are|:|:and|include)?|'
        r'best\s*on|optimized\s*for)\s*[:\s]*([^.\n]{0,80})', re.I)
    for m in directive.finditer(low):
        seg = m.group(1)
        for p in known:
            if re.search(r'\b' + p + r'\b', seg) and p not in found:
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

    # ---- required elements: full SENTENCES that mandate something ----
    # Only keep requirements that are COMPLETE, specific and enforceable. Briefs
    # get split on newlines, so naive harvesting collects: truncated sentence
    # fragments (…mid-clause ending in a dangling "must" that continues on the
    # next line), all-caps section-label headings ("SET UP YOUR ACCOUNT
    # (REQUIRED)"), and pure-hashtag mandates. Feeding those to the compliance
    # validator makes it false-fail (tokens like "SPECIAL RULE" never appear in
    # a compliant script → retry exhaustion → exit 3 blocks the run). Skip them.
    required = []
    seen = set()
    mand = re.compile(r'(must|required|no exceptions|every post|will not get paid|non-negotiable)', re.I)
    for piece in re.split(r'(?<=[.!?])\s+|\n+', text):
        s = re.sub(r'\s+', " ", piece).strip().strip('"“”')
        if not (14 <= len(s) <= 260) or s in seen:
            continue
        if not mand.search(s):
            continue
        if any(n in s.lower() for n in NOISE):
            continue
        # truncated fragment: sentence chopped mid-clause by a newline, ends on a
        # dangling connector/mandate. Drop it UNLESS it names a brand/product
        # ("…the NAD+ gummy at Target must" keeps Target/NAD+, which the validator
        # enforces gracefully); a fragment with no proper noun ("⚠ SPECIAL RULE:
        # You must") can never be satisfied and only causes a false fail.
        if re.search(r'\b(?:must|required|no exceptions)\s*$', s, re.I):
            if not re.search(r'\b[A-Z][A-Za-z0-9+.\-]{1,}\b', s):
                continue
        # heading/directive already enforced elsewhere (setup/lane labels and
        # "how to"/"your audience" instructions are not content requirements)
        head = s.lstrip('“’\'(')
        if re.match(r'(?i)^(?:set up|how to|your audience|note[: ])', head):
            continue
        # all-caps section label / legend heading ("SET UP YOUR ACCOUNT (REQUIRED)",
        # "3 THINGS EVERY SINGLE SLIDESHOW / VIDEO MUST HAVE.") — these are
        # headings whose items are spelled out separately; enforcing the heading
        # itself is impossible and only false-fails the run.
        alpha = [c for c in s if c.isalpha()]
        if s == s.upper() and len(alpha) >= 5:
            continue
        # pure-hashtag mandate ("REQUIRED on every post: #GOLINAD")
        if re.fullmatch(r'[^a-z]*#\w+[^a-z]*', s, re.I):
            continue
        seen.add(s)
        required.append(s)
    rules["required_elements"] = required[:12]

    # ---- banned claim lines: text after marker words like "never say"/"you will not get paid"/"❌" ----
    banned = get_banned_block(text)

    # merge with generic list conservatively
    merged = list(dict.fromkeys(banned + GENERIC_BANNED))
    rules["banned_claim_phrases"] = merged[:60]

    # ---- format names: real "FORMAT N" / "LANE X" header titles, deduped ----
    rules["format_names"] = harvest_formats(text)

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


_NEG = re.compile(r'(?i)\b(?:no|not|never|nothing|don[’\'"]t|cannot)\b')
_BULLET = ('•', '✖', '❌', '*', '-', '·')


def get_banned_block(text: str):
    """Collect ban-zone claims. Whop briefs denote them inconsistently.

    Two shapes are handled:
      1. Inline marker sentences  ("you will not get paid if X", "never say X")
         — which the old code handled.
      2. Bullet zones under a ban header ("❌ NEVER SAY THIS" / "YOU WILL NOT
         GET PAID") — the real, concrete claim list. Goli's brief bans
         "look 10 years younger", "lost 10 lbs", "slimmed down", "replaces my
         coffee", "turns back the clock" ONLY here, as `• No "…"` bullets that
         the old marker-line parser never reached.

    For bullets we keep only the *negated* content: quoted phrases (the most
    specific prohibited wording) plus a short de-negated core when no quote
    covers it. Allowed-claims bullets ("Only these 5, in Goli's own words: …")
    carry no negator and are skipped, so we never ban something the brief
    tells the creator they MAY say.
    """
    banned: list[str] = []
    seen: set[str] = set()
    markers = ["you will not get paid", "will not get paid", "never say",
               "do not", "can't say", "not allowed", "❌", "✖"]

    def _add(p: str):
        p = re.sub(r'[❌✖•\-*\s]+', ' ', p).strip()
        p = p.strip('.,:;"‘’“”').strip()
        if not (3 <= len(p) <= 90):
            return
        if len(p.split()) > 9:
            return
        key = p.lower()
        if key in seen or any(n in key for n in NOISE):
            return
        seen.add(key)
        banned.append(p)

    lines = [l.strip() for l in text.splitlines() if l.strip()]

    for i, line in enumerate(lines):
        low = line.lower()
        # --- inline marker sentence (shape 1) ---
        if any(mk in low for mk in markers):
            first = re.split(r'(?<=[.!?])\s+', line, maxsplit=1)[0]
            if not re.match(r'(?i)^(?:never say this|you will not get paid|do not|not allowed)[:\s]*$', first):
                cut = re.split(
                    r'(?:you will not get paid if|will not get paid if|never say|do not|not allowed)',
                    first, flags=re.I)
                core = cut[-1].strip().strip(':,;')
                if core and not re.match(r'(?i)^(?:never say this|.*health claims.*)$', core[:60]):
                    _add(core)
                # else: bare section header like "❌ NEVER SAY THIS" -> skip

        # --- bullet zone under a ban header (shape 2) ---
        if any(mk in low for mk in markers):
            j = i + 1
            while j < len(lines) and lines[j][:1] in _BULLET:
                _collect_ban_bullet(lines[j], _add)
                j += 1

    return banned


def _collect_ban_bullet(bullet: str, add) -> None:
    """Extract negated claim phrases from a single ban bullet line."""
    # skip bullets that don't prohibit anything (allowed-claims / strategy)
    if not _NEG.search(bullet):
        return
    # split into clauses; a negated phrase must sit in a clause carrying a negator.
    # The split must tolerate a closing smart quote after the punctuation —
    # 'No "boost." Use "support" instead.' has '.”' where the period sits inside
    # the closing quote; without allowing that, the whole line becomes one negated
    # clause and the ALLOWED replacement words get banned too.
    clauses = re.split(r'(?<=[.!;])["”\'’]?\s+', bullet)
    for clause in clauses:
        if not _NEG.search(clause):
            continue
        # drop an explicit allowed-substitute tail ("Use 'support' instead.")
        clause = re.sub(r'(?i)\b(?:use|say|replace)\s+.*?\binstead\b.*$', '', clause)
        quotes = [q.strip() for q in re.findall(r'["“”]([^"“”]{2,80})["“”]', clause)]
        for q in quotes:
            add(q)
        if quotes:
            continue  # the quotes already carry the prohibited wording
        # no quote — add the short de-negated core, e.g. "Never overnight" -> "overnight"
        c = re.sub(r'(?i)^\s*(?:and\s+)?(?:no|not|never|nothing|do not|don[’\'"]t|can[’\'"]t|cannot)(?:\s+say)?\s*[:,]?\s*', '', clause)
        c = re.sub(r'(?i)^(?:(?:a|an|the|any|my|your)\s+)+', '', c)
        c = re.sub(r'(?i)\s+(?:and|or)\s+(?:no|not|never|nothing|don[’\'"]t)\b.*$', '', c)
        add(c)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--brief", required=True, help="path to brief.txt")
    ap.add_argument("--output", required=True, help="path to write rules.json")
    ap.add_argument("--detail", default="", help="path to detail.json to merge the authoritative platform list")
    args = ap.parse_args()

    text = open(args.brief, encoding="utf-8", errors="ignore").read()
    rules = harvest(text)

    # The AUTHORITATIVE source for allowed platforms is the campaign detail page,
    # not regex heuristics over the brief. Merge it in when available.
    if args.detail and os.path.exists(args.detail):
        try:
            detail = json.load(open(args.detail, encoding="utf-8"))
            dp = [p.lower() for p in detail.get("platforms") or []]
            if dp:
                rules["platforms"] = dp
                rules["platforms_source"] = "detail.json"
        except Exception:
            pass
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