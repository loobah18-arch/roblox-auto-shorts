#!/usr/bin/env python3
"""
Fetch a Whop Content Rewards campaign's PUBLIC detail page -> detail.json.

No login required. Content Rewards' /discover/<id> page is a public Next.js page
whose RSC payload carries the campaign record: title, platforms, a per-platform
payouts array (rate/min/max in cents), reference-material links (brand assets,
usually Google Docs / Drive), whether it needs an application, and status.

Budget columns (budgetSpentRaw/budgetTotalRaw) are NOT here — they come from the
discovery listing, which the scout (shortlist_campaigns.py) already parses.

Usage:
    python3 scripts/campaign_detail.py --id <uuid> --output tracker/campaigns/x/detail.json
    python3 scripts/campaign_detail.py --id <uuid> --output x.json --html local.html  # offline test
"""
import argparse
import json
import os
import re
import sys
import urllib.request

UA = "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"
DETAIL_URL = "https://contentrewards.com/discover/{id}"
KNOWN_PLATFORMS = {"tiktok", "instagram", "youtube", "facebook", "twitter", "x",
                   "snapchat", "pinterest", "threads"}


def esc(key: str) -> str:
    # backslash-escaped JSON keys inside Next.js RSC payloads: \"key\":
    return r'\\"' + re.escape(key) + r'\\"'


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def unesc(s: str) -> str:
    """RSC payloads double-quote strings; peel the escaping so plain JSON regex works.
    Also decodes \\uXXXX escapes (e.g. Drive URLs carry \\u0026 for &)."""
    s = s.replace('\\"', '"').replace('\\/', '/')
    return re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), s)


def extract(html: str) -> dict:
    d: dict = {}

    title = re.findall(esc("title") + r':\\"(.*?)\\"', html)
    d["title"] = title[0].strip() if title else ""

    deep = unesc(html)

    # platforms: \"platforms\":[\"tiktok\"] or [\"instagram\",\"tiktok\",\"youtube\"]
    plat_raw = re.findall(esc("platforms") + r':\[(.*?)\]', html)
    d["platforms"] = []
    if plat_raw:
        tokens = re.findall(r'([A-Za-z0-9_]+)', plat_raw[0])
        d["platforms"] = [t.lower() for t in tokens if t.lower() in KNOWN_PLATFORMS]

    # payouts array: [{"rateCents":100,"minPayoutCents":100,"maxPayoutCents":40000,"platform":"tiktok",...}]
    payouts = []
    arr = re.search(esc("payouts") + r':\[(.*?)\](?:,\\"payoutType\\")', html)
    if arr:
        for obj in re.finditer(r'\{([^{}]*)\}', unesc(arr.group(1))):
            o = obj.group(1)
            p = {}
            for key in ("platform", "payoutType"):
                mm = re.search(r'"' + key + r'":"([^"]+)"', o)
                if mm:
                    p[key] = mm.group(1)
            for key, okey in (("rateCents", "rate_per_1k_usd"), ("minPayoutCents", "min_payout_usd"),
                              ("maxPayoutCents", "max_payout_usd")):
                mm = re.search(r'"' + key + r'":([0-9]+)', o)
                if mm:
                    p[okey] = int(mm.group(1)) / 100.0
            if p:
                payouts.append(p)
    d["payouts"] = payouts
    if payouts:
        rates = [p["rate_per_1k_usd"] for p in payouts if p.get("rate_per_1k_usd") is not None]
        mins = [p["min_payout_usd"] for p in payouts if p.get("min_payout_usd") is not None]
        maxs = [p["max_payout_usd"] for p in payouts if p.get("max_payout_usd") is not None]
        d["primary_rate_per_1k_usd"] = rates[0] if rates else None
        d["payout_min_usd"] = min(mins) if mins else None
        d["payout_max_usd"] = max(maxs) if maxs else None

    # reference materials: [{"mediaType":"external","type":"brandAsset","url":"https://..."}]
    refs = []
    rarr = re.search(esc("referenceMaterials") + r':\[(.*?)\](?:,\\"requiresApplication\\")', html)
    if rarr:
        for obj in re.finditer(r'\{([^{}]*)\}', unesc(rarr.group(1))):
            o = obj.group(1)
            u = re.search(r'"url":"([^"]+)"', o)
            t = re.search(r'"type":"([^"]+)"', o)
            if u:
                refs.append({"url": u.group(1), "type": t.group(1) if t else ""})
    d["reference_materials"] = refs
    d["reference_links"] = [r["url"] for r in refs]

    ra = re.search(esc("requiresApplication") + r':(true|false)', html)
    d["requires_application"] = (ra.group(1) == "true") if ra else None
    st = re.search(esc("status") + r':\\"(.*?)\\"', html)
    d["status"] = st.group(1) if st else ""

    return d


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--id", required=True, help="campaign uuid from the scout shortlist")
    ap.add_argument("--output", required=True, help="path to write detail.json")
    ap.add_argument("--html", default="", help="read a local html file instead of fetching (tests)")
    args = ap.parse_args()

    html = open(args.html, encoding="utf-8", errors="ignore").read() if args.html else fetch(
        DETAIL_URL.format(id=args.id)
    )
    detail = extract(html)
    detail["id"] = args.id
    detail["url"] = DETAIL_URL.format(id=args.id)

    out_dir = os.path.dirname(args.output) or "."
    os.makedirs(out_dir, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(detail, f, indent=2, ensure_ascii=False)
    print(json.dumps(detail, indent=2, ensure_ascii=False))
    return 0 if detail.get("title") else 2


if __name__ == "__main__":
    sys.exit(main())