"""
Precise Motion Tracking & Intelligent Subject Reframing Engine for Anime Shorts.

Tracks anime characters, faces, duels, and combat velocity across dense frame samples,
computing smooth ease-in/ease-out camera trajectories that keep characters perfectly framed
in 1080x1920 (9:16 portrait) with zero black bars.
"""
import os
import subprocess
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union
import numpy as np

try:
    import cv2
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
BASE_DIR = Path(__file__).resolve().parent.parent

MODELS_DIR = BASE_DIR / "assets" / "models"
_CACHED_CASCADES: Optional[List[Any]] = None


def get_cascades() -> List[Any]:
    """Loads and caches face cascades (anime face cascade + human frontal face cascade)."""
    global _CACHED_CASCADES
    if _CACHED_CASCADES is not None:
        return _CACHED_CASCADES

    cascades = []
    if not OPENCV_AVAILABLE or not hasattr(cv2, "CascadeClassifier"):
        _CACHED_CASCADES = cascades
        return cascades

    # 1. Anime face cascade (specifically trained for anime character eyes & facial structures)
    anime_xml = MODELS_DIR / "lbpcascade_animeface.xml"
    if anime_xml.exists():
        try:
            c = cv2.CascadeClassifier(str(anime_xml))
            if not c.empty():
                cascades.append(("anime", c))
        except Exception as e:
            print(f"⚠️ Notice loading anime face cascade: {e}")

    # 2. General frontal face cascade
    frontal_xml = MODELS_DIR / "haarcascade_frontalface_default.xml"
    if frontal_xml.exists():
        try:
            c = cv2.CascadeClassifier(str(frontal_xml))
            if not c.empty():
                cascades.append(("frontal", c))
        except Exception as e:
            print(f"⚠️ Notice loading frontal face cascade: {e}")

    _CACHED_CASCADES = cascades
    return cascades


