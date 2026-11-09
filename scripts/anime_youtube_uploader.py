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
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = WORKSPACE_DIR / "output"
TRACKER_DIR = WORKSPACE_DIR / "tracker"
HISTORY_PATH = TRACKER_DIR / "anime_history.json"

from anime_catalog import load_history, save_history
from anime_copyright_filter import MultiAgentCopyrightShield


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


def parse_iso_datetime(dt_str: str | None) -> datetime | None:
    """Safely parse ISO-8601 strings into UTC datetime."""
    if not dt_str or not isinstance(dt_str, str):
        return None
    try:
        clean_str = dt_str.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def get_latest_upload_time(history: dict | None) -> datetime | None:
    """Finds the most recent upload timestamp from anime_history.json."""
    if not history or not isinstance(history, dict):
        return None

    timestamps: list[datetime] = []
    for item in history.get("uploaded_parts", []):
        if isinstance(item, dict):
            up_at = item.get("uploaded_at")
            dt = parse_iso_datetime(up_at)
            if dt:
                timestamps.append(dt)

    last_up = history.get("last_updated")
    dt_last = parse_iso_datetime(last_up)
    if dt_last:
        timestamps.append(dt_last)

    if not timestamps:
        return None
    return max(timestamps)


def ensure_upload_cadence(
    history: dict | None,
    cadence_hours: float = 24.0,
    max_wait_seconds: float = 1800.0,
    allow_override: bool = False,
    now: datetime | None = None,
) -> tuple[bool, datetime | None, float]:
    """Ensures a strict 24-hour cadence between YouTube uploads.

    Returns:
        (can_proceed: bool, next_allowed_time: datetime | None, remaining_seconds: float)
    """
    if allow_override or os.environ.get("ALLOW_CADENCE_OVERRIDE", "false").lower() == "true":
        log("⚡ [CadenceManager] Cadence override active. Bypassing 24-hour upload gap check.")
        return True, None, 0.0

    last_upload = get_latest_upload_time(history)
    if not last_upload:
        log("ℹ️ [CadenceManager] No previous uploads found in history. Proceeding with upload.")
        return True, None, 0.0

    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    next_allowed = last_upload + timedelta(hours=cadence_hours)
    remaining = (next_allowed - now_utc).total_seconds()

    if remaining <= 0:
        elapsed_h = (now_utc - last_upload).total_seconds() / 3600.0
        log(f"✅ [CadenceManager] 24-hour upload cadence met. Last upload was at {last_upload.strftime('%Y-%m-%d %H:%M:%S UTC')} ({elapsed_h:.1f}h ago). Proceeding with upload.")
        return True, next_allowed, 0.0

    rem_min = remaining / 60.0
    rem_h = remaining / 3600.0
    last_str = last_upload.strftime("%Y-%m-%d %H:%M:%S UTC")
    next_str = next_allowed.strftime("%Y-%m-%d %H:%M:%S UTC")

    if remaining <= max_wait_seconds:
        log(f"⏱️ [CadenceManager] Last upload: {last_str}. Target upload timing: {next_str}.")
        log(f"⏳ [CadenceManager] Remaining wait ({rem_min:.1f} min) is within inline window ({max_wait_seconds / 60.0:.1f} min).")
        log(f"💤 [CadenceManager] Sleeping until exact target timing ({next_str})...")
        sleep_chunk = 30.0
        time_to_wait = remaining
        while time_to_wait > 0:
            step = min(sleep_chunk, time_to_wait)
            time.sleep(step)
            time_to_wait -= step
            if time_to_wait > 5.0:
                log(f"⏳ [CadenceManager] Countdown: {time_to_wait / 60.0:.1f} min remaining until target timing ({next_str})...")
        log(f"🔔 [CadenceManager] Target upload timing reached! Proceeding with upload.")
        return True, next_allowed, 0.0

    log(f"⏸️ [CadenceManager] Strict 24-hour cadence window not yet reached. Last upload: {last_str}.")
    log(f"🎯 [CadenceManager] Next upload permitted at: {next_str} (in {rem_h:.2f} hours).")
    log("📌 [CadenceManager] Deferring upload to preserve exactly 24 hours gap between uploads.")
    return False, next_allowed, remaining


