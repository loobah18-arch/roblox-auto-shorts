"""
Roblox Shorts Pipeline — Story-Authentic Visual Edition
Targets the @NinjaRoblox visual style: bright blocky Roblox environments,
consistent characters, clean captions, and a dramatic voiced story.

Visual engine order (per scene):
  A. FAL.ai text-to-video       — actual video clips              (key rotation)
  B. HuggingFace text-to-video  — free AI video via HF_TOKEN      (key rotation)
  C. Pollinations AI            — 12 motion keyframes → 24fps anim (always free)
  D. HuggingFace FLUX           — high-quality images             (key rotation)
  E. Dezgo                      — free SD images, no key, no CI blocks
  F. Local assets               — absolute last resort
"""

import os
import random
import json
import requests
import asyncio
import edge_tts
import glob
import urllib.request
import math
import time
import numpy as np

os.environ["IMAGEMAGICK_BINARY"] = "/usr/bin/convert"

from PIL import Image, ImageEnhance
from moviepy.editor import (
    VideoFileClip, CompositeVideoClip, AudioFileClip,
    CompositeAudioClip, TextClip, concatenate_videoclips,
    concatenate_audioclips, ColorClip,
)
import moviepy.video.fx.all as vfx
from groq import Groq
import google.oauth2.credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────────
VIDEO_W, VIDEO_H    = 1080, 1920
FPS                 = 24
CAPTION_Y_FRAC      = 0.82
CAPTION_FONTSIZE    = 58
CAPTION_FONT        = "Liberation-Sans-Bold"
CROSSFADE_DUR       = 0.60
KEYFRAMES_PER_SCENE = 12   # 12 motion keyframes → smooth 24fps animation

# Motion descriptors — each keyframe gets a different one so
# Pollinations generates a different action moment in the same scene
MOTION_VARIANTS = [
    "initial pose, calm before action",
    "beginning to move, slight motion",
    "winding up, gathering energy",
    "mid-motion, dynamic movement",
    "peak action, explosive moment",
    "impact frame, maximum force",
    "follow-through, momentum",
    "recoil, aftermath of action",
    "recovery stance, catching breath",
    "second wind, new surge of power",
    "dramatic climax, intense expression",
    "final pose, powerful stance",
]

ASSET_DIR  = "assets"
ASSET_MAP  = {
    "island":     ["ancient_island.jpg", "jungle_island.jpg", "volcano_island.jpg"],
    "jungle":     ["jungle_island.jpg"],
    "volcano":    ["volcano_island.jpg"],
    "ancient":    ["ancient_island.jpg"],
    "fortress":   ["fortress.jpg"],
    "ocean":      ["ocean_battle.jpg", "sea.jpg"],
    "sea":        ["sea.jpg", "ocean_battle.jpg"],
    "battle":     ["ocean_battle.jpg", "fortress.jpg"],
    "underwater": ["underwater_city.jpg"],
    "city":       ["underwater_city.jpg"],
    "monster":    ["monster_mutation.jpg"],
    "mutation":   ["monster_mutation.jpg"],
    "roblox":     ["roblox_landscape.jpg"],
    "landscape":  ["roblox_landscape.jpg"],
}
ALL_ASSETS = [
    "roblox_landscape.jpg", "ancient_island.jpg", "jungle_island.jpg",
    "ocean_battle.jpg", "fortress.jpg", "volcano_island.jpg",
    "underwater_city.jpg", "sea.jpg", "monster_mutation.jpg",
]

# ──────────────────────────────────────────────────────────────────────────────
# UTILITIES
# ──────────────────────────────────────────────────────────────────────────────
def clean_env(val):
    if not val:
        return ""
    val = val.strip()
    if val.startswith("[") and "]" in val:
        val = val.split("]")[0].lstrip("[")
    return val.strip("'\"")


def load_env_keys(base_name):
    keys = []
    v = clean_env(os.getenv(base_name, ""))
    if v:
        keys.append(v)
    for i in range(1, 11):
        v = clean_env(os.getenv(f"{base_name}_{i}", ""))
        if v:
            keys.append(v)
    return keys


def pick_assets_for_query(query, count=KEYFRAMES_PER_SCENE):
    q = query.lower()
    matched = []
    for keyword, files in ASSET_MAP.items():
        if keyword in q:
            matched.extend(files)
    if not matched:
        matched = ALL_ASSETS[:]
    random.shuffle(matched)
    selected = list(dict.fromkeys(matched))[:count]
    pool = [f for f in ALL_ASSETS if f not in selected]
    random.shuffle(pool)
    while len(selected) < count and pool:
        selected.append(pool.pop())
    return [os.path.join(ASSET_DIR, f) for f in selected
            if os.path.exists(os.path.join(ASSET_DIR, f))]


