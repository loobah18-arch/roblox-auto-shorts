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
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload)},
        ],
        "temperature": 0,
    }
    req_headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def _post(extra: dict) -> dict:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps({**body, **extra}).encode(),
            headers=req_headers,
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())

    try:
        try:
            # Prefer structured JSON, but not all models support response_format
            content = _post({"response_format": {"type": "json_object"}})["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            if e.code != 400:
                raise
            print(f"[warn] {model} rejects response_format json_object — retrying without it", file=sys.stderr)
            content = _post({})["choices"][0]["message"]["content"]
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
    ap.add_argument("--json", default="", help="also write machine-readable shortlist answers (id/brand/rate/remaining) for automation")
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

    # ---- filter: ACTIVE (cheap, local data) BEFORE the expensive detail fetches ----
    campaigns = [c for c in campaigns if c["remaining"] >= args.min_remaining]
    print(f"After active filter (≥ ${args.min_remaining:,.0f} remaining): {len(campaigns)} campaigns")

    # ---- filter: platform (fetches detail pages) ----
    # campaign_detail.py has tested escaped-JSON extraction — reuse its logic.
    try:
        from campaign_detail import extract as _detail_extract, DETAIL_URL as _BASE
    except ImportError:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        try:
            from campaign_detail import extract as _detail_extract
            _BASE = "https://contentrewards.com/discover/{}"
        except ImportError:
            _BASE = "https://contentrewards.com/discover/{}"
            def _detail_extract(html):
                return {}

    if args.platform:
        want = args.platform.lower()
        print(f"Checking {len(campaigns)} campaigns for platform='{want}'...")
        platform_ok = []
        for c in campaigns:
            if not c.get("id"):
                continue
            try:
                detail_html = fetch_html(_BASE.replace("{id}", c["id"]))
                detail = _detail_extract(detail_html)
                platforms = detail.get("platforms", [])
                c["platforms"] = platforms
                # Authoritative platform-specific rate from the payouts array
                for p in detail.get("payouts", []):
                    if p.get("platform") == want:
                        c["rate"] = p["rate_per_1k_usd"]
                # Media links from reference_materials. Raw footage can be in a
                # plain Drive folder/file OR hidden inside a Google Doc (the brief)
                # as hyperlinks — open docs to count real media (never stock).
                refs = detail.get("reference_links") or []
                try:
                    from media_links import all_media_links
                    m = all_media_links(detail.get("reference_materials") or [])
                    n_media = len(m["folders"]) + len(m["files"]) + len(m["direct"])
                except Exception:
                    n_media = len([u for u in refs if "drive.google.com" in u])
                c["drive_refs"] = n_media
                c["has_media"] = n_media > 0
                c["detail_refs"] = refs  # preserve for JSON output
                if want in platforms:
                    platform_ok.append(c)
                else:
                    print(f"  skip {c['brand']}: platforms={platforms}")
            except Exception as e:
                print(f"  skip {c['brand']}: detail fetch failed ({e})")
        campaigns = platform_ok

    # ---- filter: HIGH-PAYING (rate already refined per-platform from detail) ----
    high = []
    for c in campaigns:
        if c["rate"] is None:
            c["rate_flag"] = "?"   # rate not stated locally/model; keep but flag
            high.append(c)
        elif c["rate"] >= args.min_rate:
            c["rate_flag"] = "OK"
            high.append(c)
        # below-rate campaigns are dropped

    # ranking: campaigns that ship raw media first (drive_refs>0), then rate
    # desc (high-paying first), then remaining budget desc as a tie-break.
    high.sort(key=lambda c: (0 if c.get("drive_refs") else 1,
                             -(c["rate"] or 0), -(c["remaining"])))

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

    if args.json:
        top = []
        for c in high[: args.max_results]:
            top.append({
                "brand": c["brand"], "id": c.get("id"),
                "rate_per_1k": c["rate"], "remaining": c["remaining"],
                "total": c["total"], "category": c["category"],
                "has_media": bool(c.get("drive_refs")),
                "platforms": c.get("platforms") or [],
                "media_refs": c.get("detail_refs") or [],
            })
        Path(args.json).write_text(json.dumps({
            "generated_utc": __import__("datetime").datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "count": len(high), "top": top,
        }, indent=2) + "\n")
        print(f"Wrote machine-readable shortlist → {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
