#!/usr/bin/env python3
"""
YouTube Uploader for Bhaloo Ji Anime Explanation Channel.
Uploads both multi-part Shorts and long-form Full Episode Videos to YouTube.
Uses YouTube Data API v3 OAuth credentials from environment variables:
  - CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = WORKSPACE_DIR / "output"
TRACKER_DIR = WORKSPACE_DIR / "tracker"
HISTORY_PATH = TRACKER_DIR / "anime_history.json"


def log(msg: str) -> None:
    print(f"[anime_uploader] {msg}", flush=True)


def get_youtube_service():
    """Build authorized YouTube client from OAuth refresh token."""
    client_id = os.environ.get("CLIENT_ID", "").strip()
    client_secret = os.environ.get("CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get("REFRESH_TOKEN", "").strip()

    if not all([client_id, client_secret, refresh_token]):
        log("Missing CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN in environment.")
        return None

    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        log("google-api-python-client not installed. Run 'pip install google-api-python-client google-auth-oauthlib'")
        return None

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
    )
    return build("youtube", "v3", credentials=creds)


def upload_video_file(
    youtube,
    video_path: str | Path,
    title: str,
    description: str,
    tags: list[str],
    privacy: str = "public",
    category_id: str = "1"  # 1 = Film & Animation
) -> dict:
    """Uploads video to YouTube with chunked upload."""
    from googleapiclient.http import MediaFileUpload

    path = Path(video_path)
    if not path.exists():
        return {"status": "error", "message": f"File not found: {path}"}

    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": [t.lstrip("#") for t in tags[:20]],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        }
    }

    log(f"Uploading {path.name} ({privacy}) -> '{title[:50]}...'")
    media = MediaFileUpload(str(path), chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log(f"Upload progress: {int(status.progress() * 100)}%")

    video_id = response.get("id")
    is_short = "#shorts" in title.lower() or "#shorts" in description.lower()
    url = f"https://youtube.com/shorts/{video_id}" if is_short else f"https://youtu.be/{video_id}"
    log(f"✅ Upload success: {url} (id={video_id})")

    return {
        "status": "uploaded",
        "video_id": video_id,
        "url": url,
        "title": title,
    }


def upload_episode_package(
    episode_dir: str | Path,
    live: bool = False,
    privacy: str = "public",
    upload_shorts: bool = True,
    upload_full: bool = True,
) -> dict:
    """Upload all parts and the full video for an episode."""
    ep_dir = Path(episode_dir)
    summary_file = ep_dir / "pipeline_summary.json"
    if not summary_file.exists():
        log(f"pipeline_summary.json not found in {ep_dir}")
        return {"status": "error", "message": "manifest not found"}

    with open(summary_file, "r", encoding="utf-8") as f:
        summary = json.load(f)

    results = {
        "episode_key": summary.get("episode_key"),
        "shorts": [],
        "full_video": None,
    }

    if not live:
        log("=== [PREVIEW MODE] Simulating YouTube Uploads (use --live for actual upload) ===")
        if upload_shorts:
            for part in summary.get("parts", []):
                log(f"[PREVIEW SHORT] Title: {part['title']}")
                log(f"                 File: {part['video_path']}")
                log(f"                 Tags: {part['hashtags']}")
                results["shorts"].append({
                    "part": part["part"],
                    "status": "preview",
                    "title": part["title"],
                    "url": "https://youtube.com/shorts/PREVIEW_MOCK",
                })
        if upload_full:
            full = summary.get("full_video", {})
            log(f"[PREVIEW FULL]  Title: {full['title']}")
            log(f"                 File: {full['video_path']}")
            results["full_video"] = {
                "status": "preview",
                "title": full["title"],
                "url": "https://youtu.be/PREVIEW_MOCK",
            }
        return results

    # Live upload
    youtube = get_youtube_service()
    if not youtube:
        log("Cannot perform live upload: YouTube credentials missing or invalid.")
        return {"status": "error", "message": "missing credentials"}

    if upload_shorts:
        for part in summary.get("parts", []):
            short_res = upload_video_file(
                youtube=youtube,
                video_path=part["video_path"],
                title=part["title"],
                description=part["description"],
                tags=part["hashtags"],
                privacy=privacy,
            )
            results["shorts"].append(short_res)
            time.sleep(3)  # Brief pause between uploads

    if upload_full:
        full = summary.get("full_video", {})
        full_res = upload_video_file(
            youtube=youtube,
            video_path=full["video_path"],
            title=full["title"],
            description=full["description"],
            tags=full["hashtags"],
            privacy=privacy,
        )
        results["full_video"] = full_res

    # Save upload record
    with open(ep_dir / "upload_result.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload anime episode to YouTube")
    parser.add_argument("--dir", required=True, help="Episode output directory (e.g. output/demon-slayer-s01e01)")
    parser.add_argument("--live", action="store_true", help="Perform real YouTube upload")
    parser.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    parser.add_argument("--no-shorts", action="store_true", help="Skip Shorts upload")
    parser.add_argument("--no-full", action="store_true", help="Skip Full Video upload")

    args = parser.parse_args()
    res = upload_episode_package(
        episode_dir=args.dir,
        live=args.live,
        privacy=args.privacy,
        upload_shorts=not args.no_shorts,
        upload_full=not args.no_full,
    )
    print(json.dumps(res, indent=2))