# ──────────────────────────────────────────────────────────────────────────────
# CHARACTER-AWARE PROMPT BUILDER
# ──────────────────────────────────────────────────────────────────────────────
def build_roblox_prompt(query, narration, character_bible, motion_variant=""):
    narration_lower = narration.lower()
    mentioned_chars = []
    for char_name, char_data in character_bible.items():
        if char_name.lower() in narration_lower:
            clothes  = char_data.get("clothes", "")
            features = char_data.get("facial_features", "")
            mentioned_chars.append(f"{char_name} ({clothes}, {features})")

    char_part = ""
    if mentioned_chars:
        char_part = "featuring " + " and ".join(mentioned_chars) + ", "

    style = random.choice([
        "Roblox 3D game screenshot, blocky avatar characters, bright vivid colors, in-game environment, official Roblox Studio look",
        "Roblox gameplay render, low-poly colorful 3D world, Roblox avatars with accessories, bright sunlight, vibrant",
        "Roblox game scene, blocky characters with hats and gear, sunny bright Roblox world, high detail game render",
        "Roblox Blox Fruits screenshot, colorful sea island environment, Roblox avatars, bright vivid anime-game style",
    ])

    motion_part = f", {motion_variant}" if motion_variant else ""

    return (
        f"{style}, {char_part}{query}{motion_part}, "
        "dramatic action pose, cinematic lighting, no watermarks, no text overlay, "
        "4K sharp, vertical portrait 9:16 composition"
    )


# ──────────────────────────────────────────────────────────────────────────────
# IMAGE GRADING
# ──────────────────────────────────────────────────────────────────────────────
def _roblox_grade(pil_img):
    img = pil_img.convert("RGB")
    img = ImageEnhance.Brightness(img).enhance(1.08)
    img = ImageEnhance.Contrast(img).enhance(1.15)
    img = ImageEnhance.Color(img).enhance(1.30)
    return img


# ──────────────────────────────────────────────────────────────────────────────
# 24FPS ANIMATED CLIP — frame-by-frame interpolation between keyframes
# ──────────────────────────────────────────────────────────────────────────────
def _get_kb_frame(arr, sw, sh, direction, p):
    """Ken Burns crop at progress p (0→1), returned as float32."""
    if direction == "zoom_in":
        z = 1.0 + 0.18 * p
        cw, ch = int(VIDEO_W / z), int(VIDEO_H / z)
        x0, y0 = (sw - cw) // 2, (sh - ch) // 2
    elif direction == "zoom_out":
        z = 1.18 - 0.18 * p
        cw, ch = int(VIDEO_W / z), int(VIDEO_H / z)
        x0, y0 = (sw - cw) // 2, (sh - ch) // 2
    elif direction == "pan_left":
        cw, ch = VIDEO_W, VIDEO_H
        x0 = int((sw - VIDEO_W) * p); y0 = (sh - VIDEO_H) // 2
    elif direction == "pan_right":
        cw, ch = VIDEO_W, VIDEO_H
        x0 = int((sw - VIDEO_W) * (1 - p)); y0 = (sh - VIDEO_H) // 2
    elif direction == "pan_up":
        cw, ch = VIDEO_W, VIDEO_H
        x0 = (sw - VIDEO_W) // 2; y0 = int((sh - VIDEO_H) * p)
    else:  # pan_down
        cw, ch = VIDEO_W, VIDEO_H
        x0 = (sw - VIDEO_W) // 2; y0 = int((sh - VIDEO_H) * (1 - p))

    x0 = max(0, min(x0, sw - VIDEO_W))
    y0 = max(0, min(y0, sh - VIDEO_H))
    crop = arr[y0:y0 + ch, x0:x0 + cw]

    if crop.shape[1] != VIDEO_W or crop.shape[0] != VIDEO_H:
        crop = np.array(Image.fromarray(crop).resize((VIDEO_W, VIDEO_H), Image.BILINEAR))
    return crop.astype(np.float32)


