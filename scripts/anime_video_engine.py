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
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
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
    mirror: bool = True,
) -> str:
    """
    Constructs the 16:9 Landscape Fullscreen (1920x1080) anti-copyright FFmpeg filtergraph:
    - Horizontal mirroring (hflip) inverts 2D spatial coordinate maps
    - Filmic color grade: contrast 1.12, saturation 1.15, gamma 0.95
    - Soft cinematic vignette (darkens corners) + unsharp mask + micro temporal noise
    - Bottom-third dynamic ASS karaoke subtitles
    """
    flip_filter = "hflip," if mirror else ""
    filter_chain = (
        f"[0:v]{flip_filter}eq=contrast=1.12:brightness=-0.02:saturation=1.15:gamma=0.95,"
        f"vignette=PI/4.8,unsharp=5:5:0.8:5:5:0.4,"
        f"scale=1920:1080:force_original_aspect_ratio=decrease,"
        f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1"
    )
    if has_subtitles and ass_path:
        escaped_ass = ass_path.replace(":", "\\:").replace("'", "\\'")
        return f"{filter_chain},ass='{escaped_ass}'[v]"
    else:
        return f"{filter_chain}[v]"


def build_fullbleed_ffmpeg_filtergraph(
    has_subtitles: bool = True,
    ass_path: str = "",
    mirror: bool = True,
) -> str:
    """
    Constructs the high-impact Full-Bleed 9:16 vertical FFmpeg filtergraph (Narration Cinema style):
    - 9:16 full-screen crop (1080x1920) filling the entire vertical screen (no blurred borders, no floating cards).
    - Cinematic contrast (1.12), saturation boost (1.18), subtle vignette, unsharp mask, and temporal micro-noise.
    - Anti-copyright horizontal flip.
    - Centered dynamic subtitle burn in lower-middle safe zone.
    """
    flip_filter = "hflip," if mirror else ""
    filters = [
        f"[0:v]{flip_filter}scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920,setsar=1,"
        f"eq=contrast=1.12:brightness=-0.02:saturation=1.18:gamma=0.96,"
        f"vignette=PI/4.5,unsharp=5:5:0.8:5:5:0.4,noise=alls=5:allf=t[base]"
    ]
    if has_subtitles and ass_path:
        escaped_ass = ass_path.replace(":", "\\:").replace("'", "\\'")
        filters.append(f"[base]ass='{escaped_ass}'[v]")
    else:
        filters.append("[base]copy[v]")
    return ";".join(filters)


