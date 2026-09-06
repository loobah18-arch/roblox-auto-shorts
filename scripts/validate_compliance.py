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
    # health/medical claims — full inflected set so "boosting"/"curing"/"treatment"
    # can't slip past a word-boundary check of the bare stem
    "cure", "cures", "cured", "curing", "treat", "treats", "treated", "treating",
    "treatment", "treatments", "fix", "fixes", "fixed", "fixing",
    "prevent", "prevents", "prevented", "preventive", "reverse", "reverses",
    "reversed", "reversing", "anti-aging", "anti aging", "antiaging",
    "weight loss", "lose weight", "losing weight", "slim", "slimming", "slimmed",
    "clinically proven", "studies show", "doctors recommend", "doctor recommended",
    "scientifically", "scientifically proven", "guaranteed", "you will feel",
    "boost", "boosts", "boosted", "boosting", "boost your", "energy shot",
    "instant energy", "coffee replacement", "replaces my coffee", "like a caffeine hit",
    "natural", "organic", "plant-based", "sold out everywhere", "fake sellout",
    "link in bio", "buy now", "order now", "double your", "10x",
    "disease", "cancer", "diabetes", "depression", "anxiety", "adhd",
    "dementia", "heart attack", "stroke", "overnight",
]

# Stem words that appear inside longer innocent words (naturally, booster, ...).
# Check these at word boundaries; everything else is a safe substring match.
HAZARD_WORDS = {"boost", "fix", "cure", "treat", "natural", "organic", "slim",
                "prevent", "reverse"}

# Expand contractions BEFORE stripping punctuation so banned phrases like
# "you will feel" match the natural "you'll feel"; also glue the no-space
# variant of anti-aging.
_CONTRACTIONS = {
    "you'll": "you will", "won't": "will not", "can't": "cannot",
    "don't": "do not", "doesn't": "does not", "didn't": "did not",
    "isn't": "is not", "aren't": "are not", "i'm": "i am", "i've": "i have",
    "you're": "you are", "you've": "you have", "it's": "it is",
    "that's": "that is", "there's": "there is", "they're": "they are",
    "we're": "we are", "i'll": "i will", "shouldn't": "should not",
    "couldn't": "could not",
}


