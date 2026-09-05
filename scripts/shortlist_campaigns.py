#!/usr/bin/env python3
"""
Whop Content Rewards — campaign scout (Tier 1 automation).

Fetches the public discovery page, extracts campaign data (brand, budget spent/total,
category, id/link, raw description), filters for ACTIVE (remaining budget) and
HIGH-PAYING (rate per 1K) campaigns, optionally scores them with an OpenRouter model,
and writes a shortlist.md.

Usage:
    python3 scripts/shortlist_campaigns.py [--min-rate 1.00] [--min-remaining 1000] \
        [--max-results 15] [--output shortlist.md]

Defaults: --min-rate 1.00 (drop campaigns below $1/1K when the rate is parseable)
          --min-remaining 1000 (drop near-exhausted campaigns; $1K remaining)

Filter intent: ACTIVE + HIGH-PAYING (per user). Niche is NOT a filter by default;
pass --keywords "ai,tech,gaming" to optionally bias ranking (not filter) toward a niche.

Model (optional): if OPENROUTER_API_KEY is set, an OpenRouter call fills in reliable
rates from the messy description text and scores each campaign. Set OPENROUTER_MODEL
to reuse whatever model you already use elsewhere (default: deepseek/deepseek-chat).
Never commits the key — reads it from the environment only.
"""

import argparse
import json
import os
import re
import sys
import urllib.request

DISCOVER_URL = "https://contentrewards.com/discover"
DEFAULT_MODEL = "deepseek/deepseek-chat"

UA = "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"


# ---------------------------------------------------------------- fetch
def fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="ignore")


# ---------------------------------------------------------------- parse
def num_field(html: str, key: str):
    return [float(m) for m in re.findall(r'\\"'+key+r'\\":([0-9]+(?:\.[0-9]+)?)', html)]


def str_field(html: str, key: str):
    return re.findall(r'\\"'+key+r'\\":\\"(.*?)\\"', html)


def parse_campaigns(html: str) -> list[dict]:
    spent  = num_field(html, "budgetSpentRaw")
    total  = num_field(html, "budgetTotalRaw")
    brand  = str_field(html, "brand")
    cats   = str_field(html, "category")
    funded = str_field(html, "fundedAgo")
    ids    = str_field(html, "id")
    descs  = re.findall(r'\\"description\\":\\"(.*?)\\"', html)

    n = min(len(spent), len(total), len(brand))
    campaigns = []
    for i in range(n):
        campaigns.append({
            "brand": brand[i].strip(),
            "spent": spent[i],
            "total": total[i],
            "remaining": total[i] - spent[i],
            "category": (cats[i] if i < len(cats) else "").strip(),
            "funded_ago": (funded[i] if i < len(funded) else "").strip(),
            "id": (ids[i] if i < len(ids) else "").strip(),
            "description": (descs[i] if i < len(descs) else "").strip(),
            "rate": None,       # best-effort local parse; refined by model
        })
    return campaigns


# Best-effort rate parse from messy free text. Returns $/1K or None.
def local_rate(desc: str) -> float | None:
    if not desc:
        return None
    d = desc.replace("\\n", " ").replace("\\\"", '"')
    patterns = [
        r'\$([0-9]+(?:\.[0-9]+)?)\s*/\s*1K',
        r'\$([0-9]+(?:\.[0-9]+)?)\s*per\s*1K',
        r'\$([0-9]+(?:\.[0-9]+)?)\s*for\s*every\s*1000',
        r'\$([0-9]+(?:\.[0-9]+)?)\s*per\s*1000',
        r'\$([0-9]+(?:\.[0-9]+)?)\s*CPM',
        r'([0-9]+(?:\.[0-9]+)?)\$?\s*pour\s*chaque\s*1000',
        r'\$([0-9]+(?:\.[0-9]+)?)\s*CPM\b',
    ]
    for p in patterns:
        m = re.search(p, d, re.I)
        if m:
            return float(m.group(1))
    return None


