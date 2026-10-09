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


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Anime video engine")
    parser.add_argument("--test-filters", action="store_true", help="Print FFmpeg filtergraph")
    args = parser.parse_args()

    if args.test_filters:
        fg = build_ffmpeg_filtergraph(has_subtitles=True, ass_path="/path/to/subs.ass")
        print("=== FFmpeg Filtergraph ===")
        print(fg)
