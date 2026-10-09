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

from anime_catalog import load_history, save_history


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


def find_uploaded_part(parts_list: list, ep_key: str, p_num: int | None = None, is_full: bool = False) -> dict | None:
    """Find existing upload record for deduplication."""
    for item in parts_list:
        if item.get("episode_key") == ep_key:
            if is_full and item.get("is_full_video"):
                return item
            if not is_full and item.get("part") == p_num:
                return item
    return None


def upload_video_file(
    youtube,
    video_path: str | Path,
    title: str,
    description: str,
    tags: list[str],
    privacy: str = "public",
    category_id: str = "1"  # 1 = Film & Animation
) -> dict:
    """Uploads video to YouTube with chunked upload and quota error handling."""
    from googleapiclient.http import MediaFileUpload

    path = Path(video_path)
    if not path.exists():
        return {"status": "error", "message": f"File not found: {path}"}
    if path.stat().st_size < 1024 * 50:
        return {"status": "error", "message": f"File is empty or corrupted ({path.stat().st_size} bytes): {path}"}

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

    log(f"Uploading {path.name} ({privacy}, {path.stat().st_size} bytes) -> '{title[:50]}...'")
    media = MediaFileUpload(str(path), chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    try:
        while response is None:
            status, response = request.next_chunk()
            if status:
                log(f"Upload progress: {int(status.progress() * 100)}%")
    except Exception as exc:
        err_msg = str(exc)
        if "uploadLimitExceeded" in err_msg:
            log(f"⚠️ YouTube 24-hour upload limit reached (uploadLimitExceeded) for {path.name}.")
            return {
                "status": "quota_exceeded",
                "error": "uploadLimitExceeded",
                "message": "YouTube 24-hour channel upload limit exceeded. Resuming on next cycle.",
                "title": title,
                "video_path": str(path),
            }
        log(f"❌ Upload failed for {path.name}: {exc}")
        return {
            "status": "error",
            "message": err_msg,
            "title": title,
            "video_path": str(path),
        }

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
    """Upload all parts and the full video for an episode with deduplication & quota protection."""
    ep_dir = Path(episode_dir)
    summary_file = ep_dir / "pipeline_summary.json"
    if not summary_file.exists():
        log(f"pipeline_summary.json not found in {ep_dir}")
        return {"status": "error", "message": "manifest not found"}

    with open(summary_file, "r", encoding="utf-8") as f:
        summary = json.load(f)

    if summary.get("status") != "success":
        log(f"Refusing upload for {summary.get('episode_key')}: pipeline status was '{summary.get('status')}'")
        return {"status": "error", "message": f"Pipeline was not successful: {summary.get('status')}"}

    history = load_history()
    uploaded_parts = history.get("uploaded_parts", [])
    ep_key = summary.get("episode_key")

    if summary.get("mode") == "daily_funnel":
        action = summary.get("action")
        vid_to_upload = summary.get("video_to_upload", {})

        if not live:
            log(f"=== [PREVIEW MODE] Daily Funnel Action: '{action}' for {ep_key} ===")
            log(f"Title: {vid_to_upload.get('title')}")
            log(f"File:  {vid_to_upload.get('video_path')}")
            res = {
                "status": "preview",
                "mode": "daily_funnel",
                "action": action,
                "episode_key": ep_key,
                "video": vid_to_upload,
                "url": "https://youtube.com/PREVIEW_MOCK",
            }
            with open(ep_dir / "upload_result.json", "w", encoding="utf-8") as f:
                json.dump(res, f, indent=2)
            return res

        youtube = get_youtube_service()
        if not youtube:
            log("Cannot perform live upload: YouTube credentials missing or invalid.")
            return {"status": "error", "message": "missing credentials"}

        upload_res = upload_video_file(
            youtube=youtube,
            video_path=vid_to_upload["video_path"],
            title=vid_to_upload["title"],
            description=vid_to_upload["description"],
            tags=vid_to_upload.get("hashtags", []),
            privacy=privacy,
        )

        if upload_res.get("status") == "uploaded":
            history = load_history()
            active = history.get("active_episode")
            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            record = {
                "episode_key": ep_key,
                "part": summary.get("part"),
                "is_full_video": (action == "normal_video"),
                "video_id": upload_res.get("video_id"),
                "url": upload_res.get("url"),
                "title": vid_to_upload["title"],
                "uploaded_at": now_iso,
            }
            uploaded_parts = history.get("uploaded_parts", [])
            uploaded_parts.append(record)
            history["uploaded_parts"] = uploaded_parts

            if active and active.get("episode_key") == ep_key:
                if action == "normal_video":
                    active["normal_video_uploaded"] = True
                    active["normal_video"] = record
                    log(f"🎉 Normal Video successfully uploaded: {upload_res.get('url')}! Locked in: daily Shorts will upload next.")
                elif action == "short":
                    p_num = summary.get("part")
                    if p_num and p_num not in active.get("uploaded_shorts", []):
                        active.setdefault("uploaded_shorts", []).append(p_num)
                    log(f"✅ Short Part {p_num}/{active.get('total_parts')} uploaded: {upload_res.get('url')}!")

                    # Check completion gate: All shorts uploaded?
                    if len(active.get("uploaded_shorts", [])) >= active.get("total_parts", 3):
                        log(f"🎉 Episode {ep_key} is 100% completed! All {active.get('total_parts')} Shorts uploaded.")
                        completed = history.get("completed_episodes", [])
                        if ep_key not in completed:
                            completed.append(ep_key)
                            history["completed_episodes"] = completed
                        history["active_episode"] = None

            history["last_updated"] = now_iso
            save_history(history)
            results = {
                "status": "success",
                "mode": "daily_funnel",
                "action": action,
                "episode_key": ep_key,
                "uploaded_record": record,
            }
        else:
            results = upload_res

        with open(ep_dir / "upload_result.json", "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        return results

    results = {
        "episode_key": ep_key,
        "shorts": [],
        "full_video": None,
    }

    if not live:
        log("=== [PREVIEW MODE] Simulating YouTube Uploads (use --live for actual upload) ===")
        if upload_shorts:
            for part in summary.get("parts", []):
                p_num = part["part"]
                already = find_uploaded_part(uploaded_parts, ep_key, p_num=p_num, is_full=False)
                if already:
                    log(f"[PREVIEW SHORT] Part {p_num} already uploaded: {already.get('url')}")
                    results["shorts"].append(already)
                else:
                    log(f"[PREVIEW SHORT] Title: {part['title']}")
                    log(f"                 File: {part['video_path']}")
                    log(f"                 Tags: {part['hashtags']}")
                    results["shorts"].append({
                        "part": p_num,
                        "status": "preview",
                        "title": part["title"],
                        "url": "https://youtube.com/shorts/PREVIEW_MOCK",
                    })
        if upload_full:
            full = summary.get("full_video", {})
            already_full = find_uploaded_part(uploaded_parts, ep_key, is_full=True)
            if already_full:
                log(f"[PREVIEW FULL]  Already uploaded: {already_full.get('url')}")
                results["full_video"] = already_full
            else:
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

    quota_hit = False

    if upload_shorts:
        for part in summary.get("parts", []):
            p_num = part.get("part")
            if part.get("status") != "rendered":
                log(f"Skipping Part {p_num}: status is '{part.get('status')}', not 'rendered'")
                continue

            # Deduplication: check if already uploaded to YouTube
            already = find_uploaded_part(uploaded_parts, ep_key, p_num=p_num, is_full=False)
            if already:
                log(f"Part {p_num} already uploaded on YouTube: {already.get('url')} (skipping duplicate upload)")
                results["shorts"].append(already)
                continue

            if quota_hit:
                log(f"Skipping Part {p_num}: deferred due to 24h upload limit.")
                results["shorts"].append({
                    "part": p_num,
                    "status": "quota_deferred",
                    "title": part["title"],
                })
                continue

            short_res = upload_video_file(
                youtube=youtube,
                video_path=part["video_path"],
                title=part["title"],
                description=part["description"],
                tags=part["hashtags"],
                privacy=privacy,
            )
            if short_res.get("status") == "uploaded":
                record = {
                    "episode_key": ep_key,
                    "part": p_num,
                    "is_full_video": False,
                    "video_id": short_res.get("video_id"),
                    "url": short_res.get("url"),
                    "title": part["title"],
                    "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
                uploaded_parts.append(record)
                history["uploaded_parts"] = uploaded_parts
                save_history(history)
                results["shorts"].append(record)
            elif short_res.get("status") == "quota_exceeded":
                quota_hit = True
                results["shorts"].append(short_res)
            else:
                results["shorts"].append(short_res)

            time.sleep(3)  # Brief pause between uploads

    if upload_full:
        full = summary.get("full_video", {})
        if full.get("status") != "rendered":
            log(f"Skipping Full Video: status is '{full.get('status')}', not 'rendered'")
            results["full_video"] = {"status": "skipped", "message": f"status is {full.get('status')}"}
        else:
            already_full = find_uploaded_part(uploaded_parts, ep_key, is_full=True)
            if already_full:
                log(f"Full Video already uploaded on YouTube: {already_full.get('url')} (skipping duplicate upload)")
                results["full_video"] = already_full
            elif quota_hit:
                log("Skipping Full Video: deferred due to 24h upload limit.")
                results["full_video"] = {
                    "status": "quota_deferred",
                    "title": full["title"],
                }
            else:
                full_res = upload_video_file(
                    youtube=youtube,
                    video_path=full["video_path"],
                    title=full["title"],
                    description=full["description"],
                    tags=full["hashtags"],
                    privacy=privacy,
                )
                if full_res.get("status") == "uploaded":
                    record = {
                        "episode_key": ep_key,
                        "part": None,
                        "is_full_video": True,
                        "video_id": full_res.get("video_id"),
                        "url": full_res.get("url"),
                        "title": full["title"],
                        "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    }
                    uploaded_parts.append(record)
                    history["uploaded_parts"] = uploaded_parts
                    save_history(history)
                    results["full_video"] = record
                elif full_res.get("status") == "quota_exceeded":
                    quota_hit = True
                    results["full_video"] = full_res
                else:
                    results["full_video"] = full_res

    # Check overall completion state
    total_parts_expected = len(summary.get("parts", []))
    uploaded_shorts_count = sum(
        1 for s in results["shorts"] if s.get("status") == "uploaded" or s.get("video_id")
    )
    full_uploaded = bool(
        results.get("full_video")
        and (results["full_video"].get("status") == "uploaded" or results["full_video"].get("video_id"))
    )

    completed = history.get("completed_episodes", [])
    if uploaded_shorts_count == total_parts_expected and full_uploaded:
        if ep_key not in completed:
            completed.append(ep_key)
            history["completed_episodes"] = completed
            history["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            save_history(history)
            log(f"🎉 Episode {ep_key} is 100% uploaded ({uploaded_shorts_count}/{total_parts_expected} Shorts + Full Video)! Marked complete in history.")
    else:
        if ep_key in completed:
            completed.remove(ep_key)
            history["completed_episodes"] = completed
            history["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            save_history(history)
            log(f"Episode {ep_key} is partially uploaded ({uploaded_shorts_count}/{total_parts_expected} Shorts). Kept open in history.")

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

