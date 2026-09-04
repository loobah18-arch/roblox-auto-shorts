#!/usr/bin/env python3
"""
Helper: prepare an approved transcript for the Clip Finder prompt.
Usage: python3 prepare_transcript.py transcript.txt --campaign "Campaign Name" --output clip_finder_input.txt
"""

import argparse
import textwrap
from pathlib import Path

CLIP_FINDER_PROMPT = """I have permission from the campaign owner to use the transcript below. Act as a senior short-form editor.

Find 12 candidate clips. Return a table with:
- Exact source start/end timestamps. Do not invent them.
- Verbatim first line that could open the short.
- The viewer question / curiosity gap.
- Setup → tension → payoff.
- Best emotion: surprise, conflict, utility, awe, humour, status, or relief.
- One fact-risk item to verify in the original footage.
- One materially useful value-add: a short voiceover, context graphic, sourced comparison, or framing question.
- A score out of 10. Reject weak soundbites with no payoff.

Rules:
- Prioritise 20–45 seconds unless a longer story is necessary.
- Do not write claims that are not in the source.
- Do not use a clip if the viewer needs too much missing context.

Campaign rules:
{CAMPAIGN_RULES}

Transcript:
{TRANSCRIPT}
"""

def main():
    parser = argparse.ArgumentParser(description="Prepare Clip Finder input from transcript + rules")
    parser.add_argument("transcript", help="Path to approved transcript file")
    parser.add_argument("--campaign", required=True, help="Campaign name (to load rules)")
    parser.add_argument("--rules-file", help="Path to campaign rules file (default: campaign/<name>/RULES.md)")
    parser.add_argument("--output", default="clip_finder_input.txt", help="Output file")
    args = parser.parse_args()

    transcript_path = Path(args.transcript)
    if not transcript_path.exists():
        print(f"Error: transcript not found at {transcript_path}")
        return 1

    transcript = transcript_path.read_text().strip()

    # Load campaign rules
    if args.rules_file:
        rules_path = Path(args.rules_file)
    else:
        rules_path = Path("campaign") / args.campaign / "RULES.md"

    if rules_path.exists():
        rules = rules_path.read_text().strip()
    else:
        rules = f"[RULES NOT FOUND AT {rules_path} — PASTE MANUALLY]"

    output = CLIP_FINDER_PROMPT.format(CAMPAIGN_RULES=rules, TRANSCRIPT=transcript)
    Path(args.output).write_text(output)
    print(f"Written to {args.output} — paste into claude.ai")
    return 0

if __name__ == "__main__":
    exit(main())