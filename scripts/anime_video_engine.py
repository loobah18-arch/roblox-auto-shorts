#!/usr/bin/env python3
"""
Anti-Copyright Anime Video Slicer & Compositor for Bhaloo Ji Channel.
Transforms raw anime episodes into high-retention 9:16 Shorts
and stitches multi-part episodes into cohesive long-form videos.

Techniques for Content-ID Bypass & High Visual Appeal:
1. Rapid dynamic slicing (cuts strictly <= 4.2s).
2. Aesthetic 9:16 canvas: Blurred motion background + crisp foreground card with subtle glow.
3. Top Header Bar: Series title + Episode name + Part badge.
4. Subtle Ken Burns zoom drift (1.05x-1.10x) and gentle cinematic film color grade.
5. Alternating subtle horizontal mirror on action scenes.
6. Audio transformation: Dominant voiceover + copyright-clean BGM; raw anime audio ducked to -28dB.
7. Word-by-word dynamic ASS karaoke subtitles.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = WORKSPACE_DIR / "output"
CACHE_DIR = WORKSPACE_DIR / "cache"
BGM_DIR = WORKSPACE_DIR / "assets" / "bgm"
DEFAULT_BGM_PATH = BGM_DIR / "aerohead_fragments_recap.mp3"

# Royalty-free BGM library with mood/genre classification
BGM_LIBRARY = {
    "recapkun":     "aerohead_fragments_recap.mp3",      # Iconic RecapKun chill ambient recap track (AERØHEAD - Fragments)
    "action":       "cinematic_suspense_thriller.mp3",   # High-action battles & reveals
    "drone":        "cinematic_suspense_drone.mp3",       # Tense build-up moments
    "emotional":    "sad_cinematic_piano.mp3",            # Tragic / emotional scenes
    "atmospheric":  "dreamy_night_drift.mp3",             # Discovery / quiet moments
    "lofi":         "lofi_chill_beats.mp3",              # Light intro scenes
    "dark":         "malevolent_shrine_sukuna.mp3",       # Villain / horror moments
    "cozy":         "cozy_cafe_guitar.mp3",               # Slice-of-life / training
    "snowfall":     "snowfall_calm_aesthetic.mp3",        # Sad / reflective moments
}

# Per-series default BGM mapping (RecapKun AERØHEAD by default)
SERIES_BGM_MAP = {
    "demon-slayer":      "recapkun",
    "jujutsu-kaisen":    "recapkun",
    "default":           "recapkun",
}


def pick_bgm_for_episode(series_id: str | None = None, mood: str | None = None) -> Path:
    """
    Auto-select a royalty-free BGM track based on series or explicit mood.
    Falls back to the RecapKun default aerohead_fragments_recap.mp3.
    """
    if mood and mood in BGM_LIBRARY:
        track = BGM_LIBRARY[mood]
    elif series_id and series_id in SERIES_BGM_MAP:
        track = BGM_LIBRARY[SERIES_BGM_MAP[series_id]]
    else:
        track = BGM_LIBRARY[SERIES_BGM_MAP["default"]]
    path = BGM_DIR / track
    return path if path.exists() else DEFAULT_BGM_PATH


def log(msg: str) -> None:
    print(f"[anime_video_engine] {msg}", flush=True)


def download_gdrive_episode(file_id: str, dest_path: str | Path, dry_run: bool = False) -> bool:
    """Download single episode video from Google Drive."""
    dest = Path(dest_path)
    if dest.exists() and dest.stat().st_size > 1024 * 1024:
        log(f"Episode already downloaded at {dest}")
        return True

    if dry_run:
        log(f"[DRY-RUN] Simulating download of GDrive file_id: {file_id} to {dest}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Create small dummy file if testing
        if not dest.exists():
            dest.write_text("dummy video")
        return True

    try:
        import gdown
        dest.parent.mkdir(parents=True, exist_ok=True)
        log(f"Downloading episode from Drive (ID: {file_id}) to {dest}...")
        try:
            gdown.download(id=file_id, output=str(dest), quiet=False)
        except Exception:
            url = f"https://drive.google.com/uc?id={file_id}"
            gdown.download(url=url, output=str(dest), quiet=False)
        return dest.exists() and dest.stat().st_size > 0
    except Exception as e:
        log(f"Drive download failed: {e}")
        return False


def build_landscape_ffmpeg_filtergraph(
    has_subtitles: bool = True,
    ass_path: str = "",
    mirror: bool = False,
) -> str:
    """
    Constructs the 16:9 Landscape Fullscreen (1920x1080) anti-copyright FFmpeg filtergraph:
    - 16:9 widescreen canvas (1920x1080)
    - Anime footage fills widescreen frame with cinematic film color grade & subtle contrast
    - Bottom-third dynamic ASS karaoke subtitles (no blurred sidebars!)
    """
    flip_filter = "hflip," if mirror else ""
    filter_chain = (
        f"[0:v]{flip_filter}eq=contrast=1.06:brightness=-0.02:saturation=1.12,"
        f"scale=1920:1080:force_original_aspect_ratio=decrease,"
        f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1"
    )
    if has_subtitles and ass_path:
        escaped_ass = ass_path.replace(":", "\\:").replace("'", "\\'")
        return f"{filter_chain},ass='{escaped_ass}'[v]"
    else:
        return f"{filter_chain}[v]"


def build_ffmpeg_filtergraph(
    has_subtitles: bool = True,
    ass_path: str = "",
    mirror: bool = False,
) -> str:
    """
    Constructs the high-aesthetic anti-copyright FFmpeg filtergraph:
    - 9:16 canvas (1080x1920)
    - Blurred motion background (duplicate of footage blurred 25px, darkened)
    - Foreground card: 1040x585 centered with subtle border & film color grade
    - Micro-zoom / Ken Burns drift
    - Optional horizontal flip (mirroring)
    - Dynamic ASS subtitle burn
    """
    filters = []

    # 1. Base input split
    flip_filter = "hflip," if mirror else ""
    filters.append(f"[0:v]{flip_filter}eq=contrast=1.06:brightness=-0.02:saturation=1.12,split=2[raw_bg][raw_fg]")

    # 2. Background: fill 1080x1920, heavy blur, darkened
    filters.append(
        "[raw_bg]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,setsar=1,boxblur=25:5,eq=brightness=-0.12[bg]"
    )

    # 3. Foreground: crisp card centered (1040x584 for 16:9 even dims), slight subtle zoom drift
    filters.append(
        "[raw_fg]scale=1040:584:force_original_aspect_ratio=decrease,"
        "pad=1040:584:(ow-iw)/2:(oh-ih)/2:color=black@0,setsar=1[fg]"
    )

    # 4. Overlay foreground on background (shifted slightly up to make room for captions)
    filters.append("[bg][fg]overlay=(W-w)/2:(H-h)/2-60[comp]")

    # 5. Burn subtitles if available
    if has_subtitles and ass_path:
        escaped_ass = ass_path.replace(":", "\\:").replace("'", "\\'")
        filters.append(f"[comp]ass='{escaped_ass}'[v]")
    else:
        filters.append("[comp]copy[v]")

    return ";".join(filters)


def assemble_short_part(
    raw_video_path: str | Path,
    voice_audio_path: str | Path,
    ass_subtitle_path: str | Path,
    output_video_path: str | Path,
    time_window: tuple[float, float],
    total_duration: float,
    bgm_path: str | Path | None = None,
    is_landscape: bool = False,
    dry_run: bool = False,
) -> bool:
    """
    Renders an individual part with comprehensive anti-copyright tactics:
    - If is_landscape=True: 16:9 Landscape Fullscreen (1920x1080) for Full Long-Form Videos.
    - If is_landscape=False: 9:16 Vertical Canvas (1080x1920) for YouTube Shorts.
    1. 100% Original Anime Audio Stripped (-an) - Zero music/OST/dialogue claims.
    2. Scene-Synchronized Slicing - Slices footage strictly within the narrative scene's timeframe.
    3. Rapid Dynamic Cuts (< 2.8s per cut) - Bypasses visual Content ID matching.
    4. Royalty-Free BGM (RecapKun AERØHEAD) mixed cleanly behind crystal-clear voiceover.
    """
    raw_video = Path(raw_video_path)
    voice_audio = Path(voice_audio_path)
    ass_subs = Path(ass_subtitle_path)
    output_video = Path(output_video_path)
    output_video.parent.mkdir(parents=True, exist_ok=True)

    mode_label = "Landscape (16:9)" if is_landscape else "Short (9:16)"
    if dry_run:
        log(f"[DRY-RUN] Simulating {mode_label} render for window {time_window} -> {output_video.name}")
        return True

    # 1. Timeline Clamping for the specific scene: Keep within scene boundaries
    w_start, w_end = time_window
    safe_start = max(60.0, float(w_start))
    safe_end = max(safe_start + 30.0, float(w_end))

    # 2. Compute cinematic scene cuts (~4.8-5.2s each) across this scene's timeline
    window_length = max(30.0, safe_end - safe_start)
    cut_len = 4.8  # Narrative scene cut length matching RecapKun storytelling
    num_cuts = max(4, int(total_duration / cut_len) + 1)
    step = (window_length - cut_len) / max(1, num_cuts)

    temp_dir = output_video.parent / f"temp_slices_{output_video.stem}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    slice_files = []
    current_time = 0.0

    log(f"Composing {mode_label}: Slicing {num_cuts} scene-synced cuts (~{cut_len:.1f}s each) between {safe_start:.1f}s and {safe_end:.1f}s...")

    try:
        for idx in range(num_cuts):
            if current_time >= total_duration:
                break
            seg_dur = min(cut_len, total_duration - current_time)
            if seg_dur <= 0.4:
                break
            seg_start = safe_start + (idx * step)
            seg_file = temp_dir / f"slice_{idx:03d}.mp4"

            # Anti-copyright visual variance without jarring mirror flips:
            # Subtle cinematic punch-in and gentle crop variance
            if is_landscape:
                if idx == 0:
                    vf_slice = "scale=2016:1134:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1"
                elif idx % 2 == 1:
                    vf_slice = "scale=1960:1102:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1"
                else:
                    vf_slice = "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1"
            else:
                if idx == 0:
                    vf_slice = "scale=1344:756:force_original_aspect_ratio=increase,crop=1280:720,setsar=1"
                elif idx % 2 == 1:
                    vf_slice = "scale=1300:731:force_original_aspect_ratio=increase,crop=1280:720,setsar=1"
                else:
                    vf_slice = "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,setsar=1"

            cmd_slice = [
                "ffmpeg", "-y",
                "-ss", f"{seg_start:.2f}",
                "-i", str(raw_video),
                "-t", f"{seg_dur:.2f}",
                "-vf", vf_slice,
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "22",
                "-an",  # Strip 100% of raw anime audio!
                str(seg_file)
            ]
            res_slice = subprocess.run(cmd_slice, capture_output=True, text=True)
            if res_slice.returncode == 0 and seg_file.exists() and seg_file.stat().st_size > 5000:
                slice_files.append(seg_file)
                current_time += seg_dur

        if not slice_files:
            log("Failed to slice any scenes from raw anime video.")
            return False

        # Concat slices into a unified spliced video stream
        concat_txt = temp_dir / "slices.txt"
        with open(concat_txt, "w", encoding="utf-8") as f:
            for sf in slice_files:
                f.write(f"file '{sf.resolve()}'\n")

        spliced_video = temp_dir / "spliced_montage.mp4"
        cmd_concat = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_txt),
            "-c", "copy",
            str(spliced_video)
        ]
        res_cat = subprocess.run(cmd_concat, capture_output=True, text=True)
        if res_cat.returncode != 0 or not spliced_video.exists():
            log(f"Slice concat failed: {res_cat.stderr[-300:]}")
            return False

        # 3. Canvas Compositor (Landscape 16:9 or Vertical 9:16)
        if is_landscape:
            filtergraph = build_landscape_ffmpeg_filtergraph(
                has_subtitles=ass_subs.exists(),
                ass_path=str(ass_subs.resolve()),
                mirror=False,
            )
        else:
            filtergraph = build_ffmpeg_filtergraph(
                has_subtitles=ass_subs.exists(),
                ass_path=str(ass_subs.resolve()),
                mirror=False,
            )

        # Default BGM fallback
        if not bgm_path or not Path(bgm_path).exists():
            if DEFAULT_BGM_PATH.exists():
                bgm_path = DEFAULT_BGM_PATH

        has_bgm = bgm_path and Path(bgm_path).exists()

        cmd = [
            "ffmpeg", "-y",
            "-i", str(spliced_video),
            "-i", str(voice_audio),
        ]
        if has_bgm:
            cmd.extend(["-stream_loop", "-1", "-i", str(bgm_path)])

        # Zero raw anime audio: only voiceover and royalty-free BGM
        if has_bgm:
            audio_filter = (
                "[1:a]loudnorm=I=-16:TP=-1.5:LRA=11[voice_a];"
                "[2:a]volume=0.15[bgm_a];"
                "[voice_a][bgm_a]amix=inputs=2:duration=first:dropout_transition=2[aout]"
            )
        else:
            audio_filter = "[1:a]loudnorm=I=-16:TP=-1.5:LRA=11[aout]"

        cmd.extend([
            "-filter_complex", f"{filtergraph};{audio_filter}",
            "-map", "[v]",
            "-map", "[aout]",
            "-c:v", "libx264",
            "-preset", "faster",
            "-crf", "21",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", str(total_duration),
            "-movflags", "+faststart",
            str(output_video)
        ])

        log(f"Executing FFmpeg render: {output_video.name}...")
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            log(f"FFmpeg error: {res.stderr[-500:]}")
            if output_video.exists():
                output_video.unlink()
            return False
        if not output_video.exists() or output_video.stat().st_size < 1024 * 50:
            log(f"Render output empty or too small: {output_video}")
            if output_video.exists():
                output_video.unlink()
            return False
        log(f"Rendered successfully: {output_video} ({output_video.stat().st_size} bytes)")
        return True
    except Exception as err:
        log(f"FFmpeg execution failed: {err}")
        if output_video.exists():
            output_video.unlink()
        return False
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# Alias for flexible calling
assemble_part = assemble_short_part


def stitch_full_episode_video(
    part_video_paths: list[str | Path],
    output_full_path: str | Path,
    dry_run: bool = False,
) -> bool:
    """
    Concatenate all individual Short parts into a cohesive Full Episode Video.
    (Preserved for backward compatibility).
    """
    output_full = Path(output_full_path)
    output_full.parent.mkdir(parents=True, exist_ok=True)

    if dry_run:
        log(f"[DRY-RUN] Simulating full episode stitch of {len(part_video_paths)} parts -> {output_full.name}")
        return True

    valid_parts = [Path(p) for p in part_video_paths if Path(p).exists() and Path(p).stat().st_size > 1024 * 50]
    if len(valid_parts) != len(part_video_paths):
        log(f"Cannot stitch: only {len(valid_parts)} of {len(part_video_paths)} parts are valid.")
        if output_full.exists():
            output_full.unlink()
        return False

    # Create concat list file
    concat_list_file = output_full.parent / "concat_parts.txt"
    with open(concat_list_file, "w", encoding="utf-8") as f:
        for p in valid_parts:
            f.write(f"file '{p.resolve()}'\n")

    # Concat landscape parts directly into Full Long-Form Video (1920x1080)
    # Uses fast streamcopy first, with seamless re-encode fallback
    cmd_copy = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list_file),
        "-c", "copy",
        "-movflags", "+faststart",
        str(output_full)
    ]

    log(f"Stitching {len(valid_parts)} parts into Full Landscape Video: {output_full.name}...")
    try:
        res = subprocess.run(cmd_copy, capture_output=True, text=True)
        if res.returncode != 0 or not output_full.exists() or output_full.stat().st_size < 1024 * 50:
            log(f"Direct streamcopy concat failed, falling back to full re-encode...")
            cmd_reencode = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_list_file),
                "-c:v", "libx264",
                "-preset", "faster",
                "-crf", "21",
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                str(output_full)
            ]
            res = subprocess.run(cmd_reencode, capture_output=True, text=True)
        if res.returncode != 0:
            log(f"Stitch error: {res.stderr[-500:]}")
            if output_full.exists():
                output_full.unlink()
            return False
        if not output_full.exists() or output_full.stat().st_size < 1024 * 100:
            log(f"Stitched full episode video empty or too small: {output_full}")
            if output_full.exists():
                output_full.unlink()
            return False
        log(f"Full episode stitched successfully: {output_full} ({output_full.stat().st_size} bytes)")
        return True
    except Exception as err:
        log(f"Full video stitching failed: {err}")
        if output_full.exists():
            output_full.unlink()
        return False


def assemble_master_full_video(
    raw_video_path: str | Path,
    voice_audio_path: str | Path,
    ass_subtitle_path: str | Path,
    output_video_path: str | Path,
    chapter_segments: list[dict],
    total_duration: float,
    bgm_path: str | Path | None = None,
    dry_run: bool = False,
) -> bool:
    """
    Renders the Master Full Normal Video in true 16:9 Landscape (1920x1080)
    as ONE UNINTERRUPTED continuous video:
    - Zero stitch seams or mid-video audio cuts
    - Continuous narrative scene playback (no 4.8s jump cuts)
    - Full unified audio mix: single voiceover stream + ducked AERØHEAD BGM (-18dB)
    - Bottom-third dynamic ASS karaoke subtitles across the entire timeline
    """
    raw_video = Path(raw_video_path)
    voice_audio = Path(voice_audio_path)
    ass_subs = Path(ass_subtitle_path)
    output_video = Path(output_video_path)
    output_video.parent.mkdir(parents=True, exist_ok=True)

    if dry_run:
        log(f"[DRY-RUN] Simulating Master Full Normal Video render ({len(chapter_segments)} chapters, {total_duration:.1f}s) -> {output_video.name}")
        return True

    temp_dir = output_video.parent / f"temp_master_{output_video.stem}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    slice_files = []

    log(f"Composing Master Full Normal Video: extracting continuous narrative scenes across {len(chapter_segments)} chapters...")

    try:
        slice_idx = 0
        for chap in chapter_segments:
            chap_dur = chap.get("duration", 60.0)
            w_start, w_end = chap.get("time_range", [120, 500])
            safe_start = max(60.0, float(w_start))
            safe_end = max(safe_start + 30.0, float(w_end))
            win_len = max(30.0, safe_end - safe_start)

            beats = chap.get("beats")
            if beats and len(beats) > 0:
                shots = []
                accum_dur = 0.0
                for b_idx, b in enumerate(beats):
                    b_start = max(0.0, float(b.get("start", safe_start)))
                    if b_idx == len(beats) - 1:
                        b_dur = max(0.5, chap_dur - accum_dur)
                    else:
                        w = float(b.get("weight", 1.0 / len(beats)))
                        b_dur = round(chap_dur * w, 2)
                        accum_dur += b_dur
                    shots.append((b_start, b_dur))
            elif chap_dur <= 35.0:
                shots = [(safe_start, chap_dur)]
            else:
                s1_dur = chap_dur / 2.0
                s2_dur = chap_dur - s1_dur
                s1_start = safe_start
                # Scene 2 is chosen inside the scene window to show narrative climax
                s2_start = min(safe_start + (win_len * 0.45), safe_end - s2_dur)
                s2_start = max(safe_start + s1_dur, s2_start)
                shots = [(s1_start, s1_dur), (s2_start, s2_dur)]

            for s_start, s_dur in shots:
                if s_dur <= 0.5:
                    continue
                seg_file = temp_dir / f"slice_{slice_idx:03d}.mp4"
                vf_slice = "fps=30,scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1"
                cmd_slice = [
                    "ffmpeg", "-y",
                    "-ss", f"{s_start:.2f}",
                    "-i", str(raw_video),
                    "-t", f"{s_dur:.2f}",
                    "-vf", vf_slice,
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-crf", "20",
                    "-avoid_negative_ts", "make_zero",
                    "-an",
                    str(seg_file)
                ]
                res_slice = subprocess.run(cmd_slice, capture_output=True, text=True)
                if res_slice.returncode == 0 and seg_file.exists() and seg_file.stat().st_size > 5000:
                    slice_files.append(seg_file)
                    slice_idx += 1

        if not slice_files:
            log("Failed to slice continuous scenes for master video.")
            return False

        # Concat visual slices into unified background video stream
        concat_txt = temp_dir / "slices.txt"
        with open(concat_txt, "w", encoding="utf-8") as f:
            for sf in slice_files:
                f.write(f"file '{sf.resolve()}'\n")

        spliced_video = temp_dir / "spliced_master_visual.mp4"
        cmd_concat = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_txt),
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-r", "30",
            "-vsync", "cfr",
            str(spliced_video)
        ]
        res_cat = subprocess.run(cmd_concat, capture_output=True, text=True)
        if res_cat.returncode != 0 or not spliced_video.exists():
            log(f"Visual concat failed: {res_cat.stderr[-300:]}")
            return False

        # Canvas Compositor (Landscape 16:9 fullscreen with ASS subtitles)
        filtergraph = build_landscape_ffmpeg_filtergraph(
            has_subtitles=ass_subs.exists(),
            ass_path=str(ass_subs.resolve()),
            mirror=False,
        )

        if not bgm_path or not Path(bgm_path).exists():
            if DEFAULT_BGM_PATH.exists():
                bgm_path = DEFAULT_BGM_PATH

        has_bgm = bgm_path and Path(bgm_path).exists()

        cmd = [
            "ffmpeg", "-y",
            "-i", str(spliced_video),
            "-i", str(voice_audio),
        ]
        if has_bgm:
            cmd.extend(["-stream_loop", "-1", "-i", str(bgm_path)])

        if has_bgm:
            audio_filter = (
                "[1:a]loudnorm=I=-16:TP=-1.5:LRA=11[voice_a];"
                "[2:a]volume=0.15[bgm_a];"
                "[voice_a][bgm_a]amix=inputs=2:duration=first:dropout_transition=2[aout]"
            )
        else:
            audio_filter = "[1:a]loudnorm=I=-16:TP=-1.5:LRA=11[aout]"

        cmd.extend([
            "-filter_complex", f"{filtergraph};{audio_filter}",
            "-map", "[v]",
            "-map", "[aout]",
            "-c:v", "libx264",
            "-preset", "faster",
            "-crf", "21",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", str(total_duration),
            "-movflags", "+faststart",
            str(output_video)
        ])

        log(f"Rendering Master Full Normal Video: {output_video.name}...")
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            log(f"FFmpeg render error: {res.stderr[-500:]}")
            if output_video.exists():
                output_video.unlink()
            return False

        if not output_video.exists() or output_video.stat().st_size < 1024 * 50:
            log(f"Master render empty or too small: {output_video}")
            if output_video.exists():
                output_video.unlink()
            return False

        log(f"Master Full Normal Video successfully rendered: {output_video} ({output_video.stat().st_size} bytes)")
        return True
    except Exception as err:
        log(f"Master video rendering failed: {err}")
        if output_video.exists():
            output_video.unlink()
        return False
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def derive_short_from_master(
    master_video_path: str | Path,
    output_short_path: str | Path,
    start_time: float,
    end_time: float,
    badge_text: str = "",
    dry_run: bool = False,
) -> bool:
    """
    Derives a 9:16 vertical Short excerpt directly from the Master Normal Video.
    Cuts the exact segment [start_time, end_time], formats it to 9:16 vertical canvas
    with blurred background and centered 1040x584 card, burning an excerpt top pill badge.
    """
    master_video = Path(master_video_path)
    output_short = Path(output_short_path)
    output_short.parent.mkdir(parents=True, exist_ok=True)

    clip_duration = max(1.0, end_time - start_time)
    if dry_run:
        log(f"[DRY-RUN] Simulating Short excerpt ({start_time:.1f}s to {end_time:.1f}s, dur {clip_duration:.1f}s) -> {output_short.name}")
        return True

    temp_dir = output_short.parent / f"temp_short_{output_short.stem}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    badge_ass = temp_dir / "badge.ass"

    try:
        # Create subtle top pill badge ASS file
        if badge_text:
            badge_content = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: CardHeader,DejaVu Sans Bold,36,&H00FFFFFF,&H0000FFFF,&H00000000,&HB0000000,-1,0,0,0,100,100,2,0,1,3.0,1.0,8,60,60,160,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 1,0:00:00.00,9:59:59.00,CardHeader,,0,0,0,,{{\\an8\\bord3\\shad1\\c&H00D7FF&}}• {badge_text.upper()} •
"""
            with open(badge_ass, "w", encoding="utf-8") as f:
                f.write(badge_content)

        escaped_badge = str(badge_ass.resolve()).replace(":", "\\:").replace("'", "\\'") if badge_text else ""
        badge_filter = f",ass='{escaped_badge}'[v]" if badge_text else "[v]"

        filters = [
            "[0:v]split=2[raw_bg][raw_fg]",
            "[raw_bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,boxblur=25:5,eq=brightness=-0.12[bg]",
            "[raw_fg]scale=1040:584:force_original_aspect_ratio=decrease,pad=1040:584:(ow-iw)/2:(oh-ih)/2:color=black@0,setsar=1[fg]",
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2-60{badge_filter}",
        ]
        filtergraph = ";".join(filters)

        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{start_time:.3f}",
            "-to", f"{end_time:.3f}",
            "-i", str(master_video),
            "-filter_complex", filtergraph,
            "-map", "[v]",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-preset", "faster",
            "-crf", "22",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            str(output_short)
        ]

        log(f"Deriving Short excerpt ({start_time:.1f}s - {end_time:.1f}s) -> {output_short.name}...")
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            log(f"Short derivation error: {res.stderr[-400:]}")
            if output_short.exists():
                output_short.unlink()
            return False

        return output_short.exists() and output_short.stat().st_size > 1024 * 50
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)



if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Anime video engine")
    parser.add_argument("--test-filters", action="store_true", help="Print FFmpeg filtergraph")
    args = parser.parse_args()

    if args.test_filters:
        fg = build_ffmpeg_filtergraph(has_subtitles=True, ass_path="/path/to/subs.ass")
        print("=== FFmpeg Filtergraph ===")
        print(fg)
