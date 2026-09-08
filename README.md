# Bhaloo Ji Shorts

Automated, scheduled uploader for **Bhaloo Ji** — a kids + dog comedy Shorts
channel. Every day the pipeline picks the next video in the queue, pairs it with
its hand-written title/description/tags, and uploads it to YouTube as a Short.

This repo was created by moving the code from `roblox-auto-shorts` into its own
home, and adding the shorts-specific upload pipeline on top.

## What's here

- `video_metadata.json` — title, description, tags, and source file for all 18 videos
- `videos/` — the 18 `.mp4` shorts (AI-generated, kids + golden retriever comedy)
- `scripts/upload_short.py` — picks the next video from `tracker/state.json`,
  uploads it to YouTube (preview or live), and advances the queue
- `.github/workflows/upload-shorts.yml` — the scheduled workflow
- `scripts/`, `playbook/`, `prompts/`, `automation/`, `tracker/` — the code
  migrated verbatim from `roblox-auto-shorts` (Whop Content Rewards pipeline)

The older Whop-pipeline workflows (`scout.yml`, `weekly-review.yml`,
`auto-produce.yml`) are preserved too, but their `schedule:` triggers were removed
so they don't auto-run in this repo — they need API secrets that aren't set here.
They still run manually via **Actions → Run workflow**. The shorts uploader lives
in `upload-shorts.yml`.

## How the scheduled upload works

1. `cron: "23 10 * * *"` fires **every day at 10:23 UTC** (edit in
   `.github/workflows/upload-shorts.yml`).
2. `upload_short.py` reads `tracker/state.json` → `next_index` and picks the next
   video in `video_metadata.json` order.
3. It reads that video's `title` / `description` (hashtags included) / `tags` and
   uploads `videos/<id>.mp4` to the Bhaloo Ji channel as a public Short.
4. On success it writes `state.json` back (`next_index + 1`, URL recorded in
   `history`) and the workflow commits that so the next run continues the queue.

When all 18 are uploaded, the workflow exits cleanly with "queue complete".

## Safety gate — nothing goes live until you arm it

Scheduled runs are **preview only** by default. They print what they *would*
upload and never touch YouTube or advance the queue.

To arm live uploads on schedule, set the repo **variable**:

```
Settings → Secrets and variables → Actions → Variables
ENABLE_LIVE_UPLOADS = true
```

Manual runs bypass the variable — use the **Actions → Run workflow → mode: live**
dropdown and it uploads right away.

Preview a specific video without uploading anything:

```
Actions → Run workflow → video_id: video_04, mode: preview
```

## Credentials

The workflow reads three GitHub Actions **secrets** (same names/values as
`roblox-auto-shorts`):

| Secret         | Purpose                          |
|----------------|----------------------------------|
| `CLIENT_ID`    | YouTube OAuth client id          |
| `CLIENT_SECRET`| YouTube OAuth client secret      |
| `REFRESH_TOKEN`| YouTube OAuth refresh token      |

These are the credentials for the **Bhaloo Ji** channel. They are stored as repo
secrets and are never committed to the repository.

## Local preview (from this machine)

```bash
pip install -r requirements.txt
export CLIENT_ID=... CLIENT_SECRET=... REFRESH_TOKEN=...
python3 scripts/upload_short.py              # preview next video
python3 scripts/upload_short.py --live       # actually upload next video
```