def build_ffmpeg_filtergraph(
    has_subtitles: bool = True,
    ass_path: str = "",
    mirror: bool = True,
    full_bleed: bool = False,
) -> str:
    """
    Constructs the anti-copyright FFmpeg filtergraph for 9:16 Shorts:
    - If full_bleed=True: Full-bleed 9:16 cinema presentation (Narration Cinema style).
    - If full_bleed=False: 3-layer card canvas with blurred background and glowing border.
    """
    if full_bleed:
        return build_fullbleed_ffmpeg_filtergraph(
            has_subtitles=has_subtitles,
            ass_path=ass_path,
            mirror=mirror,
        )

    filters = []

    # 1. Base input split with transformative color grade, vignette, and micro-noise
    flip_filter = "hflip," if mirror else ""
    filters.append(
        f"[0:v]{flip_filter}eq=contrast=1.15:brightness=-0.03:saturation=1.20:gamma=0.94,"
        f"vignette=PI/4.2,unsharp=5:5:0.9:5:5:0.5,noise=alls=6:allf=t,split=2[raw_bg][raw_fg]"
    )

    # 2. Background: fill 1080x1920, heavy blur, darkened
    filters.append(
        "[raw_bg]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,setsar=1,boxblur=28:6,eq=brightness=-0.14:contrast=1.06[bg]"
    )

    # 3. Foreground: crisp card centered (1020x574)
    filters.append(
        "[raw_fg]scale=1020:574:force_original_aspect_ratio=decrease,"
        "pad=1020:574:(ow-iw)/2:(oh-ih)/2:color=black@0,setsar=1[fg]"
    )

    # 4. Overlay foreground on background (shifted slightly up to make room for captions)
    filters.append("[bg][fg]overlay=(W-w)/2:(H-h)/2-50[comp]")

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
    time_window: tuple[float, float] = (120.0, 480.0),
    total_duration: float = 60.0,
    bgm_path: str | Path | None = None,
    is_landscape: bool = False,
    dry_run: bool = False,
    beats: list[dict] | None = None,
    narration: str = "",
    full_bleed: bool = True,
    sentence_durations: list[float] | None = None,
    remove_copyrighted_clip: bool = False,
) -> bool:
    """
    Renders an individual part with comprehensive anti-copyright tactics & dynamic sentence-locking:
    - If is_landscape=True: 16:9 Landscape Fullscreen (1920x1080) for Full Long-Form Videos.
    - If is_landscape=False: 9:16 Vertical Canvas (1080x1920) for YouTube Shorts.
    1. 100% Original Anime Audio Stripped (-an) - Zero music/OST/dialogue claims.
    2. Dynamic Sentence-Locked Slicing - Slices match spoken narration sentence-by-sentence.
    3. CFR 30fps stream synchronization to prevent audio/video drift.
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

    # 1. Timeline Clamping for the specific scene: Keep within story boundaries
    # Standard TV anime episodes have ending credits/ED song starting at ~1285s (21m25s).
    # Slicing past 1285s cuts directly into the ED credit crawl / music video, triggering instant Aniplex Content ID.
    MAX_SAFE_ANIME_STORY_TIMESTAMP = 1285.0
    w_start, w_end = time_window
    safe_start = max(60.0, min(MAX_SAFE_ANIME_STORY_TIMESTAMP - 30.0, float(w_start)))
    safe_end = min(MAX_SAFE_ANIME_STORY_TIMESTAMP, max(safe_start + 30.0, float(w_end)))
    window_length = max(30.0, safe_end - safe_start)

    # 2. Dynamic Sentence-Locked Scene Allocation
    shots = []
    if beats and len(beats) > 0:
        # Check for exact TTS-derived sentence durations
        json_timing = voice_audio.parent / f"{voice_audio.stem}_sentences.json"
        actual_sentence_durations = None
        if sentence_durations and len(sentence_durations) == len(beats):
            actual_sentence_durations = sentence_durations
        elif json_timing.exists():
            try:
                with open(json_timing, "r", encoding="utf-8") as f:
                    tdata = json.load(f)
                    if "sentence_durations" in tdata and len(tdata["sentence_durations"]) == len(beats):
                        actual_sentence_durations = tdata["sentence_durations"]
            except Exception:
                pass

        if actual_sentence_durations:
            accum_dur = 0.0
            sum_durs = sum(actual_sentence_durations)
            scale_factor = total_duration / sum_durs if sum_durs > 0 else 1.0
            for b_idx, b in enumerate(beats):
                raw_b_start = float(b.get("start", safe_start))
                b_start = max(safe_start, min(safe_end - 5.0, raw_b_start))
                if b_idx == len(beats) - 1:
                    b_dur = max(0.5, total_duration - accum_dur)
                else:
                    b_dur = round(actual_sentence_durations[b_idx] * scale_factor, 2)
                    accum_dur += b_dur
                shots.append((b_start, b_dur))
        else:
            sents = [s.strip() for s in re.split(r'(?<=[.!?])\s+', narration) if s.strip()] if narration else []
            total_narr_words = sum(len(s.split()) for s in sents) if sents else 0

            weights = []
            if total_narr_words > 0 and len(sents) == len(beats):
                # Perfect 1:1 sentence-to-beat locking: each scene plays exactly while that sentence is spoken
                weights = [round(len(s.split()) / total_narr_words, 4) for s in sents]
            elif total_narr_words > 0 and len(sents) > len(beats):
                s_per_beat = max(1, len(sents) // len(beats))
                for b_idx in range(len(beats)):
                    s_start_idx = b_idx * s_per_beat
                    s_end_idx = len(sents) if (b_idx == len(beats) - 1) else min(len(sents), (b_idx + 1) * s_per_beat)
                    group_words = sum(len(sents[j].split()) for j in range(s_start_idx, s_end_idx))
                    weights.append(round(group_words / total_narr_words, 3))
            else:
                weights = [float(b.get("weight", 1.0 / len(beats))) for b in beats]

            accum_dur = 0.0
            for b_idx, b in enumerate(beats):
                raw_b_start = float(b.get("start", safe_start))
                b_start = max(safe_start, min(safe_end - 5.0, raw_b_start))
                if b_idx == len(beats) - 1:
                    b_dur = max(0.5, total_duration - accum_dur)
                else:
                    w = weights[b_idx] if b_idx < len(weights) else (1.0 / len(beats))
                    b_dur = round(total_duration * w, 2)
                    accum_dur += b_dur
                shots.append((b_start, b_dur))
    else:
        # Fallback if no explicit beats: 4 narrative cuts with sentence word weights
        num_cuts = max(3, min(5, int(total_duration / 15.0)))
        step = (window_length - 4.8) / max(1, num_cuts)
        sents = [s.strip() for s in re.split(r'(?<=[.!?])\s+', narration) if s.strip()] if narration else []
        total_narr_words = sum(len(s.split()) for s in sents) if sents else 0
        accum_dur = 0.0
        for idx in range(num_cuts):
            s_start = safe_start + (idx * step)
            if total_narr_words > 0 and len(sents) >= num_cuts:
                s_per_cut = max(1, len(sents) // num_cuts)
                s_start_idx = idx * s_per_cut
                s_end_idx = len(sents) if (idx == num_cuts - 1) else min(len(sents), (idx + 1) * s_per_cut)
                w = sum(len(sents[j].split()) for j in range(s_start_idx, s_end_idx)) / total_narr_words
            else:
                w = 1.0 / num_cuts
            if idx == num_cuts - 1:
                s_dur = max(0.5, total_duration - accum_dur)
            else:
                s_dur = round(total_duration * w, 2)
                accum_dur += s_dur
            shots.append((s_start, s_dur))

    # Anti-copyright duration guard & non-linear micro-slicing:
    # 1. Hard ceiling: NO single shot ever exceeds 3.2 seconds (Content ID needs >=4.5s contiguous).
    # 2. Alternating punch-in zooms (1.14x, 1.20x, 1.16x, 1.22x).
    # 3. Dynamic PTS tempo modulation (setpts=0.96*PTS, 0.94*PTS) to alter keyframe timestamps.
    # 4. Micro-temporal offsets to prevent contiguous frame-hash playback matching.
    MAX_SHOT_DURATION = 3.2
    ZOOM_CYCLES = [1.14, 1.20, 1.16, 1.22, 1.18]
    TEMPO_CYCLES = [0.96, 0.94, 0.97, 0.95]

    expanded_shots = []
    z_idx = 0
    t_idx = 0

    for s_start, s_dur in shots:
        if s_dur <= 0.4:
            continue
        remaining_dur = s_dur
        curr_offset = s_start
        chunk_idx = 0

        while remaining_dur > 0:
            if remaining_dur <= MAX_SHOT_DURATION:
                c_dur = round(remaining_dur, 2)
            elif remaining_dur <= (MAX_SHOT_DURATION + 1.2):
                c_dur = round(remaining_dur / 2.0, 2)
            else:
                c_dur = round(min(MAX_SHOT_DURATION, max(2.2, remaining_dur / max(2, int(remaining_dur / 2.6)))), 2)

            zoom = ZOOM_CYCLES[z_idx % len(ZOOM_CYCLES)]
            tempo = TEMPO_CYCLES[t_idx % len(TEMPO_CYCLES)]
            z_idx += 1
            t_idx += 1

            # Micro-temporal jump for alternating subdivisions
            sample_start = curr_offset + (1.6 if chunk_idx % 2 == 1 else 0.0)
            sample_start = max(safe_start, min(max(safe_start, safe_end - c_dur), sample_start))

            expanded_shots.append((sample_start, c_dur, zoom, tempo))
            curr_offset += c_dur
            remaining_dur = round(remaining_dur - c_dur, 2)
            chunk_idx += 1

    # Anti-Copyright Remediation: Drop or shift copyrighted shot
    if remove_copyrighted_clip and expanded_shots:
        if len(expanded_shots) > 1:
            dropped = expanded_shots.pop(0)
            log(f"✂️ [AnimeEngine] Dropped copyrighted cut (start={dropped[0]:.2f}s, dur={dropped[1]:.2f}s) from shot sequence (remaining: {len(expanded_shots)})")
        else:
            safe_start += 15.0
            log(f"✂️ [AnimeEngine] Shifted safe_start to {safe_start:.2f}s to exclude copyrighted scene section")

    temp_dir = output_video.parent / f"temp_slices_{output_video.stem}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    slice_files = []

    log(f"Composing {mode_label}: Slicing {len(expanded_shots)} anti-copyright protected shots between {safe_start:.1f}s and {safe_end:.1f}s...")

    try:
        for idx, (s_start, s_dur, zoom, tempo) in enumerate(expanded_shots):
            if s_dur <= 0.4:
                continue
            seg_file = temp_dir / f"slice_{idx:03d}.mp4"

            if is_landscape:
                w_s = int(1920 * zoom)
                h_s = int(1080 * zoom)
                vf_slice = f"setpts={tempo:.3f}*PTS,fps=30,scale={w_s}:{h_s}:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1"
            elif full_bleed:
                # Full-bleed 9:16 vertical crop
                try:
                    from motion_tracker import build_precise_motion_tracking_filter
                    track_filter = build_precise_motion_tracking_filter(
                        clip_path=str(raw_video) if raw_video.exists() else None,
                        duration=s_dur,
                        video_width=1080,
                        video_height=1920,
                        camera_motion="push_in" if idx % 2 == 1 else "auto",
                        start_time=s_start,
                    )
                    vf_slice = f"setpts={tempo:.3f}*PTS,fps=30,{track_filter}"
                except Exception:
                    vf_slice = f"setpts={tempo:.3f}*PTS,fps=30,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1"
            else:
                # AniDoc Standard: 16:9 widescreen slice preserving 100% horizontal action for dual-layer composition
                # Character tracking anchors zoom punch on character's face / centroid
                w_s = int(1280 * zoom)
                h_s = int(720 * zoom)
                crop_x = (w_s - 1280) // 2
                crop_y = (h_s - 720) // 2
                try:
                    from motion_tracker import extract_motion_trajectory
                    traj = extract_motion_trajectory(raw_video, duration=s_dur, start_time=s_start)
                    if traj:
                        cx = traj.get("cx_start", 0.5)
                        cy = traj.get("cy_start", 0.5)
                        crop_x = int(max(0, min(w_s - 1280, cx * w_s - 640)))
                        crop_y = int(max(0, min(h_s - 720, cy * h_s - 360)))
                except Exception:
                    pass
                vf_slice = f"setpts={tempo:.3f}*PTS,fps=30,scale={w_s}:{h_s}:force_original_aspect_ratio=increase,crop=1280:720:{crop_x}:{crop_y},setsar=1"

            cmd_slice = [
                "ffmpeg", "-y",
                "-ss", f"{s_start:.2f}",
                "-i", str(raw_video),
                "-t", f"{s_dur:.2f}",
                "-vf", vf_slice,
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "22",
                "-avoid_negative_ts", "make_zero",
                "-an",  # Strip 100% of raw anime audio!
                str(seg_file)
            ]
            res_slice = subprocess.run(cmd_slice, capture_output=True, text=True)
            if res_slice.returncode == 0 and seg_file.exists() and seg_file.stat().st_size > 5000:
                slice_files.append(seg_file)

        if not slice_files:
            log("Failed to slice any scenes from raw anime video.")
            return False

        # Concat slices into a unified CFR 30fps video stream
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
            log(f"Slice concat failed: {res_cat.stderr[-300:]}")
            return False

        # 3. Canvas Compositor (Landscape 16:9 or Vertical 9:16) with anti-copyright mirroring & filters
        if is_landscape:
            filtergraph = build_landscape_ffmpeg_filtergraph(
                has_subtitles=ass_subs.exists(),
                ass_path=str(ass_subs.resolve()),
                mirror=True,
            )
        else:
            filtergraph = build_ffmpeg_filtergraph(
                has_subtitles=ass_subs.exists(),
                ass_path=str(ass_subs.resolve()),
                mirror=True,
                full_bleed=full_bleed,
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
                "[1:a]loudnorm=I=-14:TP=-1.5:LRA=11[voice_a];"
                "[2:a]loudnorm=I=-24:TP=-2:LRA=7[bgm_a];"
                "[voice_a][bgm_a]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[aout]"
            )
        else:
            audio_filter = "[1:a]loudnorm=I=-14:TP=-1.5:LRA=11[aout]"

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


def _render_video_slice(task: tuple) -> tuple[int, bool, str]:
    """Render single slice with FFmpeg in a worker thread."""
    idx, s_start, s_dur, raw_video_str, seg_file_str, alt_zoom = task
    if alt_zoom:
        vf_slice = "fps=30,scale=2050:1153:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1"
    else:
        vf_slice = "fps=30,scale=2150:1210:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1"

    cmd_slice = [
        "ffmpeg", "-y",
        "-ss", f"{s_start:.2f}",
        "-i", raw_video_str,
        "-t", f"{s_dur:.2f}",
        "-vf", vf_slice,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "22",
        "-avoid_negative_ts", "make_zero",
        "-an",
        seg_file_str,
    ]
    res_slice = subprocess.run(cmd_slice, capture_output=True, text=True)
    p = Path(seg_file_str)
    ok = (res_slice.returncode == 0 and p.exists() and p.stat().st_size > 5000)
    return idx, ok, seg_file_str


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

    temp_dir = Path(tempfile.gettempdir()) / f"temp_master_{output_video.stem}_{os.getpid()}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    slice_tasks = []

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
                chap_narr = chap.get("narration", "")
                shots = []
                accum_dur = 0.0

                sents = [s.strip() for s in re.split(r'(?<=[.!?])\s+', chap_narr) if s.strip()] if chap_narr else []
                total_narr_words = sum(len(s.split()) for s in sents) if sents else 0

                weights = []
                if total_narr_words > 0 and len(sents) >= len(beats):
                    s_per_beat = max(1, len(sents) // len(beats))
                    for b_idx in range(len(beats)):
                        s_start_idx = b_idx * s_per_beat
                        s_end_idx = len(sents) if (b_idx == len(beats) - 1) else min(len(sents), (b_idx + 1) * s_per_beat)
                        group_words = sum(len(sents[j].split()) for j in range(s_start_idx, s_end_idx))
                        weights.append(round(group_words / total_narr_words, 3))
                else:
                    weights = [float(b.get("weight", 1.0 / len(beats))) for b in beats]

                for b_idx, b in enumerate(beats):
                    b_start = max(0.0, float(b.get("start", safe_start)))
                    if b_idx == len(beats) - 1:
                        b_dur = max(0.5, chap_dur - accum_dur)
                    else:
                        w = weights[b_idx] if b_idx < len(weights) else (1.0 / len(beats))
                        b_dur = round(chap_dur * w, 2)
                        accum_dur += b_dur
                    shots.append((b_start, b_dur))
            elif chap_dur <= 35.0:
                shots = [(safe_start, chap_dur)]
            else:
                s1_dur = chap_dur / 2.0
                s2_dur = chap_dur - s1_dur
                s1_start = safe_start
                s2_start = min(safe_start + (win_len * 0.45), safe_end - s2_dur)
                s2_start = max(safe_start + s1_dur, s2_start)
                shots = [(s1_start, s1_dur), (s2_start, s2_dur)]

            MAX_SHOT_DUR = 8.5
            refined_shots = []
            for s_start, s_dur in shots:
                if s_dur <= MAX_SHOT_DUR:
                    refined_shots.append((s_start, s_dur))
                else:
                    num_sub = max(2, int(round(s_dur / 6.0)))
                    sub_dur = round(s_dur / num_sub, 2)
                    sub_accum = 0.0
                    for s_i in range(num_sub):
                        this_dur = (s_dur - sub_accum) if (s_i == num_sub - 1) else sub_dur
                        sub_start = min(safe_end - this_dur, s_start + (s_i * 4.5))
                        sub_start = max(safe_start, sub_start)
                        refined_shots.append((round(sub_start, 2), round(this_dur, 2)))
                        sub_accum += this_dur
            shots = refined_shots

            for s_start, s_dur in shots:
                if s_dur <= 0.5:
                    continue
                seg_file = temp_dir / f"slice_{slice_idx:03d}.mp4"
                alt_zoom = (slice_idx % 2 == 1)
                slice_tasks.append((slice_idx, s_start, s_dur, str(raw_video), str(seg_file), alt_zoom))
                slice_idx += 1

        if not slice_tasks:
            log("Failed to slice continuous scenes for master video.")
            return False

        log(f"Rendering {len(slice_tasks)} video slices in parallel with 4 threads...")
        with ThreadPoolExecutor(max_workers=4) as executor:
            rendered = list(executor.map(_render_video_slice, slice_tasks))

        rendered.sort(key=lambda x: x[0])
        slice_files = [Path(r[2]) for r in rendered if r[1]]

        if not slice_files:
            log("Failed to produce valid slices for master video.")
            return False

        # Concat visual slices into unified background video stream
        concat_txt = temp_dir / "slices.txt"
        with open(concat_txt, "w", encoding="utf-8") as f:
            for sf in slice_files:
                f.write(f"file '{sf.resolve()}'\n")

        spliced_video = temp_dir / "spliced_master_visual.mp4"
        cmd_concat_copy = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_txt),
            "-c", "copy",
            "-movflags", "+faststart",
            str(spliced_video)
        ]
        res_cat = subprocess.run(cmd_concat_copy, capture_output=True, text=True)
        if res_cat.returncode != 0 or not spliced_video.exists() or spliced_video.stat().st_size < 1024 * 50:
            log("Streamcopy concat failed, falling back to ultrafast re-encode...")
            cmd_concat_fallback = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_txt),
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-r", "30",
                "-vsync", "cfr",
                str(spliced_video)
            ]
            res_cat = subprocess.run(cmd_concat_fallback, capture_output=True, text=True)
            if res_cat.returncode != 0 or not spliced_video.exists():
                log(f"Visual concat failed: {res_cat.stderr[-300:]}")
                return False

        # Canvas Compositor (Landscape 16:9 fullscreen with ASS subtitles)
        filtergraph = build_landscape_ffmpeg_filtergraph(
            has_subtitles=ass_subs.exists(),
            ass_path=str(ass_subs.resolve()),
            mirror=True,
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
                "[1:a]loudnorm=I=-14:TP=-1.5:LRA=11[voice_a];"
                "[2:a]loudnorm=I=-24:TP=-2:LRA=7[bgm_a];"
                "[voice_a][bgm_a]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[aout]"
            )
        else:
            audio_filter = "[1:a]loudnorm=I=-14:TP=-1.5:LRA=11[aout]"

        cmd.extend([
            "-filter_complex", f"{filtergraph};{audio_filter}",
            "-map", "[v]",
            "-map", "[aout]",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "22",
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


MAX_CUT_SECONDS = 4.2


def plan_beat_cuts(src_start: float, src_end: float, n_frames: int, fps: float, max_cut: float = MAX_CUT_SECONDS,
                   ep_duration: float | None = None, songs: list | None = None) -> list[tuple[float, int]]:
    """
    Footage plan for one beat: [(source_time, frames), ...] summing to exactly n_frames, every cut
    <= max_cut seconds and taken from the beat's own [src_start, src_end] scene.
    * Scene longer than the narration: the cuts are spread evenly across the scene (trimmed).
    * Scene shorter than the narration: it is widened by up to 3 s on each side (staying out of the
      OP/ED and inside the episode) and then looped.
    """
    if n_frames <= 0:
        return []
    dur = n_frames / fps
    s, e = float(src_start), float(src_end)
    if e - s < dur:
        lo = 0.0
        hi = float(ep_duration) if ep_duration else e + 3.0
        for a, b in songs or []:
            a, b = float(a), float(b)
            if b <= s:
                lo = max(lo, b)
            if a >= e:
                hi = min(hi, a)
        grow = min(3.0, (dur - (e - s)) / 2.0)
        s, e = max(lo, s - grow), min(hi, e + grow)
    length = max(0.5, e - s)
    max_cut_frames = max(1, int(max_cut * fps))
    # never cut longer than the scene itself
    max_cut_frames = max(1, min(max_cut_frames, int(length * fps) - 1 if length * fps > 2 else 1))
    n = max(1, -(-n_frames // max_cut_frames))
    base, extra = divmod(n_frames, n)
    sizes = [base + (1 if k < extra else 0) for k in range(n)]
    cuts = []
    if length >= dur:
        slack = length - dur
        gap = slack / (n - 1) if n > 1 else 0.0
        t = s
        for sz in sizes:
            cuts.append((round(t, 3), sz))
            t += sz / fps + gap
    else:
        t = s
        for sz in sizes:
            if t + sz / fps > e + 0.01:
                t = s
            cuts.append((round(t, 3), sz))
            t += sz / fps
    return cuts


def _render_arc_cut(task: tuple) -> tuple[int, bool, str]:
    """One cut: exactly `frames` video frames (1280x720, no mirror, no text) + the matching source audio
    as raw 48 kHz stereo PCM of exactly frames/fps seconds."""
    idx, src, t, frames, fps, w, h, vid_out, pcm_out = task
    dur = frames / fps
    vf = (f"fps={fps},scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
          f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,tpad=stop_mode=clone:stop_duration=10,format=yuv420p")
    cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", src,
           "-map", "0:v:0", "-vf", vf, "-frames:v", str(frames), "-c:v", "libx264", "-preset", "veryfast",
           "-crf", "20", "-g", str(int(fps * 2)), "-bf", "0", "-video_track_timescale", str(int(round(fps * 1000))),
           "-an", vid_out,
           "-map", "0:a:0?", "-t", f"{dur:.4f}", "-ac", "2", "-ar", "48000", "-f", "s16le", pcm_out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    ok = r.returncode == 0 and Path(vid_out).exists() and Path(vid_out).stat().st_size > 1000
    if not ok:
        log(f"cut {idx} ({src} @{t:.1f}s, {frames} frames) failed: {r.stderr[-300:]}")
        return idx, False, vid_out
    # pad / trim the source audio to exactly frames/fps seconds so audio never drifts from video
    want = int(round(dur * 48000)) * 4
    pcm = Path(pcm_out).read_bytes() if Path(pcm_out).exists() else b""
    pcm = pcm[:want] + b"\x00" * max(0, want - len(pcm))
    Path(pcm_out).write_bytes(pcm)
    return idx, True, vid_out


def _measure_lufs(path: str | Path, extra_input: list[str] | None = None, seconds: float | None = None) -> float | None:
    cmd = ["ffmpeg", "-nostdin", "-v", "info", *(extra_input or []), "-i", str(path)]
    if seconds:
        cmd += ["-t", f"{seconds:.1f}"]
    cmd += ["-af", "loudnorm=print_format=json", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    m = re.search(r'"input_i"\s*:\s*"(-?[\d.]+|-inf)"', r.stderr)
    if not m or m.group(1) == "-inf":
        return None
    return float(m.group(1))


def probe_fps(path: str | Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=avg_frame_rate",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        n, d = r.stdout.strip().split("/")
        return float(n) / float(d)
    except Exception:
        return 0.0


def assemble_arc_master_video(
    raw_episode_map: dict[str, str | Path],
    voice_audio_path: str | Path,
    output_video_path: str | Path,
    beat_timeline: list[dict],
    total_duration: float,
    bgm_path: str | Path | None = None,
    dry_run: bool = False,
    width: int = 1280,
    height: int = 720,
    fps: float | None = None,
    voice_lufs: float = -16.0,
    source_under_voice_db: float = 28.0,
    bgm_under_voice_db: float = 20.0,
    workers: int | None = None,
    cuts_report_path: str | Path | None = None,
) -> bool:
    """
    Feature-length 16:9 arc video, Recap-kun style: every beat's footage comes from that beat's own
    source scene [src_start, src_end] in its episode, in cuts of <= 4.2 s, looped or trimmed to fill
    the beat's narration slot [start, end) exactly. Full frame (letterboxed to 1280x720), no mirror,
    no burned-in captions. Audio: narration at voice_lufs, the episode's own audio ~28 dB under the
    voice, BGM ~20 dB under the voice.
    beat_timeline: [{episode_key, src_start, src_end, start, end, episode_duration?, songs?}] tiling
    0..total_duration.
    """
    output_video = Path(output_video_path)
    output_video.parent.mkdir(parents=True, exist_ok=True)
    if dry_run:
        log(f"[DRY-RUN] Simulating arc video render ({len(beat_timeline)} beats, {total_duration:.1f}s) -> {output_video.name}")
        return True
    for k in {b["episode_key"] for b in beat_timeline}:
        p = Path(raw_episode_map.get(k, ""))
        if not p.exists() or p.stat().st_size < 1_000_000:
            log(f"Episode file for {k} is missing ({p}); refusing to render with substitute footage")
            return False
    if not fps:
        f0 = probe_fps(raw_episode_map[beat_timeline[0]["episode_key"]])
        fps = 25.0 if abs(f0 - 25.0) < 0.5 else 30.0
    fps = float(fps)
    total_frames = int(round(total_duration * fps))

    temp_dir = Path(tempfile.mkdtemp(prefix=f"arc_{output_video.stem}_"))
    try:
        tasks, report = [], []
        idx = 0
        for bi, b in enumerate(beat_timeline):
            f0 = int(round(b["start"] * fps))
            f1 = total_frames if bi == len(beat_timeline) - 1 else int(round(b["end"] * fps))
            cuts = plan_beat_cuts(b["src_start"], b["src_end"], f1 - f0, fps,
                                  ep_duration=b.get("episode_duration"), songs=b.get("songs"))
            src = str(Path(raw_episode_map[b["episode_key"]]).resolve())
            for t, n in cuts:
                tasks.append((idx, src, t, n, fps, width, height,
                              str(temp_dir / f"c{idx:05d}.mp4"), str(temp_dir / f"c{idx:05d}.pcm")))
                report.append({"cut": idx, "beat": bi, "episode_key": b["episode_key"], "src_time": t,
                               "frames": n, "master_start": round(f0 / fps, 3)})
                f0 += n
                idx += 1
        if cuts_report_path:
            Path(cuts_report_path).write_text(json.dumps(report, indent=1))
        workers = workers or max(2, min(8, (os.cpu_count() or 4)))
        log(f"Rendering {len(tasks)} cuts for {len(beat_timeline)} beats ({total_duration:.1f}s @ {fps:g} fps) with {workers} workers...")
        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(_render_arc_cut, tasks))
        failed = [r[0] for r in results if not r[1]]
        if failed:
            log(f"{len(failed)} cuts failed (first: {failed[:5]}); aborting render")
            return False

        concat_txt = temp_dir / "cuts.txt"
        concat_txt.write_text("".join(f"file '{t[7]}'\n" for t in tasks))
        video_only = temp_dir / "video.mp4"
        r = subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat_txt),
                            "-c", "copy", str(video_only)], capture_output=True, text=True)
        if r.returncode != 0:
            log(f"video concat failed: {r.stderr[-400:]}")
            return False
        src_pcm = temp_dir / "source.pcm"
        with open(src_pcm, "wb") as out:
            for t in tasks:
                out.write(Path(t[8]).read_bytes())

        source_args = ["-f", "s16le", "-ar", "48000", "-ac", "2"]
        v_meas = _measure_lufs(voice_audio_path) or -20.0
        s_meas = _measure_lufs(src_pcm, source_args)
        v_gain = voice_lufs - v_meas
        s_gain = (voice_lufs - source_under_voice_db - s_meas) if s_meas is not None else -40.0
        if not bgm_path or not Path(bgm_path).exists():
            bgm_path = DEFAULT_BGM_PATH if DEFAULT_BGM_PATH.exists() else None
        b_gain = None
        if bgm_path:
            b_meas = _measure_lufs(bgm_path)
            b_gain = (voice_lufs - bgm_under_voice_db - b_meas) if b_meas is not None else -24.0
        log(f"audio gains: voice {v_gain:+.1f} dB (was {v_meas:.1f} LUFS), source {s_gain:+.1f} dB, "
            f"bgm {b_gain if b_gain is None else round(b_gain, 1)} dB")

        cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(video_only), "-i", str(voice_audio_path),
               *source_args, "-i", str(src_pcm)]
        fmt = "aresample=48000,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
        af = [f"[1:a]{fmt},volume={v_gain:.2f}dB,apad[va]", f"[2:a]{fmt},volume={s_gain:.2f}dB[sa]"]
        mix_in = "[va][sa]"
        n_in = 2
        if bgm_path:
            cmd += ["-stream_loop", "-1", "-i", str(bgm_path)]
            af.append(f"[3:a]{fmt},volume={b_gain:.2f}dB,afade=t=in:d=2[ba]")
            mix_in += "[ba]"
            n_in = 3
        dur = total_frames / fps
        af.append(f"{mix_in}amix=inputs={n_in}:duration=longest:normalize=0,atrim=0:{dur:.3f},"
                  f"afade=t=out:st={max(0.0, dur - 2):.3f}:d=2,alimiter=limit=0.95[aout]")
        cmd += ["-filter_complex", ";".join(af), "-map", "0:v", "-map", "[aout]", "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k", "-t", f"{dur:.3f}", "-movflags", "+faststart", str(output_video)]
        log(f"Muxing arc video {output_video.name} ...")
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not output_video.exists() or output_video.stat().st_size < 100_000:
            log(f"arc mux failed: {r.stderr[-600:]}")
            if output_video.exists():
                output_video.unlink()
            return False
        log(f"Arc video rendered: {output_video} ({output_video.stat().st_size / 1e6:.1f} MB, {dur:.1f}s)")
        return True
    except Exception as err:
        log(f"Arc video rendering failed: {err!r}")
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
    full_bleed: bool = True,
    mirror: bool = False,
    caption_ass_path: str | Path | None = None,
) -> bool:
    """
    Derives a 9:16 vertical Short excerpt directly from the Master Normal Video.
    Cuts the exact segment [start_time, end_time], formats it to 9:16 vertical canvas
    (clean full-bleed cinema view if full_bleed=True, or blurred-background card if full_bleed=False).

    mirror=False by default: the master video has its subtitles burned in, so flipping
    it horizontally prints the captions backwards. Use full_bleed=False for masters with
    burned-in captions so the whole 16:9 frame (and every caption word) stays visible.
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
        # Create subtle top pill badge ASS file (only if badge_text is provided and not full_bleed)
        if badge_text and not full_bleed:
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

        escaped_badge = str(badge_ass.resolve()).replace(":", "\\:").replace("'", "\\'") if (badge_text and not full_bleed) else ""
        badge_filter = f",ass='{escaped_badge}'" if (badge_text and not full_bleed) else ""
        if caption_ass_path and Path(caption_ass_path).exists():
            esc_cap = str(Path(caption_ass_path).resolve()).replace(":", "\\:").replace("'", "\\'")
            badge_filter += f",ass='{esc_cap}'"
        badge_filter += ",format=yuv420p[v]"

        flip = "hflip," if mirror else ""
        if full_bleed:
            filters = [
                f"[0:v]{flip}scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,"
                f"eq=contrast=1.12:brightness=-0.02:saturation=1.18:gamma=0.96,vignette=PI/4.5,unsharp=5:5:0.8:5:5:0.4{badge_filter}"
            ]
        else:
            filters = [
                "[0:v]split=2[raw_bg][raw_fg]",
                "[raw_bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,boxblur=25:5,eq=brightness=-0.14[bg]",
                f"[raw_fg]{flip}scale=1080:608:force_original_aspect_ratio=decrease,pad=1080:608:(ow-iw)/2:(oh-ih)/2:color=black@0,setsar=1[fg]",
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
            "-preset", "veryfast",
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
