#!/usr/bin/env python3
"""
Upload a built video to the 'bhaloo ji' YouTube channel as a Short.

Reads YouTube OAuth credentials from environment (same as backup main.py):
  - CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN
Builds snippet from script.json title/caption/hashtags.

Two modes:
  --preview  (default): print what would be uploaded, do nothing live
  --live: actually upload and return the YouTube video_id

Outputs upload_result.json:
  {"video_id": "...", "url": "...", "status": "uploaded|preview", "title": "..."}

Usage:
    python3 scripts/upload_youtube.py --dir tracker/campaigns/clipfarm
    python3 scripts/upload_youtube.py --dir tracker/campaigns/clipfarm --live
"""
import argparse
import json
import os
import sys
import time


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", required=True, help="campaign dir with script.json and video.mp4")
    ap.add_argument("--live", action="store_true", help="actually upload (default is preview)")
    ap.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    ap.add_argument("--video", default="video.mp4", help="video filename in campaign dir")
    args = ap.parse_args()

    script_path = os.path.join(args.dir, "script.json")
    video_path = os.path.join(args.dir, args.video)
    result_path = os.path.join(args.dir, "upload_result.json")

    if not os.path.exists(script_path):
        print(f"ERROR: {script_path} not found", file=sys.stderr)
        return 1
    if not os.path.exists(video_path):
        print(f"ERROR: {video_path} not found", file=sys.stderr)
        return 1

    script = json.load(open(script_path, encoding="utf-8"))
    title = (script.get("title") or "untitled short")[:100]
    caption = script.get("caption") or ""
    hashtags = script.get("hashtags") or []

    # build description: caption + hashtags as first line
    tag_line = " ".join(f"#{t.lstrip('#')}" for t in hashtags[:10])
    description = f"{caption}\n\n{tag_line}" if caption else tag_line
    tags = [t.lstrip("#") for t in hashtags[:15]]

    result = {
        "status": "preview",
        "title": title,
        "description": description,
        "tags": tags,
    }

    if not args.live:
        print(f"[PREVIEW] Would upload: {video_path}")
        print(f"  title: {title}")
        print(f"  description: {description[:200]}")
        print(f"  tags: {tags}")
        print(f"  privacy: {args.privacy}")
        result["status"] = "preview"
        result["video_id"] = None
        result["url"] = None
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(f"Written {result_path}")
        return 0

    # --- LIVE upload ---
    client_id = os.environ.get("CLIENT_ID")
    client_secret = os.environ.get("CLIENT_SECRET")
    refresh_token = os.environ.get("REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        print("ERROR: missing CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN in env", file=sys.stderr)
        result["status"] = "error"
        result["error"] = "missing youtube oauth credentials in env"
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        return 1

    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        print("ERROR: google-api-python-client not installed (pip install google-api-python-client)", file=sys.stderr)
        return 1

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
    )
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "22",  # People & Blogs — better for Whop content rewards
        },
        "status": {
            "privacyStatus": args.privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    print(f"Uploading {video_path} to YouTube...")
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  {int(status.progress() * 100)}%")

    video_id = response.get("id")
    video_url = f"https://youtube.com/shorts/{video_id}"

    result.update({
        "status": "uploaded",
        "video_id": video_id,
        "url": video_url,
    })

    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(f"SUCCESS: {video_url} (id={video_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