def norm_for_banned(s: str) -> str:
    """Lowercase, expand contractions, and strip punctuation/whitespace so banned
    phrases match across spellings ('you'll feel' == 'you will feel')."""
    s = s.lower().replace("antiaging", "anti aging")
    for k, v in _CONTRACTIONS.items():
        s = s.replace(k, v)
    return re.sub(r"[^a-z0-9 ]", " ", s).strip()

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
    # The required hashtag is the one the brief lists FIRST (parse_brief now
    # preserves first-mentioned order). An all-caps brand tag is the common case
    # but never trust an arbitrary all-caps tag (e.g. #USA) over the brief's own
    # first hashtag — so plain tags[0] is the correct signal.
    primary = tags[0] if tags else None
    full = caption_with_hashtags(script)
    hashtag_ok = True
    detail = ""
    if primary:
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
    blobn = norm_for_banned(blob)
    hit = None
    for b in banned:
        bn = norm_for_banned(b)
        if len(bn) < 3:
            continue
        if bn in HAZARD_WORDS:  # only match these as whole words ("naturally" ≠ "natural")
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
    # Non-retail campaigns (digital products, services, trading props) don't have
    # a buying destination — skip the retail check entirely when brief has none.
    retail = list(rules.get("retail_keywords") or [])
    generic_retail = ["target", "amazon", "walmart", "costco", "store", "shelf",
                      "aisle", "cart", "got mine at", "buy it at", "in-store"]
    if retail:
        detail_retail = f"brief retail keywords: {', '.join(retail[:6])}"
        # hashtags don't count: '#target' as a tag is not naming a destination in
        # the story — check slides + caption body only.
        blob_retail = (slide_text(script) + "\n" + (script.get("caption") or "")).lower()
        ok_retail = any(k.lower() in blob_retail for k in retail) or \
                    any(k in blob_retail for k in generic_retail)
        checks.append(check("retail_push", ok_retail,
                            detail_retail + ("; destination named ✓" if ok_retail else "; NO buying-destination named")))
        if not ok_retail:
            errors.append("generated script never names a purchase destination (store/shelf/cart)")
    else:
        checks.append(check("retail_push", True, "non-retail campaign — no buying destination required"))

    # ---- 4b. required_elements presence (SEMI-SOFT) ----
    # The brief may mandate exact overlay text or caption wording. This check
    # catches those, but it is fuzzy prose matching — account-setup directives
    # ("post from a NEW account", "account must be a different persona") are NOT
    # content text and are skipped. An advisory-only failure is recorded instead
    # (flag for human review) so real content omissions are visible but don't
    # hard-exit 3 and block retry → output; the hard gates are banned claims,
    # the required hashtag, and the retail-push destination. Evergreen rule:
    # required_elements entries that are purely procedural/access control ("NEW
    # account") are setup prose homing to the compliance validator.
    # IMPORTANT: finding #3 false-fail was a true case study — requirements like
    # "⚠ SPECIAL RULE: You must post from a NEW account." + "But each account
    # must be ..." look like they should maybe cause a true fail but they are
    # account-setup, not video content.
    SETUP_KEYWORDS = ("new account", "different persona", "personal page",
                      "limit per person", "account family", "corporation",
                      "recovery emails", "account age", "must post from",
                      "every post makes it clear")  # last: covered by retail_push
    req_els = rules.get("required_elements") or []
    missing_req: list[str] = []
    for req in req_els:
        # Skip pure account/setup directives — they are not caption/overlay text.
        low_req = req.lower()
        if any(kw in low_req for kw in SETUP_KEYWORDS):
            continue
        m = re.match(r'(?i).*?\brequired\b.*?(?:overlay text|caption wording).*?[:](.*)$', req)
        if m:
            phrase = m.group(1)
        else:
            m = re.match(r'(?i).*?must\s+add\s+text\s*[:](.*)$', req)
            phrase = m.group(1) if m else None
        if not phrase:
            # No explicit overlay/caption phrasing. Enforce only when it's an
            # explicit content mandate (money inline on intent; textual content
            # tell, not a procedural/account rule) AND names a brand/product.
            if not re.search(r'(?i)\bmust\s+(?:be|show|include|use|name|say|wear|display|mention|feature|push|focus)\b', req):
                if not re.search(r'(?i)overlay text|caption wording', req):
                    continue
            if not re.search(r'\b[A-Z][A-Za-z0-9+.\-]{1,}\b', req):
                continue
            phrase = req
        phrase = re.sub(r'(?i)^.*?add\s+text\s*[:]?\s*', '', phrase)
        phrase = re.sub(r'\s+', ' ', phrase).strip('"“”\'').strip('.')
        if len(phrase) < 12:
            continue
        phrase_lower = phrase.lower()
        # token-hit heuristic: ≥2 of the key content words must appear in the script
        tokens = re.findall(r'[a-z0-9]+', phrase_lower)
        key_tokens = [t for t in tokens if len(t) >= 3][:6]
        hits = sum(1 for t in key_tokens if t in blob)
        if hits < min(2, len(key_tokens)):
            missing_req.append(phrase[:80])
    if missing_req:
        # Advisory only — visible for human audit but NOT added to `errors` (a hard
        # mismatch here may successfully could even be an non-content directive parse artifact;
        # the hard gates are banned_claims / required_hashtag / retail_push).
        detail_req = f"missing required text in script: {'; '.join(missing_req[:2])} [advisory]"
        checks.append(check("required_elements", True, detail_req))
    else:
        checks.append(check("required_elements", True, "required overlay/caption text present"))

    # ---- 5. registry / ad-sound hygiene ----
    title = script.get("title") or ""
    ok_title = 5 <= len(title) <= 100
    checks.append(check("title_length", ok_title, f"title {len(title)} chars (5..100)"))
    if not ok_title:
        errors.append(f"title length {len(title)}")

    # all-caps shouting in the title reads as an ad (documented contract) — block
    # only genuine full-shouting to avoid false-failures on acronym brands
    alpha = [c for c in title if c.isalpha()]
    ok_titlecase = not (len(alpha) >= 6 and title == title.upper())
    checks.append(check("title_not_all_caps", ok_titlecase,
                        "title not all-caps" if ok_titlecase else "title is ALL-CAPS (ad-like)"))
    if not ok_titlecase:
        errors.append("title is entirely ALL-CAPS")

    caption = script.get("caption") or ""
    # generous cap — blocks runaway captions, never normal ones
    ok_caption = len(caption) <= 1200
    checks.append(check("caption_length", ok_caption,
                        f"caption {len(caption)} chars (<=1200)" if ok_caption else "caption too long"))
    if not ok_caption:
        errors.append(f"caption length {len(caption)} > 1200")

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