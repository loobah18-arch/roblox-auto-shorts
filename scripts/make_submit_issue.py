#!/usr/bin/env python3
"""
Create a GitHub issue titled "Ready to submit: <campaign>" with the one manual step:
  paste the YouTube link into the Whop Content Rewards campaign page.

Reads:
  - detail.json (campaign title, URL)
  - upload_result.json (video_id, url)
  - script.json (title, hashtags)

Outputs:
  - submit_issue.md (the markdown body, ready to paste or post via `gh`)

Usage:
    python3 scripts/make_submit_issue.py --dir tracker/campaigns/clipfarm
    python3 scripts/make_submit_issue.py --dir tracker/campaigns/clipfarm --post   # actually creates the issue via gh
"""
import argparse
import json
import os
import subprocess
import sys

TITLE_PREFIX = "Ready to submit"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", required=True, help="campaign dir")
    ap.add_argument("--post", action="store_true", help="create the GitHub issue via `gh`")
    ap.add_argument("--repo", default="", help="owner/repo for gh (auto-detected if blank)")
    args = ap.parse_args()

    detail = json.load(open(os.path.join(args.dir, "detail.json"), encoding="utf-8"))
    slug = detail.get("slug", os.path.basename(args.dir))
    title_line = detail.get("title", slug)

    upload = {}
    up_path = os.path.join(args.dir, "upload_result.json")
    if os.path.exists(up_path):
        upload = json.load(open(up_path))

    script = {}
    sc_path = os.path.join(args.dir, "script.json")
    if os.path.exists(sc_path):
        script = json.load(open(sc_path, encoding="utf-8"))

    video_url = upload.get("url", "NOT YET UPLOADED")
    video_id = upload.get("video_id", "")
    yt_title = upload.get("title") or script.get("title", "")
    hashtags = script.get("hashtags") or []

    # find the Whop campaign page (public detail URL from detail.json)
    whop_url = detail.get("url", detail.get("detail_url", ""))

    issue_title = f"{TITLE_PREFIX}: {title_line}"

    body = f"""## Campaign: {title_line}
**Slug:** {slug}
**Whop page:** {whop_url}

---

## ✅ One manual step: paste the YouTube link into Whop

1. Open the campaign page above
2. Click **Submit clip** (or paste into the submission form)
3. Paste this URL:
   ```
   {video_url}
   ```
4. Done — the campaign will review and pay per 1K views

---

## Video details

| Field | Value |
|-------|-------|
| YouTube ID | `{video_id}` |
| YouTube URL | {video_url} |
| Script title | {yt_title} |
| Hashtags | {', '.join('#'+t for t in hashtags[:8])} |
| Status | {upload.get('status', 'unknown')} |

---

*Generated automatically by whop-producer pipeline.*
"""

    # write the issue body to file
    issue_path = os.path.join(args.dir, "submit_issue.md")
    with open(issue_path, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"Written {issue_path}")

    if not args.post:
        print(f"[PREVIEW] Issue title: {issue_title}")
        print("  Use --post to create the GitHub issue.")
        return 0

    # post via gh CLI
    cmd = ["gh", "issue", "create", "--title", issue_title, "--body", body]
    if args.repo:
        cmd += ["--repo", args.repo]
    print(f"Creating GitHub issue: {issue_title}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"gh issue create failed: {r.stderr}", file=sys.stderr)
        return 1
    print(f"Issue created: {r.stdout.strip()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
