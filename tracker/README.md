# Posting Tracker — Template + Sample Rows

Copy `tracker.csv` and log **every** post immediately. Never trust memory.

## Columns

`Date, Campaign, Source/Timecode, Hook Style, Value Layer, Platform, Views, Approval, Cap/Notes, Next Test`

- **Date** — date posted
- **Campaign** — which campaign (with rate/budget context)
- **Source/Timecode** — source file + start–end timestamp
- **Hook Style** — surprise / stakes / mechanism / reveal / takeaway (or a custom label)
- **Value Layer** — question / voiceover / graphic / sourced fact / narrative
- **Platform** — TikTok / Instagram / YouTube
- **Views** — current view count
- **Approval** — PENDING / APPROVED / FLAGGED / REJECTED / NOT SUBMITTED
- **Cap/Notes** — per-video cap, watermark, hashtags, any notes
- **Next Test** — the single variable to change next time

## Sample Rows (from the playbook)

| Date | Campaign | Source/Timecode | Hook Style | Value Layer | Platform | Views | Approval | Cap/Notes | Next Test |
|------|----------|-----------------|------------|-------------|----------|-------|----------|-----------|-----------|
| Aug 25 | Tech product campaign | Interview 02 / 12:14–12:43 | Contrarian lesson | Voiceover + diagram | TikTok | 8,240 | PENDING | $50 per video | Story-first opening |
| Aug 25 | Tech product campaign | Interview 02 / 12:14–12:43 | Story-first | Voiceover + diagram | Instagram | 3,160 | APPROVED | Required hashtag added | Shorten opening text |
| Aug 26 | Gaming campaign | Stream 01 / 23:07–23:35 | High-stakes question | On-screen route map | YouTube | — | NOT SUBMITTED | Confirm source audio rule | Submit when live |

## Weekly Review

Each week, export this CSV and run `../prompts/weekly-review.md` on it.
