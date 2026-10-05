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

from anime_catalog import get_next_episode, load_catalog, load_history, save_history
from anime_script_engine import generate_episode_script
from anime_voice_subtitles import produce_part_audio_subtitles
from anime_video_engine import assemble_short_part, download_gdrive_episode, stitch_full_episode_video

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = WORKSPACE_DIR / "output"
CACHE_DIR = WORKSPACE_DIR / "cache"
DEFAULT_BGM_PATH = WORKSPACE_DIR / "assets" / "bgm" / "cinematic_suspense_thriller.mp3"


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
    
    if not bgm_path and DEFAULT_BGM_PATH.exists():
        bgm_path = DEFAULT_BGM_PATH
        log(f"Using default royalty-free BGM: {DEFAULT_BGM_PATH.name}")
    
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

        # Render Short Part Video
        assemble_success = assemble_short_part(
            raw_video_path=raw_video_path,
            voice_audio_path=audio_file,
            ass_subtitle_path=ass_file,
            output_video_path=video_file,
            time_window=tuple(part_info.get("time_range", [0, 450])),
            total_duration=duration,
            bgm_path=bgm_path,
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

    # 5. Stitch into Full Episode Video
    log("\n=== Stitching All Parts into Full Episode Video ===")
    full_video_file = ep_work_dir / f"full_{target_ep['episode_key']}.mp4"
    stitch_success = stitch_full_episode_video(
        part_video_paths=rendered_part_videos,
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

    # 6. Update History (only on complete success)
    history = load_history()
    completed = history.get("completed_episodes", [])
    if target_ep["episode_key"] not in completed and not dry_run:
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run anime explanation pipeline")
    parser.add_argument("--episode", default=None, help="Episode key (e.g. demon-slayer-s01e01)")
    parser.add_argument("--series", default=None, help="Series filter (e.g. demon-slayer, jujutsu-kaisen)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without heavy rendering")
    parser.add_argument("--voice", default="en-US-ChristopherNeural", help="Edge-TTS voice")
    parser.add_argument("--bgm", default=None, help="Optional background music path")
    parser.add_argument("--live", action="store_true", help="Live YouTube upload mode")

    args = parser.parse_args()
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
