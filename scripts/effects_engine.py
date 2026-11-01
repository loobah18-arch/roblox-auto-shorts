"""
4K HDR Color Correction, Velocity Ramping, Beat Flashes & Dynamic Zoom Impact Engine.
Replicates top viral anime/Marvel TikTok & Shorts editing styles:
- Dynamic Twixtor-style slow-motion curves (0.50x - 0.65x) on power strikes, dialogue intro, and technique charges.
- Explosive snap impact speedups (1.25x - 1.30x) on 808 bass drops and rapid clashes.
- Dynamic 4-tier velocity zoom punches (1.18x downbeat impact, 1.14x power hit, 1.08x fast strike, 1.04x cinematic slow push).
- Fast 0.07s optical white flashes on 808 bass drops.
- High-contrast 4K HDR Color Grading with deep blacks and vibrant highlights.
"""
from pathlib import Path
from typing import List, Dict, Any, Optional, Union, Tuple
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
FPS = 30
CC_PRESETS = {
    "vibrant_anime_glow": {
        "contrast": 1.15,
        "brightness": 0.04,
        "saturation": 1.35,
        "gamma": 1.05,
        "colorbalance": "rs=0.02:gs=0.01:bs=0.03",
        "unsharp": "5:5:1.2:5:5:0.0",
        "vignette": "0",
    },
    "anime_hdr_vibrant": {
        "contrast": 1.15,
        "brightness": 0.04,
        "saturation": 1.35,
        "gamma": 1.05,
        "colorbalance": "rs=0.02:gs=0.01:bs=0.03",
        "unsharp": "5:5:1.2:5:5:0.0",
        "vignette": "0",
    }
}


def get_segment_velocity_profile(
    seg: Dict[str, Any],
    seg_idx: int,
    total_segs: int,
    enable_velocity_ramping: bool = True
) -> Dict[str, Any]:
    """
    Determines the visual profile for a clip segment.
    If enable_velocity_ramping=False: uses straight cuts (speed=1.0).
    If enable_velocity_ramping=True (default modern AMV):
    - Intro (0-4.5s): Cinematic slow-mo hold (0.85x) with black bars.
    - Beat Drop (~4.8s): Explosive speed snap (1.30x) with impact zoom punch and flash.
    - Combat exchanges: Alternating velocity dynamics (1.25x snap clashes vs 0.85x slow-mo impact holds).
    - Climax finisher: Cinematic slow-mo weight (0.80x) into lingering resolution.
    """
    is_drop = seg.get("is_drop", False)
    duration = seg.get("duration", 1.0)

    if not is_drop:
        # Pre-fight conversation scene (>3.0s): play at natural 1.0x speed for crystal-clear spoken dialogue & lip-sync
        if duration > 3.0 or seg.get("is_conversation", False) or seg.get("role") == "conversation_dialogue":
            return {
                "role": "conversation_dialogue",
                "speed": 1.0,
                "scale_factor": 1.02,
                "add_bars": False,
                "add_flash": False,
                "use_smooth_slowmo": False
            }
        # Pre-drop transition into fight: buttery smooth slow-motion hold right before beat drop (for short cuts <= 3.0s)
        elif seg.get("next_is_drop", False) or seg.get("is_pre_drop", False) or seg.get("role") == "transition_slowmo":
            return {
                "role": "transition_slowmo",
                "speed": 0.40,
                "scale_factor": 1.05,
                "add_bars": False,
                "add_flash": False,
                "use_smooth_slowmo": True
            }
        else:
            # Default intro slow-mo for cinematic weight & narrative buildup
            return {
                "role": "intro_slowmo",
                "speed": 0.85,
                "scale_factor": 1.02,
                "add_bars": False,
                "add_flash": False,
                "use_smooth_slowmo": True
            }

    if not enable_velocity_ramping:
        return {
            "role": "straight_cut",
            "speed": 1.0,
            "scale_factor": 1.0,
            "add_bars": False,
            "add_flash": False
        }

    if seg_idx == total_segs - 1:
        # Final Outro — held climax finisher, dramatic weight
        return {
            "role": "climax_outro",
            "speed": 0.80,
            "scale_factor": 1.03,
            "add_bars": False,
            "add_flash": False,
            "use_smooth_slowmo": True
        }

    # First drop segment: Explosive impact matching benchmark favorites
    if seg.get("is_first_drop", False) or (is_drop and (seg_idx == 0 or seg.get("prev_is_drop") is False)):
        return {
            "role": "drop_impact",
            "speed": 1.30,
            "scale_factor": 1.35,  # Explosive punch zoom in on beat drop
            "add_bars": False,
            "add_flash": True,
            "use_bezier_velocity": True
        }

    # If this segment is a repeat of a previous clip, apply dynamic punch zoom in / zoom out matching reference FtImSrL2DOg
    if seg.get("is_repeat", False):
        repeat_idx = seg.get("repeat_count", 1)
        repeat_scale = 1.40 if repeat_idx % 2 == 1 else 1.10
        return {
            "role": "repeat_zoom_punch",
            "speed": 1.25,
            "scale_factor": repeat_scale,
            "add_bars": False,
            "add_flash": False,
            "use_bezier_velocity": True
        }

    # Alternating combat dynamics matching reference FtImSrL2DOg (Zoom-in punch vs Zoom-out reveal)
    if seg_idx % 2 == 0:
        return {
            "role": "combat_zoom_in",
            "speed": 1.25,
            "scale_factor": 1.32,  # Punch Zoom-in on action strike
            "add_bars": False,
            "add_flash": False,
            "use_bezier_velocity": True
        }
    else:
        return {
            "role": "combat_zoom_out",
            "speed": 0.85,
            "scale_factor": 1.05,  # Zoom-out reveal for full choreography
            "add_bars": False,
            "add_flash": False,
            "use_bezier_velocity": True,
            "use_smooth_slowmo": True
        }


