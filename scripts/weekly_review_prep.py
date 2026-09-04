#!/usr/bin/env python3
"""
Helper: prepare weekly review input from tracker CSV.
Usage: python3 weekly_review_prep.py tracker.csv --output weekly_review_input.txt
"""

import argparse
from pathlib import Path

WEEKLY_REVIEW_PROMPT = """Analyse this CSV of my own Whop campaign posts.

Do not claim causation from small samples. Separate observations from hypotheses. Flag campaigns that cannot be compared because their rates, caps, or approval rules differ.

Return:
1. The three strongest patterns among posts with the best qualified-view performance.
2. The three patterns among weak posts.
3. Results by hook type, source type, clip length, platform, and value-add layer.
4. Five next tests. Each test must change only one variable.
5. Data-quality issues: pending approvals, caps, missing fields, or non-comparable campaigns.

CSV:
{CSV_CONTENT}
"""

def main():
    parser = argparse.ArgumentParser(description="Prepare Weekly Review input from tracker CSV")
    parser.add_argument("tracker", help="Path to tracker CSV file")
    parser.add_argument("--output", default="weekly_review_input.txt", help="Output file")
    args = parser.parse_args()

    tracker_path = Path(args.tracker)
    if not tracker_path.exists():
        print(f"Error: tracker not found at {tracker_path}")
        return 1

    csv_content = tracker_path.read_text().strip()
    output = WEEKLY_REVIEW_PROMPT.format(CSV_CONTENT=csv_content)
    Path(args.output).write_text(output)
    print(f"Written to {args.output} — paste into claude.ai")
    return 0

if __name__ == "__main__":
    exit(main())