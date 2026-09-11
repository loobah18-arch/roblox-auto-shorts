# Bhaloo Ji Shorts

Automated, scheduled uploader for **Bhaloo Ji** — a kids + dog comedy Shorts
channel. Twice a day the pipeline picks the next video in the queue, pairs it
with its hand-written title/description/tags, and uploads it to YouTube as a
Short. The queue loops forever: after `video_18` it wraps back to `video_01`,
so uploads never stop.

## What's here

- `video_metadata.json` — title, description, tags, and source file for all 18 videos
- `videos/` — the 18 `.mp4` shorts (AI-generated, kids + golden retriever comedy)
- `scripts/upload_short.py` — picks the next video from `tracker/state.json`,
  uploads it to YouTube (preview or live), and advances the queue
- `.github/workflows/upload-shorts.yml` — the scheduled workflow
- `tracker/state.json` — queue cursor (`next_index`, upload history)
- `requirements.txt` — pip dependencies for the uploader

## How the scheduled upload works

1. Two `cron` entries fire **twice a day, at 10:23 and 22:23 UTC** (edit in
   `.github/workflows/upload-shorts.yml`).
2. `upload_short.py` reads `tracker/state.json` → `next_index` and picks the next
   video in `video_metadata.json` order.
3. It reads that video's `title` / `description` (hashtags included) / `tags` and
   uploads `videos/<id>.mp4` to the Bhaloo Ji channel as a public Short.
4. On success it writes `state.json` back (`next_index + 1`, URL recorded in
   `history`) and the workflow commits that so the next run continues the queue.

The queue **loops forever**: after `video_18` it wraps back to `video_01`, so a
new Short is always uploaded — the channel never goes quiet.

## Upload behavior

**Scheduled runs** (10:23 and 22:23 UTC) upload **live** to the Bhaloo Ji
channel automatically. That is the approved, intended behavior — a new Short
goes live twice a day, on a loop that never stops.

**Manual runs** (Actions → Run workflow) respect the **"Upload to YouTube"**
checkbox: tick it to go live, leave unticked for a dry run that prints what it *would*
upload without touching the channel. You can also dry-run a specific video:

```
Actions → Run workflow → video_id: video_04, upload_to_youtube: unticked
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