def build_bezier_velocity_pts_expression(
    duration: float,
    fast_speed: float = 2.2,
    slow_speed: float = 0.40
) -> str:
    """
    Constructs a 3-phase velocity curve PTS remapping expression for FFmpeg setpts.
    Phase 1 (0 to 25% duration): Fast snap-in (2.2x speed) rushing into the action.
    Phase 2 (25% to 65% duration): Cinematic slow-motion hold (0.40x speed) savouring the impact.
    Phase 3 (65% to 100% duration): Acceleration snap-out (2.0x speed) into the next scene cut.
    Normalized so output duration matches exact segment duration.
    """
    t1 = round(duration * 0.25, 3)
    t2 = round(duration * 0.65, 3)

    m1 = 1.0 / max(0.1, fast_speed)
    m2 = 1.0 / max(0.1, slow_speed)
    m3 = 1.0 / max(0.1, fast_speed * 0.9)

    out1 = t1 * m1
    out2 = out1 + (t2 - t1) * m2
    out_end = out2 + (duration - t2) * m3

    # Normalization factor
    k = duration / max(0.001, out_end)
    m1_norm = m1 * k
    m2_norm = m2 * k
    m3_norm = m3 * k
    o1_norm = out1 * k
    o2_norm = out2 * k

    expr = (
        f"(if(lt(T\\,{t1:.3f})\\,{m1_norm:.4f}*T\\,"
        f"if(lt(T\\,{t2:.3f})\\,{o1_norm:.4f}+{m2_norm:.4f}*(T-{t1:.3f})\\,"
        f"{o2_norm:.4f}+{m3_norm:.4f}*(T-{t2:.3f}))))/TB"
    )
    return expr


