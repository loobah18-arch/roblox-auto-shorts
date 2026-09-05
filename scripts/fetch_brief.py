#!/usr/bin/env python3
"""
Fetch a campaign's PUBLIC brief document (Google Doc or Drive folder) -> brief.txt.

Both are publicly readable without login — the doc via /export?format=txt, the
drive folder via its public listing. The script tries both and writes whatever
text it gets; the next step (parse_brief.py) will filter and structure it.

Usage:
    python3 scripts/fetch_brief.py --url "https://docs.google.com/document/d/.../edit?usp=sharing" --output tracker/campaigns/x/brief.txt
"""
import argparse
import os
import re
import sys
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Chrome/120 Safari/605.1.15"


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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", required=True, help="Google Doc / Drive URL from campaign detail")
    ap.add_argument("--output", required=True, help="path to write brief.txt")
    args = ap.parse_args()

    text = ""
    if "docs.google.com/document" in args.url:
        text = fetch_google_doc(args.url)
    elif "drive.google.com" in args.url:
        text = fetch_drive_folder(args.url)

    if not text or len(text.strip()) < 20:
        print("warning: brief fetch returned empty/too-short text", file=sys.stderr)

    out_dir = os.path.dirname(args.output) or "."
    os.makedirs(out_dir, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(text.strip() + "\n")
    print(f"wrote {len(text)} chars -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())