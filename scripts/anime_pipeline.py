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
import re
import sys
import time
from pathlib import Path

from anime_catalog import get_next_episode, get_active_episode, load_catalog, load_history, save_history, get_next_arc, get_arc, get_story_arcs
from anime_script_engine import generate_episode_script, generate_cinema_script, generate_arc_script
from anime_subtitle_sync import get_episode_scene_acts
from anime_voice_subtitles import produce_part_audio_subtitles, produce_master_audio_subtitles, produce_beat_narration, CINEMA_VOICE
from anime_copyright_filter import MultiAgentCopyrightShield
from anime_video_engine import (
    assemble_short_part,
    download_gdrive_episode,
    stitch_full_episode_video,
    pick_bgm_for_episode,
    assemble_master_full_video,
    assemble_arc_master_video,
    derive_short_from_master,
)

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
    full_bleed: bool = False,
    bgm_mood: str | None = None,
    remove_copyrighted_clip: bool = False,
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

    # 4. Produce Master Full Normal Video (16:9 Landscape) as ONE UNIFIED Continuous Master
    log("\n=== 🎬 Producing Master Full Normal Video (16:9 Landscape) ===")
    full_video_file = ep_work_dir / f"full_{target_ep['episode_key']}.mp4"
    full_audio_file = ep_work_dir / "full_voice.mp3"
    full_ass_file = ep_work_dir / "full_subtitles.ass"

    # Generate single continuous voiceover audio and landscape karaoke subtitles
    chapter_texts = [p["narration"] for p in script_package["parts"]]
    if dry_run:
        total_master_duration = sum(len(t.split()) / 3.0 for t in chapter_texts)
        chapter_segments = []
        curr_start = 0.0
        for idx, text in enumerate(chapter_texts):
            dur = len(text.split()) / 3.0
            chapter_segments.append({
                "chapter_index": idx + 1,
                "title": f"Chapter {idx + 1}",
                "start_time": curr_start,
                "end_time": curr_start + dur,
                "duration": dur,
                "narration": text,
            })
            curr_start += dur
        master_audio_res = {
            "duration": total_master_duration,
            "word_count": sum(len(t.split()) for t in chapter_texts),
            "chapter_segments": chapter_segments,
        }
        log(f"[DRY-RUN] Simulating master voiceover: {total_master_duration:.1f}s ({len(chapter_texts)} chapters)")
    else:
        master_audio_res = produce_master_audio_subtitles(
            chapter_texts=chapter_texts,
            output_audio_path=full_audio_file,
            output_ass_path=full_ass_file,
            voice=voice,
            is_landscape=True,
        )
        total_master_duration = master_audio_res["duration"]
        chapter_segments = master_audio_res.get("chapter_segments", [])
    log(f"Master continuous voiceover duration: {total_master_duration:.2f}s ({master_audio_res['word_count']} words)")

    # Build chapter segments mapping with exact time_ranges and beats from script package
    chapter_segments = master_audio_res.get("chapter_segments", [])
    for idx, chap in enumerate(chapter_segments):
        if idx < len(script_package["parts"]):
            part_p = script_package["parts"][idx]
            chap["time_range"] = part_p.get("time_range", [120, 500])
            chap["narration"] = part_p.get("narration", "")
            if "beats" in part_p and part_p["beats"]:
                chap["beats"] = part_p["beats"]

    master_render_success = assemble_master_full_video(
        raw_video_path=raw_video_path,
        voice_audio_path=full_audio_file,
        ass_subtitle_path=full_ass_file,
        output_video_path=full_video_file,
        chapter_segments=chapter_segments,
        total_duration=total_master_duration,
        bgm_path=bgm_path,
        dry_run=dry_run,
    )

    full_video_meta = {
        "title": script_package["full_video"]["title"],
        "video_path": str(full_video_file),
        "chapters": script_package["full_video"]["chapters"],
        "description": script_package["full_video"]["description"],
        "hashtags": script_package["full_video"]["hashtags"],
        "duration": total_master_duration,
        "status": "rendered" if master_render_success else "failed",
        "is_full_video": True,
    }
    with open(ep_work_dir / "full_video_meta.json", "w", encoding="utf-8") as f:
        json.dump(full_video_meta, f, indent=2)

    if not master_render_success:
        log("❌ Failed to produce Master Full Normal Video.")
        pipeline_result = {
            "status": "error",
            "message": "master normal video production failed",
            "episode_key": target_ep["episode_key"],
            "display_name": target_ep["display_name"],
            "parts": [],
            "full_video": full_video_meta,
        }
        with open(ep_work_dir / "pipeline_summary.json", "w", encoding="utf-8") as f:
            json.dump(pipeline_result, f, indent=2)
        return pipeline_result

    log(f"🎬 Master Full Normal Video successfully produced: {full_video_file.name}")

    # 5. Derive Sequential Daily Shorts FROM Master Video (9:16 Vertical Excerpts)
    log("\n=== 📱 Deriving Daily Shorts Excerpts from Master Video ===")
    parts_meta = []
    rendered_part_videos = []

    for idx, part_info in enumerate(script_package["parts"]):
        p_num = part_info["part"]
        total_p = part_info["total_parts"]
        log(f"\n--- Deriving Short Excerpt Part {p_num}/{total_p} ---")

        part_dir = ep_work_dir / f"part_{p_num:02d}"
        part_dir.mkdir(parents=True, exist_ok=True)
        video_file = part_dir / f"short_{target_ep['episode_key']}_part{p_num}.mp4"

        # Lookup chapter start and end from master audio segments
        if idx < len(chapter_segments):
            c_start = chapter_segments[idx]["start_time"]
            c_end = chapter_segments[idx]["end_time"]
            c_dur = chapter_segments[idx]["duration"]
        else:
            c_start = 0.0
            c_end = 60.0
            c_dur = 60.0

        derive_ok = derive_short_from_master(
            master_video_path=full_video_file,
            output_short_path=video_file,
            start_time=c_start,
            end_time=c_end,
            badge_text=part_info.get("badge", f"PART {p_num}/{total_p}"),
            dry_run=dry_run,
        )

        part_meta = {
            "part": p_num,
            "total_parts": total_p,
            "title": part_info["short_title"],
            "video_path": str(video_file),
            "start_time": c_start,
            "end_time": c_end,
            "duration": c_dur,
            "hashtags": part_info["hashtags"],
            "description": part_info["description"],
            "status": "rendered" if derive_ok else "failed",
        }
        parts_meta.append(part_meta)
        if derive_ok and (dry_run or (video_file.exists() and video_file.stat().st_size > 1024 * 50)):
            rendered_part_videos.append(video_file)

        # Save individual Short excerpt manifest
        with open(part_dir / "meta.json", "w", encoding="utf-8") as f:
            json.dump(part_meta, f, indent=2)

    all_parts_ok = (len(rendered_part_videos) == len(script_package["parts"]))
    if not all_parts_ok:
        log("⚠️ Some Short excerpts failed to render, but Master Full Video was successfully produced.")

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
        "mode": "recapkun",
        "action": "normal_video",
        "episode_key": target_ep["episode_key"],
        "display_name": target_ep["display_name"],
        "video_to_upload": full_video_meta,
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


