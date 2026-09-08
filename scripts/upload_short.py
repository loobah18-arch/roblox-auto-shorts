#!/usr/bin/env python3
"""
Upload one "Bhaloo Ji" short (kids + dog comedy video) to YouTube as a Short.

Metadata comes from video_metadata.json (title / description / tags per video_id).
Sequential state lives in tracker/state.json: each successful LIVE upload advances
the cursor so the next scheduled run uploads the next video in the queue.

Credentials come from env (repo secrets, identical to the existing
roblox-auto-shorts setup): CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN.

Modes:
  --preview (default): print what WOULD upload. Uploads nothing, advances nothing.
  --live:              actually upload to YouTube and advance tracker/state.json.

Usage:
    python3 scripts/upload_short.py                       # preview next in sequence
    python3 scripts/upload_short.py --video-id video_04   # preview a specific video
    python3 scripts/upload_short.py --live                # live-upload next in sequence
    python3 scripts/upload_short.py --video-id video_04 --live
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
META_PATH = os.path.join(REPO_ROOT, "video_metadata.json")
STATE_PATH = os.path.join(REPO_ROOT, "tracker", "state.json")
VIDEO_DIR = os.path.join(REPO_ROOT, "videos")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def build_youtube_service():
    client_id = os.environ.get("CLIENT_ID")
    client_secret = os.environ.get("CLIENT_SECRET")
    refresh_token = os.environ.get("REFRESH_TOKEN")
    if not all([client_id, client_secret, refresh_token]):
        print("ERROR: missing CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN in env", file=sys.stderr)
        sys.exit(1)
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
    )
    return build("youtube", "v3", credentials=creds)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--video-id", help="specific video id (video_01 .. video_18); default: next in sequence")
    ap.add_argument("--live", action="store_true", help="actually upload + advance state (default: preview only)")
    args = ap.parse_args()

    meta = load_json(META_PATH)
    videos = meta["videos"]

    state = load_json(STATE_PATH) if os.path.exists(STATE_PATH) else {
        "next_index": 0, "total_videos": len(videos), "uploaded": [], "history": []
    }
    state.setdefault("next_index", 0)
    state.setdefault("uploaded", [])
    state.setdefault("history", [])

    # ---- pick the video for this run ----
    if args.video_id:
        index = next((i for i, v in enumerate(videos) if v["id"] == args.video_id), None)
        if index is None:
            print(f"ERROR: no video with id '{args.video_id}' in video_metadata.json", file=sys.stderr)
            return 1
    else:
        index = state["next_index"]
        if index >= len(videos):
            print(f"All {len(videos)} videos already uploaded — queue complete. Nothing to do.")
            return 0
    video = videos[index]

    video_path = os.path.join(VIDEO_DIR, f"{video['id']}.mp4")
    if not os.path.exists(video_path):
        print(f"ERROR: video file not found: {video_path}", file=sys.stderr)
        return 1

    title = video["title"][:100]
    description = video["description"] or ""
    tags = [t.lstrip("#") for t in (video.get("tags") or [])[:15]]

    if not args.live:
        print(f"[PREVIEW] Would upload: {video_path}")
        print(f"  id          : {video['id']}")
        print(f"  sequence pos: {index}")
        print(f"  title       : {title}")
        print(f"  description : {description[:160]}{'...' if len(description) > 160 else ''}")
        print(f"  tags        : {tags}")
        print("  (preview only — nothing uploaded, queue not advanced)")
        return 0

    # ---- live upload ----
    youtube = build_youtube_service()
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "22",  # People & Blogs — same as the existing upload_youtube.py
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    from googleapiclient.http import MediaFileUpload
    print(f"Uploading {video_path} to YouTube...")
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  {int(status.progress() * 100)}%")

    video_id = response.get("id")
    url = f"https://youtube.com/shorts/{video_id}"

    # ---- advance state (only after a confirmed upload) ----
    state["uploaded"].append(video["id"])
    state["history"].append({
        "index": index,
        "video_id": video["id"],
        "title": title,
        "youtube_url": url,
        "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    state["next_index"] = index + 1
    state["total_videos"] = len(videos)
    save_json(STATE_PATH, state)

    print(f"SUCCESS: {url} (id={video_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