VIEW_THRESHOLD_PER_HOUR = 2500  # 2k-3k views/hr midpoint protection


def evaluate_view_velocity_gate(
    youtube,
    history: dict | None,
    threshold_per_hour: int = VIEW_THRESHOLD_PER_HOUR,
    early_views_threshold: int = 2000,
    early_hours_window: float = 24.0,
    allow_override: bool = False,
) -> tuple[bool, str, dict]:
    """Evaluates YouTube Data API view velocity on the channel's most recent upload.

    Protects well-performing videos (>= 2k-3k views/hr or >= 2k in first 24h)
    from being choked by too-frequent uploads.
    """
    if allow_override or os.environ.get("ALLOW_VELOCITY_OVERRIDE", "false").lower() == "true":
        return True, "Override active; velocity check bypassed", {}

    if not youtube:
        return True, "No YouTube client provided; proceeding", {}

    vid_id = None
    if history and isinstance(history, dict):
        uploaded_parts = history.get("uploaded_parts", [])
        for item in reversed(uploaded_parts):
            if isinstance(item, dict):
                candidate_id = item.get("video_id")
                if candidate_id and not str(candidate_id).startswith("dry_run"):
                    vid_id = candidate_id
                    break

    if not vid_id:
        return True, "No prior video ID found in history; initial upload cleared", {}

    try:
        videos_res = getattr(youtube, "videos", None)
        if callable(videos_res):
            videos_res = videos_res()
        res = videos_res.list(id=vid_id, part="statistics,snippet").execute()
        items = res.get("items", [])
        if not items:
            return True, f"Could not fetch stats for video {vid_id}; clearing upload", {}

        stats = items[0].get("statistics", {})
        snippet = items[0].get("snippet", {})
        title = snippet.get("title", f"Video {vid_id}")
        total_views = int(stats.get("viewCount", 0))
        pub_str = snippet.get("publishedAt", "")
        if not pub_str:
            return True, "No publishedAt found; clearing upload", {}

        pub_dt = parse_iso_datetime(pub_str)
        now_utc = datetime.now(timezone.utc)
        elapsed_hours = max((now_utc - pub_dt).total_seconds() / 3600.0, 0.1) if pub_dt else 24.0
        hourly_velocity = int(total_views / elapsed_hours)

        # 1. Early momentum check (>= 2,000 views in first 24h)
        if elapsed_hours <= early_hours_window and total_views >= early_views_threshold:
            msg = (
                f"🚀 [VelocityGate] Early momentum detected! Active video '{title}' has reached "
                f"{total_views:,} views in {elapsed_hours:.1f}h (>= {early_views_threshold:,} in {early_hours_window:.0f}h). "
                f"Pausing upload to let early algorithmic traction perform."
            )
            log(msg)
            return False, msg, {"total_views": total_views, "velocity": hourly_velocity, "elapsed_hours": elapsed_hours}

        # 2. Viral velocity check (>= 2,500 views/hr)
        if elapsed_hours <= 48 and hourly_velocity >= threshold_per_hour:
            msg = (
                f"🔥 [VelocityGate] Active video '{title}' is performing well ({hourly_velocity:,} views/hr >= {threshold_per_hour:,}/hr)! "
                f"Pausing upload to let it perform on the algorithm before uploading another."
            )
            log(msg)
            return False, msg, {"total_views": total_views, "velocity": hourly_velocity, "elapsed_hours": elapsed_hours}

        msg = f"✅ [VelocityGate] Active video velocity ({hourly_velocity:,} views/hr, total: {total_views:,}) is below {threshold_per_hour:,}/hr threshold. Upload cleared."
        log(msg)
        return True, msg, {"total_views": total_views, "velocity": hourly_velocity, "elapsed_hours": elapsed_hours}

    except Exception as e:
        log(f"⚠️ [VelocityGate] Check failed ({e}); granting clearance as safe fallback.")
        return True, f"Check failed: {e}", {}