def build_animated_clip(img_paths, duration):
    """
    Builds a true 24fps animated clip from keyframe images.

    Each keyframe was generated with a different motion descriptor, so they
    show different action moments. Between consecutive keyframes, every single
    frame (at 24fps) is computed as a weighted blend of the two surrounding
    keyframes. This produces smooth motion that looks like real animation
    rather than a slideshow.

    Example with 12 keyframes over 10 seconds:
      - Each keyframe occupies ~0.83 seconds
      - At 24fps that is 20 interpolated frames between each pair
      - Total = 240 rendered frames of smooth motion
    """
    from moviepy.video.VideoClip import VideoClip

    if not img_paths:
        return ColorClip(size=(VIDEO_W, VIDEO_H), color=(30, 120, 60), duration=duration)

    KB_DIRS = ["zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down"]

    # Pre-load and grade every keyframe image into memory
    print(f"    🖼  Loading {len(img_paths)} keyframes into memory...")
    keyframes = []
    for path in img_paths:
        pil   = _roblox_grade(Image.open(path).convert("RGB"))
        scale = max(VIDEO_W * 1.22 / pil.width, VIDEO_H * 1.22 / pil.height)
        sw    = int(pil.width  * scale)
        sh    = int(pil.height * scale)
        pil   = pil.resize((sw, sh), Image.LANCZOS)
        keyframes.append({
            "arr": np.array(pil),
            "sw":  sw,
            "sh":  sh,
            "dir": random.choice(KB_DIRS),
        })

    n       = len(keyframes)
    seg_dur = duration / n          # seconds per keyframe segment
    xfade   = min(CROSSFADE_DUR, seg_dur * 0.5)  # crossfade window

    def make_frame(t):
        # Which keyframe segment are we in?
        seg_idx = min(int(t / seg_dur), n - 1)
        seg_t   = t - seg_idx * seg_dur      # elapsed time within this segment
        kb_p    = max(0.0, min(1.0, seg_t / seg_dur))

        kf   = keyframes[seg_idx]
        base = _get_kb_frame(kf["arr"], kf["sw"], kf["sh"], kf["dir"], kb_p)

        # Smooth alpha blend into next keyframe during tail of segment
        if seg_idx < n - 1 and seg_t > seg_dur - xfade:
            alpha  = (seg_t - (seg_dur - xfade)) / xfade   # 0.0 → 1.0
            alpha  = max(0.0, min(1.0, alpha))
            kf_nxt = keyframes[seg_idx + 1]
            nxt    = _get_kb_frame(kf_nxt["arr"], kf_nxt["sw"], kf_nxt["sh"],
                                   kf_nxt["dir"], 0.0)
            base   = base * (1.0 - alpha) + nxt * alpha

        return base.astype(np.uint8)

    clip     = VideoClip(make_frame, duration=duration)
    clip.fps = FPS
    return clip


# ──────────────────────────────────────────────────────────────────────────────
# ENGINE A — FAL.AI TEXT-TO-VIDEO (fixed polling URL)
# ──────────────────────────────────────────────────────────────────────────────
def fetch_fal_video(prompt, out_path, api_keys):
    if not api_keys:
        return False

    MODEL_BASE = "fal-ai/wan/v2.1/1.3b/text-to-video"

    for key in api_keys:
        print(f"  🎬 FAL.ai text-to-video...")
        try:
            headers = {
                "Authorization": f"Key {key}",
                "Content-Type":  "application/json",
            }
            payload = {
                "prompt":       prompt,
                "duration":     "5",
                "aspect_ratio": "9:16",
                "resolution":   "720p",
            }
            submit = requests.post(
                f"https://queue.fal.run/{MODEL_BASE}",
                headers=headers, json=payload, timeout=30,
            )
            if submit.status_code not in (200, 201):
                print(f"    ⚠️ FAL submit {submit.status_code} — trying next key.")
                continue

            request_id = submit.json().get("request_id")
            if not request_id:
                print(f"    ⚠️ FAL submit returned no request_id.")
                continue

            status_url = f"https://queue.fal.run/{MODEL_BASE}/requests/{request_id}/status"
            result_url = f"https://queue.fal.run/{MODEL_BASE}/requests/{request_id}"

            for _ in range(36):
                time.sleep(5)
                poll = requests.get(status_url, headers=headers, timeout=15)
                if poll.status_code != 200:
                    continue
                job_status = poll.json().get("status", "")
                if job_status == "COMPLETED":
                    result_resp = requests.get(result_url, headers=headers, timeout=30)
                    if result_resp.status_code != 200:
                        print(f"    ⚠️ FAL result fetch failed: {result_resp.status_code}.")
                        break
                    output    = result_resp.json().get("output", {})
                    video_url = (
                        output.get("video", {}).get("url", "")
                        or (output.get("videos") or [{}])[0].get("url", "")
                    )
                    if video_url:
                        urllib.request.urlretrieve(video_url, out_path)
                        if os.path.exists(out_path) and os.path.getsize(out_path) > 10_000:
                            print(f"    ✅ FAL.ai video downloaded.")
                            return True
                    print(f"    ⚠️ FAL completed but no video URL found.")
                    break
                elif job_status in ("FAILED", "CANCELLED"):
                    print(f"    ⚠️ FAL job {job_status}.")
                    break
            else:
                print(f"    ⏱ FAL.ai timed out after 3 minutes.")

        except Exception as e:
            print(f"    ⚠️ FAL.ai error: {e}")

    print("    ❌ FAL.ai: all keys exhausted.")
    return False