def run_cinema_pipeline(
    episode_key: str | None = None,
    series_filter: str | None = None,
    dry_run: bool = False,
    voice: str = CINEMA_VOICE,
    bgm_path: str | Path | None = None,
    full_bleed: bool = True,
    bgm_mood: str | None = None,
    remove_copyrighted_clip: bool = False,
) -> dict:
    """
    Executes a single standalone 2.5 to 3 minute YouTube Short production
    modeled directly after 'narration cinema' (ICFR22QXs_o):
    - Single uninterrupted 150-175s Short per episode (zero multi-part fragmentation).
    - Full-bleed 9:16 vertical canvas (1080x1920) with filmic grading and unsharp mask.
    - Deep cinematic trailer baritone voice (en-US-GuyNeural) with lower-third dynamic captions.
    - High-tension thriller action BGM.
    - Viral title formula: 'He Was the [X]… Until He [Y]! | Story Recap Explanation #shorts'.
    - High-retention comment trap CTA ending: 'To watch the next episode, comment yes.'
    """
    log("=== 🎬 Starting Bhaloo Ji Narration Cinema Engine (Standalone 3-Min Short) ===")
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
            log("All episodes in catalog are complete! Nothing to process.")
            return {"status": "complete", "message": "all episodes complete"}

    ep_key = target_ep["episode_key"]
    log(f"🎬 Producing Cinema Short for: {target_ep['display_name']} ({ep_key})")
    ep_work_dir = OUTPUT_DIR / ep_key
    ep_work_dir.mkdir(parents=True, exist_ok=True)

    # 1. BGM selection (Default series recap track, e.g. AERØHEAD - Fragments, or explicit mood)
    if not bgm_path or not Path(bgm_path).exists():
        bgm_path = pick_bgm_for_episode(series_id=target_ep.get("series_id"), mood=bgm_mood)
        log(f"Auto-selected BGM: {bgm_path.name}")

    # 2. Cinema Script Generation
    log("Generating 3-minute Narration Cinema script with impossible rule hook & comment trap CTA...")
    script = generate_cinema_script(target_ep)
    with open(ep_work_dir / "cinema_script.json", "w", encoding="utf-8") as f:
        json.dump(script, f, indent=2, ensure_ascii=False)
    log(f"Title: {script['title']}")
    log(f"Word count: {script['word_count']} words (~{script['estimated_duration']:.1f}s)")

    # 3. Audio & Cinema Subtitles (en-US-GuyNeural baritone, lower-third safe zone, full_bleed=True)
    audio_f = ep_work_dir / "voice.mp3"
    ass_f = ep_work_dir / "subtitles.ass"
    if dry_run:
        actual_dur = script["estimated_duration"]
        v_res = {"duration": actual_dur, "word_count": script["word_count"]}
        log(f"[DRY-RUN] Simulating cinema voiceover: {actual_dur:.1f}s ({script['word_count']} words)")
    else:
        v_res = produce_part_audio_subtitles(
            text=script["narration"],
            output_audio_path=audio_f,
            output_ass_path=ass_f,
            badge_text="",
            voice=voice or CINEMA_VOICE,
            rate="+2%" if (voice == "adam" or voice == CINEMA_VOICE) else "+6%",
            is_landscape=False,
            full_bleed=full_bleed,
        )
        actual_dur = v_res["duration"]
        log(f"Cinema voiceover synthesized: {actual_dur:.1f}s using {voice or CINEMA_VOICE}")

    # 4. Source raw anime video
    raw_video_path = CACHE_DIR / target_ep["filename"]
    if not dry_run and not raw_video_path.exists():
        ok = download_gdrive_episode(target_ep["gdrive_file_id"], raw_video_path, dry_run=dry_run)
        if not ok:
            log("Failed to download raw anime episode from Google Drive.")
            return {"status": "error", "message": "gdrive download failed"}
    elif dry_run:
        download_gdrive_episode(target_ep["gdrive_file_id"], raw_video_path, dry_run=True)

    # 5. Video Assembly (AniDoc Full-Bleed 9:16 Vertical with Character Tracking, 1080x1920)
    vid_f = ep_work_dir / f"cinema_{ep_key}.mp4"
    render_ok = assemble_short_part(
        raw_video_path=raw_video_path,
        voice_audio_path=audio_f,
        ass_subtitle_path=ass_f,
        output_video_path=vid_f,
        time_window=tuple(script["time_window"]),
        total_duration=min(178.0, actual_dur),
        bgm_path=bgm_path,
        is_landscape=False,
        dry_run=dry_run,
        beats=script.get("beats"),
        narration=script["narration"],
        full_bleed=full_bleed,
        sentence_durations=v_res.get("sentence_durations"),
        remove_copyrighted_clip=remove_copyrighted_clip,
    )

    # 6. Anti-Copyright Shield Verification
    shield = MultiAgentCopyrightShield()
    clean_title, clean_desc = shield.remediate_metadata(
        title=script["title"],
        description=script["description"],
        is_short=True,
        part_num=None,
        display_name=target_ep["display_name"],
    )

    short_meta = {
        "title": clean_title,
        "video_path": str(vid_f),
        "description": clean_desc,
        "hashtags": script["hashtags"],
        "duration": actual_dur,
        "status": "rendered" if render_ok else "failed",
        "is_full_video": False,
        "is_cinema_short": True,
    }

    result = {
        "status": "success",
        "mode": "cinema",
        "action": "short",
        "episode_key": ep_key,
        "display_name": target_ep["display_name"],
        "full_bleed": full_bleed,
        "presentation_style": "full_bleed" if full_bleed else "card_blur",
        "bgm_mood": bgm_mood,
        "video_to_upload": short_meta,
    }

    with open(ep_work_dir / "pipeline_summary.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    log(f"🎬 Standalone 3-Minute Cinema Short ready for {target_ep['display_name']}!")
    log(f"Title: {clean_title}")
    return result


def run_daily_funnel(
    series_filter: str | None = None,
    dry_run: bool = False,
    voice: str = "en-US-ChristopherNeural",
    bgm_path: str | Path | None = None,
    full_bleed: bool = False,
    remove_copyrighted_clip: bool = False,
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

        # Produce Master Full Normal Video (16:9 Landscape) as ONE UNIFIED Continuous Master
        full_video_f = ep_work_dir / f"full_{ep_key}.mp4"
        full_audio_f = ep_work_dir / "full_voice.mp3"
        full_ass_f = ep_work_dir / "full_subtitles.ass"

        chapter_texts = [p["narration"] for p in script_package["parts"]]
        if dry_run:
            total_master_dur = sum(len(t.split()) / 3.0 for t in chapter_texts)
            chapter_segments = []
            curr_start = 0.0
            for idx, text in enumerate(chapter_texts):
                dur = len(text.split()) / 3.0
                chapter_segments.append({
                    "chapter_index": idx + 1,
                    "title": f"Chapter {idx + 1}",
                    "start_time": curr_start,
                    "end_time": curr_start + dur,
                    "duration": dur,
                    "narration": text,
                })
                curr_start += dur
            log(f"[DRY-RUN] Simulating master voiceover: {total_master_dur:.1f}s ({len(chapter_texts)} chapters)")
        else:
            master_audio_res = produce_master_audio_subtitles(
                chapter_texts=chapter_texts,
                output_audio_path=full_audio_f,
                output_ass_path=full_ass_f,
                voice=voice,
                is_landscape=True,
            )
            total_master_dur = master_audio_res["duration"]
            chapter_segments = master_audio_res.get("chapter_segments", [])
        for idx, chap in enumerate(chapter_segments):
            if idx < len(script_package["parts"]):
                part_p = script_package["parts"][idx]
                chap["time_range"] = part_p.get("time_range", [120, 500])
                chap["narration"] = part_p.get("narration", "")
                if "beats" in part_p and part_p["beats"]:
                    chap["beats"] = part_p["beats"]

        master_ok = assemble_master_full_video(
            raw_video_path=raw_video_path,
            voice_audio_path=full_audio_f,
            ass_subtitle_path=full_ass_f,
            output_video_path=full_video_f,
            chapter_segments=chapter_segments,
            total_duration=total_master_dur,
            bgm_path=bgm_path,
            dry_run=dry_run,
        )

        shield = MultiAgentCopyrightShield()
        full_title_raw = script_package["full_video"]["title"]
        clean_full_title, clean_full_desc = shield.remediate_metadata(
            title=full_title_raw,
            description=script_package["full_video"]["description"],
            is_short=False,
            display_name=target_ep["display_name"],
        )

        full_meta = {
            "title": clean_full_title,
            "video_path": str(full_video_f),
            "chapters": script_package["full_video"]["chapters"],
            "description": clean_full_desc,
            "hashtags": script_package["full_video"]["hashtags"],
            "duration": total_master_dur,
            "status": "rendered" if master_ok else "failed",
            "is_full_video": True,
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
        parts_meta = []
        for p in script_package["parts"]:
            p_num = p["part"]
            p_title = p.get("short_title", f"Part {p_num}")
            if "explanation" not in p_title.lower() and "explained" not in p_title.lower():
                if re.search(rf"\bPart\s*{p_num}\b", p_title, re.IGNORECASE):
                    p_title = re.sub(rf"\bPart\s*{p_num}\b", f"Explanation Part {p_num}", p_title, count=1, flags=re.IGNORECASE)
                elif "#shorts" in p_title.lower():
                    p_title = re.sub(r"#shorts", f"Explanation Part {p_num} #shorts", p_title, count=1, flags=re.IGNORECASE)
                else:
                    p_title = f"{p_title} | Explanation Part {p_num} #shorts"
            parts_meta.append({
                "part": p_num,
                "title": p_title,
                "video_path": str(ep_work_dir / f"part_{p_num:02d}" / f"short_{ep_key}_part{p_num}.mp4"),
                "hashtags": p.get("hashtags", []),
                "description": p.get("description", ""),
                "status": "pending",
            })

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

                if dry_run:
                    v_res = {"duration": len(part_info.get("narration", "").split()) / 3.0}
                    log(f"[DRY-RUN] Simulating landscape voiceover: {v_res['duration']:.1f}s (Part {p_num})")
                else:
                    v_res = produce_part_audio_subtitles(
                        text=part_info["narration"],
                        output_audio_path=audio_f,
                        output_ass_path=ass_f,
                        badge_text="",
                        voice=voice,
                        is_landscape=True,
                    )
                part_beats = part_info.get("beats")
                if not part_beats:
                    acts = get_episode_scene_acts({"episode_key": ep_key}, num_parts=len(script_package.get("parts", [])), raw_video_path=raw_video_path)
                    for act in acts:
                        if act.get("part") == p_num and "beats" in act:
                            part_beats = act["beats"]
                            break

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
                    beats=part_beats,
                    narration=part_info.get("narration", ""),
                )
                rendered_landscape.append(vid_f)

            stitch_full_episode_video(rendered_landscape, full_video_f, dry_run=dry_run)

        shield = MultiAgentCopyrightShield()
        full_title_raw = script_package.get("full_video", {}).get("title", f"{ep_key} Full Recap")
        clean_full_title, clean_full_desc = shield.remediate_metadata(
            title=full_title_raw,
            description=script_package.get("full_video", {}).get("description", ""),
            is_short=False,
            display_name=active_ep.get("display_name", ep_key),
        )

        full_meta = {
            "title": clean_full_title,
            "video_path": str(full_video_f),
            "chapters": script_package.get("full_video", {}).get("chapters", []),
            "description": clean_full_desc,
            "hashtags": script_package.get("full_video", {}).get("hashtags", ["anime", "bhalooji"]),
            "status": "rendered",
            "is_full_video": True,
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

    if dry_run:
        actual_dur = len(part_info.get("narration", "").split()) / 3.0
        v_res = {"duration": actual_dur, "word_count": len(part_info.get("narration", "").split())}
        log(f"[DRY-RUN] Simulating Short Part {next_p} voiceover: {actual_dur:.1f}s")
    else:
        v_res = produce_part_audio_subtitles(
            text=part_info["narration"],
            output_audio_path=audio_f,
            output_ass_path=ass_f,
            badge_text=part_info.get("badge", f"PART {next_p}/{total_parts}"),
            voice=voice,
        )
    part_beats = part_info.get("beats")
    if not part_beats:
        acts = get_episode_scene_acts({"episode_key": ep_key}, num_parts=total_parts, raw_video_path=raw_video_path)
        for act in acts:
            if act.get("part") == next_p and "beats" in act:
                part_beats = act["beats"]
                break

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
        beats=part_beats,
        narration=part_info.get("narration", ""),
        full_bleed=full_bleed,
        remove_copyrighted_clip=remove_copyrighted_clip,
    )

    normal_vid_info = active_ep.get("normal_video", {})
    normal_url = normal_vid_info.get("url", "")
    teaser = f"\n🎬 Full episode explanation is live on our channel now: {normal_url}\n" if normal_url else "\n🎬 Full episode explanation is live on our channel now!\n"

    shield = MultiAgentCopyrightShield()
    raw_title = part_info.get("short_title", f"{active_ep['display_name']} Story Recap Explanation #shorts")
    raw_desc = part_info.get("description") or f"{part_info.get('hook', '')}\nPart {next_p} of {total_parts} covering {active_ep['display_name']}.{teaser}\n#anime #animerecap #shorts #bhalooji"

    # Multi-Agent Anti-Copyright Filter & Remediation Retry Loop
    MAX_FILTER_RETRIES = 3
    candidate_passed = False
    last_filter_res = None

    for attempt in range(1, MAX_FILTER_RETRIES + 1):
        clean_title, clean_desc = shield.remediate_metadata(
            title=raw_title,
            description=raw_desc,
            is_short=True,
            part_num=next_p,
            display_name=active_ep['display_name'],
        )
        raw_title = clean_title
        raw_desc = clean_desc

        filter_res = shield.inspect_candidate(
            video_path=vid_f,
            title=raw_title,
            description=raw_desc,
            is_short=True,
            time_window=tuple(part_info.get("time_range", [90, 450])),
            hashtags=part_info.get("hashtags", []),
        )
        last_filter_res = filter_res
        log(f"🛡️ [MultiAgentShield] Attempt {attempt}/{MAX_FILTER_RETRIES}: {filter_res.summary}")

        if filter_res.passed or dry_run:
            candidate_passed = True
            break

        log(f"⚠️ [MultiAgentShield] Candidate rejected on attempt {attempt}. Retrying with enhanced remediation...")
        if not dry_run and attempt < MAX_FILTER_RETRIES:
            log(f"🔄 Re-rendering Short Part {next_p} with tightened micro-cuts and safe bounds...")
            assemble_short_part(
                raw_video_path=raw_video_path,
                voice_audio_path=audio_f,
                ass_subtitle_path=ass_f,
                output_video_path=vid_f,
                time_window=tuple(part_info.get("time_range", [90, 450])),
                total_duration=min(58.0, v_res["duration"]),
                bgm_path=bgm_path,
                is_landscape=False,
                dry_run=dry_run,
                beats=part_beats,
                narration=part_info.get("narration", ""),
            )

    if not candidate_passed and not dry_run:
        log("🛑 [MultiAgentShield] All retry attempts failed copyright checks. Video will NOT be uploaded to prevent block.")
        result = {
            "status": "filter_rejected",
            "message": "Candidate failed multi-agent anti-copyright verification",
            "violations": last_filter_res.violations if last_filter_res else ["Unknown violation"],
            "episode_key": ep_key,
        }
        with open(ep_work_dir / "pipeline_summary.json", "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        return result

    short_meta = {
        "part": next_p,
        "title": raw_title,
        "video_path": str(vid_f),
        "hashtags": part_info["hashtags"],
        "description": raw_desc,
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


def run_arc_pipeline(
    arc_key: str | None = None,
    series_filter: str | None = None,
    dry_run: bool = False,
    voice: str = "en-US-ChristopherNeural",
    bgm_path: str | Path | None = None,
    part: int = 1,
    upload_live: bool = False,
    max_duration: float = 3600.0,
    reuse_script: bool = False,
    tts_rate: str = "+10%",
) -> dict:
    """
    Recap-kun style story-arc video: every episode of the arc is downloaded, transcribed and
    retold as grounded beats (anime_arc_grounding); each beat is spoken on its own so its length is
    exact, and the video shows that beat's own source scene for exactly as long as it is spoken.
    One chapter per episode. Any grounding failure aborts the run (status "error", no summary for
    the uploader) - there is no template narration fallback.
    """
    from anime_arc_grounding import GroundingError, NARRATION_WPS

    log("=== Starting Bhaloo Ji Story Arc Recap Pipeline (grounded, Recap-kun style) ===")
    history = load_history()
    active_arc = history.get("active_arc")
    if not arc_key and active_arc:
        arc_key = active_arc.get("arc_key")
        if part == 1 and active_arc.get("part"):
            part = active_arc.get("part")

    if arc_key:
        target_arc = get_arc(arc_key)
        if not target_arc:
            log(f"Story Arc '{arc_key}' not found.")
            return {"status": "error", "message": "arc not found"}
    else:
        target_arc = get_next_arc(series_filter)
        if not target_arc:
            log("No pending story arcs found in catalog.")
            return {"status": "complete", "message": "all arcs completed"}

    log(f"Target Story Arc: {target_arc['display_name']} ({len(target_arc['episode_keys'])} episodes: "
        f"{', '.join(target_arc['episode_keys'])})")
    arc_work_dir = OUTPUT_DIR / target_arc["arc_key"]
    arc_work_dir.mkdir(parents=True, exist_ok=True)

    if not bgm_path or not Path(bgm_path).exists():
        bgm_path = pick_bgm_for_episode(series_id=target_arc.get("series_id"))
        log(f"BGM: {Path(bgm_path).name}")

    # 1. Download EVERY episode of the arc before writing anything (the script is grounded in them)
    catalog = load_catalog()
    ep_map = {e["episode_key"]: e for e in catalog.get("episodes", [])}
    raw_episode_map: dict[str, Path] = {}
    for ep_k in target_arc["episode_keys"]:
        ep_obj = ep_map.get(ep_k, {})
        raw_path = CACHE_DIR / ep_obj.get("filename", f"{ep_k}.mp4")
        raw_episode_map[ep_k] = raw_path
        if dry_run:
            continue
        ok = download_gdrive_episode(ep_obj.get("gdrive_file_id", ""), raw_path) if ep_obj.get("gdrive_file_id") else False
        if not ok or not raw_path.exists() or raw_path.stat().st_size < 1_000_000:
            log(f"Episode {ep_k} could not be downloaded ({raw_path}); aborting the arc run.")
            return {"status": "error", "message": f"episode {ep_k} not available", "arc_key": target_arc["arc_key"]}

    # 2. Grounded script (one chapter per episode)
    script_file = arc_work_dir / "arc_script.json"
    arc_script = None
    if reuse_script and script_file.exists():
        try:
            cached = json.loads(script_file.read_text(encoding="utf-8"))
            if cached.get("grounded") and cached.get("part") == part:
                arc_script = cached
                log("Reusing the grounded arc script from this run's output folder.")
        except Exception:
            arc_script = None
    if arc_script is None:
        try:
            arc_script = generate_arc_script(target_arc, part=part, max_duration=max_duration, catalog=catalog,
                                             episode_paths=raw_episode_map)
        except GroundingError as e:
            log(f"GROUNDING FAILED: {e}")
            (arc_work_dir / "grounding_error.txt").write_text(str(e), encoding="utf-8")
            return {"status": "error", "message": f"grounding failed: {e}", "arc_key": target_arc["arc_key"]}
    part_suffix = f"_part{arc_script['part']}" if arc_script.get("is_split") else ""
    script_file = arc_work_dir / f"arc_script{part_suffix}.json"
    script_file.write_text(json.dumps(arc_script, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"Arc script: '{arc_script['full_video']['title']}' - {len(arc_script['chapters'])} chapters, "
        f"{arc_script['word_count']} words")

    # 3. Flatten beats and narrate each one (exact durations)
    beats = []
    for ci, chap in enumerate(arc_script["chapters"]):
        for b in chap["beats"]:
            beats.append({"text": b["text"], "src_start": float(b["src_start"]), "src_end": float(b["src_end"]),
                          "episode_key": chap["episode_key"], "chapter_index": ci,
                          "episode_duration": chap.get("episode_duration"), "songs": chap.get("songs", [])})
    voice_wav = arc_work_dir / f"arc_voice{part_suffix}.wav"
    if dry_run:
        t = 0.0
        timeline, chapter_starts, word_cues = [], {}, []
        for b in beats:
            d = len(b["text"].split()) / NARRATION_WPS
            chapter_starts.setdefault(b["chapter_index"], t)
            timeline.append(dict(b, start=t, speech_end=t + d, end=t + d))
            t += d
        narration = {"duration": t, "timeline": timeline, "word_cues": word_cues,
                     "chapter_starts": [chapter_starts[k] for k in sorted(chapter_starts)]}
    else:
        narration = produce_beat_narration(beats, CACHE_DIR / "tts_beats", voice_wav,
                                           voice=voice or "en-US-ChristopherNeural", rate=tts_rate)
    total = narration["duration"]
    timeline = narration["timeline"]
    (arc_work_dir / f"beat_timeline{part_suffix}.json").write_text(json.dumps(timeline, indent=1), encoding="utf-8")
    if narration["word_cues"]:
        from anime_voice_subtitles import cues_to_ass
        (arc_work_dir / f"arc_subtitles{part_suffix}.ass").write_text(
            cues_to_ass(narration["word_cues"], is_landscape=True), encoding="utf-8")

    # 4. Exact chapter timestamps in the description
    from anime_script_engine import format_chapter_time, build_arc_description
    long_form = total >= 3600
    exact = []
    for ci, chap in enumerate(arc_script["chapters"]):
        st = 0.0 if ci == 0 else narration["chapter_starts"][ci]
        exact.append(f"{format_chapter_time(st, long_form)} {chap['chapter_title']} (Episode {chap['episode']})")
    arc_script["full_video"]["chapters"] = exact
    arc_script["chapter_timestamps"] = exact
    arc_script["full_video"]["duration"] = total
    arc_script["full_video"]["description"] = build_arc_description(
        target_arc, arc_script["full_video"]["title"], arc_script.get("summary", ""), exact)
    script_file.write_text(json.dumps(arc_script, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"Narration {total:.1f}s ({total / 60:.1f} min). Chapters:\n  " + "\n  ".join(exact))

    # 5. Long video: each beat shows its own scene
    arc_video_file = arc_work_dir / f"full_{target_arc['arc_key']}{part_suffix}.mp4"
    ok = assemble_arc_master_video(
        raw_episode_map=raw_episode_map,
        voice_audio_path=voice_wav,
        output_video_path=arc_video_file,
        beat_timeline=timeline,
        total_duration=total,
        bgm_path=bgm_path,
        dry_run=dry_run,
        cuts_report_path=arc_work_dir / f"cuts{part_suffix}.json",
    )
    arc_video_meta = {
        "title": arc_script["full_video"]["title"],
        "video_path": str(arc_video_file),
        "chapters": exact,
        "description": arc_script["full_video"]["description"],
        "hashtags": arc_script["full_video"]["hashtags"],
        "duration": total,
        "word_count": arc_script["word_count"],
        "status": "rendered" if ok else "failed",
        "is_full_video": True,
        "is_arc": True,
        "arc_key": target_arc["arc_key"],
        "part": arc_script["part"],
        "total_parts": arc_script["total_parts"],
        "is_split": arc_script["is_split"],
    }
    (arc_work_dir / f"arc_video_meta{part_suffix}.json").write_text(json.dumps(arc_video_meta, indent=2), encoding="utf-8")
    if not ok:
        log("Arc video render failed.")
        return {"status": "error", "message": "arc video rendering failed", "arc_key": target_arc["arc_key"]}

    # 6. Short: ~55 s starting on a beat boundary near the climax, captions from the beat word cues
    parts_meta = []
    num_shorts = int(os.environ.get("ARC_SHORTS_COUNT", "1") or 1)
    windows = _pick_arc_short_windows(timeline, arc_script["chapters"], num_shorts)
    for p_order, (b0, b1) in enumerate(windows, 1):
        st = 0.0 if b0 == 0 else timeline[b0]["start"]
        en = timeline[b1]["speech_end"] + 0.4
        en = min(en, timeline[b1]["end"]) if b1 + 1 < len(timeline) else min(en, total)
        ci = timeline[b0]["chapter_index"]
        chap = arc_script["chapters"][ci]
        part_dir = arc_work_dir / f"short_{p_order:02d}"
        part_dir.mkdir(parents=True, exist_ok=True)
        short_file = part_dir / f"short_{target_arc['arc_key']}_p{arc_script['part']}_{p_order}.mp4"
        cap_ass = part_dir / "captions.ass"
        badge = f"{target_arc['series'].split(':')[0]} • {chap['chapter_title']}"
        if not dry_run:
            from anime_voice_subtitles import build_short_caption_ass
            cap_ass.write_text(build_short_caption_ass(narration["word_cues"], st, en, badge_text=badge), encoding="utf-8")
        derive_ok = derive_short_from_master(
            master_video_path=arc_video_file,
            output_short_path=short_file,
            start_time=st,
            end_time=en,
            badge_text="",
            dry_run=dry_run,
            full_bleed=False,   # card layout: the whole 16:9 frame stays visible
            mirror=False,
            caption_ass_path=cap_ass if cap_ass.exists() else None,
        )
        series_tag = target_arc["series_id"].replace("-", "")
        hook = _short_hook_title(timeline[b0]["text"], chap["chapter_title"])
        part_meta = {
            "part": p_order,
            "chapter_index": ci,
            "beats": [b0, b1],
            "title": _arc_short_title(chap["chapter_title"], target_arc["display_name"]),
            "hook": hook,
            "video_path": str(short_file),
            "start_time": round(st, 3),
            "end_time": round(en, 3),
            "duration": round(en - st, 3),
            "hashtags": ["anime", "animerecap", "shorts", series_tag, "bhalooji"],
            "description": (
                f"{' '.join(b['text'] for b in timeline[b0:b0 + 2])}\n\n"
                f"From our full recap of the {target_arc['arc_name']}: {{FULL_VIDEO_URL}}\n\n"
                f"#anime #animerecap #shorts #{series_tag} #bhalooji"
            ),
            "status": "rendered" if derive_ok else "failed",
        }
        parts_meta.append(part_meta)
        (part_dir / "meta.json").write_text(json.dumps(part_meta, indent=2), encoding="utf-8")

    pipeline_result = {
        "status": "success",
        "mode": "arc",
        "action": "normal_video",
        "is_arc": True,
        "arc_key": target_arc["arc_key"],
        "display_name": target_arc["display_name"],
        "video_to_upload": arc_video_meta,
        "parts": parts_meta,
        "full_video": arc_video_meta,
    }
    (arc_work_dir / "pipeline_summary.json").write_text(json.dumps(pipeline_result, indent=2), encoding="utf-8")
    log(f"Story Arc pipeline complete: 1 long video ({total / 60:.1f} min) + {len(parts_meta)} Short(s) in {arc_work_dir}")
    return pipeline_result


def build_episode_description(ep: dict, title: str, summary: str, chapter_lines: list[str]) -> str:
    """Long-video description: the plot in two sentences, the 'Recap' / fair-use framing the copyright
    check needs, and the act chapters with exact timestamps."""
    from anime_script_engine import FAIR_USE_DISCLAIMER
    series = ep.get("series", "Anime")
    series_tag = re.sub(r"[^A-Za-z0-9]", "", series.split(":")[0]).lower()
    return f"""{summary.strip()}

Full story recap of {series}, season {ep.get('season')} episode {ep.get('episode')}, retold scene by scene.

Chapters:
{chr(10).join(chapter_lines)}

{FAIR_USE_DISCLAIMER}
#anime #{series_tag} #animerecap #animeexplained #bhalooji"""


def _act_chapters(acts: list[dict], timeline: list[dict], total: float, long_form: bool = False) -> list[str]:
    """YouTube chapters from the story acts: first at 00:00, each at the exact start of its first beat,
    an act shorter than 10 s is merged into the one before it."""
    from anime_script_engine import format_chapter_time
    lines, last_t = [], None
    for ai, a in enumerate(acts):
        t = 0.0 if ai == 0 else timeline[a["start_beat"]]["start"]
        if last_t is not None and (t - last_t < 10.0 or total - t < 10.0):
            continue
        lines.append(f"{format_chapter_time(t, long_form)} {a['title']}")
        last_t = t
    return lines


def _render_episode_short(cand: dict, timeline: list[dict], raw_map: dict, part_dir: Path, voice: str, rate: str,
                          bgm_path, badge: str, dry_run: bool = False) -> dict:
    """
    Build one Short from beats [start_beat..end_beat] directly: re-narrate them (the hook beat with its
    cold-open rewrite; unchanged beats come from the TTS cache), render their footage with the same
    per-beat footage plan as the long video, then lay it out as a 9:16 card with word-timed captions
    and a big hook headline for the first ~2 s. Returns {ok, duration, video_path, ...}.
    """
    from anime_episode_recap import EPISODE_BEAT_GAP, SHORT_TAIL_S
    import tempfile
    b0, b1 = cand["start_beat"], cand["end_beat"]
    beats = []
    for i in range(b0, b1 + 1):
        b = {k: timeline[i][k] for k in ("text", "src_start", "src_end", "episode_key", "episode_duration", "songs")}
        b["chapter_index"] = 0
        beats.append(b)
    beats[0]["text"] = cand["hook_text"]
    part_dir.mkdir(parents=True, exist_ok=True)
    voice_wav = part_dir / "short_voice.wav"
    if dry_run:
        from anime_episode_recap import EPISODE_WPS
        dur = sum(len(b["text"].split()) / EPISODE_WPS + EPISODE_BEAT_GAP for b in beats) + SHORT_TAIL_S
        return {"ok": True, "duration": dur, "video_path": str(part_dir / "short.mp4"), "word_cues": []}
    narr = produce_beat_narration(beats, CACHE_DIR / "tts_beats", voice_wav, voice=voice, rate=rate,
                                  beat_gap=EPISODE_BEAT_GAP, chapter_gap=EPISODE_BEAT_GAP, trim_silence=True)
    dur = narr["duration"] + SHORT_TAIL_S
    out = {"ok": False, "duration": round(dur, 3), "word_cues": narr["word_cues"], "timeline": narr["timeline"]}
    from anime_episode_recap import SHORT_MIN_S, SHORT_MAX_S
    if not (SHORT_MIN_S <= dur <= SHORT_MAX_S + 0.5):
        out["reason"] = f"narration is {dur:.1f}s (need {SHORT_MIN_S:.0f}-{SHORT_MAX_S:.0f}s)"
        return out
    tmp = Path(tempfile.mkdtemp(prefix="ep_short_"))
    landscape = tmp / "short_16x9.mp4"
    ok = assemble_arc_master_video(raw_episode_map=raw_map, voice_audio_path=voice_wav, output_video_path=landscape,
                                   beat_timeline=narr["timeline"], total_duration=dur, bgm_path=bgm_path,
                                   cuts_report_path=part_dir / "cuts.json", fade_out=0.35)
    if not ok:
        out["reason"] = "16:9 render failed"
        return out
    from anime_voice_subtitles import build_short_caption_ass
    cap = part_dir / "captions.ass"
    cap.write_text(build_short_caption_ass(narr["word_cues"], 0.0, dur, badge_text=badge,
                                           hook_text=cand["title"], hook_seconds=2.2), encoding="utf-8")
    short_file = part_dir / "short.mp4"
    ok = derive_short_from_master(master_video_path=landscape, output_short_path=short_file, start_time=0.0,
                                  end_time=dur, badge_text="", full_bleed=False, mirror=False, caption_ass_path=cap)
    try:
        landscape.unlink()
        tmp.rmdir()
    except Exception:
        pass
    out.update(ok=bool(ok), video_path=str(short_file))
    if not ok:
        out["reason"] = "9:16 derivation failed"
    return out


def run_episode_pipeline(
    episode_key: str | None = None,
    series_filter: str | None = None,
    dry_run: bool = False,
    voice: str = "en-US-ChristopherNeural",
    bgm_path: str | Path | None = None,
    reuse_script: bool = False,
    tts_rate: str | None = None,
) -> dict:
    """
    Daily long video that retells ONE episode in the cold-open storyteller style (see
    anime_episode_recap), cut into one Short that runs from a hook to its payoff.
    1. Pick the next episode (history['completed_episode_recaps']; the uploader marks it done).
    2. Ground it: Whisper transcript (cached), LLM beats + acts + hook title + short candidates, all validated.
    3. Narrate every beat (ChristopherNeural, faster rate), render each beat's own footage (OP/ED skipped).
    4. Chapters = the story's acts with exact timestamps.
    5. Short(s): best valid candidate (or the deterministic climax window), built from its beats.
    Any grounding failure aborts the run; nothing is uploaded from filler.
    """
    from anime_catalog import get_next_recap_episode, neighbour_episode, get_arc_for_episode
    from anime_arc_grounding import GroundingError
    from anime_episode_recap import (ground_episode, EPISODE_RATE, EPISODE_BEAT_GAP, EPISODE_ACT_GAP, EPISODE_WPS,
                                     validate_short_candidates, fallback_short_window, character_names, shorts_title)
    tts_rate = tts_rate or os.environ.get("EPISODE_TTS_RATE") or EPISODE_RATE

    log("=== Starting Bhaloo Ji Episode Recap Pipeline (grounded, cold-open storyteller style) ===")
    catalog = load_catalog()
    ep_map = {e["episode_key"]: e for e in catalog.get("episodes", [])}
    if episode_key:
        ep = ep_map.get(episode_key)
        if not ep:
            log(f"Episode '{episode_key}' is not in the catalog.")
            return {"status": "error", "message": "episode not found"}
    else:
        ep = get_next_recap_episode(series_filter, catalog=catalog)
        if not ep:
            log("Every catalog episode already has a recap.")
            return {"status": "complete", "message": "all episodes recapped"}
    ep_key = ep["episode_key"]
    arc = get_arc_for_episode(ep_key)
    log(f"Target episode: {ep['display_name']} ({ep_key})" + (f" - {arc['display_name']}" if arc else ""))
    work = OUTPUT_DIR / f"{ep_key}-recap"
    work.mkdir(parents=True, exist_ok=True)
    if not bgm_path or not Path(bgm_path).exists():
        bgm_path = pick_bgm_for_episode(series_id=ep.get("series_id"))
        log(f"BGM: {Path(bgm_path).name}")

    # 1. Footage (and a neighbour episode only when the OP/ED has to be detected)
    raw = CACHE_DIR / ep.get("filename", f"{ep_key}.mp4")
    if not dry_run:
        ok = download_gdrive_episode(ep.get("gdrive_file_id", ""), raw) if ep.get("gdrive_file_id") else raw.exists()
        if not ok or not raw.exists() or raw.stat().st_size < 1_000_000:
            log(f"Episode {ep_key} could not be downloaded ({raw}).")
            return {"status": "error", "message": f"episode {ep_key} not available", "episode_key": ep_key}
    neighbour = None
    from anime_episode_recap import find_cached_songs
    if not dry_run and find_cached_songs(ep_key) is None:
        nb = neighbour_episode(ep_key, catalog)
        if nb and nb.get("gdrive_file_id"):
            nb_path = CACHE_DIR / nb["filename"]
            if download_gdrive_episode(nb["gdrive_file_id"], nb_path) and nb_path.exists():
                neighbour = nb_path
                log(f"OP/ED reference episode: {nb['episode_key']}")

    # 2. Grounded script
    script_file = work / "episode_script.json"
    script = None
    if reuse_script and script_file.exists():
        try:
            script = json.loads(script_file.read_text(encoding="utf-8"))
            log("Reusing the grounded episode script from this run's output folder.")
        except Exception:
            script = None
    if script is None:
        try:
            script = ground_episode(ep, raw, neighbour, arc)
        except GroundingError as e:
            log(f"GROUNDING FAILED: {e}")
            (work / "grounding_error.txt").write_text(str(e), encoding="utf-8")
            return {"status": "error", "message": f"grounding failed: {e}", "episode_key": ep_key}
    script_file.write_text(json.dumps(script, indent=2, ensure_ascii=False), encoding="utf-8")
    acts = script["acts"]
    log(f"Episode script: '{script['title']}' - {len(script['beats'])} beats, {script['word_count']} words, "
        f"acts: {[a['title'] for a in acts]}")

    # 3. Narration, one TTS per beat; an act boundary gets a slightly longer pause
    act_of = []
    for i in range(len(script["beats"])):
        act_of.append(max(ai for ai, a in enumerate(acts) if a["start_beat"] <= i))
    beats = [{"text": b["text"], "src_start": float(b["src_start"]), "src_end": float(b["src_end"]),
              "episode_key": ep_key, "chapter_index": act_of[i], "episode_duration": script.get("duration"),
              "songs": script.get("songs", [])} for i, b in enumerate(script["beats"])]
    voice_wav = work / "episode_voice.wav"
    if dry_run:
        t, timeline = 0.0, []
        for b in beats:
            d = len(b["text"].split()) / EPISODE_WPS
            timeline.append(dict(b, start=t, speech_end=t + d, end=t + d + EPISODE_BEAT_GAP))
            t += d + EPISODE_BEAT_GAP
        narration = {"duration": t, "timeline": timeline, "word_cues": []}
    else:
        narration = produce_beat_narration(beats, CACHE_DIR / "tts_beats", voice_wav, voice=voice, rate=tts_rate,
                                           beat_gap=EPISODE_BEAT_GAP, chapter_gap=EPISODE_ACT_GAP, trim_silence=True)
    timeline = narration["timeline"]
    total = narration["duration"] + 1.0  # a beat of silence after the last line
    (work / "beat_timeline.json").write_text(json.dumps(timeline, indent=1), encoding="utf-8")

    # 4. Chapters from the acts, exact
    chapters = _act_chapters(acts, timeline, total)
    title = script["title"][:100]
    description = build_episode_description(ep, title, script.get("summary", ""), chapters)
    log(f"Narration {total:.1f}s ({total / 60:.1f} min, {script['word_count'] / max(total, 1) * 60:.0f} wpm). "
        f"Chapters:\n  " + "\n  ".join(chapters))

    # 5. Long video
    video_file = work / f"full_{ep_key}_recap.mp4"
    ok = assemble_arc_master_video(raw_episode_map={ep_key: raw}, voice_audio_path=voice_wav,
                                   output_video_path=video_file, beat_timeline=timeline, total_duration=total,
                                   bgm_path=bgm_path, dry_run=dry_run, cuts_report_path=work / "cuts.json",
                                   fade_out=1.0)
    series_tag = re.sub(r"[^A-Za-z0-9]", "", ep.get("series", "anime").split(":")[0]).lower()
    meta = {
        "title": title,
        "video_path": str(video_file),
        "chapters": chapters,
        "description": description,
        "hashtags": ["anime", "animerecap", "animeexplained", series_tag, "bhalooji", "episoderecap"],
        "duration": total,
        "word_count": script["word_count"],
        "status": "rendered" if ok else "failed",
        "is_full_video": True,
        "is_episode_recap": True,
        "episode_key": ep_key,
    }
    (work / "episode_video_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    if not ok:
        log("Episode video render failed.")
        return {"status": "error", "message": "episode video rendering failed", "episode_key": ep_key}

    # 6. Short(s): validated LLM candidates re-checked against the real beat lengths, then the fallback
    texts = [b["text"] for b in timeline]
    slots = [b["end"] - b["start"] for b in timeline]
    speech = [b["speech_end"] - b["start"] for b in timeline]
    names = character_names(texts)
    cands, probs = validate_short_candidates(script.get("short_candidates", []), texts, names, slots, speech)
    for p_ in probs:
        log(f"short candidate dropped: {p_}")
    fb = fallback_short_window(texts, slots, speech, script.get("climax_beat"), names)
    if fb:
        if len(script["title"]) <= 90:
            fb["title"] = script["title"]   # the long video's hook title reads better than a clipped sentence
        cands.append(fb)
    num_shorts = int(os.environ.get("EPISODE_SHORTS_COUNT") or os.environ.get("ARC_SHORTS_COUNT") or "1")
    parts_meta, used = [], []
    badge = ep.get("series", "").split(":")[0]
    for cand in cands:
        if len(parts_meta) >= num_shorts:
            break
        if any(not (cand["end_beat"] < a or cand["start_beat"] > b) for a, b in used):
            continue
        p_order = len(parts_meta) + 1
        part_dir = work / f"short_{p_order:02d}"
        res = _render_episode_short(cand, timeline, {ep_key: raw}, part_dir, voice, tts_rate, bgm_path, badge, dry_run)
        if not res["ok"]:
            log(f"Short candidate beats {cand['start_beat']}-{cand['end_beat']} ({cand['source']}) skipped: {res.get('reason')}")
            continue
        used.append((cand["start_beat"], cand["end_beat"]))
        hook_line = cand["hook_text"]
        payoff_line = timeline[cand["end_beat"]]["text"]
        part_meta = {
            "part": p_order,
            "beats": [cand["start_beat"], cand["end_beat"]],
            "source": cand["source"],
            "title": shorts_title(cand["title"]),
            "hook": hook_line,
            "hook_rewritten": cand.get("hook_rewritten", False),
            "payoff": payoff_line,
            "video_path": res["video_path"],
            "master_start": round(timeline[cand["start_beat"]]["start"], 3),
            "master_end": round(timeline[cand["end_beat"]]["speech_end"], 3),
            "duration": res["duration"],
            "hashtags": ["anime", "animerecap", "shorts", series_tag, "bhalooji"],
            "description": (
                f"{hook_line} {timeline[cand['start_beat'] + 1]['text'] if cand['start_beat'] + 1 <= cand['end_beat'] else ''}".strip()
                + f"\n\nWatch the full episode recap: {{FULL_VIDEO_URL}}\n\n"
                  f"Story recap / commentary under fair use.\n#anime #animerecap #shorts #{series_tag} #bhalooji"
            ),
            "status": "rendered",
        }
        parts_meta.append(part_meta)
        (part_dir / "meta.json").write_text(json.dumps(part_meta, indent=2, ensure_ascii=False), encoding="utf-8")
        log(f"Short {p_order}: '{part_meta['title']}' beats {cand['start_beat']}-{cand['end_beat']} "
            f"({cand['source']}, {res['duration']:.1f}s)")
    if not parts_meta:
        log("No Short could be built from this episode (no 35-59 s hook-to-payoff window).")

    result = {
        "status": "success",
        "mode": "episode",
        "action": "normal_video",
        "episode_key": ep_key,
        "upload_key": f"{ep_key}-recap",
        "display_name": ep["display_name"],
        "video_to_upload": meta,
        "full_video": meta,
        "parts": parts_meta,
        "bgm_path": str(bgm_path) if bgm_path else None,
    }
    (work / "pipeline_summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"Episode pipeline complete: long video {total / 60:.1f} min + {len(parts_meta)} Short(s) in {work}")
    return result


def _arc_short_title(chapter_title: str, display_name: str) -> str:
    """'<chapter title> | <arc> Recap #shorts', trimmed to YouTube's 100 characters."""
    tail = f" | {display_name} Recap #shorts"
    if len(chapter_title) + len(tail) > 100:
        tail = " | Recap #shorts"
    return f"{chapter_title[:100 - len(tail)].rstrip()}{tail}"


def _pick_arc_short_windows(timeline: list[dict], chapters: list[dict], num_shorts: int = 1,
                            target: float = 55.0, max_len: float = 59.0, min_len: float = 40.0) -> list[tuple[int, int]]:
    """
    Beat windows [(first_beat, last_beat)] for the Shorts. One Short: in the climax chapter (~70%
    through the arc), around the beat the writer marked as the episode's climax; the window starts on
    a beat boundary, runs ~55 s and never exceeds max_len. Several: one per evenly spread chapter.
    """
    if not timeline or num_shorts <= 0:
        return []
    n_ch = max(b["chapter_index"] for b in timeline) + 1
    if num_shorts == 1:
        ch_list = [min(n_ch - 1, int(round(n_ch * 0.7)))]
    else:
        ch_list = _pick_arc_short_chapters([None] * n_ch, chapters, num_shorts)
    out = []
    for ci in ch_list:
        idxs = [i for i, b in enumerate(timeline) if b["chapter_index"] == ci]
        if not idxs:
            continue
        hint = (chapters[ci] if ci < len(chapters) else {}).get("climax_hint")
        anchor = idxs[int(len(idxs) * 0.6)]
        if isinstance(hint, (int, float)):
            after = [i for i in idxs if timeline[i]["src_end"] >= float(hint)]
            if after:
                anchor = after[0]

        def span(a, z):
            return timeline[z]["speech_end"] - timeline[a]["start"]

        # back up ~20 s before the climax beat so the Short builds into it
        start = anchor
        while start - 1 >= 0 and span(start - 1, anchor) <= 20.0:
            start -= 1
        end = start
        while end + 1 < len(timeline) and span(start, end + 1) <= max_len - 0.5 and span(start, end) < target:
            end += 1
        while span(start, end) < min_len and start - 1 >= 0 and span(start - 1, end) <= max_len - 0.5:
            start -= 1
        while span(start, end) > max_len - 0.5 and end > start:
            end -= 1
        out.append((start, end))
    return out


def _pick_arc_short_chapters(chapter_segments: list, chapters: list, num_shorts: int = 1) -> list[int]:
    """Pick chapter indices for Shorts. One Short: the arc's climax (~70% through).
    Several: spread evenly across the arc, skipping the intro chapter."""
    n = len(chapter_segments)
    if n == 0 or num_shorts <= 0:
        return []
    if num_shorts == 1:
        return [min(n - 1, int(round(n * 0.7)))]
    candidates = list(range(1, n)) if n > num_shorts else list(range(n))
    step = len(candidates) / float(num_shorts)
    picks = []
    for k in range(num_shorts):
        i = candidates[min(len(candidates) - 1, int(k * step + step / 2))]
        if i not in picks:
            picks.append(i)
    return picks


def _short_hook_title(hook: str, fallback: str) -> str:
    """Turn a chapter hook into a short title (first sentence, <= 60 chars)."""
    h = re.split(r"(?<=[.!?])\s", (hook or "").strip(), maxsplit=1)[0].strip()
    if not h or h.lower().startswith("chapter "):
        h = fallback
    if len(h) > 60:
        h = h[:60].rsplit(" ", 1)[0].rstrip(",;:-")
    return h


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run anime explanation pipeline")
    parser.add_argument("--mode", default="episode", choices=["episode", "arc", "recapkun", "cinema", "daily", "full"], help="Pipeline mode: 'episode' (one episode retold as a cold-open story + one hook-to-payoff Short), 'arc' (Full Story Arc Recap Video <= 60 mins), 'recapkun' (Master Long-Form RecapKun Video + Shorts), 'daily' (funnel), 'cinema' (3-minute shorts), or 'full'")
    parser.add_argument("--arc", default=None, help="Specific story arc key (e.g. demon-slayer-mount-natagumo)")
    parser.add_argument("--part", type=int, default=1, help="Part number if arc is split (default: 1)")
    parser.add_argument("--episode", default=None, help="Episode key (e.g. demon-slayer-s01e01)")
    parser.add_argument("--series", default=None, help="Series filter (e.g. demon-slayer, jujutsu-kaisen)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without heavy rendering")
    parser.add_argument("--voice", default="default", help="Voice (default: adam for cinema, ChristopherNeural for arc/recapkun)")
    parser.add_argument("--bgm", default=None, help="Optional background music path")
    parser.add_argument("--live", action="store_true", help="Live YouTube upload mode")

    args = parser.parse_args()
    if args.mode == "episode":
        res = run_episode_pipeline(
            episode_key=args.episode,
            series_filter=args.series,
            dry_run=args.dry_run,
            voice=args.voice if args.voice != "default" else "en-US-ChristopherNeural",
            bgm_path=args.bgm,
        )
    elif args.mode == "arc":
        res = run_arc_pipeline(
            arc_key=args.arc,
            series_filter=args.series,
            dry_run=args.dry_run,
            voice=args.voice if args.voice != "default" else "en-US-ChristopherNeural",
            bgm_path=args.bgm,
            part=args.part,
            upload_live=args.live,
        )
    elif args.mode == "cinema":
        res = run_cinema_pipeline(
            episode_key=args.episode,
            series_filter=args.series,
            dry_run=args.dry_run,
            voice=args.voice if args.voice != "default" else CINEMA_VOICE,
            bgm_path=args.bgm,
        )
    elif args.mode == "daily" and not args.episode:
        res = run_daily_funnel(
            series_filter=args.series,
            dry_run=args.dry_run,
            voice=args.voice if args.voice != "default" else "en-US-ChristopherNeural",
            bgm_path=args.bgm,
        )
    else:
        # 'recapkun' or 'full': produces Master Long-Form 16:9 Video and derived Shorts
        res = run_pipeline(
            episode_key=args.episode,
            series_filter=args.series,
            dry_run=args.dry_run,
            voice=args.voice if args.voice != "default" else "en-US-ChristopherNeural",
            bgm_path=args.bgm,
            upload_live=args.live,
        )
    print(json.dumps(res, indent=2))
    if res.get("status") != "success":
        sys.exit(1)