def check_youtube_video_status(
    youtube,
    video_id: str,
    timeout_sec: float = 12.0,
    poll_interval_sec: float = 3.0,
) -> tuple[bool, str | None, dict]:
    """Polls YouTube Data API to verify if an uploaded video is blocked or rejected.

    Returns:
        (is_blocked, rejection_reason, raw_status_dict)
    """
    if not youtube or not video_id:
        return False, None, {}

    videos_resource = getattr(youtube, "videos", None)
    if callable(videos_resource):
        videos_resource = videos_resource()

    if not videos_resource or not hasattr(videos_resource, "list"):
        return False, None, {}

    start_time = time.time()
    last_status: dict = {}

    while True:
        try:
            req = videos_resource.list(
                part="status,contentDetails,processingDetails",
                id=video_id,
            )
            resp = req.execute() if hasattr(req, "execute") else req
        except Exception as e:
            err_str = str(e).lower()
            if any(term in err_str for term in ("blocked", "copyright", "termsofservice", "rejected", "claim")):
                log(f"🛑 API indicates block on video {video_id}: {e}")
                return True, "api_error_blocked", {"error": str(e)}
            log(f"⚠️ YouTube status check query warning for {video_id}: {e}")
            break

        if not isinstance(resp, dict):
            return False, None, {}

        items = resp.get("items", [])
        if not items:
            log(f"⚠️ Video {video_id} not found in YouTube query.")
            return True, "video_not_found_post_upload", {}

        item = items[0]
        if not isinstance(item, dict):
            return False, None, {}

        status = item.get("status", {})
        content_details = item.get("contentDetails", {})
        processing_details = item.get("processingDetails", {})
        last_status = {
            "status": status,
            "contentDetails": content_details,
            "processingDetails": processing_details,
        }

        upload_status = str(status.get("uploadStatus", "")).lower()
        rejection_reason = status.get("rejectionReason")
        processing_status = str(processing_details.get("processingStatus", "")).lower()
        processing_failure = processing_details.get("processingFailureReason")

        # 1. Check explicit rejection reason or uploadStatus
        if upload_status == "rejected" or rejection_reason:
            reason = str(rejection_reason or "upload_rejected")
            log(f"🛑 Video {video_id} rejected by YouTube: reason='{reason}' (uploadStatus={upload_status})")
            return True, reason, last_status

        # 2. Check processing failure
        if processing_status in ("failed", "terminated") or processing_failure:
            reason = str(processing_failure or "processing_failed")
            log(f"🛑 Video {video_id} processing failed: reason='{reason}' (processingStatus={processing_status})")
            return True, reason, last_status

        # 3. Check region restrictions (blocked worldwide)
        region_restriction = content_details.get("regionRestriction", {})
        blocked_regions = region_restriction.get("blocked", [])
        allowed_regions = region_restriction.get("allowed")
        if blocked_regions and len(blocked_regions) > 50:
            log(f"🛑 Video {video_id} is blocked in {len(blocked_regions)} regions.")
            return True, "region_restricted_block", last_status
        if allowed_regions is not None and len(allowed_regions) == 0:
            log(f"🛑 Video {video_id} has empty allowed regions list.")
            return True, "region_restricted_empty_allowed", last_status

        elapsed = time.time() - start_time
        if upload_status in ("uploaded", "processed") and processing_status in ("succeeded", "processing"):
            if elapsed >= timeout_sec or timeout_sec <= 0:
                log(f"✅ Video {video_id} clean after check (uploadStatus={upload_status}, processingStatus={processing_status}).")
                return False, None, last_status

        if elapsed >= timeout_sec:
            break

        time.sleep(poll_interval_sec)

    return False, None, last_status


