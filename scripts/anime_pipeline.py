#!/usr/bin/env python3
"""
End-to-End Anime Explanation Pipeline Orchestrator for Bhaloo Ji Channel.
Orchestrates:
1. Episode selection from Google Drive catalog.
2. AI-Adaptive multi-part script generation (3-5 parts).
3. Neural voiceover & animated ASS karaoke subtitles.
4. Anti-copyright video slicing and composition for each Short part.
5. Stitching all parts into a cohesive Full Episode Video.
6. YouTube metadata packaging (titles, descriptions, tags, fair use disclaimers).
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from anime_catalog import get_next_episode, get_active_episode, load_catalog, load_history, save_history
from anime_script_engine import generate_episode_script
from anime_voice_subtitles import produce_part_audio_subtitles
from anime_video_engine import assemble_short_part, download_gdrive_episode, stitch_full_episode_video, pick_bgm_for_episode

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = WORKSPACE_DIR / "output"
CACHE_DIR = WORKSPACE_DIR / "cache"


def log(msg: str) -> None:
    print(f"[anime_pipeline] {msg}", flush=True)


def run_pipeline(
    episode_key: str | None = None,
    series_filter: str | None = None,
    dry_run: bool = False,
    voice: str = "en-US-ChristopherNeural",
    bgm_path: str | Path | None = None,
    upload_live: bool = False,
) -> dict:
    """Run full episodic production."""
    log("=== Starting Bhaloo Ji Anime Explanation Pipeline ===")

    # 1. Select Episode

    catalog = load_catalog()
    episodes = catalog.get("episodes", [])
    if not episodes:
        log("No episodes in catalog. Run 'python3 scripts/anime_catalog.py --sync' first.")
        return {"status": "error", "message": "empty catalog"}

    target_ep = None
    if episode_key:
        for ep in episodes:
            if ep["episode_key"] == episode_key:
                target_ep = ep
                break
        if not target_ep:
            log(f"Episode key '{episode_key}' not found in catalog.")
            return {"status": "error", "message": "episode not found"}
    else:
        target_ep = get_next_episode(series_filter)
        if not target_ep:
            log("No pending episodes found in catalog.")
            return {"status": "complete", "message": "all episodes done"}

    log(f"Target Episode: {target_ep['display_name']} (Key: {target_ep['episode_key']})")
    ep_work_dir = OUTPUT_DIR / target_ep["episode_key"]
    ep_work_dir.mkdir(parents=True, exist_ok=True)

    # Auto-select royalty-free BGM based on series (overridable via --bgm flag)
    if not bgm_path:
        bgm_path = pick_bgm_for_episode(series_id=target_ep.get("series_id"))
        log(f"Auto-selected royalty-free BGM: {bgm_path.name} (series: {target_ep.get('series_id')})")
    elif not Path(bgm_path).exists():
        bgm_path = pick_bgm_for_episode(series_id=target_ep.get("series_id"))
        log(f"Specified BGM not found, auto-selecting: {bgm_path.name}")

    # 2. Generate AI Script Package
    log("Generating AI-Adaptive multi-part script and full video metadata...")
    script_package = generate_episode_script(target_ep)
    script_file = ep_work_dir / "script_package.json"
    with open(script_file, "w", encoding="utf-8") as f:
        json.dump(script_package, f, indent=2, ensure_ascii=False)
    log(f"Script saved: {script_package['episode_title']} ({script_package['total_parts']} parts)")

    # 3. Source Episode Video
    raw_video_path = CACHE_DIR / target_ep["filename"]
    if not dry_run and not raw_video_path.exists():
        download_success = download_gdrive_episode(
            file_id=target_ep["gdrive_file_id"],
            dest_path=raw_video_path,
            dry_run=dry_run
        )
        if not download_success:
            log("Failed to download raw anime episode from Google Drive.")
            return {"status": "error", "message": "gdrive download failed"}
    elif dry_run:
        download_gdrive_episode(target_ep["gdrive_file_id"], raw_video_path, dry_run=True)

    # 4. Produce Each Part (Shorts)
    rendered_part_videos = []
    parts_meta = []

    for part_info in script_package["parts"]:
        p_num = part_info["part"]
        total_p = part_info["total_parts"]
        log(f"\n--- Processing Part {p_num}/{total_p} ---")

        part_dir = ep_work_dir / f"part_{p_num:02d}"
        part_dir.mkdir(parents=True, exist_ok=True)

        audio_file = part_dir / "voice.mp3"
        ass_file = part_dir / "subtitles.ass"
        video_file = part_dir / f"short_{target_ep['episode_key']}_part{p_num}.mp4"

        # Generate voiceover & animated subtitles
        log(f"Generating voiceover and animated ASS subtitles for Part {p_num}...")
        voice_res = produce_part_audio_subtitles(
            text=part_info["narration"],
            output_audio_path=audio_file,
            output_ass_path=ass_file,
            badge_text=part_info["badge"],
            voice=voice,
        )
        duration = voice_res["duration"]
        log(f"Voiceover duration: {duration:.2f}s ({voice_res['word_count']} words)")

        # Render Short Part Video (9:16 vertical as it is)
        assemble_success = assemble_short_part(
            raw_video_path=raw_video_path,
            voice_audio_path=audio_file,
            ass_subtitle_path=ass_file,
            output_video_path=video_file,
            time_window=tuple(part_info.get("time_range", [90, 450])),
            total_duration=duration,
            bgm_path=bgm_path,
            is_landscape=False,
            dry_run=dry_run,
        )

        part_meta = {
            "part": p_num,
            "total_parts": total_p,
            "title": part_info["short_title"],
            "video_path": str(video_file),
            "audio_path": str(audio_file),
            "ass_path": str(ass_file),
            "duration": duration,
            "hashtags": part_info["hashtags"],
            "description": part_info["description"],
            "status": "rendered" if assemble_success else "failed",
        }
        parts_meta.append(part_meta)
        if assemble_success and video_file.exists() and video_file.stat().st_size > 1024 * 50:
            rendered_part_videos.append(video_file)

        # Save individual Short manifest
        with open(part_dir / "meta.json", "w", encoding="utf-8") as f:
            json.dump(part_meta, f, indent=2)

    all_parts_ok = (len(rendered_part_videos) == len(script_package["parts"]))
    if not all_parts_ok:
        log("❌ Some or all Short parts failed to render. Aborting stitching and history update.")
        pipeline_result = {
            "status": "error",
            "message": "one or more shorts failed to render",
            "episode_key": target_ep["episode_key"],
            "display_name": target_ep["display_name"],
            "parts": parts_meta,
            "full_video": {"status": "skipped", "message": "parts failed"},
        }
        with open(ep_work_dir / "pipeline_summary.json", "w", encoding="utf-8") as f:
            json.dump(pipeline_result, f, indent=2)
        return pipeline_result

    # 5. Render Landscape Parts and Stitch into Full Landscape Episode Video
    log("\n=== Rendering Landscape Parts & Stitching into Full Episode Video ===")
    full_video_file = ep_work_dir / f"full_{target_ep['episode_key']}.mp4"
    rendered_landscape_videos = []
    for part_info in script_package["parts"]:
        p_num = part_info["part"]
        p_dir = ep_work_dir / f"part_{p_num:02d}"
        audio_file = p_dir / "voice.mp3"
        ass_land_file = p_dir / "subtitles_landscape.ass"
        vid_land_file = p_dir / f"landscape_{target_ep['episode_key']}_part{p_num}.mp4"

        produce_part_audio_subtitles(
            text=part_info["narration"],
            output_audio_path=audio_file,
            output_ass_path=ass_land_file,
            badge_text="",
            voice=voice,
            is_landscape=True,
        )
        assemble_short_part(
            raw_video_path=raw_video_path,
            voice_audio_path=audio_file,
            ass_subtitle_path=ass_land_file,
            output_video_path=vid_land_file,
            time_window=tuple(part_info.get("time_range", [90, 450])),
            total_duration=part_info.get("estimated_duration", 60.0),
            bgm_path=bgm_path,
            is_landscape=True,
            dry_run=dry_run,
        )
        rendered_landscape_videos.append(vid_land_file)

    stitch_success = stitch_full_episode_video(
        part_video_paths=rendered_landscape_videos,
        output_full_path=full_video_file,
        dry_run=dry_run,
    )

    full_video_meta = {
        "title": script_package["full_video"]["title"],
        "video_path": str(full_video_file),
        "chapters": script_package["full_video"]["chapters"],
        "description": script_package["full_video"]["description"],
        "hashtags": script_package["full_video"]["hashtags"],
        "status": "rendered" if stitch_success else "failed",
    }
    with open(ep_work_dir / "full_video_meta.json", "w", encoding="utf-8") as f:
        json.dump(full_video_meta, f, indent=2)

    if not stitch_success:
        log("❌ Failed to stitch full episode video.")
        pipeline_result = {
            "status": "error",
            "message": "full episode video stitch failed",
            "episode_key": target_ep["episode_key"],
            "display_name": target_ep["display_name"],
            "parts": parts_meta,
            "full_video": full_video_meta,
        }
        with open(ep_work_dir / "pipeline_summary.json", "w", encoding="utf-8") as f:
            json.dump(pipeline_result, f, indent=2)
        return pipeline_result

    # 6. Update History (live completion managed by anime_youtube_uploader after verified upload)
    history = load_history()
    completed = history.get("completed_episodes", [])
    if target_ep["episode_key"] not in completed and dry_run:
        completed.append(target_ep["episode_key"])
        history["completed_episodes"] = completed
        history["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        save_history(history)

    pipeline_result = {
        "status": "success",
        "episode_key": target_ep["episode_key"],
        "display_name": target_ep["display_name"],
        "parts": parts_meta,
        "full_video": full_video_meta,
    }

    # Save summary manifest
    with open(ep_work_dir / "pipeline_summary.json", "w", encoding="utf-8") as f:
        json.dump(pipeline_result, f, indent=2)

    log(f"\n🎉 Pipeline complete for {target_ep['display_name']}!")
    log(f"Produced {len(parts_meta)} Shorts + 1 Full Episode Video.")
    log(f"Artifacts located at: {ep_work_dir}")

    return pipeline_result


def run_daily_funnel(
    series_filter: str | None = None,
    dry_run: bool = False,
    voice: str = "en-US-ChristopherNeural",
    bgm_path: str | Path | None = None,
) -> dict:
    """
    Executes exactly ONE step of the daily anime funnel (RecapKun Style):
    - Step 1: If no active episode, select next episode, generate RecapKun script,
      render & stitch Full Normal Video (16:9 widescreen), and queue it for upload first.
    - Step 2: If active episode has normal video uploaded, find next pending Short part
      (Part 1, Part 2, ...), render it, and queue it for upload.
    - Step 3: Until all Short parts are uploaded, NO new episode or normal video is allowed.
    - Step 4: When the final Short part is uploaded, the episode is marked complete and gate unlocks next episode!
    """
    log("=== Starting Bhaloo Ji Daily Anime Funnel (RecapKun Style) ===")
    history = load_history()
    active_ep = history.get("active_episode")

    # CASE A: No active episode in progress -> Start next episode, upload Normal Video FIRST
    if not active_ep or not active_ep.get("episode_key"):
        target_ep = get_next_episode(series_filter)
        if not target_ep:
            log("All episodes in catalog are complete! Nothing to process.")
            return {"status": "complete", "message": "all episodes complete"}

        ep_key = target_ep["episode_key"]
        log(f"🎬 Starting NEW Episode: {target_ep['display_name']} ({ep_key})")
        ep_work_dir = OUTPUT_DIR / ep_key
        ep_work_dir.mkdir(parents=True, exist_ok=True)

        if not bgm_path or not Path(bgm_path).exists():
            bgm_path = pick_bgm_for_episode(series_id=target_ep.get("series_id"))
            log(f"Auto-selected royalty-free BGM: {bgm_path.name}")

        log("Generating RecapKun-style full script & multi-part breakdown...")
        script_package = generate_episode_script(target_ep)
        with open(ep_work_dir / "script_package.json", "w", encoding="utf-8") as f:
            json.dump(script_package, f, indent=2, ensure_ascii=False)

        raw_video_path = CACHE_DIR / target_ep["filename"]
        if not dry_run and not raw_video_path.exists():
            ok = download_gdrive_episode(target_ep["gdrive_file_id"], raw_video_path, dry_run=dry_run)
            if not ok:
                log("Failed to download raw anime episode.")
                return {"status": "error", "message": "gdrive download failed"}
        elif dry_run:
            download_gdrive_episode(target_ep["gdrive_file_id"], raw_video_path, dry_run=True)

        # Render all parts in true 16:9 Landscape (1920x1080) and stitch Full Normal Video
        rendered_part_videos = []
        parts_meta = []
        for part_info in script_package["parts"]:
            p_num = part_info["part"]
            p_dir = ep_work_dir / f"part_{p_num:02d}"
            p_dir.mkdir(parents=True, exist_ok=True)
            audio_f = p_dir / "voice.mp3"
            ass_f = p_dir / "subtitles_landscape.ass"
            vid_f = p_dir / f"landscape_{ep_key}_part{p_num}.mp4"

            v_res = produce_part_audio_subtitles(
                text=part_info["narration"],
                output_audio_path=audio_f,
                output_ass_path=ass_f,
                badge_text="",  # Clean presentation for landscape full movie recap
                voice=voice,
                is_landscape=True,
            )
            assemble_short_part(
                raw_video_path=raw_video_path,
                voice_audio_path=audio_f,
                ass_subtitle_path=ass_f,
                output_video_path=vid_f,
                time_window=tuple(part_info.get("time_range", [90, 450])),
                total_duration=v_res["duration"],
                bgm_path=bgm_path,
                is_landscape=True,
                dry_run=dry_run,
            )
            part_meta = {
                "part": p_num,
                "title": part_info.get("short_title", f"Part {p_num}"),
                "video_path": str(vid_f),
                "hashtags": part_info.get("hashtags", []),
                "description": part_info.get("description", ""),
                "status": "rendered",
            }
            parts_meta.append(part_meta)
            rendered_part_videos.append(vid_f)

        # Stitch 16:9 Full Normal Video (true fullscreen landscape)
        full_video_f = ep_work_dir / f"full_{ep_key}.mp4"
        stitch_full_episode_video(
            part_video_paths=rendered_part_videos,
            output_full_path=full_video_f,
            dry_run=dry_run,
        )

        full_meta = {
            "title": script_package["full_video"]["title"],
            "video_path": str(full_video_f),
            "chapters": script_package["full_video"]["chapters"],
            "description": script_package["full_video"]["description"],
            "hashtags": script_package["full_video"]["hashtags"],
            "status": "rendered",
        }

        # Initialize active episode in history (normal video ready to upload first)
        history["active_episode"] = {
            "episode_key": ep_key,
            "series_id": target_ep.get("series_id"),
            "display_name": target_ep["display_name"],
            "filename": target_ep.get("filename"),
            "gdrive_file_id": target_ep.get("gdrive_file_id"),
            "total_parts": script_package["total_parts"],
            "normal_video_uploaded": False,
            "uploaded_shorts": [],
            "script_package": script_package,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        save_history(history)

        result = {
            "status": "success",
            "mode": "daily_funnel",
            "action": "normal_video",
            "episode_key": ep_key,
            "display_name": target_ep["display_name"],
            "video_to_upload": full_meta,
            "parts": parts_meta,
            "total_parts": script_package["total_parts"],
        }
        with open(ep_work_dir / "pipeline_summary.json", "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

        log(f"🎬 Full Normal Video prepared for {target_ep['display_name']}! Ready for YouTube upload.")
        return result

    # CASE B / C: Active episode is already in progress
    ep_key = active_ep["episode_key"]
    ep_work_dir = OUTPUT_DIR / ep_key
    ep_work_dir.mkdir(parents=True, exist_ok=True)
    script_package = active_ep.get("script_package", {})
    total_parts = active_ep.get("total_parts", len(script_package.get("parts", [])))

    # If Normal Video not yet uploaded, ensure full landscape video is rendered
    if not active_ep.get("normal_video_uploaded"):
        full_video_f = ep_work_dir / f"full_{ep_key}.mp4"
        if dry_run or not full_video_f.exists() or full_video_f.stat().st_size < 1024 * 100:
            raw_video_path = CACHE_DIR / active_ep.get("filename", f"{ep_key}.mp4")
            if not raw_video_path.exists():
                download_gdrive_episode(active_ep.get("gdrive_file_id", ""), raw_video_path, dry_run=dry_run)
            if not bgm_path or not Path(bgm_path).exists():
                bgm_path = pick_bgm_for_episode(series_id=active_ep.get("series_id"))

            rendered_landscape = []
            for part_info in script_package.get("parts", []):
                p_num = part_info["part"]
                p_dir = ep_work_dir / f"part_{p_num:02d}"
                p_dir.mkdir(parents=True, exist_ok=True)
                audio_f = p_dir / "voice.mp3"
                ass_f = p_dir / "subtitles_landscape.ass"
                vid_f = p_dir / f"landscape_{ep_key}_part{p_num}.mp4"

                v_res = produce_part_audio_subtitles(
                    text=part_info["narration"],
                    output_audio_path=audio_f,
                    output_ass_path=ass_f,
                    badge_text="",
                    voice=voice,
                    is_landscape=True,
                )
                assemble_short_part(
                    raw_video_path=raw_video_path,
                    voice_audio_path=audio_f,
                    ass_subtitle_path=ass_f,
                    output_video_path=vid_f,
                    time_window=tuple(part_info.get("time_range", [90, 450])),
                    total_duration=v_res["duration"],
                    bgm_path=bgm_path,
                    is_landscape=True,
                    dry_run=dry_run,
                )
                rendered_landscape.append(vid_f)

            stitch_full_episode_video(rendered_landscape, full_video_f, dry_run=dry_run)

        full_meta = {
            "title": script_package.get("full_video", {}).get("title", f"{ep_key} Full Recap"),
            "video_path": str(full_video_f),
            "chapters": script_package.get("full_video", {}).get("chapters", []),
            "description": script_package.get("full_video", {}).get("description", ""),
            "hashtags": script_package.get("full_video", {}).get("hashtags", ["anime", "bhalooji"]),
            "status": "rendered",
        }

        result = {
            "status": "success",
            "mode": "daily_funnel",
            "action": "normal_video",
            "episode_key": ep_key,
            "display_name": active_ep.get("display_name", ep_key),
            "video_to_upload": full_meta,
            "total_parts": total_parts,
        }
        with open(ep_work_dir / "pipeline_summary.json", "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        return result

    # CASE C: Normal video is already live! Upload next SHORT part
    uploaded_shorts = active_ep.get("uploaded_shorts", [])
    if len(uploaded_shorts) >= total_parts:
        # All shorts already uploaded -> unlock gate, mark episode complete, start next episode
        log(f"Episode {ep_key} all {total_parts} shorts already uploaded. Completing episode.")
        completed = history.get("completed_episodes", [])
        if ep_key not in completed:
            completed.append(ep_key)
            history["completed_episodes"] = completed
        history["active_episode"] = None
        save_history(history)
        return run_daily_funnel(series_filter, dry_run, voice, bgm_path)

    # Next short part number
    next_p = len(uploaded_shorts) + 1
    log(f"📱 Processing Short Part {next_p} of {total_parts} for {active_ep['display_name']}...")

    part_info = None
    for p in script_package.get("parts", []):
        if p["part"] == next_p:
            part_info = p
            break
    if not part_info:
        part_info = {
            "part": next_p,
            "hook": f"Part {next_p} of {active_ep['display_name']}!",
            "narration": f"Continuing the intense battle in {active_ep['display_name']} Part {next_p}.",
            "short_title": f"{active_ep['display_name']} Part {next_p} #shorts",
            "hashtags": ["anime", "animerecap", "shorts", "bhalooji"],
            "badge": f"PART {next_p}/{total_parts}",
            "time_range": [0, 450],
        }

    p_dir = ep_work_dir / f"part_{next_p:02d}"
    p_dir.mkdir(parents=True, exist_ok=True)
    audio_f = p_dir / "voice.mp3"
    ass_f = p_dir / "subtitles.ass"
    vid_f = p_dir / f"short_{ep_key}_part{next_p}.mp4"

    if not bgm_path or not Path(bgm_path).exists():
        bgm_path = pick_bgm_for_episode(series_id=active_ep.get("series_id"))

    raw_video_path = CACHE_DIR / active_ep.get("filename", f"{ep_key}.mp4")
    if not dry_run and not raw_video_path.exists():
        ok = download_gdrive_episode(active_ep.get("gdrive_file_id", ""), raw_video_path, dry_run=dry_run)
        if not ok:
            log("Failed to download raw anime episode.")
            return {"status": "error", "message": "gdrive download failed"}
    elif dry_run:
        download_gdrive_episode(active_ep.get("gdrive_file_id", ""), raw_video_path, dry_run=True)

    v_res = produce_part_audio_subtitles(
        text=part_info["narration"],
        output_audio_path=audio_f,
        output_ass_path=ass_f,
        badge_text=part_info.get("badge", f"PART {next_p}/{total_parts}"),
        voice=voice,
    )
    assemble_short_part(
        raw_video_path=raw_video_path,
        voice_audio_path=audio_f,
        ass_subtitle_path=ass_f,
        output_video_path=vid_f,
        time_window=tuple(part_info.get("time_range", [90, 450])),
        total_duration=v_res["duration"],
        bgm_path=bgm_path,
        is_landscape=False,
        dry_run=dry_run,
    )

    normal_vid_info = active_ep.get("normal_video", {})
    normal_url = normal_vid_info.get("url", "")
    teaser = f"\n🎬 Full episode explanation is live on our channel now: {normal_url}\n" if normal_url else "\n🎬 Full episode explanation is live on our channel now!\n"

    short_meta = {
        "part": next_p,
        "title": part_info["short_title"],
        "video_path": str(vid_f),
        "hashtags": part_info["hashtags"],
        "description": f"{part_info.get('hook', '')}\nPart {next_p} of {total_parts} covering {active_ep['display_name']}.{teaser}\n#anime #animerecap #shorts #bhalooji",
        "status": "rendered",
    }

    result = {
        "status": "success",
        "mode": "daily_funnel",
        "action": "short",
        "part": next_p,
        "total_parts": total_parts,
        "episode_key": ep_key,
        "display_name": active_ep["display_name"],
        "video_to_upload": short_meta,
    }
    with open(ep_work_dir / "pipeline_summary.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    log(f"📱 Short Part {next_p}/{total_parts} prepared for {active_ep['display_name']}! Ready for YouTube upload.")
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run anime explanation pipeline")
    parser.add_argument("--mode", default="daily", choices=["daily", "full"], help="Pipeline mode: 'daily' (1 video/day: normal video first, then daily shorts) or 'full' (legacy all-in-one)")
    parser.add_argument("--episode", default=None, help="Episode key (e.g. demon-slayer-s01e01)")
    parser.add_argument("--series", default=None, help="Series filter (e.g. demon-slayer, jujutsu-kaisen)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without heavy rendering")
    parser.add_argument("--voice", default="en-US-ChristopherNeural", help="Edge-TTS voice (default: RecapKun ChristopherNeural)")
    parser.add_argument("--bgm", default=None, help="Optional background music path")
    parser.add_argument("--live", action="store_true", help="Live YouTube upload mode")

    args = parser.parse_args()
    if args.mode == "daily" and not args.episode:
        res = run_daily_funnel(
            series_filter=args.series,
            dry_run=args.dry_run,
            voice=args.voice,
            bgm_path=args.bgm,
        )
    else:
        res = run_pipeline(
            episode_key=args.episode,
            series_filter=args.series,
            dry_run=args.dry_run,
            voice=args.voice,
            bgm_path=args.bgm,
            upload_live=args.live,
        )
    print(json.dumps(res, indent=2))
    if res.get("status") != "success":
        sys.exit(1)