def build_pre_drop_audio_vacuum_filter(
    drop_time: float,
    vacuum_duration: float = 0.16,
    riser_duration: float = 0.55
) -> str:
    """
    Generates an audio filter chain creating the signature AMV pre-drop vacuum:
    1. Low-cut riser (drop_time - 0.71s to drop_time - 0.16s): highpass at 1200Hz thins out bass.
    2. Dead-silence vacuum (drop_time - 0.16s to drop_time): volume = 0.0 for 160ms.
    3. Drop impact explosion (drop_time to drop_time + 1.4s): volume = 1.35x with +4dB sub-bass boost (65Hz).
    """
    vac_start = max(0.1, drop_time - vacuum_duration)
    vac_end = drop_time
    riser_start = max(0.05, vac_start - riser_duration)
    intro_end = riser_start
    impact_end = drop_time + 1.40

    filters = [
        # 1. Pre-fight conversation ducking & lowpass: phonk acts as a moody sub-bass drone under dialogue
        f"volume=enable='between(t\\,0\\,{intro_end:.3f})':volume=0.20",
        f"lowpass=f=380:enable='between(t\\,0\\,{intro_end:.3f})'",
        # 2. Pre-drop riser & vacuum: sweep into dead silence
        f"highpass=f=1200:enable='between(t\\,{riser_start:.3f}\\,{vac_start:.3f})'",
        f"volume=enable='between(t\\,{vac_start:.3f}\\,{vac_end:.3f})':volume=0.0",
        # 3. Explosive Beat Drop impact
        f"volume=enable='between(t\\,{drop_time:.3f}\\,{impact_end:.3f})':volume=1.35",
        f"bass=g=4:f=65:enable='gte(t\\,{drop_time:.3f})'",
        f"treble=g=2.5:f=4500:enable='between(t\\,{drop_time:.3f}\\,{drop_time+0.80:.3f})'"
    ]
    return ",".join(filters)


