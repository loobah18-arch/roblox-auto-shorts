"""
Open-Source Video Editor Integration Engine for AniDoc.
Integrates mifi/editly (5.5k+ stars on GitHub) for declarative WebGL-powered AMV editing
with seamless fallback to FFmpeg xfade transitions.
"""
import os
import json
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
FPS = 30
SCRATCH_DIR = Path(__file__).resolve().parent.parent / "output" / "scratch"


# Curated high-energy WebGL gl-transitions supported by editly
EDITLY_TRANSITIONS = [
    "crosszoom",
    "directional-left",
    "directional-right",
    "glitchmemories",
    "dreamzoom",
    "wipeleft",
    "wiperight",
    "luminanceMelt",
    "linearblur"
]


def is_editly_available() -> bool:
    """Checks if editly CLI is installed and available in PATH."""
    return shutil.which("editly") is not None


def generate_editly_spec(
    clip_paths: List[Path],
    segments: List[Dict[str, Any]],
    audio_path: Path,
    output_path: Path,
    width: int = VIDEO_WIDTH,
    height: int = VIDEO_HEIGHT,
    fps: int = FPS,
    audio_offset: float = 0.0
) -> Dict[str, Any]:
    """
    Constructs an Editly declarative JSON specification.
    Preserves 100% widescreen 16:9 anime combat using resizeMode: 'contain'.
    Applies high-impact crosszoom on beat drop and alternating GL transitions on combat cuts.
    """
    clips = []
    n_clips = len(clip_paths)

    for idx, (cp, seg) in enumerate(zip(clip_paths, segments)):
        dur = seg.get("duration", 1.0)
        is_drop = seg.get("is_drop", False)

        # Transition to NEXT clip
        transition = None
        if idx < n_clips - 1:
            next_seg = segments[idx + 1] if idx + 1 < len(segments) else {}
            if next_seg.get("is_drop", False) and not is_drop:
                # Transition into the 808 beat drop: explosive crosszoom!
                transition = {"name": "crosszoom", "duration": 0.18}
            elif idx == n_clips - 2:
                # Climax into outro: dramatic fade
                transition = {"name": "fade", "duration": 0.25}
            else:
                # Rhythmic transition pairing: snappy 0.12s punch crosszoom and directional gl-wipes
                t_name = "crosszoom" if idx % 2 == 0 else EDITLY_TRANSITIONS[idx % len(EDITLY_TRANSITIONS)]
                transition = {"name": t_name, "duration": 0.12}

        clip_spec = {
            "duration": dur,
            "layers": [
                {
                    "type": "video",
                    "path": str(Path(cp).resolve()),
                    "resizeMode": "contain"
                }
            ]
        }
        if transition:
            clip_spec["transition"] = transition

        clips.append(clip_spec)

    spec = {
        "outPath": str(Path(output_path).resolve()),
        "width": width,
        "height": height,
        "fps": fps,
        "audioFilePath": str(Path(audio_path).resolve()),
        "clipsAudioVolume": 0.25,
        "outputVolume": 1.0,
        "defaults": {
            "layer": {
                "resizeMode": "contain"
            },
            "transition": {
                "duration": 0.12,
                "name": "directional-left"
            }
        },
        "clips": clips
    }
    return spec


def render_with_editly(
    spec: Dict[str, Any],
    spec_path: Optional[Path] = None,
    output_path: Optional[Path] = None
) -> bool:
    """
    Renders an AMV short using editly via xvfb-run (or direct execution).
    Returns True if rendering succeeded and output file exists.
    """
    if not spec_path:
        spec_path = SCRATCH_DIR / "editly_spec.json"
    spec_path = Path(spec_path)
    spec_path.parent.mkdir(parents=True, exist_ok=True)

    with open(spec_path, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2)

    out_file = Path(spec.get("outPath", output_path or "output.mp4"))

    # Determine command: xvfb-run if available (required on headless CI)
    if shutil.which("xvfb-run"):
        cmd = ["xvfb-run", "--auto-servernum", "--server-args=-screen 0 1280x1024x24 -ac", "editly", str(spec_path)]
    else:
        cmd = ["editly", str(spec_path)]

    print(f"🎬 [OpenSourceEditor] Executing editly: {' '.join(cmd)}")
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"⚠️ [OpenSourceEditor] editly render warning:\n{res.stderr[:300]}")
            return False
        return out_file.exists() and out_file.stat().st_size > 50000
    except Exception as e:
        print(f"⚠️ [OpenSourceEditor] editly invocation exception: {e}")
        return False


def post_process_editly_output(
    raw_video: Path,
    final_output: Path,
    drop_time: Optional[float] = None,
    combat_cut_times: Optional[List[float]] = None,
    ass_path: Optional[Path] = None
) -> bool:
    """
    Applies high-bitrate loudnorm -14 LUFS audio normalization, pre-drop vacuum,
    combat Foley transient enhancement, and optional ASS subtitles to editly output.
    """
    FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
    af_filters = []
    if drop_time is not None:
        from effects_engine import build_pre_drop_audio_vacuum_filter, build_combat_foley_audio_filter
        af_filters.append(build_pre_drop_audio_vacuum_filter(drop_time))
        if combat_cut_times:
            af_filters.append(build_combat_foley_audio_filter(combat_cut_times, drop_time))
    af_filters.append("loudnorm=I=-14:TP=-1.5:LRA=11")
    af_str = ",".join(af_filters)

    vf_opts = []
    if ass_path and ass_path.exists():
        escaped_ass = str(ass_path).replace("\\", "/").replace(":", "\\:")
        fonts_arg = f":fontsdir='{FONTS_DIR}'" if FONTS_DIR.exists() else ""
        vf_opts = ["-vf", f"subtitles='{escaped_ass}'{fonts_arg}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18"]
    else:
        vf_opts = ["-c:v", "copy"]

    cmd = [
        "ffmpeg", "-y",
        "-i", str(raw_video),
        *vf_opts,
        "-c:a", "aac",
        "-b:a", "192k",
        "-af", af_str,
        "-movflags", "+faststart",
        str(final_output)
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        return res.returncode == 0 and final_output.exists() and final_output.stat().st_size > 50000
    except Exception as e:
        print(f"⚠️ [OpenSourceEditor] Post-processing exception: {e}")
        return False
