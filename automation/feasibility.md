# Automation Feasibility — What Can & Cannot Be Automated

**Read this before building any GitHub Actions / CI pipeline.** The playbook is a **human-in-the-loop system by design**. Full autopilot (fetch → cut → post → submit) is not achievable — here's why.

---

## What CAN Be Automated (Locally / CI)

| Task | How | Notes |
|------|-----|-------|
| **Transcript → Clip Finder input** | `scripts/prepare_transcript.py` | Just string templating. Run locally or in CI. |
| **Tracker CSV → Weekly Review input** | `scripts/weekly_review_prep.py` | String templating. |
| **Clip scoring table → Markdown/CSV** | Post-process Claude output | The Clip Finder returns a table; parse it to structured data. |
| **Folder structure creation** | Shell script / Makefile | `mkdir -p campaign/{name}/{source,transcript,project,export,links}` |
| **Tracker template enforcement** | CI lint on CSV | Ensure required columns exist, no missing fields. |
| **Weekly review scheduling** | GitHub Actions `schedule` trigger | Runs the prep script, reminds you to paste output to Claude. |
| **Campaign sheet lint** | Validate `RULES.md` has all required fields | `rate`, `budget_remaining`, `min_payout`, `platforms`, `length_min`, `length_max`, `required_hashtags`, `watermark`, etc. |

## What CANNOT Be Automated (Hard Blockers)

### 1. Campaign Discovery & Joining — No Public API

- Whop Content Rewards has **no public API** for listing campaigns, checking remaining budget, or joining.
- The discovery page (`contentrewards.com/discover`) is a **private web app** behind auth.
- You must manually browse, read rules, click "Join."
- *Workaround:* Manual step. No way around this.

### 2. Accessing Approved Assets — No Programmatic Access

- Campaigns provide approved videos/audio/transcripts via **private Whop pages** or download links after joining.
- No API to list or download assets.
- Transcripts are often PDFs or plain text in the campaign brief, not served via API.
- *Workaround:* You download manually, drop in `source/` and `transcript/`.

### 3. Clip Verification (Step 4) — Requires Human Eyes

> "Claude identifies structure but **cannot reliably judge the visual reveal, facial reaction, or how a line was delivered**." — Playbook

You must:
- Play 20s before/after each candidate in the *actual footage*.
- Confirm the hook isn't out of context.
- Find the frame that proves the opening claim.
- Reject clips needing misleading headlines.

No AI can do this reliably. It's a **visual + contextual judgment**.

### 4. Editing (Step 5) — Creative, Not Mechanical

The playbook requires **one value layer per clip**:
- Truthful question / voiceover / graphic / sourced fact / new narrative.
- Timeline structure: 0–2s hook → 2–22s forward motion → final proof/payoff.

This is creative editing. CapCut / ffmpeg can *execute* cuts, but **deciding what to add and where** is human work.

### 5. Posting — Platform APIs Are Restricted

- **TikTok**: Creator Marketplace API requires application/approval; posting API is restricted.
- **Instagram Reels**: Graph API requires Business verification + app review; posting is gated.
- **YouTube Shorts**: YouTube Data API v3 allows upload, but **Shorts shelf placement is not guaranteed**; quotas are tight.

Even if you get API access, you still need:
- Campaign-specific hashtags, watermark, caption, links, disclosures per post.
- Platform-specific aspect ratio, length limits.
- **You must manually verify the post is live and correct** before submitting to Whop.

### 6. Submission to Whop — No API

- Submitting a post URL + media file to a campaign is a **manual web form** on Whop.
- No public API for submission or checking approval status.
- Approval status (`pending` / `approved` / `flagged` / `rejected`) is only visible in the Whop dashboard.

### 7. Payout Verification — Human Check

- You must check: is the post approved? Did views qualify? Did it hit the cap? Is budget still available?
- These are shown only in the Whop dashboard.

---

## The Honest Automation Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        HUMAN LOOP (REQUIRED)                    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │ 1. Discover │  │ 4. Verify   │  │ 5. Edit +   │             │
│  │    campaign │  │    clips    │  │  add value  │             │
│  │  (manual)   │  │  (manual)   │  │  (manual)   │             │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘             │
└─────────┼────────────────┼────────────────┼────────────────────┘
          │                │                │
          ▼                ▼                ▼
┌─────────────────────────────────────────────────────────────────┐
│                   AUTOMATABLE GLUE (SCRIPTS/CI)                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │ 2. Transcript│  │ 3. Clip     │  │ 6. Log +    │             │
│  │  → prompt   │  │  Finder     │  │  weekly     │             │
│  │  (script)   │  │  (Claude)   │  │  review     │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
└─────────────────────────────────────────────────────────────────┘
```

**The bottleneck is human judgment — not script speed.**

---

## What a "GitHub Integration" Realistically Looks Like

A useful repo setup gives you:
- **Reminders** to do the manual steps (via GitHub Actions schedule).
- **Templates** so you don't forget fields (campaign sheet, tracker).
- **Lint** to catch missing data before you submit.
- **Prep scripts** that format your clipboard-ready prompts for Claude.

It does **not** give you:
- Auto-fetching campaigns.
- Auto-downloading assets.
- Auto-cutting verified clips.
- Auto-posting to TikTok/IG/YouTube.
- Auto-submitting to Whop.

---

## Recommendation

1. **Use this repo as a local toolkit** (scripts, prompts, templates, tracker). Run prep scripts locally.
2. **Optionally add a GitHub Actions workflow** that:
   - Runs weekly to remind you to do the Weekly Review.
   - Lints your `tracker.csv` and campaign `RULES.md` on push.
   - Generates the Clip Finder / Weekly Review input files as artifacts you can download.
3. **Do not** try to build a "fully automated pipeline." It will fail at steps 1, 2, 4, 5, 6, 7 above — and waste time.

The playbook works *because* of the human checks. The automation is only the glue between them.