def build_combat_foley_audio_filter(
    combat_cut_times: List[float],
    drop_time: float,
    boost_window: float = 0.20
) -> str:
    """
    Constructs dynamic transient shaping for anime combat Foley sound design:
    1. Vocal Dialogue Clarity (0.0s to drop_time - 0.55s):
       Boosts dialogue volume to 1.60 with highpass at 80Hz and speech treble lift for crisp monologue intelligibility.
    2. Katana / Combat Clash Transients (on peak combat cut onsets):
       - High-treble presence boost (4800Hz, +3.5dB) to make blade clashes and sparks slice through.
       - Mid-bass impact boost (85Hz, +3.0dB) for kinetic weight on technique strikes.
       - Dynamic volume lift (1.5x) during the first 200ms of each combat cut.
    """
    filters = []

    # 1. Dialogue clarity during pre-fight conversation: loud, rich, and crisp voices
    intro_end = max(0.1, drop_time - 0.55)
    filters.append(f"volume=enable='between(t\\,0\\,{intro_end:.3f})':volume=1.60")
    filters.append(f"highpass=f=80:enable='between(t\\,0\\,{intro_end:.3f})'")
    filters.append(f"treble=g=2.5:f=3200:enable='between(t\\,0\\,{intro_end:.3f})'")

    # 2. Combat Foley boosts on cut timestamps after drop
    valid_cuts = [t for t in combat_cut_times if t >= drop_time - 0.10]
    if len(valid_cuts) > 8:
        step = max(1, len(valid_cuts) // 8)
        valid_cuts = valid_cuts[::step][:8]

    for t in valid_cuts:
        t_end = t + boost_window
        cond = f"between(t\\,{t:.3f}\\,{t_end:.3f})"
        filters.append(f"volume=enable='{cond}':volume=1.50")
        filters.append(f"treble=g=3.5:f=4800:enable='{cond}'")
        filters.append(f"bass=g=3.0:f=85:enable='{cond}'")

    return ",".join(filters) if filters else "anull"


def build_velocity_clip_filter(
    seg_idx: int,
    duration: float,
    speed: float = 1.0,
    scale_factor: float = 1.0,
    video_width: int = VIDEO_WIDTH,
    video_height: int = VIDEO_HEIGHT,
    fps: int = FPS,
    add_bars: bool = False,
    is_intro_hook: bool = False,
    use_bezier_velocity: bool = False,
    use_smooth_slowmo: bool = False,
    clip_path: Optional[Union[str, Path]] = None,
    enable_motion_tracking: bool = True,
    camera_motion: str = "auto",
    narrative_role: Optional[str] = None,
    input_tag: str = "",
    output_tag: str = ""
) -> str:
    """
    Builds the per-clip video filter chain with Adaptive Dual-Layer Framing & Motion Tracking:
    - Solo Portraits / Character Close-ups: Full-bleed 9:16 OpenCV motion-tracked portrait crop
      (keeps eyes in golden upper-third, dynamic pan-and-scan following character).
    - Combat Duels (2+ fighters): Dual-Layer Ambient Background with uncropped 16:9 foreground,
      preserving 100% of both combatants, martial arts strikes, and choreography.
    - Wide Action (Domain expansions, explosions, landscapes): Dual-Layer Ambient Background with
      centered 4:3 card, preserving 80%+ of the action window.
    - Non-linear Bézier 3-phase velocity curves (fast snap-in -> slow-motion hold -> fast snap-out).
    - Zero black bars (100% filled with color-graded anime ambiance).
    """
    from motion_tracker import (
        build_precise_motion_tracking_filter,
        extract_motion_trajectory
    )

    trajectory_info = None
    shot_composition = "solo_portrait"
    if enable_motion_tracking and clip_path is not None:
        try:
            trajectory_info = extract_motion_trajectory(clip_path, duration=duration)
            shot_composition = trajectory_info.get("shot_composition", "solo_portrait")
        except Exception as e:
            print(f"⚠️ [EffectsEngine] Notice extracting composition: {e}")
            shot_composition = "solo_portrait"

    # Common speed remapping, duration trim, FPS, and SAR filters
    post_filters = []
    if use_bezier_velocity and duration >= 0.40 and not is_intro_hook:
        bezier_pts = build_bezier_velocity_pts_expression(duration=duration, fast_speed=2.2, slow_speed=0.40)
        post_filters.append(f"setpts='{bezier_pts}'")
        # Silky smooth motion frame blending during the slow-mo hold of the bezier curve
        post_filters.append("minterpolate=fps=60:mi_mode=blend")
    elif speed > 1.05:
        pts_mult = 1.0 / speed
        post_filters.append(f"setpts={pts_mult:.4f}*PTS")
    elif speed < 0.95:
        pts_mult = 1.0 / max(0.2, speed)
        post_filters.append(f"setpts={pts_mult:.4f}*PTS")
        if use_smooth_slowmo or speed <= 0.65:
            post_filters.append("minterpolate=fps=60:mi_mode=blend")

    post_filters.extend([
        "tpad=stop_mode=clone:stop_duration=5",
        f"trim=duration={duration:.3f}",
        "setpts=PTS-STARTPTS",
        f"fps={fps}",
        "setsar=1"
    ])

    if add_bars:
        bar_h = max(60, int(video_height * 0.125))
        post_filters.append(f"drawbox=x=0:y=0:w=iw:h={bar_h}:color=black:t=fill")
        post_filters.append(f"drawbox=x=0:y=ih-{bar_h}:w=iw:h={bar_h}:color=black:t=fill")

    post_str = ",".join(post_filters)

    # Adaptive Dual-Layer Framing vs Full-Bleed 9:16 Portrait (0 Black Bars, Crystal Clear Foreground)
    if input_tag and output_tag:
        bg_raw = f"bg_raw_{seg_idx}"
        fg_raw = f"fg_raw_{seg_idx}"
        bg_out = f"bg_{seg_idx}"
        fg_out = f"fg_{seg_idx}"
        comp_out = f"comp_{seg_idx}"

        # Ambient bokeh background (fills video canvas with blurred, color-matched motion)
        bg_filter = (
            f"scale=360:640:force_original_aspect_ratio=increase,crop=360:640,"
            f"boxblur=16:3,scale={video_width}:{video_height}:flags=fast_bilinear,"
            f"eq=brightness=0.02:contrast=1.05,setsar=1"
        )

        eff_scale = max(1.0, scale_factor)
        if shot_composition == "combat_duel":
            # 100% uncropped 16:9 widescreen action window so BOTH combatants are completely visible
            if eff_scale > 1.05:
                scaled_w = int(round(video_width * eff_scale / 2) * 2)
                fg_filter = (
                    f"scale={scaled_w}:-2:flags=lanczos+accurate_rnd,"
                    f"crop={video_width}:ih/(iw/{video_width}):(in_w-{video_width})/2:(in_h-out_h)/2,"
                    f"cas=0.55,unsharp=5:5:1.2:5:5:0.0,"
                    f"drawbox=x=0:y=0:w=iw:h=ih:color=white@0.35:t=2,setsar=1"
                )
            else:
                fg_filter = (
                    f"scale={video_width}:-2:flags=lanczos+accurate_rnd,cas=0.55,unsharp=5:5:1.2:5:5:0.0,"
                    f"drawbox=x=0:y=0:w=iw:h=ih:color=white@0.35:t=2,setsar=1"
                )
            y_pos = f"({video_height}-h)/2"
        elif shot_composition == "wide_action":
            # 4:3 action window for wide action, domain expansions, and magic bursts
            fg_h = int(round(video_width * 3 / 4 / 2) * 2)
            scaled_w = int(round(video_width * eff_scale / 2) * 2)
            scaled_h = int(round(fg_h * eff_scale / 2) * 2)
            fg_filter = (
                f"scale={scaled_w}:{scaled_h}:force_original_aspect_ratio=increase,"
                f"crop={video_width}:{fg_h}:(in_w-{video_width})/2:(in_h-{fg_h})/2,"
                f"cas=0.55,unsharp=5:5:1.2:5:5:0.0,"
                f"drawbox=x=0:y=0:w=iw:h=ih:color=white@0.35:t=2,setsar=1"
            )
            y_pos = f"({video_height}-{fg_h})/2"
        else:
            # Solo Portrait / Focus: High-retention 4:5 tall character action frame with dynamic punch zoom
            fg_h = int(round(video_width * 5 / 4 / 2) * 2)
            scaled_w = int(round(video_width * eff_scale / 2) * 2)
            scaled_h = int(round(fg_h * eff_scale / 2) * 2)
            fg_filter = (
                f"scale={scaled_w}:{scaled_h}:force_original_aspect_ratio=increase,"
                f"crop={video_width}:{fg_h}:(in_w-{video_width})/2:(in_h-{fg_h})/2,"
                f"cas=0.55,unsharp=5:5:1.2:5:5:0.0,"
                f"drawbox=x=0:y=0:w=iw:h=ih:color=white@0.35:t=2,setsar=1"
            )
            y_pos = f"({video_height}-{fg_h})/2"

        split_step = f"{input_tag}split=2[{bg_raw}][{fg_raw}]"
        bg_step = f"[{bg_raw}]{bg_filter}[{bg_out}]"
        fg_step = f"[{fg_raw}]{fg_filter}[{fg_out}]"
        comp_step = f"[{bg_out}][{fg_out}]overlay=x=0:y={y_pos}:eval=init,setsar=1[{comp_out}]"
        final_step = f"[{comp_out}]{post_str}{output_tag}"

        return f"{split_step};{bg_step};{fg_step};{comp_step};{final_step}"

    # Default / Solo Portrait: High-precision subject-locked 9:16 portrait crop
    tracking_filter = build_precise_motion_tracking_filter(
        clip_path=clip_path,
        duration=duration,
        video_width=video_width,
        video_height=video_height,
        trajectory_info=trajectory_info,
        camera_motion=camera_motion,
        narrative_role=narrative_role
    )

    if input_tag and output_tag:
        return f"{input_tag}{tracking_filter},{post_str}{output_tag}"
    return f"{tracking_filter},{post_str}"


def build_vertical_dual_layer_chain(
    input_tag: str,
    output_tag: str,
    seg_idx: int,
    duration: float,
    speed: float = 1.0,
    scale_factor: float = 1.0,
    video_width: int = VIDEO_WIDTH,
    video_height: int = VIDEO_HEIGHT,
    fg_height: int = 1350,
    y_offset: int = 285,
    fps: int = FPS,
    is_intro_hook: bool = False
) -> str:
    """
    Builds the complete 2026 9:16 Vertical Layout (Blurred Synced Background + 4:5 Foreground):
    1. Edge Watermark Crop: Crops 6% off all four edges (strips TV logos & studio credits).
    2. Background Layer (1080x1920): Scales/crops to fill canvas, heavy Gaussian blur (boxblur=28:5),
       brightness scaled by 0.45.
    3. Foreground Layer (1080x1350, 4:5): Center-crop to 4:5 tall frame, subtle 4px white border.
    4. Overlays foreground onto background at y=285 (0% black bars).
    5. Applies velocity speed remapping and exponential zoom punch.
    """
    bg_raw = f"bg_raw_{seg_idx}"
    fg_raw = f"fg_raw_{seg_idx}"
    bg_out = f"bg_{seg_idx}"
    fg_out = f"fg_{seg_idx}"
    comp_out = f"comp_{seg_idx}"

    # 1. 6% Edge Crop & split into background and foreground
    crop_split = (
        f"{input_tag}crop=in_w*0.88:in_h*0.88:in_w*0.06:in_h*0.06,split=2[{bg_raw}][{fg_raw}]"
    )

    # 2. Ambient Blurred Background (1080x1920)
    bg_chain = (
        f"[{bg_raw}]scale={video_width}:{video_height}:force_original_aspect_ratio=increase,"
        f"crop={video_width}:{video_height},boxblur=28:5,"
        f"colorchannelmixer=aa=1.0:rr=0.45:gg=0.45:bb=0.45,setsar=1[{bg_out}]"
    )

    # 3. 4:5 Foreground Frame (1080x1350) with 4px border
    fg_chain = (
        f"[{fg_raw}]scale={video_width}:{fg_height}:force_original_aspect_ratio=increase,"
        f"crop={video_width}:{fg_height},"
        f"drawbox=x=0:y=0:w={video_width}:h={fg_height}:color=white@0.65:t=4,setsar=1[{fg_out}]"
    )

    # 4. Composite Overlay
    composite = f"[{bg_out}][{fg_out}]overlay=x=0:y={y_offset},setsar=1,fps={fps}[{comp_out}]"

    # 5. Speed remapping, zoom punch, trim
    post_filters = []
    if speed > 1.05:
        pts_mult = 1.0 / speed
        post_filters.append(f"setpts={pts_mult:.4f}*PTS")
    elif speed < 0.95:
        pts_mult = 1.0 / max(0.2, speed)
        post_filters.append(f"setpts={pts_mult:.4f}*PTS")

    post_filters.extend([
        f"trim=duration={duration:.3f}",
        "setpts=PTS-STARTPTS"
    ])
    post_str = ",".join(post_filters)
    final_chain = f"[{comp_out}]{post_str}{output_tag}"

    return f"{crop_split};{bg_chain};{fg_chain};{composite};{final_chain}"


def build_cc_filter(preset_name: str = "vibrant_anime_glow", is_dark_scene: bool = False) -> str:
    """
    Builds clean HDR-style Anime Glow Color Grading with Contrast Adaptive Sharpening (CAS):
    1. Auto-Exposure Lift: If scene is dark, applies gamma=1.35 and brightness=0.14.
    2. S-curve contrast (1.15x) and high-vibrance saturation boost (1.65x).
    3. AMD CAS (Contrast Adaptive Sharpening) + unsharp mask for crystal clear anime line art.
    4. Eliminates dark-red vignette that crushes shadows.
    """
    cfg = CC_PRESETS.get(preset_name, CC_PRESETS.get("vibrant_anime_glow", CC_PRESETS.get("flame_hashira")))
    contrast = cfg.get("contrast", 1.15)
    saturation = cfg.get("saturation", 1.65)
    brightness = cfg.get("brightness", 0.12)
    gamma = cfg.get("gamma", 1.32)

    if is_dark_scene:
        gamma = max(1.35, gamma)
        brightness = max(0.14, brightness)

    eq_part = f"eq=contrast={contrast}:brightness={brightness}:saturation={saturation}:gamma={gamma}"
    unsharp_part = f"unsharp={cfg.get('unsharp', '5:5:1.4:5:5:0.0')}"
    cas_part = "cas=0.55"

    parts = [eq_part]
    if cfg.get("colorbalance"):
        parts.append(f"colorbalance={cfg['colorbalance']}")

    parts.extend([cas_part, unsharp_part])
    vig = cfg.get("vignette", "0")
    if vig and vig != "0":
        parts.append(f"vignette={vig}")

    return ",".join(parts)


def build_selective_bloom_filter(input_tag: str, output_tag: str, threshold: int = 185, opacity: float = 0.30) -> str:
    """
    Hierarchical Multi-Radius Selective Neon Bloom / Element Glow:
    1. Thresholds bright combat sakuga (luma > threshold, e.g. Hinokami fire, lightning).
    2. Inner neon core: boxblur=4:2 for intense edge sharpness on sword blades and eyes.
    3. Outer atmospheric aura: boxblur=20:3 for smooth ambient light dispersion.
    4. Blends inner + outer additively, then overlays onto base video without washing out dark shadows.
    """
    base_tag = "bloom_base"
    hi_tag = "bloom_hi"
    inner_raw = "glow_in_raw"
    outer_raw = "glow_out_raw"
    inner_glow = "glow_inner"
    outer_glow = "glow_outer"
    tot_glow = "glow_tot"

    return (
        f"{input_tag}split=2[{base_tag}][{hi_tag}];"
        f"[{hi_tag}]lutyuv=y='if(gt(val,{threshold}),val,0)',split=2[{inner_raw}][{outer_raw}];"
        f"[{inner_raw}]boxblur=4:2[{inner_glow}];"
        f"[{outer_raw}]boxblur=20:3[{outer_glow}];"
        f"[{inner_glow}][outer_glow]blend=all_mode=addition[{tot_glow}];"
        f"[{base_tag}][{tot_glow}]blend=all_mode=addition:all_opacity={opacity:.2f}{output_tag}"
    )


def build_heavy_drop_impact_filters(
    heavy_drop_times: List[float],
    duration: float = 0.033,  # 2 frames at 60fps
    flash_opacity: float = 0.25,
    chroma_shift_px: int = 0
) -> List[str]:
    """
    Signature 2026 Beat Drop Impact Flash:
    On the top 30% loudest bass hits:
    - 2-frame 25% white exposure flash (clean, zero nearest-neighbor pixelation, zero 3D-glasses blur)
    """
    if not heavy_drop_times:
        return []

    filters = []
    for t in heavy_drop_times:
        t_end = t + duration
        cond = f"between(t\\,{t:.3f}\\,{t_end:.3f})"
        filters.append(
            f"drawbox=x=0:y=0:w=iw:h=ih:color=white@{flash_opacity}:t=fill:enable='{cond}'"
        )
    return filters


def build_monochrome_cc_filter(preset_name: str = "mono_bw") -> str:
    """
    Builds extreme monochromatic treatments matching the reference's 3 modes:
    - 'mono_blue': Cold blue desaturation (character moments)
    - 'mono_white': High-key washed-out pale (dreamlike transitions)
    - 'mono_bw': High-contrast B&W (manga-panel power moments)

    Each mode uses the full CC_PRESETS config for that monochrome variant.
    """
    cfg = CC_PRESETS.get(preset_name, CC_PRESETS["mono_bw"])

    eq_part = f"eq=contrast={cfg['contrast']}:brightness={cfg['brightness']}:saturation={cfg['saturation']}:gamma={cfg['gamma']}"
    levels_part = "colorlevels=rimin=0.05:gimin=0.05:bimin=0.05:rimax=0.96:gimax=0.96:bimax=0.96"
    unsharp_part = f"unsharp={cfg['unsharp']}"
    vignette_part = f"vignette={cfg['vignette']}"
    grain_part = "noise=c0s=14:allf=t+u"

    parts = [eq_part, levels_part]
    if cfg.get("colorbalance"):
        parts.append(f"colorbalance={cfg['colorbalance']}")
    parts.extend([unsharp_part, vignette_part, grain_part])
    return ",".join(parts)


def build_beat_flash_filters(beat_timestamps: List[float], flash_duration: float = 0.12, opacity: float = 0.70) -> List[str]:
    """
    Builds white flash overlays — ONLY at the 2-3 biggest drop moments.
    Reference edit has 2-3 total flashes across the entire video.
    Uses the FIRST and LAST few beat timestamps as the major energy peaks.
    """
    if not beat_timestamps:
        return []

    flash_filters = []
    # Pick only2-3 timestamps: the first drop moment, one mid-point, one near the end
    n = len(beat_timestamps)
    if n <= 3:
        flash_times = beat_timestamps
    else:
        flash_times = [
            beat_timestamps[0],                    # First drop hit
            beat_timestamps[n // 2],               # Mid-energy peak
            beat_timestamps[min(n - 2, n * 3 // 4)]  # Late climax
        ]

    for t in flash_times:
        cond = f"between(t,{t:.2f},{t + flash_duration:.2f})"
        flash_filters.append(
            f"drawbox=x=0:y=0:w=iw:h=ih:color=white@{opacity}:t=fill:enable='{cond}'"
        )
    return flash_filters

