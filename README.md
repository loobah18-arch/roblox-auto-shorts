# The Whop Clipping Playbook — Claude AI Edition

A full, structured clone of the playbook from **https://luminous-moonbeam-5488da.netlify.app/** (companion to the YouTube tutorial *"Claude AI + Whop Clipping = $6,500/Month"*).

This is a **content-work system**, not a money printer. Whop Content Rewards pays per approved, eligible view. Claude is a **clip-research assistant** that finds and ranks story moments — it does not automate posting or replace human judgment.

## Core Loop

```
Find → Clip → Submit → Learn
```

## Repo Layout

```
whop-clipping-playbook/
├── README.md                 ← you are here
├── playbook/                 ← the full method, section by section
│   ├── 00-overview.md        ← how payment works, the core loop
│   ├── 01-setup.md           ← non-negotiable setup before starting
│   ├── 02-campaigns.md       ← discovery, niche guide, 6-point filter
│   ├── 03-workflow.md        ← the 6-step workflow + worked example
│   ├── 04-payouts.md         ← payout stages, 3 traps, calculator
│   └── 05-30day-plan.md      ← 30-day starting plan + closing principle
├── prompts/                  ← the two Claude prompts, verbatim
│   ├── clip-finder.md
│   └── weekly-review.md
├── tracker/
│   ├── tracker.csv           ← the posting log (template + sample rows)
│   └── folder-structure.md   ← campaign/source/transcript/project/export/links
├── scripts/                  ← local helpers
│   ├── prepare_transcript.py ← transcript+rules → Clipboard Finder prompt
│   ├── weekly_review_prep.py ← tracker CSV → Weekly Review prompt
│   └── shortlist_campaigns.py← ★ scout: fetch → filter active+high-paying → shortlist.md
├── .github/workflows/
│   ├── scout.yml             ← ★ daily: runs the scout, posts shortlist as an issue
│   ├── weekly-review.yml     ← weekly reminder + CSV lint + prompt artifact
│   └── clip-finder-prep.yml  ← manual: build a ready-to-paste Clip Finder prompt
└── automation/
    ├── feasibility.md        ← ★ what CAN and CANNOT be automated (read this first)
    └── github-actions.md     ← realistic GH Actions setup
```

## Quick Start

1. Read `playbook/00-overview.md` → `01-setup.md` (do the setup before anything else).
2. Use `playbook/02-campaigns.md` to shortlist 3 campaigns and run the 6-point filter.
3. Join 1–2 campaigns. Read every rule. Set up `tracker/` folders.
4. For each source: paste approved transcript + campaign rules into `prompts/clip-finder.md`.
5. Verify manually, edit to add value, post, submit, log. See `playbook/03-workflow.md`.
6. Weekly: export your CSV, run `prompts/weekly-review.md`.

> **Before you build any automation, read `automation/feasibility.md`.** The playbook is a human-in-the-loop system by design, and full autopilot (fetch → cut → post → submit) is not achievable — see why there.

## Scout (the automated part)

`scripts/shortlist_campaigns.py` fetches the public Whop discovery page, filters **active** (remaining budget) + **high-paying** (rate/1K) campaigns, optionally scores them with your OpenRouter key, and writes `shortlist.md`. Run it:

```bash
# pure data filter (no key needed)
python3 scripts/shortlist_campaigns.py

# with model scoring (uses OPENROUTER_API_KEY + OPENROUTER_MODEL)
OPENROUTER_API_KEY=... python3 scripts/shortlist_campaigns.py
```

Push to GitHub and the `scout.yml` workflow does the same daily, posting the shortlist as an issue. **You** then open each link and do the human 6-point filter — join, verify, edit, post, submit.