# ──────────────────────────────────────────────────────────────────────────────
# ENGINE B — HUGGINGFACE TEXT-TO-VIDEO
# ──────────────────────────────────────────────────────────────────────────────
def fetch_hf_video(prompt, out_path, api_keys):
    if not api_keys:
        return False

    HF_VIDEO_MODELS = [
        "https://router.huggingface.co/hf-inference/models/damo-vilab/text-to-video-ms-1.7b",
        "https://router.huggingface.co/hf-inference/models/cerspense/zeroscope_v2_576w",
    ]
    short_prompt = " ".join(prompt.split()[:50])

    for key in api_keys:
        for model_url in HF_VIDEO_MODELS:
            model_name = model_url.split("/")[-1]
            print(f"  🎥 HuggingFace video ({model_name})...")
            try:
                headers = {
                    "Authorization":    f"Bearer {key}",
                    "Content-Type":     "application/json",
                    "x-wait-for-model": "true",
                }
                resp = requests.post(
                    model_url, headers=headers,
                    json={"inputs": short_prompt}, timeout=180,
                )
                if resp.status_code == 200:
                    ct = resp.headers.get("content-type", "")
                    if "video" in ct or "octet-stream" in ct or len(resp.content) > 50_000:
                        with open(out_path, "wb") as f:
                            f.write(resp.content)
                        if os.path.exists(out_path) and os.path.getsize(out_path) > 50_000:
                            print(f"    ✅ HuggingFace video generated ({model_name}).")
                            return True
                        if os.path.exists(out_path):
                            os.remove(out_path)
                elif resp.status_code == 503:
                    print(f"    ⏳ HF model loading, retrying in 20s...")
                    time.sleep(20)
                    resp2 = requests.post(
                        model_url, headers=headers,
                        json={"inputs": short_prompt}, timeout=180,
                    )
                    if resp2.status_code == 200 and len(resp2.content) > 50_000:
                        with open(out_path, "wb") as f:
                            f.write(resp2.content)
                        if os.path.exists(out_path) and os.path.getsize(out_path) > 50_000:
                            print(f"    ✅ HuggingFace video generated ({model_name}, retry).")
                            return True
                elif resp.status_code == 429:
                    print(f"    ⚠️ HF rate limited — trying next model.")
                else:
                    print(f"    ⚠️ HF {model_name} returned {resp.status_code}.")
            except requests.exceptions.Timeout:
                print(f"    ⏱ HF {model_name} timed out.")
            except Exception as e:
                print(f"    ⚠️ HF video error ({model_name}): {e}")

    print("    ❌ HuggingFace video: all keys/models exhausted.")
    return False


# ──────────────────────────────────────────────────────────────────────────────
# ENGINE C — POLLINATIONS: 12 motion keyframes → 24fps animated clip
# ──────────────────────────────────────────────────────────────────────────────
def fetch_pollinations_keyframes(base_prompt, narration, character_bible,
                                  count, out_dir, prefix):
    """
    Generates `count` images from Pollinations, each with a different
    motion-variant descriptor appended to the prompt. The varying descriptors
    ("winding up", "peak action", "impact frame", etc.) push Pollinations to
    generate different action moments of the same scene.
    Each image also gets a unique random seed for maximum variety.
    """
    paths = []
    for i in range(count):
        motion = MOTION_VARIANTS[i % len(MOTION_VARIANTS)]
        prompt = build_roblox_prompt(base_prompt, narration, character_bible, motion)
        seed   = random.randint(10_000, 9_999_999)
        encoded = requests.utils.quote(prompt)
        url = (
            f"https://image.pollinations.ai/prompt/{encoded}"
            f"?width=1080&height=1920&nologo=true&seed={seed}&model=flux"
        )
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": "https://pollinations.ai/",
            "Accept":  "image/webp,image/apng,image/*,*/*;q=0.8",
        }
        out_path = os.path.join(out_dir, f"{prefix}_{i}.jpg")
        try:
            resp = requests.get(url, headers=headers, timeout=90, stream=True)
            if resp.status_code == 200 and "image" in resp.headers.get("content-type", ""):
                with open(out_path, "wb") as f:
                    for chunk in resp.iter_content(8192):
                        f.write(chunk)
                if os.path.exists(out_path) and os.path.getsize(out_path) > 5000:
                    print(f"    ✅ Keyframe {i + 1}/{count} — [{motion}]")
                    paths.append(out_path)
                    continue
            print(f"    ⚠️ Keyframe {i + 1} failed (status {resp.status_code}) — skipping.")
        except Exception as e:
            print(f"    ⚠️ Keyframe {i + 1} error: {e} — skipping.")
    return paths