def detect_active_content_bounds(frame: np.ndarray, threshold: float = 12.0) -> Tuple[int, int, int, int]:
    """
    Detects the true active content area in a frame, stripping baked-in letterbox black bars.
    Returns (left, top, width, height) with even dimensions.
    """
    if frame is None or frame.size == 0:
        return (0, 0, 1920, 1080)

    orig_h, orig_w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame

    row_means = np.mean(gray, axis=1)
    col_means = np.mean(gray, axis=0)

    valid_rows = np.where(row_means > threshold)[0]
    valid_cols = np.where(col_means > threshold)[0]

    if len(valid_rows) > 0 and len(valid_cols) > 0:
        top = int(valid_rows[0])
        bot = int(valid_rows[-1])
        left = int(valid_cols[0])
        right = int(valid_cols[-1])
        w = max(2, ((right - left + 1) // 2) * 2)
        h = max(2, ((bot - top + 1) // 2) * 2)
        return (left, top, w, h)

    return (0, 0, orig_w, orig_h)


def detect_subject_focal_point(frame: np.ndarray, return_details: bool = False) -> Union[Tuple[float, float, float], Tuple[float, float, float, int, float]]:
    """
    Detects the primary subject's normalized center coordinates (cx, cy) and confidence.
    If return_details=True, returns (cx_norm, cy_norm, confidence, num_faces, max_face_ratio).
    Otherwise returns (cx_norm, cy_norm, confidence) for backward compatibility.
    """
    if not OPENCV_AVAILABLE or frame is None or frame.size == 0:
        return (0.5, 0.5, 0.0, 0, 0.0) if return_details else (0.5, 0.5, 0.0)

    orig_h, orig_w = frame.shape[:2]
    if orig_h == 0 or orig_w == 0:
        return (0.5, 0.5, 0.0, 0, 0.0) if return_details else (0.5, 0.5, 0.0)

    # Downscale for high-speed detection (max width 640)
    scale = 1.0
    if orig_w > 640:
        scale = 640.0 / orig_w
        proc_w = 640
        proc_h = int(round(orig_h * scale))
        proc_frame = cv2.resize(frame, (proc_w, proc_h), interpolation=cv2.INTER_LINEAR)
    else:
        proc_w = orig_w
        proc_h = orig_h
        proc_frame = frame

    gray = cv2.cvtColor(proc_frame, cv2.COLOR_BGR2GRAY)
    gray_eq = cv2.equalizeHist(gray)

    # 1. Face / Character Detection (High sensitivity)
    cascades = get_cascades()
    detected_faces = []
    for c_type, cascade in cascades:
        img_input = gray_eq if c_type == "anime" else gray
        min_sz = (int(24 * scale), int(24 * scale))
        try:
            faces = cascade.detectMultiScale(img_input, scaleFactor=1.08, minNeighbors=2, minSize=min_sz)
            if len(faces) > 0:
                for (fx, fy, fw, fh) in faces:
                    area = fw * fh
                    detected_faces.append((area, fx, fy, fw, fh, 1.0 if c_type == "anime" else 0.85))
        except Exception:
            pass

    if detected_faces:
        detected_faces.sort(key=lambda item: item[0], reverse=True)
        num_faces = len(detected_faces)
        max_face_area = detected_faces[0][0]
        max_face_ratio = float(max_face_area) / float(proc_w * proc_h)

        # Check if top 2 faces are a two-character clash / conversation
        if len(detected_faces) >= 2:
            f1, f2 = detected_faces[0], detected_faces[1]
            cx1 = (f1[1] + f1[3] / 2.0) / float(proc_w)
            cx2 = (f2[1] + f2[3] / 2.0) / float(proc_w)
            # If both faces are prominent (second face >= 30% area of first face)
            # and within 9:16 portrait framing width (< 0.36 of frame width)
            if f2[0] >= f1[0] * 0.30 and abs(cx1 - cx2) < 0.36:
                cx_mid = (cx1 + cx2) / 2.0
                cy1 = (f1[2] + f1[4] / 2.0) / float(proc_h)
                cy2 = (f2[2] + f2[4] / 2.0) / float(proc_h)
                cy_mid = (cy1 + cy2) / 2.0
                ret_cx = float(np.clip(cx_mid, 0.0, 1.0))
                ret_cy = float(np.clip(cy_mid, 0.0, 1.0))
                return (ret_cx, ret_cy, 1.0, num_faces, max_face_ratio) if return_details else (ret_cx, ret_cy, 1.0)

        # Pick the most prominent / largest face
        _, fx, fy, fw, fh, conf = detected_faces[0]
        cx_norm = (fx + fw / 2.0) / float(proc_w)
        cy_norm = (fy + fh / 2.0) / float(proc_h)
        ret_cx = float(np.clip(cx_norm, 0.0, 1.0))
        ret_cy = float(np.clip(cy_norm, 0.0, 1.0))
        return (ret_cx, ret_cy, conf, num_faces, max_face_ratio) if return_details else (ret_cx, ret_cy, conf)

    # 2. Multi-Modal Anime Character Saliency (Skin Tone + Saturation + High-contrast line art)
    try:
        small_w = 320
        small_h = int(round(orig_h * (320.0 / orig_w)))
        small = cv2.resize(proc_frame, (small_w, small_h), interpolation=cv2.INTER_AREA)
        small_gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        small_hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)

        # Skin tone mask (YCrCb + HSV) - reliably flags anime characters
        ycrcb = cv2.cvtColor(small, cv2.COLOR_BGR2YCrCb)
        skin_ycrcb = cv2.inRange(ycrcb, np.array([0, 133, 77]), np.array([255, 173, 127]))
        skin_hsv = cv2.inRange(small_hsv, np.array([0, 25, 50]), np.array([25, 185, 255]))
        skin_mask = cv2.bitwise_and(skin_ycrcb, skin_hsv)
        skin_px = np.count_nonzero(skin_mask)

        # High-contrast line art / edges
        lap = np.abs(cv2.Laplacian(small_gray, cv2.CV_32F))
        edges = cv2.normalize(lap, None, 0, 1, cv2.NORM_MINMAX)

        # Vivid anime color saturation
        sat = small_hsv[:, :, 1].astype(np.float32) / 255.0
        skin_weight = (skin_mask.astype(np.float32) / 255.0) * 3.5

        combined = edges * 0.40 + sat * 0.70 + skin_weight

        # Dampen outer 4% to ignore letterbox borders
        margin = int(small_w * 0.04)
        guard = np.ones((small_h, small_w), dtype=np.float32)
        if margin > 0:
            guard[:, :margin] = np.linspace(0.2, 1.0, margin)
            guard[:, -margin:] = np.linspace(1.0, 0.2, margin)

        energy_map = combined * guard
        total_energy = np.sum(energy_map)

        if total_energy > 1e-4:
            col_weights = np.sum(energy_map, axis=0)
            row_weights = np.sum(energy_map, axis=1)

            cx = np.sum(np.arange(small_w) * col_weights) / (total_energy)
            cy = np.sum(np.arange(small_h) * row_weights) / (total_energy)

            cx_norm = cx / float(small_w)
            cy_norm = cy / float(small_h)
            conf = 0.85 if skin_px > 80 else 0.65
            ret_cx = float(np.clip(cx_norm, 0.0, 1.0))
            ret_cy = float(np.clip(cy_norm, 0.0, 1.0))
            return (ret_cx, ret_cy, conf, 0, 0.0) if return_details else (ret_cx, ret_cy, conf)
    except Exception:
        pass

    # Safe center fallback
    return (0.5, 0.5, 0.0, 0, 0.0) if return_details else (0.5, 0.5, 0.0)


def extract_motion_trajectory(
    clip_path: Union[str, Path],
    duration: float = 1.0,
    samples_per_sec: int = 8,
    start_time: float = 0.0,
) -> Dict[str, Any]:
    """
    Extracts a dense motion trajectory across a video clip.
    Returns:
      in_w, in_h, act_x, act_y, act_w, act_h,
      cx_start, cx_end, cy_start, cy_end,
      trajectory: List of (t, cx, cy),
      is_dynamic: bool
    """
    clip_p = Path(clip_path)
    default_res = {
        "in_w": 1920, "in_h": 1080,
        "act_x": 0, "act_y": 0, "act_w": 1920, "act_h": 1080,
        "cx_start": 0.5, "cx_end": 0.5,
        "cy_start": 0.5, "cy_end": 0.5,
        "trajectory": [(0.0, 0.5, 0.5), (duration, 0.5, 0.5)],
        "is_dynamic": False,
        "shot_composition": "solo_portrait",
        "max_faces": 1,
        "peak_face_ratio": 0.10
    }
    if not clip_p.exists() or not OPENCV_AVAILABLE:
        return default_res

    try:
        cap = cv2.VideoCapture(str(clip_p))
        if not cap.isOpened():
            return default_res

        in_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        in_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        video_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0

        if total_frames <= 0 or in_w <= 0 or in_h <= 0:
            cap.release()
            return default_res

        # Determine sample frames (at least 6 samples, max 24 samples)
        effective_duration = duration if duration > 0.1 else (total_frames / video_fps)
        num_samples = int(np.clip(int(round(effective_duration * samples_per_sec)), 6, 24))
        if start_time > 0.0:
            start_frame = int(round(start_time * video_fps))
            slice_frames = int(round(effective_duration * video_fps))
            frame_indices = [
                min(total_frames - 1, int(round(start_frame + (slice_frames * (i + 0.5) / num_samples))))
                for i in range(num_samples)
            ]
        else:
            frame_indices = [
                int(round(total_frames * (i + 0.5) / num_samples))
                for i in range(num_samples)
            ]

        act_x, act_y, act_w, act_h = 0, 0, in_w, in_h
        raw_points = []
        prev_gray = None
        max_faces_seen = 0
        peak_face_ratio = 0.0

        for idx, frame_idx in enumerate(frame_indices):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue

            t_val = (frame_idx / float(total_frames)) * effective_duration

            # Detect active content boundaries on middle frame
            if idx == len(frame_indices) // 2 or act_w <= 0:
                act_x, act_y, act_w, act_h = detect_active_content_bounds(frame)

            # Focus detection inside active area
            if act_w > 0 and act_h > 0 and (act_w < in_w or act_h < in_h):
                sub_frame = frame[act_y:act_y + act_h, act_x:act_x + act_w]
            else:
                sub_frame = frame

            focal_res = detect_subject_focal_point(sub_frame, return_details=True)
            cx, cy, conf = focal_res[0], focal_res[1], focal_res[2]
            n_faces = focal_res[3]
            f_ratio = focal_res[4]

            max_faces_seen = max(max_faces_seen, n_faces)
            peak_face_ratio = max(peak_face_ratio, f_ratio)

            # Optical flow & frame differencing for combat action tracking
            gray_curr = cv2.cvtColor(sub_frame, cv2.COLOR_BGR2GRAY)
            if prev_gray is not None and prev_gray.shape == gray_curr.shape:
                diff = cv2.absdiff(prev_gray, gray_curr)
                diff_mean = np.mean(diff)
                if diff_mean > 7.0:
                    diff_sum = np.sum(diff, axis=0)
                    tot = np.sum(diff_sum)
                    if tot > 0:
                        cx_motion = float(np.sum(np.arange(sub_frame.shape[1]) * diff_sum) / (tot * sub_frame.shape[1]))
                        # Blend facial focal point with motion direction
                        cx = float(cx * 0.40 + cx_motion * 0.60)
            prev_gray = gray_curr
            raw_points.append((t_val, cx, cy))

        cap.release()

        if not raw_points:
            return default_res

        # Trajectory smoothing (3-point moving average with deadband)
        smoothed = []
        cx_vals = [p[1] for p in raw_points]
        cy_vals = [p[2] for p in raw_points]
        n_pts = len(raw_points)

        for i in range(n_pts):
            t_val = raw_points[i][0]
            start_k = max(0, i - 1)
            end_k = min(n_pts, i + 2)
            smooth_x = float(np.mean(cx_vals[start_k:end_k]))
            smooth_y = float(np.mean(cy_vals[start_k:end_k]))
            smoothed.append((t_val, smooth_x, smooth_y))

        # Check for dynamic tracking movement
        half = max(1, n_pts // 2)
        cx_start = float(np.mean(cx_vals[:half]))
        cx_end = float(np.mean(cx_vals[-half:]))
        cy_start = float(np.mean(cy_vals[:half]))
        cy_end = float(np.mean(cy_vals[-half:]))

        is_dynamic = abs(cx_end - cx_start) >= 0.035

        # Classify Shot Composition:
        # 1. combat_duel: 2 or more characters present in the frame
        # 2. solo_portrait: single prominent character face (close-up/medium close-up, >= 3.8% of frame)
        # 3. wide_action: wide battle choreography, domain expansion, magic explosion, scenery
        if max_faces_seen >= 2:
            shot_composition = "combat_duel"
        elif peak_face_ratio >= 0.038:
            shot_composition = "solo_portrait"
        else:
            shot_composition = "wide_action"

        return {
            "in_w": in_w, "in_h": in_h,
            "act_x": act_x, "act_y": act_y, "act_w": act_w, "act_h": act_h,
            "cx_start": cx_start, "cx_end": cx_end,
            "cy_start": cy_start, "cy_end": cy_end,
            "trajectory": smoothed,
            "is_dynamic": is_dynamic,
            "shot_composition": shot_composition,
            "max_faces": max_faces_seen,
            "peak_face_ratio": peak_face_ratio
        }
    except Exception as e:
        print(f"⚠️ [MotionTracker] Trajectory extraction notice: {e}")
        return default_res


def build_precise_motion_tracking_filter(
    clip_path: Optional[Union[str, Path]] = None,
    duration: float = 1.0,
    video_width: int = VIDEO_WIDTH,
    video_height: int = VIDEO_HEIGHT,
    trajectory_info: Optional[Dict[str, Any]] = None,
    camera_motion: str = "auto",
    narrative_role: Optional[str] = None,
    start_time: float = 0.0,
) -> str:
    """
    Builds the high-precision FFmpeg filter string for subject-locked motion tracking
    and 9:16 portrait composition.
    - Zero black bars (fills 1080x1920 canvas).
    - Locks on tracked character faces & combat centroids.
    - Adaptive vertical framing: keeps eyes in upper-third (golden ratio).
    - Smooth continuous ease-in/ease-out camera panning.
    """
    target_ar = video_width / float(video_height)  # 1080 / 1920 = 0.5625

    if trajectory_info is None and clip_path is not None:
        trajectory_info = extract_motion_trajectory(clip_path, duration=duration, start_time=start_time)

    if trajectory_info is None:
        # Fallback safe crop
        return (
            f"crop=w='min(iw,trunc(ih*9/16/2)*2)':h='min(ih,trunc(iw*16/9/2)*2)':"
            f"x='(iw-ow)/2':y='(ih-oh)/2',scale={video_width}:{video_height}:flags=lanczos,setsar=1"
        )

    act_x = trajectory_info.get("act_x", 0)
    act_y = trajectory_info.get("act_y", 0)
    act_w = trajectory_info.get("act_w", 1920)
    act_h = trajectory_info.get("act_h", 1080)
    input_ar = act_w / float(act_h)

    resolved_motion = camera_motion
    if resolved_motion == "auto":
        if narrative_role == "intro_buildup":
            resolved_motion = "push_in"
        elif narrative_role == "climax_finisher":
            resolved_motion = "push_in"
        elif narrative_role == "payoff_outro":
            resolved_motion = "pull_out"
        elif narrative_role in ("combat_strike", "combat_micro_rush"):
            resolved_motion = "punch_in"
        elif trajectory_info.get("is_dynamic"):
            resolved_motion = "pan_track"
        else:
            resolved_motion = "static_steady"

    # Focal centers
    cx = trajectory_info.get("cx_start", 0.5)
    cy = trajectory_info.get("cy_start", 0.5)
    anchor_x = int(round(act_x + cx * act_w))
    anchor_y = int(round(act_y + cy * act_h))

    # Case A: Active content is wider than 9:16 (widescreen 16:9)
    if input_ar >= target_ar:
        # Adaptive vertical tracking: when character is in lower third, adjust height to center on them
        is_vert_offcenter = abs(cy - 0.5) > 0.08
        v_scale = 0.86 if is_vert_offcenter else 1.0
        base_crop_h = int(round(act_h * v_scale / 2.0)) * 2
        base_crop_w = int(round(base_crop_h * target_ar / 2.0)) * 2
        base_crop_w = min(base_crop_w, act_w)

        max_scroll_x = max(0, act_w - base_crop_w)
        max_scroll_y = max(0, act_h - base_crop_h)

        ideal_y = act_y + (cy * act_h - (base_crop_h / 2.0))
        crop_y = int(round(np.clip(ideal_y, act_y, act_y + max_scroll_y)))

        if resolved_motion == "push_in" and duration > 0.35:
            # Subtle 1.00x -> 1.06x push-in anchored on tracked subject
            w_expr = f"({base_crop_w}*(1.0-0.06*min(t/{duration:.3f}\\,1)))"
            h_expr = f"({base_crop_h}*(1.0-0.06*min(t/{duration:.3f}\\,1)))"
            x_expr = f"clip({anchor_x}-{w_expr}/2\\,{act_x}\\,{act_x+act_w}-{w_expr})"
            y_expr = f"clip({anchor_y}-{h_expr}/2\\,{act_y}\\,{act_y+act_h}-{h_expr})"
            crop_filter = f"crop=w='{w_expr}':h='{h_expr}':x='{x_expr}':y='{y_expr}'"
        elif resolved_motion == "pull_out" and duration > 0.35:
            # Subtle 1.06x -> 1.00x pull-out anchored on tracked subject
            w_expr = f"({base_crop_w}*(0.94+0.06*min(t/{duration:.3f}\\,1)))"
            h_expr = f"({base_crop_h}*(0.94+0.06*min(t/{duration:.3f}\\,1)))"
            x_expr = f"clip({anchor_x}-{w_expr}/2\\,{act_x}\\,{act_x+act_w}-{w_expr})"
            y_expr = f"clip({anchor_y}-{h_expr}/2\\,{act_y}\\,{act_y+act_h}-{h_expr})"
            crop_filter = f"crop=w='{w_expr}':h='{h_expr}':x='{x_expr}':y='{y_expr}'"
        elif resolved_motion == "punch_in" and duration > 0.25:
            # 1.08x -> 1.00x impact punch-in recovering over first 0.18s
            w_expr = f"({base_crop_w}*(0.93+0.07*min(t/0.18\\,1)))"
            h_expr = f"({base_crop_h}*(0.93+0.07*min(t/0.18\\,1)))"
            x_expr = f"clip({anchor_x}-{w_expr}/2\\,{act_x}\\,{act_x+act_w}-{w_expr})"
            y_expr = f"clip({anchor_y}-{h_expr}/2\\,{act_y}\\,{act_y+act_h}-{h_expr})"
            crop_filter = f"crop=w='{w_expr}':h='{h_expr}':x='{x_expr}':y='{y_expr}'"
        elif max_scroll_x <= 0:
            crop_filter = f"crop={base_crop_w}:{base_crop_h}:{act_x}:{crop_y}"
        else:
            # Horizontal motion tracking
            ideal_x_start = act_x + (trajectory_info.get("cx_start", 0.5) * act_w - (base_crop_w / 2.0))
            ideal_x_end = act_x + (trajectory_info.get("cx_end", 0.5) * act_w - (base_crop_w / 2.0))
            x_start = int(round(np.clip(ideal_x_start, act_x, act_x + max_scroll_x)))
            x_end = int(round(np.clip(ideal_x_end, act_x, act_x + max_scroll_x)))

            if x_start == x_end or duration <= 0.20 or resolved_motion == "static_steady":
                crop_x_expr = str(x_start)
            else:
                crop_x_expr = f"'{x_start}+({x_end - x_start})*(0.5-0.5*cos(PI*min(t/{duration:.3f}\\,1)))'"
            crop_filter = f"crop={base_crop_w}:{base_crop_h}:{crop_x_expr}:{crop_y}"

    # Case B: Active content is narrower than 9:16
    else:
        base_crop_w = act_w
        base_crop_h = int(round(act_w / target_ar / 2.0)) * 2
        base_crop_h = min(base_crop_h, act_h)
        max_scroll_y = max(0, act_h - base_crop_h)

        if max_scroll_y <= 0:
            crop_y_expr = str(act_y)
        else:
            ideal_y_start = act_y + (trajectory_info.get("cy_start", 0.5) * act_h - (base_crop_h / 2.0))
            ideal_y_end = act_y + (trajectory_info.get("cy_end", 0.5) * act_h - (base_crop_h / 2.0))
            y_start = int(round(np.clip(ideal_y_start, act_y, act_y + max_scroll_y)))
            y_end = int(round(np.clip(ideal_y_end, act_y, act_y + max_scroll_y)))

            if y_start == y_end or duration <= 0.20 or resolved_motion == "static_steady":
                crop_y_expr = str(y_start)
            else:
                crop_y_expr = f"'{y_start}+({y_end - y_start})*(0.5-0.5*cos(PI*min(t/{duration:.3f}\\,1)))'"
        crop_filter = f"crop={base_crop_w}:{base_crop_h}:{act_x}:{crop_y_expr}"

    return f"{crop_filter},scale={video_width}:{video_height}:flags=lanczos+accurate_rnd,cas=0.55,unsharp=5:5:1.2:5:5:0.0,setsar=1"
