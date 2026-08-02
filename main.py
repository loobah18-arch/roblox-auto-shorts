"""
Roblox Shorts Pipeline — Visual-Authentic Edition
Targets the @NinjaRoblox visual style: real Roblox gameplay footage,
clean captions, bright Roblox-style renders. No anime. No dark filters.
"""

import os
import random
import json
import subprocess
import requests
import asyncio
import edge_tts
import glob
import urllib.request
import math
import re
import numpy as np

os.environ["IMAGEMAGICK_BINARY"] = "/usr/bin/convert"

from PIL import Image, ImageEnhance, ImageDraw, ImageFont
from moviepy.editor import (
    VideoFileClip, ImageClip, CompositeVideoClip, AudioFileClip,
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
VIDEO_W, VIDEO_H = 1080, 1920
FPS = 30
CAPTION_Y_FRAC = 0.82          # captions sit at 82 % of video height
CAPTION_FONTSIZE = 58
CAPTION_FONT = "Liberation-Sans-Bold"
CROSSFADE_DUR = 0.25            # seconds of overlap between scenes

# Local assets used when yt-dlp fails — keyword → image filename(s)
ASSET_DIR = "assets"
ASSET_MAP = {
    "island":    ["ancient_island.jpg", "jungle_island.jpg", "volcano_island.jpg"],
    "jungle":    ["jungle_island.jpg"],
    "volcano":   ["volcano_island.jpg"],
    "ancient":   ["ancient_island.jpg"],
    "fortress":  ["fortress.jpg"],
    "ocean":     ["ocean_battle.jpg", "sea.jpg"],
    "sea":       ["sea.jpg", "ocean_battle.jpg"],
    "battle":    ["ocean_battle.jpg", "fortress.jpg"],
    "underwater": ["underwater_city.jpg"],
    "city":      ["underwater_city.jpg"],
    "monster":   ["monster_mutation.jpg"],
    "mutation":  ["monster_mutation.jpg"],
    "roblox":    ["roblox_landscape.jpg"],
    "landscape": ["roblox_landscape.jpg"],
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


def pick_assets_for_query(query, count=2):
    """Return `count` local asset paths that best match the query."""
    q = query.lower()
    matched = []
    for keyword, files in ASSET_MAP.items():
        if keyword in q:
            matched.extend(files)
    if not matched:
        matched = ALL_ASSETS[:]
    random.shuffle(matched)
    selected = list(dict.fromkeys(matched))[:count]  # dedupe, keep order
    # pad with random if not enough unique matches
    pool = [f for f in ALL_ASSETS if f not in selected]
    random.shuffle(pool)
    while len(selected) < count and pool:
        selected.append(pool.pop())
    return [os.path.join(ASSET_DIR, f) for f in selected
            if os.path.exists(os.path.join(ASSET_DIR, f))]


# ──────────────────────────────────────────────────────────────────────────────
# KEN BURNS ENGINE
# ──────────────────────────────────────────────────────────────────────────────
def _roblox_grade(pil_img):
    """
    Bright, saturated Roblox palette grade — matches the colourful
    game-capture aesthetic of channels like @NinjaRoblox.
    """
    img = pil_img.convert("RGB")
    img = ImageEnhance.Brightness(img).enhance(1.08)   # slightly brighter
    img = ImageEnhance.Contrast(img).enhance(1.15)      # punchy contrast
    img = ImageEnhance.Color(img).enhance(1.30)          # vivid Roblox colours
    return img


def make_ken_burns_clip(img_path, duration):
    """
    Loads a Roblox-graded image and returns a 1080×1920 clip
    with a random pan+zoom Ken Burns move.
    """
    DIRECTIONS = [
        "zoom_in",  "zoom_out",
        "pan_left", "pan_right",
        "pan_up",   "pan_down",
    ]
    direction = random.choice(DIRECTIONS)

    pil_img = _roblox_grade(Image.open(img_path).convert("RGB"))

    # Scale image so it covers the frame with 22 % extra room for motion
    scale = max(VIDEO_W * 1.22 / pil_img.width, VIDEO_H * 1.22 / pil_img.height)
    sw = int(pil_img.width * scale)
    sh = int(pil_img.height * scale)
    pil_img = pil_img.resize((sw, sh), Image.LANCZOS)
    arr = np.array(pil_img)

    def make_frame(t):
        p = t / max(duration, 0.001)  # 0→1

        if direction == "zoom_in":
            z = 1.0 + 0.20 * p
            cw, ch = int(VIDEO_W / z), int(VIDEO_H / z)
            x0 = (sw - cw) // 2
            y0 = (sh - ch) // 2
        elif direction == "zoom_out":
            z = 1.20 - 0.20 * p
            cw, ch = int(VIDEO_W / z), int(VIDEO_H / z)
            x0 = (sw - cw) // 2
            y0 = (sh - ch) // 2
        elif direction == "pan_left":
            cw, ch = VIDEO_W, VIDEO_H
            x0 = int((sw - VIDEO_W) * p)
            y0 = (sh - VIDEO_H) // 2
        elif direction == "pan_right":
            cw, ch = VIDEO_W, VIDEO_H
            x0 = int((sw - VIDEO_W) * (1 - p))
            y0 = (sh - VIDEO_H) // 2
        elif direction == "pan_up":
            cw, ch = VIDEO_W, VIDEO_H
            x0 = (sw - VIDEO_W) // 2
            y0 = int((sh - VIDEO_H) * p)
        else:  # pan_down
            cw, ch = VIDEO_W, VIDEO_H
            x0 = (sw - VIDEO_W) // 2
            y0 = int((sh - VIDEO_H) * (1 - p))

        x0 = max(0, min(x0, sw - VIDEO_W))
        y0 = max(0, min(y0, sh - VIDEO_H))
        crop = arr[y0:y0 + ch, x0:x0 + cw]

        if crop.shape[1] != VIDEO_W or crop.shape[0] != VIDEO_H:
            crop = np.array(
                Image.fromarray(crop).resize((VIDEO_W, VIDEO_H), Image.BILINEAR)
            )
        return crop

    from moviepy.video.VideoClip import VideoClip
    clip = VideoClip(make_frame, duration=duration)
    clip.fps = FPS
    return clip


def build_image_clip(img_paths, duration):
    """Build a clip from 1–N local images, Ken Burns on each."""
    if not img_paths:
        return ColorClip(size=(VIDEO_W, VIDEO_H), color=(30, 120, 60), duration=duration)

    if len(img_paths) == 1:
        return make_ken_burns_clip(img_paths[0], duration)

    seg = duration / len(img_paths)
    clips = [make_ken_burns_clip(p, seg) for p in img_paths]
    # Crossfade join
    joined = clips[0]
    for c in clips[1:]:
        c2 = c.fx(vfx.fadein, CROSSFADE_DUR)
        joined = concatenate_videoclips([joined, c2], method="compose")
    return joined.set_duration(duration)


# ──────────────────────────────────────────────────────────────────────────────
# POLLINATIONS ROBLOX-STYLE AI FALLBACK
# ──────────────────────────────────────────────────────────────────────────────
def fetch_pollinations_image(query, out_path):
    """
    Downloads one Roblox-style AI image from Pollinations.
    Prompts are designed for the bright, blocky Roblox aesthetic.
    """
    style = random.choice([
        "Roblox 3D game screenshot, blocky avatar characters, bright vivid colors, in-game environment",
        "Roblox gameplay render, low poly 3D world, colorful Roblox studio style, game UI",
        "Roblox game scene, blocky characters with accessories, bright sunlight, vibrant Roblox world",
    ])
    full_prompt = f"{style}, {query}, no text, no watermark"
    encoded = requests.utils.quote(full_prompt)
    seed = random.randint(1000, 999999)
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width=1080&height=1920&nologo=true&seed={seed}&model=flux"
    )
    try:
        urllib.request.urlretrieve(url, out_path)
        if os.path.exists(out_path) and os.path.getsize(out_path) > 5000:
            print(f"    ✅ Pollinations Roblox image generated.")
            return True
    except Exception as e:
        print(f"    ⚠️ Pollinations failed: {e}")
    return False


# ──────────────────────────────────────────────────────────────────────────────
# YT-DLP CLIP FETCHING  (no cookies — avoids IP-ban risk per yt-dlp docs)
# ──────────────────────────────────────────────────────────────────────────────

# Search templates tried in order per scene
ROBLOX_SEARCH_TEMPLATES = [
    "{query} Roblox shorts",
    "{query} Roblox blox fruits gameplay",
    "{query} Roblox funny moments",
    "Roblox {query} shorts 2024",
]

# Curated last-resort searches — broad Roblox terms that almost always return
# a public, freely downloadable short
SAFE_FALLBACK_SEARCHES = [
    "ytsearch1:Roblox blox fruits showcase shorts",
    "ytsearch1:Roblox funny moments shorts vertical",
    "ytsearch1:Roblox gameplay shorts 2024",
    "ytsearch1:Roblox blox fruits pvp shorts",
]

# yt-dlp player-client chains to try in order (safest → broadest)
# tv_embedded and web_embedded are server-side clients — less bot-detection
# android/ios are mobile clients with a separate token flow
_PLAYER_CLIENT_CHAINS = [
    "tv_embedded,web_embedded",
    "android,ios",
    "android,ios,tv_embedded,web_embedded",
]


def _run_ytdlp(target, output_path):
    """
    Tries each player-client chain in turn. Returns True on first success.
    No cookies — avoids the IP-ban risk documented by yt-dlp maintainers.
    """
    for client_chain in _PLAYER_CLIENT_CHAINS:
        cmd = [
            "yt-dlp", target,
            "--extractor-args", f"youtube:player_client={client_chain}",
            "--user-agent",
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36",
            "--add-header", "Accept-Language:en-US,en;q=0.9",
            "--geo-bypass",
            "--no-check-certificates",
            "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "-o", output_path,
            "--max-downloads", "1",
            "--no-playlist",
            "--socket-timeout", "20",
            "--quiet",
            "--no-warnings",
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
            if (res.returncode == 0
                    and os.path.exists(output_path)
                    and os.path.getsize(output_path) > 10_000):
                return True
            # Clean up partial file before next attempt
            if os.path.exists(output_path):
                os.remove(output_path)
        except subprocess.TimeoutExpired:
            print(f"    ⏱ yt-dlp timeout (client={client_chain}).")
        except Exception as e:
            print(f"    ⚠️ yt-dlp error: {e}")
    return False


def fetch_video_clip(query, clip_filename, youtube_client):
    """
    Three-engine fetch (no cookies):
      1. YouTube Data API → yt-dlp  (if API key is configured)
      2. Search templates  → yt-dlp
      3. Curated fallback searches → yt-dlp
    Returns local file path on success, None on failure.
    """
    templates_dir = "motion_templates"
    os.makedirs(templates_dir, exist_ok=True)
    output_path = os.path.join(templates_dir, clip_filename)

    # ── Engine 1: YouTube Data API → yt-dlp ──────────────────────────────────
    if youtube_client:
        print(f"  🔎 YouTube API: '{query}'")
        try:
            resp = youtube_client.search().list(
                q=f"{query} Roblox gameplay shorts",
                part="snippet",
                type="video",
                maxResults=3,
                videoDuration="short",
            ).execute()
            for item in resp.get("items", []):
                vid_id = item["id"]["videoId"]
                target = f"https://www.youtube.com/watch?v={vid_id}"
                print(f"    → {vid_id}")
                if _run_ytdlp(target, output_path):
                    print(f"  ✅ Downloaded via YouTube API.")
                    return output_path
        except Exception as e:
            print(f"  ⚠️ YouTube API error: {e}")

    # ── Engine 2: yt-dlp search templates ────────────────────────────────────
    for tmpl in ROBLOX_SEARCH_TEMPLATES:
        search_str = tmpl.format(query=query)
        print(f"  📥 yt-search: {search_str}")
        if _run_ytdlp(f"ytsearch1:{search_str}", output_path):
            print(f"  ✅ Downloaded via search template.")
            return output_path

    # ── Engine 3: Curated fallback searches ──────────────────────────────────
    for fb in SAFE_FALLBACK_SEARCHES:
        print(f"  📥 Fallback: {fb}")
        if _run_ytdlp(fb, output_path):
            print(f"  ✅ Downloaded via fallback search.")
            return output_path

    print(f"  ❌ yt-dlp: all attempts failed — switching to AI visuals.")
    return None


def crop_video_to_vertical(clip, duration):
    """
    Crops a downloaded video to 1080×1920 vertical format.
    Adds a bright Roblox-green letterbox if the clip is too narrow.
    """
    clip = clip.set_duration(min(duration, clip.duration))
    # Resize to fill 1920 height
    clip = clip.resize(height=VIDEO_H)
    if clip.w >= VIDEO_W:
        # Centre-crop width
        x_mid = clip.w / 2
        clip = clip.crop(x1=x_mid - VIDEO_W // 2, x2=x_mid + VIDEO_W // 2,
                         y1=0, y2=VIDEO_H)
    else:
        # Pad sides — bright green matching Roblox grass aesthetic
        pad = ColorClip(size=(VIDEO_W, VIDEO_H), color=(56, 148, 56), duration=duration)
        clip = CompositeVideoClip([pad, clip.set_position("center")],
                                  size=(VIDEO_W, VIDEO_H))
    return clip.set_duration(duration)


# ──────────────────────────────────────────────────────────────────────────────
# CAPTION RENDERING  (matches @NinjaRoblox style)
# ──────────────────────────────────────────────────────────────────────────────
def make_caption_clip(text, duration):
    """
    Clean white bold caption with a black stroke at the bottom of the frame.
    Matches the caption style seen in NinjaRoblox Shorts.
    """
    try:
        txt = TextClip(
            text,
            font=CAPTION_FONT,
            fontsize=CAPTION_FONTSIZE,
            color="white",
            stroke_color="black",
            stroke_width=4,
            size=(VIDEO_W - 100, None),
            method="caption",
            align="center",
        )
        y_pos = int(VIDEO_H * CAPTION_Y_FRAC)
        return txt.set_duration(duration).set_position(("center", y_pos))
    except Exception:
        try:
            return TextClip(
                text,
                font="Liberation-Sans",
                fontsize=CAPTION_FONTSIZE,
                color="white",
                stroke_color="black",
                stroke_width=4,
                size=(VIDEO_W - 100, None),
                method="caption",
            ).set_duration(duration).set_position(("center", int(VIDEO_H * CAPTION_Y_FRAC)))
        except Exception as e:
            print(f"  ⚠️ Caption failed: {e}")
            return None


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
    bible_file = "character_bible.json"

    previous_context = "Episode 1. Start with a shocking hook about Roblox Blox Fruits."
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
For each scene give a specific visual QUERY describing the Roblox gameplay setting (e.g. "dough awakening showcase blox fruits").
Update the CHARACTER BIBLE if anything changes.

Output ONLY this JSON structure (no markdown fences):
{{
  "title": "Short catchy title",
  "scenes": [
    {{"narration": "Scene 1 text...", "query": "roblox blox fruits dough awakening showcase", "duration": 10}},
    {{"narration": "Scene 2 text...", "query": "roblox blox fruits sea beast boss fight", "duration": 10}},
    {{"narration": "Scene 3 text...", "query": "roblox jujutsu zero domain expansion", "duration": 10}},
    {{"narration": "Scene 4 text...", "query": "roblox blox fruits max level pvp", "duration": 10}}
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

    data = json.loads(raw)
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

    # YouTube API client (optional)
    youtube_api_key = clean_env(os.getenv("YOUTUBE_API_KEY"))
    youtube_client = None
    if youtube_api_key:
        try:
            youtube_client = build("youtube", "v3",
                                   developerKey=youtube_api_key,
                                   cache_discovery=False)
        except Exception:
            pass

    # Clean old clips
    templates_dir = "motion_templates"
    os.makedirs(templates_dir, exist_ok=True)
    for f in glob.glob(os.path.join(templates_dir, "*")):
        try:
            os.remove(f)
        except Exception:
            pass

    video_segments = []
    audio_segments = []

    for idx, scene in enumerate(storyboard_data["scenes"]):
        narration = scene["narration"]
        query = scene["query"]
        print(f"\n🎬 Scene {idx + 1}/{len(storyboard_data['scenes'])}: {query}")

        # Voiceover
        audio_file = f"scene_{idx + 1}.mp3"
        asyncio.run(generate_voiceover(narration, audio_file))
        scene_audio = AudioFileClip(audio_file)
        dur = scene_audio.duration
        audio_segments.append(scene_audio)

        visual = None

        # ── A: Try real Roblox gameplay footage via yt-dlp ──
        clip_path = fetch_video_clip(query, f"clip_{idx + 1}.mp4",
                                     youtube_client)
        if clip_path:
            try:
                raw_clip = VideoFileClip(clip_path)
                max_start = max(0, raw_clip.duration - dur)
                start_t = random.uniform(0, max_start) if max_start > 0 else 0
                snippet = raw_clip.subclip(start_t, start_t + dur)
                visual = crop_video_to_vertical(snippet, dur)
                print(f"  🎮 Real gameplay footage used.")
            except Exception as e:
                print(f"  ⚠️ Video load failed: {e}")
                visual = None

        # ── B: Pollinations Roblox-style AI image ──
        if visual is None:
            print(f"  🖼  Generating Roblox-style AI image...")
            ai_paths = []
            for i in range(2):
                ai_out = os.path.join(templates_dir, f"ai_{idx}_{i}.jpg")
                if fetch_pollinations_image(query, ai_out):
                    ai_paths.append(ai_out)
            if ai_paths:
                visual = build_image_clip(ai_paths, dur)
                print(f"  🎨 AI Roblox image(s) used ({len(ai_paths)} frames).")

        # ── C: Local assets with Ken Burns ──
        if visual is None:
            print(f"  📁 Using local Roblox assets...")
            asset_paths = pick_assets_for_query(query, count=2)
            if asset_paths:
                visual = build_image_clip(asset_paths, dur)
                print(f"  ✅ Local assets used: {[os.path.basename(p) for p in asset_paths]}")
            else:
                visual = ColorClip(size=(VIDEO_W, VIDEO_H),
                                   color=(56, 148, 56), duration=dur)

        # ── Add captions ──
        caption = make_caption_clip(narration, dur)
        layers = [visual.set_duration(dur)]
        if caption:
            layers.append(caption)

        scene_clip = CompositeVideoClip(layers, size=(VIDEO_W, VIDEO_H))
        scene_clip = scene_clip.set_duration(dur).set_audio(scene_audio)

        if idx > 0:
            scene_clip = scene_clip.fx(vfx.fadein, CROSSFADE_DUR)

        video_segments.append(scene_clip)

    # ──────────────────────────────────────────────────────────────────────────
    # 4. FINAL RENDER
    # ──────────────────────────────────────────────────────────────────────────
    print("\n─── [4/5] Final Render ───")
    final_video = concatenate_videoclips(video_segments, method="compose")

    # BGM mix
    bgm_folder = "bgm"
    os.makedirs(bgm_folder, exist_ok=True)
    mp3_files = [f for f in os.listdir(bgm_folder) if f.endswith(".mp3")]
    combined_voice = (
        concatenate_audioclips(audio_segments) if len(audio_segments) > 1
        else audio_segments[0]
    )
    target_dur = combined_voice.duration

    if mp3_files:
        bg = AudioFileClip(os.path.join(bgm_folder, random.choice(mp3_files)))
        if bg.duration < target_dur:
            loops = math.ceil(target_dur / bg.duration)
            bg = concatenate_audioclips([bg] * loops).subclip(0, target_dur)
        else:
            bg = bg.subclip(0, target_dur)
        bg = bg.volumex(0.10)
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

    client_id = clean_env(os.getenv("CLIENT_ID"))
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
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    title = storyboard_data.get("title", "Blox Fruits Madness!")
    hook = storyboard_data["scenes"][0]["narration"]

    body = {
        "snippet": {
            "title": f"{title} #Shorts",
            "description": f"{hook}\n\n#Shorts #Roblox #BloxFruits #Gaming #RobloxShorts",
            "tags": ["Roblox", "BloxFruits", "Shorts", "Gaming", "Roblox Shorts", "Blox Fruits"],
            "categoryId": "20",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload("final_short.mp4", chunksize=-1, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)

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
    print("═══ 🎬 Roblox Shorts Pipeline (Visual-Authentic Edition) ═══\n")
    data = generate_storyboard()
    assemble_storyboard(data)
    upload_to_youtube(data)
    print("\n═══ ✅ Done — Short is live! ═══")


if __name__ == "__main__":
    main()