# ──────────────────────────────────────────────────────────────────────────────
# ENGINE D — HUGGINGFACE FLUX images
# ──────────────────────────────────────────────────────────────────────────────
def fetch_huggingface_image(prompt, out_path, api_keys):
    if not api_keys:
        return False

    MODEL_URLS = [
        "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell",
        "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell",
    ]
    payload = {
        "inputs": prompt,
        "parameters": {
            "width": 1080, "height": 1920,
            "num_inference_steps": 4, "guidance_scale": 0.0,
        },
    }

    for key in api_keys:
        print(f"  🖼  HuggingFace FLUX image...")
        for model_url in MODEL_URLS:
            try:
                headers = {
                    "Authorization":    f"Bearer {key}",
                    "Content-Type":     "application/json",
                    "x-wait-for-model": "true",
                }
                resp = requests.post(model_url, headers=headers, json=payload, timeout=90)
                if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image"):
                    with open(out_path, "wb") as f:
                        f.write(resp.content)
                    if os.path.exists(out_path) and os.path.getsize(out_path) > 5000:
                        print(f"    ✅ HuggingFace FLUX image generated.")
                        return True
                elif resp.status_code == 503:
                    print(f"    ⏳ HF model loading — retrying in 20s...")
                    time.sleep(20)
                    resp2 = requests.post(model_url, headers=headers, json=payload, timeout=90)
                    if resp2.status_code == 200 and resp2.headers.get("content-type", "").startswith("image"):
                        with open(out_path, "wb") as f:
                            f.write(resp2.content)
                        if os.path.exists(out_path) and os.path.getsize(out_path) > 5000:
                            print(f"    ✅ HuggingFace FLUX image generated (retry).")
                            return True
                else:
                    print(f"    ⚠️ HF returned {resp.status_code} — trying next URL.")
                    continue
            except Exception as e:
                print(f"    ⚠️ HuggingFace error: {e}")
                continue
            break

    print("    ❌ HuggingFace: all keys exhausted.")
    return False


# ──────────────────────────────────────────────────────────────────────────────
# ENGINE E — DEZGO
# ──────────────────────────────────────────────────────────────────────────────
def fetch_dezgo_image(prompt, out_path):
    print(f"  🎨 Dezgo free SD image...")
    try:
        resp = requests.post(
            "https://dezgo.com/text2image",
            data={
                "prompt":          prompt[:400],
                "negative_prompt": "blurry, low quality, text, watermark, nsfw",
                "guidance": "7", "steps": "20",
                "sampler": "euler_a", "upscale": "1",
                "model": "dreamshaper_8",
            },
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Referer": "https://dezgo.com/",
            },
            timeout=90,
        )
        if resp.status_code == 200 and "image" in resp.headers.get("content-type", ""):
            with open(out_path, "wb") as f:
                f.write(resp.content)
            if os.path.exists(out_path) and os.path.getsize(out_path) > 5000:
                print(f"    ✅ Dezgo image generated.")
                return True
        else:
            print(f"    ⚠️ Dezgo returned {resp.status_code}.")
    except Exception as e:
        print(f"    ⚠️ Dezgo failed: {e}")
    return False


# ──────────────────────────────────────────────────────────────────────────────
# VIDEO CROP UTILITY
# ──────────────────────────────────────────────────────────────────────────────
def crop_video_to_vertical(clip, duration):
    clip = clip.set_duration(min(duration, clip.duration))
    clip = clip.resize(height=VIDEO_H)
    if clip.w >= VIDEO_W:
        x_mid = clip.w / 2
        clip  = clip.crop(x1=x_mid - VIDEO_W // 2, x2=x_mid + VIDEO_W // 2,
                          y1=0, y2=VIDEO_H)
    else:
        pad  = ColorClip(size=(VIDEO_W, VIDEO_H), color=(56, 148, 56), duration=duration)
        clip = CompositeVideoClip([pad, clip.set_position("center")], size=(VIDEO_W, VIDEO_H))
    return clip.set_duration(duration)


