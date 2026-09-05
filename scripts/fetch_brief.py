#!/usr/bin/env python3
"""
Fetch a campaign's PUBLIC brief document (Google Doc or Drive folder) -> brief.txt.

Both are publicly readable without login — the doc via /export?format=txt, the
drive folder via its public listing. The script tries both and writes whatever
text it gets; the next step (parse_brief.py) will filter and structure it.

Usage:
    python3 scripts/fetch_brief.py --url "https://docs.google.com/document/d/.../edit?usp=sharing" --output tracker/campaigns/x/brief.txt
    python3 scripts/fetch_brief.py --dir tracker/campaigns/x
        # reads the first Google-Doc/Drive reference link from detail.json
        # and writes <dir>/brief.txt (the workflow's preferred invocation)
"""
import argparse
import json
import os
import re
import sys
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Chrome/120 Safari/605.1.15"

MIN_BRIEF = (
    "Promote the product. Must name where to buy it (retail line). "
    "5-8 slides, first slide is a hook. No banned health/weight-loss claims. "
    "Caption ends with one comment question. Include required hashtags."
)


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def fetch_google_doc(doc_url: str) -> str:
    """Convert /document/d/<id>/edit?usp=sharing to /export?format=txt and fetch."""
    m = re.search(r'/document/d/([a-zA-Z0-9_-]+)', doc_url)
    if not m:
        return ""
    doc_id = m.group(1)
    export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
    return fetch(export_url)


def fetch_drive_folder(drive_url: str) -> str:
    """Best-effort: hit the public folder listing and extract file names + links.
    This won't get file *contents* from Drive (requires auth / API), but it
    gives you the inventory. For actual assets you'll fall back to Pexels
    or the campaign's own explicit URLs in the brief text."""
    # The public folder page is HTML; we grab the listing text for now.
    return fetch(drive_url)


def pick_brief_url(detail: dict) -> str:
    """First reference material that looks like a brief: a Google Doc, or any
    Drive link. Prefer docs.google.com/document (the typical brief)."""
    refs = detail.get("reference_materials") or []
    # direct links, prefer documents over raw drive files
    docs = [r["url"] for r in refs if "docs.google.com/document" in r.get("url", "")]
    drives = [r["url"] for r in refs if "drive.google.com" in r.get("url", "")]
    return (docs + drives)[0] if (docs + drives) else ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", help="Google Doc / Drive URL from campaign detail")
    ap.add_argument("--output", help="path to write brief.txt")
    ap.add_argument("--dir", help="campaign dir (reads detail.json, writes brief.txt)")
    args = ap.parse_args()

    if args.dir:
        detail_path = os.path.join(args.dir, "detail.json")
        if not os.path.exists(detail_path):
            print("warning: no detail.json — using minimal brief", file=sys.stderr)
            url, output = "", os.path.join(args.dir, "brief.txt")
        else:
            detail = json.load(open(detail_path, encoding="utf-8"))
            url = pick_brief_url(detail)
            output = os.path.join(args.dir, "brief.txt")
        if not url:
            print("warning: no Google Doc / Drive link in detail.json — using minimal brief",
                  file=sys.stderr)
            os.makedirs(args.dir, exist_ok=True)
            with open(output, "w", encoding="utf-8") as f:
                f.write(MIN_BRIEF)
            print(f"wrote minimal brief -> {output}")
            return 0
    elif args.url and args.output:
        url, output = args.url, args.output
    else:
        print("ERROR: provide --dir, or --url + --output", file=sys.stderr)
        return 2

    text = ""
    if "docs.google.com/document" in url:
        text = fetch_google_doc(url)
    elif "drive.google.com" in url:
        text = fetch_drive_folder(url)

    if not text or len(text.strip()) < 20:
        print("warning: brief fetch returned empty/too-short text", file=sys.stderr)
        text = MIN_BRIEF

    out_dir = os.path.dirname(output) or "."
    os.makedirs(out_dir, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        f.write(text.strip() + "\n")
    print(f"wrote {len(text)} chars -> {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())