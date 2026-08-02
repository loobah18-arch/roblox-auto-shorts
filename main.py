"""
Roblox Shorts Pipeline — Story-Authentic Visual Edition
Targets the @NinjaRoblox visual style: bright blocky Roblox environments,
consistent characters, clean captions, and a dramatic voiced story.

Visual engine order (per scene):
  A. FAL.ai text-to-video  — actual Roblox-style video clips  (key rotation)
  B. Pollinations AI        — character-aware Roblox images     (always free)
  C. HuggingFace FLUX       — high-quality Roblox images        (key rotation)
  D. Local assets           — last resort static images
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
VIDEO_W, VIDEO_H   = 1080, 1920
FPS                = 30
CAPTION_Y_FRAC     = 0.82
CAPTION_FONTSIZE   = 58
CAPTION_FONT       = "Liberation-Sans-Bold"
CROSSFADE_DUR      = 0.40
IMAGES_PER_SCENE   = 3

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
    """Collect BASE_NAME, BASE_NAME_1 … BASE_NAME_10 for key rotation."""
    keys = []
    v = clean_env(os.getenv(base_name, ""))
    if v:
        keys.append(v)
    for i in range(1, 11):
        v = clean_env(os.getenv(f"{base_name}_{i}", ""))
        if v:
            keys.append(v)
    return keys


def pick_assets_for_query(query, count=IMAGES_PER_SCENE):
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
def build_roblox_prompt(query, narration, character_bible):
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

    return (
        f"{style}, {char_part}{query}, "
        "dramatic action pose, cinematic lighting, no watermarks, no text overlay, "
        "4K sharp, vertical portrait 9:16 composition"
    )


# ──────────────────────────────────────────────────────────────────────────────
# KEN BURNS ENGINE
# ──────────────────────────────────────────────────────────────────────────────
def _roblox_grade(pil_img):
    img = pil_img.convert("RGB")
    img = ImageEnhance.Brightness(img).enhance(1.08)
    img = ImageEnhance.Contrast(img).enhance(1.15)
    img = ImageEnhance.Color(img).enhance(1.30)
    return img


def make_ken_burns_clip(img_path, duration):
    DIRECTIONS = ["zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down"]
    direction  = random.choice(DIRECTIONS)

    pil_img = _roblox_grade(Image.open(img_path).convert("RGB"))
    scale   = max(VIDEO_W * 1.22 / pil_img.width, VIDEO_H * 1.22 / pil_img.height)
    sw = int(pil_img.width  * scale)
    sh = int(pil_img.height * scale)
    pil_img = pil_img.resize((sw, sh), Image.LANCZOS)
    arr     = np.array(pil_img)

    def make_frame(t):
        p = t / max(duration, 0.001)

        if direction == "zoom_in":
            z = 1.0 + 0.20 * p
            cw, ch = int(VIDEO_W / z), int(VIDEO_H / z)
            x0 = (sw - cw) // 2; y0 = (sh - ch) // 2
        elif direction == "zoom_out":
            z = 1.20 - 0.20 * p
            cw, ch = int(VIDEO_W / z), int(VIDEO_H / z)
            x0 = (sw - cw) // 2; y0 = (sh - ch) // 2
        elif direction == "pan_left":
            cw, ch = VIDEO_W, VIDEO_H
            x0 = int((sw - VIDEO_W) * p);       y0 = (sh - VIDEO_H) // 2
        elif direction == "pan_right":
            cw, ch = VIDEO_W, VIDEO_H
            x0 = int((sw - VIDEO_W) * (1 - p)); y0 = (sh - VIDEO_H) // 2
        elif direction == "pan_up":
            cw, ch = VIDEO_W, VIDEO_H
            x0 = (sw - VIDEO_W) // 2; y0 = int((sh - VIDEO_H) * p)
        else:
            cw, ch = VIDEO_W, VIDEO_H
            x0 = (sw - VIDEO_W) // 2; y0 = int((sh - VIDEO_H) * (1 - p))

        x0   = max(0, min(x0, sw - VIDEO_W))
        y0   = max(0, min(y0, sh - VIDEO_H))
        crop = arr[y0:y0 + ch, x0:x0 + cw]

        if crop.shape[1] != VIDEO_W or crop.shape[0] != VIDEO_H:
            crop = np.array(
                Image.fromarray(crop).resize((VIDEO_W, VIDEO_H), Image.BILINEAR)
            )
        return crop

    from moviepy.video.VideoClip import VideoClip
    clip     = VideoClip(make_frame, duration=duration)
    clip.fps = FPS
    return clip


def build_image_clip(img_paths, duration):
    if not img_paths:
        return ColorClip(size=(VIDEO_W, VIDEO_H), color=(30, 120, 60), duration=duration)
    if len(img_paths) == 1:
        return make_ken_burns_clip(img_paths[0], duration)
    seg    = duration / len(img_paths)
    clips  = [make_ken_burns_clip(p, seg) for p in img_paths]
    joined = clips[0]
    for c in clips[1:]:
        joined = concatenate_videoclips(
            [joined, c.fx(vfx.fadein, CROSSFADE_DUR)], method="compose"
        )
    return joined.set_duration(duration)


# ──────────────────────────────────────────────────────────────────────────────
# ENGINE A — FAL.AI TEXT-TO-VIDEO
# ──────────────────────────────────────────────────────────────────────────────
def fetch_fal_video(prompt, out_path, api_keys):
    if not api_keys:
        return False

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
                "https://queue.fal.run/fal-ai/wan/v2.1/1.3b/text-to-video",
                headers=headers,
                json=payload,
                timeout=30,
            )
            if submit.status_code not in (200, 201):
                print(f"    ⚠️ FAL submit {submit.status_code} — trying next key.")
                continue

            request_id = submit.json().get("request_id")
            if not request_id:
                continue

            status_url = (
                f"https://queue.fal.run/fal-ai/wan/v2.1/1.3b/"
                f"text-to-video/requests/{request_id}"
            )
            for _ in range(36):
                time.sleep(5)
                poll   = requests.get(status_url, headers=headers, timeout=15)
                if poll.status_code != 200:
                    continue
                result = poll.json()
                status = result.get("status", "")
                if status == "COMPLETED":
                    output    = result.get("output", {})
                    video_url = (
                        output.get("video", {}).get("url", "")
                        or (output.get("videos") or [{}])[0].get("url", "")
                    )
                    if video_url:
                        urllib.request.urlretrieve(video_url, out_path)
                        if os.path.exists(out_path) and os.path.getsize(out_path) > 10_000:
                            print(f"    ✅ FAL.ai video downloaded.")
                            return True
                    break
                elif status in ("FAILED", "CANCELLED"):
                    print(f"    ⚠️ FAL job {status}.")
                    break
            else:
                print(f"    ⏱ FAL.ai timed out.")

        except Exception as e:
            print(f"    ⚠️ FAL.ai error: {e}")

    print("    ❌ FAL.ai: all keys exhausted.")
    return False


# ──────────────────────────────────────────────────────────────────────────────
# ENGINE B — POLLINATIONS AI (always free, no key needed)
# ──────────────────────────────────────────────────────────────────────────────
def fetch_pollinations_image(prompt, out_path):
    encoded = requests.utils.quote(prompt)
    seed    = random.randint(1000, 999999)
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width=1080&height=1920&nologo=true&seed={seed}&model=flux"
    )
    try:
        urllib.request.urlretrieve(url, out_path)
        if os.path.exists(out_path) and os.path.getsize(out_path) > 5000:
            print(f"    ✅ Pollinations image generated.")
            return True
    except Exception as e:
        print(f"    ⚠️ Pollinations failed: {e}")
    return False


# ──────────────────────────────────────────────────────────────────────────────
# ENGINE C — HUGGINGFACE FLUX (free inference, key rotation)
# ──────────────────────────────────────────────────────────────────────────────
def fetch_huggingface_image(prompt, out_path, api_keys):
    if not api_keys:
        return False

    model_url = (
        "https://api-inference.huggingface.co/models/"
        "black-forest-labs/FLUX.1-schnell"
    )
    payload = {
        "inputs": prompt,
        "parameters": {
            "width":               1080,
            "height":              1920,
            "num_inference_steps": 4,
            "guidance_scale":      0.0,
        },
    }

    for key in api_keys:
        print(f"  🖼  HuggingFace FLUX image...")
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
                print(f"    ⚠️ HF returned {resp.status_code} — trying next key.")
        except Exception as e:
            print(f"    ⚠️ HuggingFace error: {e}")

    print("    ❌ HuggingFace: all keys exhausted.")
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
                text,
                font=font,
                fontsize=CAPTION_FONTSIZE,
                color="white",
                stroke_color="black",
                stroke_width=4,
                size=(VIDEO_W - 100, None),
                method="caption",
                align="center",
            )
            return (txt.set_duration(duration)
                       .set_position(("center", int(VIDEO_H * CAPTION_Y_FRAC))))
        except Exception:
            continue
    print("  ⚠️ Caption rendering failed — skipping.")
    return None


# ──────────────────────────────────────────────────────────────────────────────
# SCENE VISUAL FETCHER — Four-Engine Chain
# ──────────────────────────────────────────────────────────────────────────────
def fetch_scene_visual(scene, scene_idx, character_bible,
                       fal_keys, hf_keys, templates_dir):
    query       = scene["query"]
    narration   = scene["narration"]
    dur         = scene.get("duration", 12)
    rich_prompt = build_roblox_prompt(query, narration, character_bible)
    print(f"  📝 Prompt: {rich_prompt[:120]}...")

    # Engine A — FAL.ai video
    if fal_keys:
        fal_out = os.path.join(templates_dir, f"fal_clip_{scene_idx}.mp4")
        if fetch_fal_video(rich_prompt, fal_out, fal_keys):
            try:
                raw_clip = VideoFileClip(fal_out)
                loops    = math.ceil(dur / raw_clip.duration)
                looped   = concatenate_videoclips([raw_clip] * loops)
                visual   = crop_video_to_vertical(looped, dur)
                print(f"  🎮 FAL.ai video used (looped {loops}x for {dur:.1f}s).")
                return visual
            except Exception as e:
                print(f"  ⚠️ FAL clip load failed: {e}")

    # Engine B — Pollinations images
    print(f"  🖼  Pollinations — character-aware images...")
    poll_paths = []
    for i in range(IMAGES_PER_SCENE):
        poll_out = os.path.join(templates_dir, f"poll_{scene_idx}_{i}.jpg")
        if fetch_pollinations_image(rich_prompt, poll_out):
            poll_paths.append(poll_out)
    if poll_paths:
        print(f"  🎨 Pollinations: {len(poll_paths)} story-matched image(s).")
        return build_image_clip(poll_paths, dur)

    # Engine C — HuggingFace FLUX
    if hf_keys:
        hf_paths = []
        for i in range(IMAGES_PER_SCENE):
            hf_out = os.path.join(templates_dir, f"hf_{scene_idx}_{i}.jpg")
            if fetch_huggingface_image(rich_prompt, hf_out, hf_keys):
                hf_paths.append(hf_out)
        if hf_paths:
            print(f"  🤗 HuggingFace: {len(hf_paths)} image(s) used.")
            return build_image_clip(hf_paths, dur)

    # Engine D — Local assets
    print(f"  📁 Falling back to local assets...")
    asset_paths = pick_assets_for_query(query, count=IMAGES_PER_SCENE)
    if asset_paths:
        print(f"  ✅ Local assets: {[os.path.basename(p) for p in asset_paths]}")
        return build_image_clip(asset_paths, dur)

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
    {{"narration": "Scene 1 text...", "query": "Luffy roblox blox fruits dough awakening showcase", "duration": 12}},
    {{"narration": "Scene 2 text...", "query": "Shanks Big Mom roblox blox fruits sea beast boss fight", "duration": 12}},
    {{"narration": "Scene 3 text...", "query": "Mysterious Figure roblox jujutsu zero domain expansion", "duration": 12}},
    {{"narration": "Scene 4 text...", "query": "Luffy roblox blox fruits max level pvp cliffhanger", "duration": 12}}
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

        audio_file  = f"scene_{idx + 1}.mp3"
        asyncio.run(generate_voiceover(narration, audio_file))
        scene_audio = AudioFileClip(audio_file)
        actual_dur  = max(scene_audio.duration, scene.get("duration", 12))
        scene["duration"] = actual_dur
        audio_segments.append(scene_audio)

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
                      .set_audio(scene_audio.set_duration(actual_dur)))

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
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        threads=4,
        preset="fast",
        logger=None,
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
        None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
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
            "privacyStatus":           "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    media    = MediaFileUpload("final_short.mp4", chunksize=-1, resumable=True)
    req      = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = req.next_chunk()
        if status:
            print(f"  ⏳ Uploading: {int(status.progress() * 100)}%")

    video_id = response.get("id")
    print(f"🎉 Uploaded! https://youtube.com/shorts/{video_id}")


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