# ──────────────────────────────────────────────────────────────────────────────
# CAPTION RENDERING
# ──────────────────────────────────────────────────────────────────────────────
def make_caption_clip(text, duration):
    for font in (CAPTION_FONT, "Liberation-Sans"):
        try:
            txt = TextClip(
                text, font=font, fontsize=CAPTION_FONTSIZE,
                color="white", stroke_color="black", stroke_width=4,
                size=(VIDEO_W - 100, None), method="caption", align="center",
            )
            return (txt.set_duration(duration)
                       .set_position(("center", int(VIDEO_H * CAPTION_Y_FRAC))))
        except Exception:
            continue
    print("  ⚠️ Caption rendering failed — skipping.")
    return None


# ──────────────────────────────────────────────────────────────────────────────
# SCENE VISUAL FETCHER — Six-Engine Chain
# ──────────────────────────────────────────────────────────────────────────────
def fetch_scene_visual(scene, scene_idx, character_bible,
                       fal_keys, hf_keys, templates_dir):
    query     = scene["query"]
    narration = scene["narration"]
    dur       = scene.get("duration", 10)
    # Base prompt (no motion variant — used for video engines)
    base_prompt = build_roblox_prompt(query, narration, character_bible)
    print(f"  📝 Base prompt: {base_prompt[:100]}...")

    # Engine A — FAL.ai video
    if fal_keys:
        fal_out = os.path.join(templates_dir, f"fal_clip_{scene_idx}.mp4")
        if fetch_fal_video(base_prompt, fal_out, fal_keys):
            try:
                raw_clip = VideoFileClip(fal_out)
                loops    = math.ceil(dur / raw_clip.duration)
                looped   = concatenate_videoclips([raw_clip] * loops)
                visual   = crop_video_to_vertical(looped, dur)
                print(f"  🎮 FAL.ai video used.")
                return visual
            except Exception as e:
                print(f"  ⚠️ FAL clip load failed: {e}")

    # Engine B — HuggingFace text-to-video
    if hf_keys:
        hf_vid_out = os.path.join(templates_dir, f"hf_video_{scene_idx}.mp4")
        if fetch_hf_video(base_prompt, hf_vid_out, hf_keys):
            try:
                raw_clip = VideoFileClip(hf_vid_out)
                loops    = math.ceil(dur / raw_clip.duration)
                looped   = concatenate_videoclips([raw_clip] * loops)
                visual   = crop_video_to_vertical(looped, dur)
                print(f"  🎥 HuggingFace video used.")
                return visual
            except Exception as e:
                print(f"  ⚠️ HF video clip load failed: {e}")

    # Engine C — Pollinations: 12 motion keyframes → 24fps animated clip
    print(f"  🎬 Pollinations: generating {KEYFRAMES_PER_SCENE} motion keyframes...")
    poll_paths = fetch_pollinations_keyframes(
        query, narration, character_bible,
        count=KEYFRAMES_PER_SCENE,
        out_dir=templates_dir,
        prefix=f"poll_{scene_idx}",
    )
    if poll_paths:
        print(f"  ✅ {len(poll_paths)} keyframes ready → building 24fps animated clip.")
        return build_animated_clip(poll_paths, dur)

    # Engine D — HuggingFace FLUX images → animated clip
    if hf_keys:
        hf_paths = []
        for i in range(6):
            hf_out = os.path.join(templates_dir, f"hf_{scene_idx}_{i}.jpg")
            if fetch_huggingface_image(base_prompt, hf_out, hf_keys):
                hf_paths.append(hf_out)
        if hf_paths:
            print(f"  🤗 HuggingFace FLUX: {len(hf_paths)} images → animated clip.")
            return build_animated_clip(hf_paths, dur)

    # Engine E — Dezgo
    dezgo_paths = []
    for i in range(4):
        dezgo_out = os.path.join(templates_dir, f"dezgo_{scene_idx}_{i}.jpg")
        if fetch_dezgo_image(base_prompt, dezgo_out):
            dezgo_paths.append(dezgo_out)
    if dezgo_paths:
        print(f"  🎨 Dezgo: {len(dezgo_paths)} images → animated clip.")
        return build_animated_clip(dezgo_paths, dur)

    # Engine F — Local assets
    print(f"  📁 Falling back to local assets...")
    asset_paths = pick_assets_for_query(query, count=6)
    if asset_paths:
        return build_animated_clip(asset_paths, dur)

    return ColorClip(size=(VIDEO_W, VIDEO_H), color=(56, 148, 56), duration=dur)