def classify_block_reason(
    rejection_reason: str | None = None,
    raw_status: dict | None = None,
    bgm_path: str | Path | None = None,
) -> str:
    """Classifies YouTube block/rejection cause into 'audio', 'clip', or 'both'.

    - 'audio': audio match, sound recording claim, or commercial non-NCS audio used.
    - 'clip': video match, visual footage claim, or audio was already verified NCS.
    - 'both': mixed or generic claim where both audio and video require remediation.
    """
    raw_status = raw_status or {}
    corpus = f"{rejection_reason or ''} {json.dumps(raw_status)}".lower()

    audio_signals = ["audio", "music", "sound", "song", "track", "melody", "phonk", "sound_recording", "audio_fingerprint", "audiomatch"]
    video_signals = ["video", "visual", "footage", "clip", "scene", "audiovisual", "videomatch", "visual_fingerprint"]

    has_audio = any(s in corpus for s in audio_signals)
    has_video = any(s in corpus for s in video_signals)

    if has_audio and not has_video:
        return "audio"
    if has_video and not has_audio:
        return "clip"

    # If already using an authentic NCS track, audio cannot be the block cause -> must be the video clip!
    bgm_lower = str(bgm_path or "").lower()
    if any(ncs_kw in bgm_lower for ncs_kw in ("ncs", "cradles", "aerohead", "nocopyright")):
        return "clip"

    # If generic "copyright" with non-NCS audio, audio is the dominant content ID claim
    return "audio" if not has_video else "both"


def upload_video_file(
    youtube,
    video_path: str | Path,
    title: str,
    description: str,
    tags: list[str],
    privacy: str = "public",
    category_id: str = "1",  # 1 = Film & Animation
    max_retries: int = 2,
    verify_timeout_sec: float = 12.0,
    media_upload_cls: Any = None,
    bgm_path: str | Path | None = None,
) -> dict:
    """Uploads video to YouTube with chunked upload, block detection, deletion & remediation retry."""
    path = Path(video_path)
    if not path.exists():
        return {"status": "error", "message": f"File not found: {path}"}
    if path.stat().st_size < 1024 * 50:
        return {"status": "error", "message": f"File is empty or corrupted ({path.stat().st_size} bytes): {path}"}

    effective_upload_cls = media_upload_cls
    if effective_upload_cls is None:
        from googleapiclient.http import MediaFileUpload
        effective_upload_cls = MediaFileUpload

    curr_title = title
    curr_desc = description
    curr_tags = list(tags)
    last_block_reason: str | None = None

    for attempt in range(max_retries + 1):
        if attempt > 0:
            log(f"🔄 [UploadGuard] RETRY {attempt}/{max_retries} for {path.name} after block ({last_block_reason}). Applying remediation...")
            clean_t = curr_title.replace("#Shorts", "").replace("#shorts", "").strip()
            curr_title = f"{clean_t} | Story Breakdown 🎬🔥 #shorts"[:100]
            curr_desc = f"{curr_desc.strip()}\n\n📌 Transformative Fair Use: Original commentary and narrative recap."

        body = {
            "snippet": {
                "title": curr_title[:100],
                "description": curr_desc,
                "tags": [t.lstrip("#") for t in curr_tags[:20]],
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
            }
        }

        log(f"Uploading {path.name} (Attempt {attempt + 1}/{max_retries + 1}, {privacy}) -> '{curr_title[:50]}...'")
        try:
            media = effective_upload_cls(str(path), chunksize=-1, resumable=True, mimetype="video/mp4")
            videos_res = getattr(youtube, "videos", None)
            if callable(videos_res):
                videos_res = videos_res()
            request = videos_res.insert(part="snippet,status", body=body, media_body=media)

            response = None
            if hasattr(request, "next_chunk"):
                while response is None:
                    status, response = request.next_chunk()
                    if status and hasattr(status, "progress"):
                        log(f"Upload progress: {int(status.progress() * 100)}%")
            elif hasattr(request, "execute"):
                response = request.execute()
        except Exception as exc:
            err_msg = str(exc)
            if "uploadLimitExceeded" in err_msg:
                log(f"⚠️ YouTube 24-hour upload limit reached (uploadLimitExceeded) for {path.name}.")
                return {
                    "status": "quota_exceeded",
                    "error": "uploadLimitExceeded",
                    "message": "YouTube 24-hour channel upload limit exceeded. Resuming on next cycle.",
                    "title": curr_title,
                    "video_path": str(path),
                }
            log(f"❌ Upload failed for {path.name}: {exc}")
            last_block_reason = f"api_error: {err_msg}"
            continue

        video_id = response.get("id") if isinstance(response, dict) else None
        if not video_id:
            last_block_reason = "missing_video_id"
            continue

        is_short = "#shorts" in curr_title.lower() or "#shorts" in curr_desc.lower()
        url = f"https://youtube.com/shorts/{video_id}" if is_short else f"https://youtu.be/{video_id}"
        log(f"📤 Upload complete: {url} (id={video_id}). Verifying block status (timeout={verify_timeout_sec}s)...")

        # Verify YouTube Status for Blocks / Rejections
        is_blocked, rejection_reason, raw_status = check_youtube_video_status(
            youtube=youtube,
            video_id=video_id,
            timeout_sec=verify_timeout_sec,
        )

        if not is_blocked:
            log(f"🎉 [UploadGuard] Video {video_id} VERIFIED CLEAN! YouTube accepted the upload.")
            return {
                "status": "uploaded",
                "video_id": video_id,
                "url": url,
                "title": curr_title,
                "attempts": attempt + 1,
            }

        # Video WAS BLOCKED!
        last_block_reason = rejection_reason or "unknown_rejection"
        block_type = classify_block_reason(last_block_reason, raw_status, bgm_path)
        log(f"🛑 [UploadGuard] Detected YouTube BLOCK on video {video_id}: '{last_block_reason}' (diagnosed cause: '{block_type}'). Deleting immediately to protect channel standing...")
        delete_video(youtube, video_id)

    block_type = classify_block_reason(last_block_reason, raw_status, bgm_path)
    log(f"❌ [UploadGuard] Video remained blocked after {max_retries} remediation retries ({block_type}).")
    return {
        "status": "blocked",
        "rejection_reason": last_block_reason,
        "block_type": block_type,
        "attempts": max_retries + 1,
        "title": title,
        "video_path": str(path),
    }