# ---------------------------------------------------------------- model pass
def openrouter_score(campaigns: list[dict], model: str) -> dict[str, dict]:
    """Ask OpenRouter to return reliable rate/1K + a shortlist score per campaign.
    Returns {brand: {rate, score, note}}."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return {}
    payload = [{
        "brand": c["brand"],
        "category": c["category"],
        "remaining_budget_usd": round(c["remaining"]),
        "funded_ago": c["funded_ago"],
        "description": c["description"][:600],
    } for c in campaigns]
    system = (
        "You are a Whop Content Rewards scout. For each campaign, return JSON with "
        "keys: brand, rate_per_1k (float or null if not stated), score (1-10, "
        "rewarding high rate + large remaining budget + clear clippable source), "
        "note (one short sentence). Only return the JSON array, nothing else."
    )
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
        content = data["choices"][0]["message"]["content"]
        # tolerate fenced json
        content = re.sub(r"^```(?:json)?|```$", "", content.strip()).strip()
        arr = json.loads(content)
        if isinstance(arr, dict):  # tolerate {"campaigns": [...]}
            arr = arr.get("campaigns", arr.get("results", []))
        out = {}
        for row in arr:
            if isinstance(row, dict) and "brand" in row:
                out[row["brand"]] = row
        return out
    except Exception as e:
        print(f"[warn] OpenRouter pass failed ({e}); falling back to local rates", file=sys.stderr)
        return {}


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="Whop campaign scout")
    ap.add_argument("--min-rate", type=float, default=1.00, help="drop below $/1K (if parseable)")
    ap.add_argument("--min-remaining", type=float, default=1000, help="drop below $ remaining budget")
    ap.add_argument("--max-results", type=int, default=15)
    ap.add_argument("--keywords", default="", help="optional comma list to bias ranking (not filter)")
    ap.add_argument("--platform", default="", help="only keep campaigns with this platform (e.g. youtube). Fetches detail pages to verify.")
    ap.add_argument("--output", default="shortlist.md")
    ap.add_argument("--html", default="", help="local html file to parse instead of fetching")
    args = ap.parse_args()

    html = open(args.html, encoding="utf-8", errors="ignore").read() if args.html else fetch_html(DISCOVER_URL)
    campaigns = parse_campaigns(html)
    if not campaigns:
        print("No campaigns parsed (site structure may have changed).", file=sys.stderr)
        return 1

    # local rate fill
    for c in campaigns:
        c["rate"] = local_rate(c["description"])

    # model refinement (optional)
    model = os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)
    scored = openrouter_score(campaigns, model)
    if scored:
        for c in campaigns:
            row = scored.get(c["brand"])
            if row:
                c["rate"] = row.get("rate_per_1k", c["rate"])
                c["model_score"] = row.get("score")
                c["model_note"] = row.get("note", "")

    # ---- filter: platform (fetches detail pages) ----
    if args.platform:
        want = args.platform.lower()
        print(f"Checking {len(active) if active else len(campaigns)} campaigns for platform='{want}'...")
        platform_ok = []
        to_check = active if active else campaigns
        for c in to_check:
            if not c.get("id"):
                continue
            try:
                detail_url = f"https://contentrewards.com/discover/{c['id']}"
                detail_html = fetch_html(detail_url)
                # extract platforms from detail page
                known = {"tiktok","instagram","youtube","facebook","twitter","x","snapchat","pinterest","threads"}
                plat_raw = re.findall(r'"platforms":\s*\[([^\]]*)\]', detail_html)
                if plat_raw:
                    tokens = re.findall(r'([A-Za-z0-9_]+)', plat_raw[0])
                    platforms = [t.lower() for t in tokens if t.lower() in known]
                else:
                    platforms = []
                c["platforms"] = platforms
                if want in platforms:
                    platform_ok.append(c)
                else:
                    print(f"  skip {c['brand']}: platforms={platforms}")
            except Exception as e:
                print(f"  skip {c['brand']}: detail fetch failed ({e})")
        campaigns = platform_ok
        active = platform_ok

    # ---- filter: ACTIVE + HIGH-PAYING ----
    active = [c for c in campaigns if c["remaining"] >= args.min_remaining]
    high = []
    for c in active:
        if c["rate"] is None:
            c["rate_flag"] = "?"   # rate not stated locally/model; keep but flag
            high.append(c)
        elif c["rate"] >= args.min_rate:
            c["rate_flag"] = "OK"
            high.append(c)
        # below-rate campaigns are dropped

    # ranking: remaining budget desc, then rate desc
    high.sort(key=lambda c: (-(c["remaining"]), -(c["rate"] or 0)))

    # de-duplicate by brand (keep highest-remaining entry)
    seen = set()
    deduped = []
    for c in high:
        if c["brand"] not in seen:
            seen.add(c["brand"])
            deduped.append(c)
    high = deduped[: args.max_results]

    # optional niche keyword bias (tie-break only, not a hard filter)
    kws = [k.strip().lower() for k in args.keywords.split(",") if k.strip()]
    if kws:
        def kwscore(c):
            blob = (c["brand"] + " " + c["category"] + " " + c["description"]).lower()
            return -sum(1 for k in kws if k in blob)
        high.sort(key=lambda c: (kwscore(c), -(c["remaining"])))

    # ---- write shortlist ----
    lines = [
        "# Whop Content Rewards — Campaign Shortlist",
        "",
        f"Generated: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')} UTC",
        f"Filter: active (≥ ${args.min_remaining:,.0f} remaining) + high-paying (≥ ${args.min_rate:.2f}/1K)",
        f"From {len(campaigns)} live campaigns → {len(high)} shortlisted.",
        "",
        "| Campaign | Rate/1K | Remaining | Total | Category | Funded | Score |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in high:
        rate = f"${c['rate']:.2f}" if c["rate"] is not None else "n/a"
        score = c.get("model_score", "")
        link = f"[{c['brand']}](https://contentrewards.com/discover/{c['id']})" if c["id"] else c["brand"]
        lines.append(
            f"| {link} | {rate} | ${c['remaining']:,.0f} | ${c['total']:,.0f} "
            f"| {c['category']} | {c['funded_ago']} | {score} |"
        )
    lines += [
        "",
        "## How to use this",
        "1. Open each campaign link, read the FULL rules, apply the 6-point filter "
        "(playbook/02-campaigns.md).",
        "2. Rate shown as n/a = not stated in the public description — verify in the brief.",
        "3. Only join after confirming remaining budget, allowed platforms, min payout, and caps.",
    ]
    if kws:
        lines += ["", f"_Niche keywords (bias only): {', '.join(kws)}_"]

    Path = __import__("pathlib").Path
    Path(args.output).write_text("\n".join(lines) + "\n")
    print(f"Shortlisted {len(high)} campaigns → {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