# ──────────────────────────────────────────────────────────────────────────────
# 1. GROQ STORYBOARD DIRECTOR
# ──────────────────────────────────────────────────────────────────────────────
def generate_storyboard():
    print("─── [1/5] Groq Story Director ───")
    api_key = clean_env(os.getenv("GROQ_API_KEY"))
    if not api_key:
        raise Exception("Missing GROQ_API_KEY environment variable!")

    client = Groq(api_key=api_key)

    history_file = "story_memory.txt"
    bible_file   = "character_bible.json"

    previous_context  = "Episode 1. Start with a shocking hook about Roblox Blox Fruits."
    character_context = "{}"

    if os.path.exists(history_file):
        content = open(history_file).read().strip()
        if content:
            previous_context = content

    if os.path.exists(bible_file):
        bc = open(bible_file).read().strip()
        if bc:
            character_context = bc

    prompt = f"""
You are an unhinged, viral AI director for a serialized Roblox Blox Fruits / Jujutsu Zero YouTube Shorts saga.

PREVIOUS EPISODE CONTEXT:
{previous_context}

CHARACTER BIBLE:
{character_context}

TASK:
Write the NEXT part of the story as exactly 4 scenes (~130-150 words total). End on a massive cliffhanger.
For each scene give a specific visual QUERY that includes the CHARACTER NAMES appearing in it and the Roblox setting.
Example query: "Luffy and Shanks clash, roblox blox fruits dough awakening sea battle"
Update the CHARACTER BIBLE if anything changes.

Output ONLY this JSON (no markdown fences):
{{
  "title": "Short catchy title",
  "scenes": [
    {{"narration": "Scene 1 text...", "query": "Luffy roblox blox fruits dough awakening showcase", "duration": 10}},
    {{"narration": "Scene 2 text...", "query": "Shanks Big Mom roblox blox fruits sea beast boss fight", "duration": 10}},
    {{"narration": "Scene 3 text...", "query": "Mysterious Figure roblox jujutsu zero domain expansion", "duration": 10}},
    {{"narration": "Scene 4 text...", "query": "Luffy roblox blox fruits max level pvp cliffhanger", "duration": 10}}
  ],
  "character_bible": {{
    "CharacterName": {{
      "facial_features": "...",
      "clothes": "...",
      "personality": "..."
    }}
  }}
}}
"""

    resp = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=900,
        temperature=0.92,
    )

    raw = resp.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    data      = json.loads(raw)
    full_text = " ".join(s["narration"] for s in data["scenes"])
    open(history_file, "w").write(full_text)
    json.dump(data.get("character_bible", {}), open(bible_file, "w"), indent=4)

    print(f"🎬 Title: {data.get('title')}")
    print(f"📌 {len(data['scenes'])} scenes generated.\n")
    return data


# ──────────────────────────────────────────────────────────────────────────────
# 2. VOICEOVER
# ──────────────────────────────────────────────────────────────────────────────
async def generate_voiceover(text, out_file):
    communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural", rate="+10%")
    await communicate.save(out_file)