def upload_episode_package(
    episode_dir: str | Path,
    live: bool = False,
    privacy: str = "public",
    upload_shorts: bool = True,
    upload_full: bool = True,
    allow_cadence_override: bool = False,
    cadence_hours: float = 24.0,
) -> dict:
    """Upload all parts and the full video for an episode with deduplication, 24h cadence & quota protection."""
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

    if live:
        can_proceed, next_allowed, remaining_sec = ensure_upload_cadence(
            history=history,
            cadence_hours=cadence_hours,
            allow_override=allow_cadence_override,
        )
        if not can_proceed:
            next_iso = next_allowed.isoformat() if next_allowed else None
            rem_h = remaining_sec / 3600.0
            log(f"⏸️ [CadenceManager] Upload deferred: 24h cadence window not met ({rem_h:.2f}h remaining). Next allowed: {next_iso}")
            res = {
                "status": "deferred_cadence",
                "message": f"Upload deferred: 24h cadence window not met ({rem_h:.2f}h remaining)",
                "next_allowed": next_iso,
                "remaining_seconds": remaining_sec,
            }
            with open(ep_dir / "upload_result.json", "w", encoding="utf-8") as f:
                json.dump(res, f, indent=2)
            return res

        # Velocity Gate check: protect well-performing videos (>= 2k-3k views/hr or >= 2k in first 12h)
        youtube = get_youtube_service()
        can_upload_vel, vel_msg, vel_data = evaluate_view_velocity_gate(
            youtube=youtube,
            history=history,
            allow_override=allow_cadence_override,
        )
        if not can_upload_vel:
            log(f"🛑 [VelocityGate] Upload deferred: {vel_msg}")
            res = {
                "status": "deferred_velocity_gate",
                "message": vel_msg,
                "velocity_data": vel_data,
            }
            with open(ep_dir / "upload_result.json", "w", encoding="utf-8") as f:
                json.dump(res, f, indent=2)
            return res

    if summary.get("mode") in ("daily_funnel", "cinema") or "video_to_upload" in summary:
        action = summary.get("action", "short")
        vid_to_upload = summary.get("video_to_upload", {})

        if not live:
            log(f"=== [PREVIEW MODE] Funnel/Cinema Action: '{action}' for {ep_key} ===")
            log(f"Title: {vid_to_upload.get('title')}")
            log(f"File:  {vid_to_upload.get('video_path')}")
            res = {
                "status": "preview",
                "mode": summary.get("mode", "daily_funnel"),
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
            bgm_path=summary.get("bgm_path") or (WORKSPACE_DIR / "assets" / "bgm" / "cradles.mp3"),
        )

        # Handle YouTube Block & Style Restart
        if upload_res.get("status") == "blocked":
            block_type = upload_res.get("block_type") or "both"
            log(f"🛑 [Bhaloo Ji] Upload was blocked by YouTube and remained blocked after retrying ({upload_res.get('rejection_reason')}, diagnosed cause='{block_type}')!")

            curr_presentation = summary.get("presentation_style", "full_bleed")
            alt_presentation = "card_blur" if curr_presentation == "full_bleed" else "full_bleed"
            ncs_bgm = WORKSPACE_DIR / "assets" / "bgm" / "cradles.mp3"
            if not ncs_bgm.exists():
                ncs_bgm = WORKSPACE_DIR / "assets" / "bgm" / "aerohead_fragments_recap.mp3"

            from anime_pipeline import run_cinema_pipeline, run_pipeline

            if block_type == "audio":
                log(f"🎵 [Bhaloo Ji] BGM audio flagged by Content ID. Swapping track to verified copyright-free NCS release ({ncs_bgm.name})...")
                if summary.get("mode") == "cinema":
                    re_res = run_cinema_pipeline(
                        episode_key=ep_key,
                        full_bleed=(curr_presentation == "full_bleed"),
                        bgm_path=ncs_bgm,
                        remove_copyrighted_clip=False,
                        dry_run=False,
                    )
                else:
                    re_res = run_pipeline(
                        episode_key=ep_key,
                        full_bleed=(curr_presentation == "full_bleed"),
                        bgm_path=ncs_bgm,
                        remove_copyrighted_clip=False,
                        dry_run=False,
                    )
            elif block_type == "clip":
                log(f"🎬 [Bhaloo Ji] Video footage clip flagged by Content ID. Removing copyrighted clip cut and switching style presentation to '{alt_presentation}'...")
                if summary.get("mode") == "cinema":
                    re_res = run_cinema_pipeline(
                        episode_key=ep_key,
                        full_bleed=(alt_presentation == "full_bleed"),
                        bgm_mood=summary.get("bgm_mood"),
                        remove_copyrighted_clip=True,
                        dry_run=False,
                    )
                else:
                    re_res = run_pipeline(
                        episode_key=ep_key,
                        full_bleed=(alt_presentation == "full_bleed"),
                        bgm_mood=summary.get("bgm_mood"),
                        remove_copyrighted_clip=True,
                        dry_run=False,
                    )
            else:  # "both"
                log(f"🛡️ [Bhaloo Ji] Mixed video clip and audio claims. Removing copyrighted clip cut, switching presentation to '{alt_presentation}', and swapping to NCS BGM ({ncs_bgm.name})...")
                if summary.get("mode") == "cinema":
                    re_res = run_cinema_pipeline(
                        episode_key=ep_key,
                        full_bleed=(alt_presentation == "full_bleed"),
                        bgm_path=ncs_bgm,
                        remove_copyrighted_clip=True,
                        dry_run=False,
                    )
                else:
                    re_res = run_pipeline(
                        episode_key=ep_key,
                        full_bleed=(alt_presentation == "full_bleed"),
                        bgm_path=ncs_bgm,
                        remove_copyrighted_clip=True,
                        dry_run=False,
                    )

            if re_res.get("status") == "success":
                alt_vid = re_res.get("video_to_upload", {})
                log(f"🚀 [UploadGuard] Re-attempting upload with newly styled video: {alt_vid.get('title')}...")
                upload_res = upload_video_file(
                    youtube=youtube,
                    video_path=alt_vid.get("video_path"),
                    title=alt_vid.get("title"),
                    description=alt_vid.get("description"),
                    tags=alt_vid.get("hashtags", []),
                    privacy=privacy,
                    bgm_path=ncs_bgm if block_type in ("audio", "both") else summary.get("bgm_path"),
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

            if summary.get("mode") == "cinema" or vid_to_upload.get("is_cinema_short"):
                log(f"🎉 Standalone 3-Minute Cinema Short successfully uploaded: {upload_res.get('url')}!")
                completed = history.get("completed_episodes", [])
                if ep_key not in completed:
                    completed.append(ep_key)
                    history["completed_episodes"] = completed
                history["active_episode"] = None
            elif active and active.get("episode_key") == ep_key:
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
                "mode": summary.get("mode", "daily_funnel"),
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

            shield = MultiAgentCopyrightShield()
            check_res = shield.inspect_candidate(
                video_path=part["video_path"],
                title=part["title"],
                description=part["description"],
                is_short=True,
                hashtags=part.get("hashtags", []),
            )
            if not check_res.passed:
                log(f"🛑 [Uploader Shield] Part {p_num} REJECTED by copyright filter: {check_res.summary}")
                log("Aborting upload for this part to protect channel standing.")
                results["shorts"].append({"part": p_num, "status": "filter_rejected", "violations": check_res.violations})
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
                shield = MultiAgentCopyrightShield()
                check_full = shield.inspect_candidate(
                    video_path=full["video_path"],
                    title=full["title"],
                    description=full["description"],
                    is_short=False,
                    hashtags=full.get("hashtags", []),
                )
                if not check_full.passed:
                    log(f"🛑 [Uploader Shield] Full Video REJECTED by copyright filter: {check_full.summary}")
                    log("Aborting full video upload to protect channel standing.")
                    results["full_video"] = {"status": "filter_rejected", "violations": check_full.violations}
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


def delete_video(youtube, video_id: str) -> bool:
    """Delete a video by ID."""
    try:
        youtube.videos().delete(id=video_id).execute()
        log(f"🗑️ Successfully deleted video {video_id} from YouTube channel.")
        return True
    except Exception as e:
        log(f"⚠️ Could not delete video {video_id} via API: {e}")
        log(f"💡 Note: If your OAuth token has upload-only scope, you can quickly delete blocked video {video_id} in YouTube Studio.")
        return False


def set_video_visibility(youtube, video_id: str, privacy: str = "private") -> bool:
    """Update privacy status of a video."""
    try:
        youtube.videos().update(
            part="status",
            body={"id": video_id, "status": {"privacyStatus": privacy}},
        ).execute()
        log(f"🔒 Successfully set visibility for {video_id} to '{privacy}'.")
        return True
    except Exception as e:
        log(f"⚠️ Failed to set visibility for {video_id}: {e}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload or manage anime videos on YouTube")
    parser.add_argument("--dir", help="Episode output directory (e.g. output/demon-slayer-s01e01)")
    parser.add_argument("--live", action="store_true", help="Perform real YouTube upload")
    parser.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    parser.add_argument("--no-shorts", action="store_true", help="Skip Shorts upload")
    parser.add_argument("--no-full", action="store_true", help="Skip Full Video upload")
    parser.add_argument("--delete", help="Video ID to delete from channel")
    parser.add_argument("--set-privacy", nargs=2, metavar=("VIDEO_ID", "PRIVACY"), help="Update video privacy (e.g. --set-privacy G-zNVrRr82I private)")
    parser.add_argument("--allow-cadence-override", action="store_true", help="Bypass 24-hour upload cadence interval")
    parser.add_argument("--cadence-hours", type=float, default=24.0, help="Minimum hours between uploads (default: 24.0)")

    args = parser.parse_args()

    if args.delete:
        yt = get_youtube_service()
        if yt:
            delete_video(yt, args.delete)
        sys.exit(0)

    if args.set_privacy:
        yt = get_youtube_service()
        if not yt:
            sys.exit(1)
        vid_id, priv = args.set_privacy
        ok = set_video_visibility(yt, vid_id, priv)
        sys.exit(0 if ok else 1)

    if not args.dir:
        parser.error("--dir is required when uploading")

    res = upload_episode_package(
        episode_dir=args.dir,
        live=args.live,
        privacy=args.privacy,
        upload_shorts=not args.no_shorts,
        upload_full=not args.no_full,
        allow_cadence_override=args.allow_cadence_override,
        cadence_hours=args.cadence_hours,
    )
    print(json.dumps(res, indent=2))

