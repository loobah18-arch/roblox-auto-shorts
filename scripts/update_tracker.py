#!/usr/bin/env python3
"""
Append a campaign run to the tracker CSV + update state.json.

tracker.csv columns:
  date, campaign_slug, campaign_title, rate_per_1k, payout_max,
  video_url, status, script_file, build_time_s

state.json:
  { "last_run": "...", "total_runs": N, "campaigns_done": ["slug1","slug2"] }

Usage:
    python3 scripts/update_tracker.py --dir tracker/campaigns/clipfarm
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone

TRACKER_CSV = "tracker/tracker.csv"
STATE_JSON = "tracker/state.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", required=True, help="campaign dir with detail.json + script.json")
    ap.add_argument("--repo-root", default=".", help="repo root (where tracker/ lives)")
    args = ap.parse_args()

    detail = json.load(open(os.path.join(args.dir, "detail.json"), encoding="utf-8"))
    script = json.load(open(os.path.join(args.dir, "script.json"), encoding="utf-8"))
    slug = detail.get("slug", os.path.basename(args.dir))
    title = detail.get("title", slug)
    rate = detail.get("payouts", [{}])[0].get("rate_per_1k_usd", 0) if detail.get("payouts") else 0
    payout_max = detail.get("payouts", [{}])[0].get("max_payout_usd", 0) if detail.get("payouts") else 0

    # read upload result if present
    upload_path = os.path.join(args.dir, "upload_result.json")
    if os.path.exists(upload_path):
        upload = json.load(open(upload_path))
        video_url = upload.get("url", "")
        status = upload.get("status", "built")
    else:
        video_url = ""
        status = "built"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # append to CSV
    csv_path = os.path.join(args.repo_root, TRACKER_CSV)
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    file_exists = os.path.exists(csv_path)
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not file_exists:
            w.writerow(["date", "campaign_slug", "campaign_title", "rate_per_1k", "payout_max",
                         "video_url", "status", "script_file", "attempt"])
        meta = script.get("_meta", {})
        w.writerow([now, slug, title, rate, payout_max, video_url, status,
                     os.path.basename(args.dir) + "/script.json", meta.get("attempt", "")])

    # update state.json
    state_path = os.path.join(args.repo_root, STATE_JSON)
    state = {}
    if os.path.exists(state_path):
        state = json.load(open(state_path, encoding="utf-8"))

    state["last_run"] = now
    state["total_runs"] = state.get("total_runs", 0) + 1
    done = state.get("campaigns_done", [])
    if slug not in done:
        done.append(slug)
    state["campaigns_done"] = done

    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

    print(f"tracker: appended {slug} ({status}), total_runs={state['total_runs']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