# ──────────────────────────────────────────────────────────────────────────────
# 3. ASSEMBLY
# ──────────────────────────────────────────────────────────────────────────────
def assemble_storyboard(storyboard_data):
    print("─── [3/5] Scene Assembly ───")

    templates_dir = "motion_templates"
    os.makedirs(templates_dir, exist_ok=True)
    for f in glob.glob(os.path.join(templates_dir, "*")):
        try:
            os.remove(f)
        except Exception:
            pass

    fal_keys = load_env_keys("FAL_API_KEY")
    hf_keys  = load_env_keys("HF_TOKEN")

    if fal_keys:
        print(f"  🎬 FAL.ai: {len(fal_keys)} key(s) loaded.")
    if hf_keys:
        print(f"  🤗 HuggingFace: {len(hf_keys)} key(s) loaded.")

    character_bible = {}
    if os.path.exists("character_bible.json"):
        try:
            character_bible = json.load(open("character_bible.json"))
        except Exception:
            pass

    video_segments = []
    audio_segments = []

    for idx, scene in enumerate(storyboard_data["scenes"]):
        narration = scene["narration"]
        print(f"\n🎬 Scene {idx + 1}/{len(storyboard_data['scenes'])}: {scene['query']}")

        # Voiceover first — its duration drives the scene length exactly
        audio_file  = f"scene_{idx + 1}.mp3"
        asyncio.run(generate_voiceover(narration, audio_file))
        scene_audio = AudioFileClip(audio_file)
        actual_dur        = scene_audio.duration   # audio = source of truth, no padding
        scene["duration"] = actual_dur
        audio_segments.append(scene_audio)
        print(f"  🔊 Voiceover: {actual_dur:.1f}s")

        visual = fetch_scene_visual(
            scene, idx, character_bible, fal_keys, hf_keys, templates_dir
        ).set_duration(actual_dur)

        caption = make_caption_clip(narration, actual_dur)
        layers  = [visual]
        if caption:
            layers.append(caption)

        scene_clip = CompositeVideoClip(layers, size=(VIDEO_W, VIDEO_H))
        scene_clip = (scene_clip
                      .set_duration(actual_dur)
                      .set_audio(scene_audio))   # exact match — no looping

        if idx > 0:
            scene_clip = scene_clip.fx(vfx.fadein, CROSSFADE_DUR)

        video_segments.append(scene_clip)

    # ── FINAL RENDER ──────────────────────────────────────────────────────────
    print("\n─── [4/5] Final Render ───")
    final_video = concatenate_videoclips(video_segments, method="compose")

    bgm_folder = "bgm"
    os.makedirs(bgm_folder, exist_ok=True)
    mp3_files      = [f for f in os.listdir(bgm_folder) if f.endswith(".mp3")]
    combined_voice = (
        concatenate_audioclips(audio_segments)
        if len(audio_segments) > 1 else audio_segments[0]
    )
    target_dur = combined_voice.duration

    if mp3_files:
        bg = AudioFileClip(os.path.join(bgm_folder, random.choice(mp3_files)))
        if bg.duration < target_dur:
            loops = math.ceil(target_dur / bg.duration)
            bg    = concatenate_audioclips([bg] * loops).subclip(0, target_dur)
        else:
            bg = bg.subclip(0, target_dur)
        bg          = bg.volumex(0.10)
        final_audio = CompositeAudioClip([combined_voice, bg])
    else:
        final_audio = combined_voice

    final_video = final_video.set_audio(final_audio)

    print("🎞  Rendering final_short.mp4 ...")
    final_video.write_videofile(
        "final_short.mp4",
        fps=FPS, codec="libx264", audio_codec="aac",
        threads=4, preset="fast", logger=None,
    )
    print("✅ Render complete: final_short.mp4\n")


# ──────────────────────────────────────────────────────────────────────────────
# 5. YOUTUBE UPLOAD
# ──────────────────────────────────────────────────────────────────────────────
def upload_to_youtube(storyboard_data):
    print("─── [5/5] YouTube Upload ───")

    client_id     = clean_env(os.getenv("CLIENT_ID"))
    client_secret = clean_env(os.getenv("CLIENT_SECRET"))
    refresh_token = clean_env(os.getenv("REFRESH_TOKEN"))

    if not client_id or not client_secret or not refresh_token:
        print("🚨 YouTube secrets missing — skipping upload.")
        return

    creds = google.oauth2.credentials.Credentials(
        None, refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id, client_secret=client_secret,
    )
    yt    = build("youtube", "v3", credentials=creds, cache_discovery=False)
    title = storyboard_data.get("title", "Blox Fruits Madness!")
    hook  = storyboard_data["scenes"][0]["narration"]

    body = {
        "snippet": {
            "title":       f"{title} #Shorts",
            "description": f"{hook}\n\n#Shorts #Roblox #BloxFruits #Gaming #RobloxShorts",
            "tags":        ["Roblox", "BloxFruits", "Shorts", "Gaming",
                            "Roblox Shorts", "Blox Fruits"],
            "categoryId":  "20",
        },
        "status": {
            "privacyStatus": "public", "selfDeclaredMadeForKids": False,
        },
    }

    media    = MediaFileUpload("final_short.mp4", chunksize=-1, resumable=True)
    req      = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = req.next_chunk()
        if status:
            print(f"  ⏳ Uploading: {int(status.progress() * 100)}%")

    print(f"🎉 Uploaded! https://youtube.com/shorts/{response.get('id')}")


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  Roblox Auto-Shorts — Story-Authentic Visual Edition")
    print("=" * 60 + "\n")

    storyboard = generate_storyboard()
    assemble_storyboard(storyboard)
    upload_to_youtube(storyboard)

    print("\n🏁 Pipeline complete.")


if __name__ == "__main__":
    main()
