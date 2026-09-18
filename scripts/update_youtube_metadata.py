#!/usr/bin/env python3
"""
Retroactively update metadata (title, description, tags, category) for all videos
already uploaded to YouTube, based on the latest video_metadata.json.

This updates videos on YouTube in-place via the YouTube Data API without re-uploading them.

Modes:
  --preview (default): print what would be updated without modifying anything.
  --live:              actually update the videos on YouTube via API.

Usage:
    python3 scripts/update_youtube_metadata.py           # preview
    python3 scripts/update_youtube_metadata.py --live    # apply to YouTube
"""
import argparse
import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
META_PATH = os.path.join(REPO_ROOT, "video_metadata.json")
STATE_PATH = os.path.join(REPO_ROOT, "tracker", "state.json")


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


def extract_video_id(url_or_id):
    if not url_or_id:
        return None
    if "shorts/" in url_or_id:
        return url_or_id.split("shorts/")[1].split("?")[0].strip("/")
    if "v=" in url_or_id:
        return url_or_id.split("v=")[1].split("&")[0]
    return url_or_id.strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true", help="actually update videos on YouTube (default: preview)")
    ap.add_argument("--video-id", help="update only this specific video_id (e.g. video_01)")
    args = ap.parse_args()

    meta = load_json(META_PATH)
    meta_by_id = {v["id"]: v for v in meta["videos"]}

    if not os.path.exists(STATE_PATH):
        print(f"ERROR: {STATE_PATH} does not exist", file=sys.stderr)
        return 1

    state = load_json(STATE_PATH)
    history = state.get("history", [])

    if not history:
        print("No uploaded videos found in tracker/state.json history.")
        return 0

    youtube = build_youtube_service() if args.live else None

    print(f"{'[LIVE UPDATE]' if args.live else '[PREVIEW]'} Found {len(history)} uploaded videos in history.\n")

    updated_count = 0
    for entry in history:
        vid = entry.get("video_id")
        if args.video_id and vid != args.video_id:
            continue

        meta_info = meta_by_id.get(vid)
        if not meta_info:
            print(f"Skipping {vid}: not found in video_metadata.json")
            continue

        yt_id = extract_video_id(entry.get("youtube_url"))
        if not yt_id:
            print(f"Skipping {vid}: invalid youtube_url '{entry.get('youtube_url')}'")
            continue

        new_title = meta_info["title"][:100]
        new_description = meta_info.get("description", "")
        new_tags = [t.lstrip("#") for t in (meta_info.get("tags") or [])[:15]]
        old_title = entry.get("title", "")

        print(f"Video {vid} (YT: {yt_id}):")
        print(f"  Old Title: {old_title}")
        print(f"  New Title: {new_title}")
        print(f"  New Tags : {new_tags[:5]}...")

        if args.live:
            try:
                body = {
                    "id": yt_id,
                    "snippet": {
                        "title": new_title,
                        "description": new_description,
                        "tags": new_tags,
                        "categoryId": "15",  # Pets & Animals
                    },
                }
                youtube.videos().update(part="snippet", body=body).execute()
                entry["title"] = new_title
                updated_count += 1
                print(f"  -> SUCCESS: updated on YouTube!\n")
                time.sleep(1)  # small pause to avoid rate limiting
            except Exception as e:
                print(f"  -> FAILED to update {vid} ({yt_id}): {e}\n", file=sys.stderr)
        else:
            print(f"  (preview only — will update when --live is passed)\n")
            updated_count += 1

    if args.live and updated_count > 0:
        save_json(STATE_PATH, state)
        print(f"Completed! Updated {updated_count} videos on YouTube and saved state.json.")
    else:
        print(f"Preview complete for {updated_count} videos.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
