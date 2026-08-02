import os
import random
import json
import subprocess
import requests
import asyncio
import edge_tts
import glob
import urllib.request
import re
import math
import numpy as np

# Fix MoviePy ImageMagick path detection on GitHub Actions Ubuntu runners
os.environ["IMAGEMAGICK_BINARY"] = "/usr/bin/convert"

from PIL import Image, ImageFilter, ImageEnhance, ImageDraw
from moviepy.editor import (
    VideoFileClip, ImageClip, CompositeVideoClip, AudioFileClip,
    CompositeAudioClip, TextClip, concatenate_videoclips,
    concatenate_audioclips, ColorClip
)
from moviepy.video.fx.fadein import fadein
from moviepy.video.fx.fadeout import fadeout
import moviepy.video.fx.all as vfx
from groq import Groq
import google.auth.transport.requests
import google.oauth2.credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ==========================================
# CONSTANTS
# ==========================================
VIDEO_W, VIDEO_H = 1080, 1920
FPS = 24
CAPTION_Y = 1380          # vertical position of caption box
CAPTION_FONT_SIZE = 54
CAPTION_FONT = "Liberation-Sans-Bold"
VIGNETTE_STRENGTH = 0.55  # 0 = no vignette, 1 = very heavy
CROSSFADE_DUR = 0.35      # seconds of overlap between scenes

# ==========================================
# HELPERS
# ==========================================
def clean_env(val):
    """Sanitizes environment variables to remove accidental markdown wrappers."""
    if not val:
        return ""
    val = val.strip()
    if val.startswith("[") and "]" in val:
        val = val.split("]")[0].lstrip("[")
    return val.strip("'\"")

def get_safe_url(service_type):
    if service_type == "google_token":
        return "https://oauth2.googleapis.com/token"
    elif service_type == "youtube_short":
        return "https://youtube.com/shorts/"
    return ""

# ==========================================
# VISUAL UTILITIES
# ==========================================
def build_vignette(width, height, strength=VIGNETTE_STRENGTH):
    """Returns an RGBA numpy array with a dark elliptical vignette."""
    x = np.linspace(-1, 1, width)
    y = np.linspace(-1, 1, height)
    xv, yv = np.meshgrid(x, y)
    dist = np.sqrt(xv ** 2 + yv ** 2)
    mask = np.clip(dist, 0, 1) ** 1.8
    alpha = (mask * 255 * strength).astype(np.uint8)
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    rgba[..., 3] = alpha  # pure black with variable alpha
    return rgba

def apply_cinematic_grade(pil_img):
    """
    Applies a filmic color grade:
      - Slight warm push (lift reds, desaturate slightly)
      - Crushed blacks
      - Increased contrast
    All done with PIL – no extra dependencies.
    """
    img = pil_img.convert("RGB")
    # Boost contrast
    img = ImageEnhance.Contrast(img).enhance(1.20)
    # Slight saturation boost for vivid gaming look
    img = ImageEnhance.Color(img).enhance(1.25)
    # Warm tint via per-channel multipliers (R+, G=, B-)
    r, g, b = img.split()
    r = r.point(lambda p: min(255, int(p * 1.07)))
    b = b.point(lambda p: min(255, int(p * 0.93)))
    img = Image.merge("RGB", (r, g, b))
    return img

def make_ken_burns_clip(img_path, duration, direction=None):
    """
    Loads an image and creates a 1080x1920 clip with a Ken Burns
    pan+zoom effect. Direction is one of:
      'zoom_in_center', 'zoom_out_center',
      'pan_left', 'pan_right', 'pan_up', 'pan_down'
    """
    directions = [
        "zoom_in_center", "zoom_out_center",
        "pan_left", "pan_right", "pan_up", "pan_down",
    ]
    if direction is None:
        direction = random.choice(directions)

    pil_img = Image.open(img_path).convert("RGB")
    pil_img = apply_cinematic_grade(pil_img)

    # Scale image so it fully covers 1080×1920 with 20% extra room for motion
    scale = max(VIDEO_W * 1.20 / pil_img.width, VIDEO_H * 1.20 / pil_img.height)
    scaled_w = int(pil_img.width * scale)
    scaled_h = int(pil_img.height * scale)
    pil_img = pil_img.resize((scaled_w, scaled_h), Image.LANCZOS)
    img_arr = np.array(pil_img)

    # Build the vignette once (RGBA overlay)
    vignette_arr = build_vignette(VIDEO_W, VIDEO_H)
    vignette_img = Image.fromarray(vignette_arr, "RGBA")

    def make_frame(t):
        progress = t / max(duration, 0.001)  # 0 → 1

        if direction == "zoom_in_center":
            zoom = 1.0 + 0.18 * progress
            src_w = int(VIDEO_W / zoom)
            src_h = int(VIDEO_H / zoom)
            x0 = (scaled_w - src_w) // 2
            y0 = (scaled_h - src_h) // 2
        elif direction == "zoom_out_center":
            zoom = 1.18 - 0.18 * progress
            src_w = int(VIDEO_W / zoom)
            src_h = int(VIDEO_H / zoom)
            x0 = (scaled_w - src_w) // 2
            y0 = (scaled_h - src_h) // 2
        elif direction == "pan_left":
            max_pan = scaled_w - VIDEO_W
            x0 = int(max_pan * progress)
            y0 = (scaled_h - VIDEO_H) // 2
            src_w, src_h = VIDEO_W, VIDEO_H
        elif direction == "pan_right":
            max_pan = scaled_w - VIDEO_W
            x0 = int(max_pan * (1 - progress))
            y0 = (scaled_h - VIDEO_H) // 2
            src_w, src_h = VIDEO_W, VIDEO_H
        elif direction == "pan_up":
            max_pan = scaled_h - VIDEO_H
            x0 = (scaled_w - VIDEO_W) // 2
            y0 = int(max_pan * progress)
            src_w, src_h = VIDEO_W, VIDEO_H
        else:  # pan_down
            max_pan = scaled_h - VIDEO_H
            x0 = (scaled_w - VIDEO_W) // 2
            y0 = int(max_pan * (1 - progress))
            src_w, src_h = VIDEO_W, VIDEO_H

        # Crop
        x0 = max(0, min(x0, scaled_w - VIDEO_W))
        y0 = max(0, min(y0, scaled_h - VIDEO_H))
        crop = img_arr[y0:y0 + src_h, x0:x0 + src_w]

        # Resize crop back to exact VIDEO dimensions if needed
        if crop.shape[1] != VIDEO_W or crop.shape[0] != VIDEO_H:
            crop_pil = Image.fromarray(crop).resize((VIDEO_W, VIDEO_H), Image.BILINEAR)
        else:
            crop_pil = Image.fromarray(crop)

        # Composite vignette
        crop_pil = crop_pil.convert("RGBA")
        crop_pil.alpha_composite(vignette_img)
        return np.array(crop_pil.convert("RGB"))

    clip = VideoFileClip.__new__(VideoFileClip)
    from moviepy.video.VideoClip import VideoClip
    clip = VideoClip(make_frame, duration=duration)
    clip.fps = FPS
    return clip

def fetch_ai_images(query, scene_idx, count=2):
    """
    Downloads `count` different AI images from Pollinations for a scene.
    Returns a list of local file paths.
    """
    templates_dir = "motion_templates"
    os.makedirs(templates_dir, exist_ok=True)
    paths = []

    # Craft a vivid gaming-style prompt
    style_tags = [
        "cinematic lighting, epic, ultra detailed",
        "dramatic angle, hyper realistic, 4K",
        "action shot, vivid colors, dynamic composition",
    ]

    for i in range(count):
        style = style_tags[i % len(style_tags)]
        full_prompt = f"Roblox gaming {query}, anime style, {style}"
        encoded = requests.utils.quote(full_prompt)
        seed = random.randint(1000, 999999)
        url = (
            f"https://image.pollinations.ai/prompt/{encoded}"
            f"?width=1080&height=1920&nologo=true&seed={seed}"
        )
        out = os.path.join(templates_dir, f"ai_scene{scene_idx}_frame{i}.jpg")
        try:
            urllib.request.urlretrieve(url, out)
            if os.path.exists(out) and os.path.getsize(out) > 5000:
                paths.append(out)
                print(f"  ✅ AI frame {i+1}/{count} generated.")
        except Exception as e:
            print(f"  ⚠️ AI frame {i+1} failed: {e}")

    return paths

def build_visual_clip_from_images(img_paths, duration):
    """
    Builds a single video clip from 1-N AI images.
    If multiple images, splits duration equally and crossfades between them.
    """
    if not img_paths:
        return ColorClip(size=(VIDEO_W, VIDEO_H), color=(10, 10, 20), duration=duration)

    if len(img_paths) == 1:
        dirs = ["zoom_in_center", "zoom_out_center", "pan_left", "pan_right"]
        return make_ken_burns_clip(img_paths[0], duration, random.choice(dirs))

    seg_dur = duration / len(img_paths)
    clips = []
    chosen_dirs = ["zoom_in_center", "pan_left", "zoom_out_center", "pan_right", "pan_up", "pan_down"]
    for idx, img_path in enumerate(img_paths):
        d = random.choice(chosen_dirs)
        c = make_ken_burns_clip(img_path, seg_dur, d)
        clips.append(c)

    # Crossfade between sub-clips
    faded = [clips[0]]
    for c in clips[1:]:
        faded.append(c.fx(fadein, CROSSFADE_DUR))
    return concatenate_videoclips(faded, method="compose")

# ==========================================
# CAPTION RENDERING
# ==========================================
def make_caption_clip(text, duration):
    """
    Modern caption: white bold text on a semi-transparent dark pill/banner.
    Falls back to plain TextClip if ImageMagick isn't available.
    """
    try:
        txt = TextClip(
            text,
            font=CAPTION_FONT,
            fontsize=CAPTION_FONT_SIZE,
            color="white",
            stroke_color="black",
            stroke_width=3,
            size=(VIDEO_W - 80, None),
            method="caption",
            align="center",
        )
        txt_w, txt_h = txt.size

        # Dark pill background via PIL
        pad = 24
        bg_w = txt_w + pad * 2
        bg_h = txt_h + pad * 2
        bg = Image.new("RGBA", (bg_w, bg_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(bg)
        radius = 20
        draw.rounded_rectangle([0, 0, bg_w - 1, bg_h - 1], radius=radius, fill=(0, 0, 0, 165))
        bg_arr = np.array(bg)

        from moviepy.video.VideoClip import ImageClip as IC
        bg_clip = (
            IC(bg_arr, ismask=False)
            .set_duration(duration)
            .set_position(("center", CAPTION_Y - pad))
        )
        txt_clip = (
            txt.set_duration(duration)
            .set_position(("center", CAPTION_Y))
        )
        return CompositeVideoClip([bg_clip, txt_clip], size=(VIDEO_W, VIDEO_H)).set_duration(duration)
    except Exception as e:
        print(f"  ⚠️ Fancy caption failed ({e}), using fallback.")
        try:
            return TextClip(
                text, font="Liberation-Sans", fontsize=CAPTION_FONT_SIZE,
                color="yellow", stroke_color="black", stroke_width=4,
                size=(VIDEO_W - 80, None), method="caption"
            ).set_duration(duration).set_position(("center", CAPTION_Y))
        except Exception:
            return None

# ==========================================
# 1. GROQ SCENE-BY-SCENE DIRECTOR & MEMORY
# ==========================================
def generate_storyboard():
    print("--- [Step 1/5] Groq Scene-by-Scene Directing & Character Memory ---")
    api_key = clean_env(os.getenv("GROQ_API_KEY"))
    if not api_key:
        raise Exception("Missing GROQ_API_KEY environment variable!")

    client = Groq(api_key=api_key)

    history_file = "story_memory.txt"
    bible_file = "character_bible.json"

    previous_context = "This is Episode 1 of the saga. Start with a massive, mind-breaking hook about Roblox Blox Fruits."
    character_context = "{}"

    if os.path.exists(history_file):
        with open(history_file, "r") as f:
            content = f.read().strip()
            if content:
                previous_context = content

    if os.path.exists(bible_file):
        with open(bible_file, "r") as f:
            bible_content = f.read().strip()
            if bible_content:
                character_context = bible_content

    prompt = f"""
    You are an unhinged, viral AI director creating an infinite, serialized epic saga about Roblox Blox Fruits or Jujutsu Zero for YouTube Shorts.

    PREVIOUS EPISODE CONTEXT:
    {previous_context}

    CURRENT CHARACTER BIBLE (Features, Clothes, Personality):
    {character_context}

    YOUR TASK:
    1. Write the NEXT immediate part of this story split into exactly 4 detailed sequential scenes. Total word count across all scenes should be around 130-150 words. End on a massive cliffhanger.
    2. For EACH scene, provide a highly specific search query describing the exact visual gameplay or motion background that matches that specific sentence.
    3. UPDATE THE CHARACTER BIBLE! If a character changes clothes or gets a power-up, update their traits. Otherwise, carry current traits forward.

    You MUST output your response strictly as a JSON object with this exact structure, with no markdown formatting around it (no ```json):
    {{
      "title": "Catchy Short Title",
      "scenes": [
        {{
          "narration": "Script line for scene 1...",
          "query": "dough awakening showcase cinematic",
          "duration": 10
        }},
        {{
          "narration": "Script line for scene 2...",
          "query": "jujutsu zero domain expansion combat epic",
          "duration": 10
        }},
        {{
          "narration": "Script line for scene 3...",
          "query": "blox fruits max level pvp bounty hunt action",
          "duration": 10
        }},
        {{
          "narration": "Script line for scene 4...",
          "query": "funny glitch meme moment cinematic explosion",
          "duration": 10
        }}
      ],
      "character_bible": {{
        "CharacterName1": {{
          "facial_features": "Description of face...",
          "clothes": "Current outfit...",
          "personality": "Core traits..."
        }}
      }}
    }}
    """

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1000,
        temperature=0.9
    )

    raw_response = response.choices[0].message.content.strip()

    if raw_response.startswith("```"):
        raw_response = raw_response.split("```")[1]
        if raw_response.startswith("json"):
            raw_response = raw_response[4:]
    raw_response = raw_response.strip()

    data = json.loads(raw_response)

    full_script_text = " ".join([scene["narration"] for scene in data["scenes"]])
    with open(history_file, "w") as f:
        f.write(full_script_text)

    with open(bible_file, "w") as f:
        json.dump(data.get("character_bible", {}), f, indent=4)

    print(f"🎬 Story Title: {data.get('title')}\n")
    print(f"📌 Generated {len(data['scenes'])} Structured Scenes successfully.\n")
    return data

async def generate_scene_voiceover(text, output_filename):
    communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural", rate="+10%")
    await communicate.save(output_filename)

# ==========================================
# 2. TRIPLE-ENGINE CLIP FETCHING PER SCENE
# ==========================================
def fetch_video_clip(query, clip_filename, youtube_client):
    """
    Tries YouTube API + yt-dlp to get a real gameplay video clip.
    Returns the path to the downloaded file, or None on failure.
    """
    templates_dir = "motion_templates"
    os.makedirs(templates_dir, exist_ok=True)
    output_path = os.path.join(templates_dir, clip_filename)
    yt_dlp_target = None

    # --- Engine 1: YouTube Data API Search ---
    if youtube_client:
        print(f"  🔎 YouTube Data API: '{query}'")
        try:
            request = youtube_client.search().list(
                q=f"{query} roblox shorts gameplay",
                part="snippet",
                type="video",
                maxResults=3,
                videoDuration="short"
            )
            response = request.execute()
            items = response.get("items", [])
            if items:
                video_id = items[0]["id"]["videoId"]
                yt_dlp_target = f"https://www.youtube.com/watch?v={video_id}"
        except Exception:
            pass

    if not yt_dlp_target:
        yt_dlp_target = f"ytsearch1:{query} roblox gameplay shorts"

    # --- Engine 2: yt-dlp Download ---
    print(f"  📥 yt-dlp: {yt_dlp_target}")
    cmd = [
        "yt-dlp", yt_dlp_target,
        "--extractor-args", "youtube:player_client=ios,web,android",
        "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "-o", output_path,
        "--max-downloads", "1",
        "--no-playlist",
        "--quiet",
        "--no-warnings",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 5000:
            print(f"  ✅ yt-dlp succeeded.")
            return output_path
    except Exception:
        pass

    print(f"  ⚠️ yt-dlp blocked/failed.")
    return None

def process_video_clip(video_path, duration):
    """
    Crops and grades a downloaded video clip to 1080×1920.
    Returns a MoviePy clip.
    """
    sub_clip = VideoFileClip(video_path)
    max_start = max(0, sub_clip.duration - duration)
    start_t = random.uniform(0, max_start) if max_start > 0 else 0
    end_t = min(start_t + duration, sub_clip.duration)
    snippet = sub_clip.subclip(start_t, end_t)

    # Fit to 1920 height, then centre-crop to 1080 width
    snippet = snippet.resize(height=VIDEO_H)
    if snippet.w > VIDEO_W:
        x_center = snippet.w / 2
        snippet = snippet.crop(x1=x_center - VIDEO_W // 2, x2=x_center + VIDEO_W // 2, y1=0, y2=VIDEO_H)
    elif snippet.w < VIDEO_W:
        # Pad with black on sides
        pad = ColorClip(size=(VIDEO_W, VIDEO_H), color=(0, 0, 0), duration=duration)
        snippet = CompositeVideoClip([pad, snippet.set_position("center")], size=(VIDEO_W, VIDEO_H))

    # Add vignette overlay
    vignette_arr = build_vignette(VIDEO_W, VIDEO_H)
    vig_clip = (
        ImageClip(vignette_arr, ismask=False)
        .set_duration(duration)
        .set_position((0, 0))
    )

    return CompositeVideoClip([snippet.set_duration(duration), vig_clip], size=(VIDEO_W, VIDEO_H))

# ==========================================
# 3. SCENE-BY-SCENE ASSEMBLY
# ==========================================
def assemble_storyboard(storyboard_data):
    print("--- [Step 3/5] Processing and Assembling Scenes ---")

    youtube_api_key = clean_env(os.getenv("YOUTUBE_API_KEY"))
    youtube_client = None
    if youtube_api_key:
        try:
            youtube_client = build("youtube", "v3", developerKey=youtube_api_key, cache_discovery=False)
        except Exception:
            pass

    # Clean up old clips
    templates_dir = "motion_templates"
    os.makedirs(templates_dir, exist_ok=True)
    for old_file in glob.glob(os.path.join(templates_dir, "*.mp4")):
        try:
            os.remove(old_file)
        except Exception:
            pass
    for old_file in glob.glob(os.path.join(templates_dir, "*.jpg")):
        try:
            os.remove(old_file)
        except Exception:
            pass

    video_segments = []
    audio_segments = []

    for idx, scene in enumerate(storyboard_data["scenes"]):
        narration = scene["narration"]
        query = scene["query"]
        print(f"\n🎬 Scene {idx + 1}/{len(storyboard_data['scenes'])}: '{query}'")

        # --- Voiceover ---
        audio_filename = f"scene_{idx + 1}.mp3"
        asyncio.run(generate_scene_voiceover(narration, audio_filename))
        scene_audio = AudioFileClip(audio_filename)
        dur = scene_audio.duration
        audio_segments.append(scene_audio)

        # --- Try real gameplay video first ---
        visual_clip = None
        video_path = fetch_video_clip(query, f"clip_{idx + 1}.mp4", youtube_client)
        if video_path:
            try:
                visual_clip = process_video_clip(video_path, dur)
                print(f"  🎮 Using real gameplay footage.")
            except Exception as e:
                print(f"  ⚠️ Video processing failed: {e}")
                visual_clip = None

        # --- AI image fallback (2 frames with Ken Burns) ---
        if visual_clip is None:
            print(f"  🖼️  Generating AI cinematic frames...")
            img_paths = fetch_ai_images(query, idx, count=2)
            if img_paths:
                visual_clip = build_visual_clip_from_images(img_paths, dur)
                print(f"  🎨 AI visual clip built from {len(img_paths)} frame(s).")
            else:
                print(f"  ⚠️  All visuals failed. Using dark fallback.")
                visual_clip = ColorClip(size=(VIDEO_W, VIDEO_H), color=(10, 10, 20), duration=dur)

        # --- Add captions ---
        caption = make_caption_clip(narration, dur)
        layers = [visual_clip.set_duration(dur)]
        if caption is not None:
            layers.append(caption)

        composite = CompositeVideoClip(layers, size=(VIDEO_W, VIDEO_H)).set_duration(dur)
        composite = composite.set_audio(scene_audio)

        # Crossfade into previous scene
        if video_segments:
            composite = composite.fx(fadein, CROSSFADE_DUR)
        video_segments.append(composite)

    # ==========================================
    # 4. FINAL ASSEMBLY
    # ==========================================
    print("\n--- [Step 4/5] Rendering Final MP4 ---")
    final_video = concatenate_videoclips(video_segments, method="compose")

    # Background music mix
    bgm_folder = "bgm"
    os.makedirs(bgm_folder, exist_ok=True)
    mp3_files = [f for f in os.listdir(bgm_folder) if f.endswith(".mp3")]
    combined_voice = concatenate_audioclips(audio_segments) if len(audio_segments) > 1 else audio_segments[0]
    target_duration = combined_voice.duration

    if mp3_files:
        bg_music = AudioFileClip(os.path.join(bgm_folder, random.choice(mp3_files)))
        if bg_music.duration < target_duration:
            loops = math.ceil(target_duration / bg_music.duration)
            bg_music = concatenate_audioclips([bg_music] * loops).subclip(0, target_duration)
        else:
            bg_music = bg_music.subclip(0, target_duration)
        bg_music = bg_music.volumex(0.12)
        final_audio = CompositeAudioClip([combined_voice, bg_music])
    else:
        final_audio = combined_voice

    final_video = final_video.set_audio(final_audio)

    print("🎞️  Rendering final_short.mp4 ...")
    final_video.write_videofile(
        "final_short.mp4",
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        threads=4,
        preset="fast",
        logger=None
    )
    print("✅ Video assembly complete: final_short.mp4\n")

# ==========================================
# 5. YOUTUBE UPLOAD
# ==========================================
def upload_to_youtube(storyboard_data):
    print("--- [Step 5/5] Uploading to YouTube as Short ---")

    client_id = clean_env(os.getenv("CLIENT_ID"))
    client_secret = clean_env(os.getenv("CLIENT_SECRET"))
    refresh_token = clean_env(os.getenv("REFRESH_TOKEN"))

    if not client_id or not client_secret or not refresh_token:
        print("🚨 ERROR: YouTube API secrets are missing!")
        return

    try:
        credentials = google.oauth2.credentials.Credentials(
            None,
            refresh_token=refresh_token,
            token_uri=get_safe_url("google_token"),
            client_id=client_id,
            client_secret=client_secret,
        )

        youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
        title = storyboard_data.get("title", "Blox Fruits Madness!")
        first_scene_text = storyboard_data["scenes"][0]["narration"]

        body = {
            "snippet": {
                "title": f"{title} #Shorts",
                "description": f"{first_scene_text}\n\n#Shorts #Roblox #BloxFruits #Gaming",
                "tags": ["Roblox", "BloxFruits", "Shorts", "Gaming", "Gameplay"],
                "categoryId": "20",
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload("final_short.mp4", chunksize=-1, resumable=True)
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"  ⏳ Uploading: {int(status.progress() * 100)}%")

        final_url = f"{get_safe_url('youtube_short')}{response.get('id')}"
        print(f"🎉 Upload Successful!\n   URL: {final_url}")

    except Exception as e:
        print(f"🚨 CRITICAL ERROR during upload: {e}")
        raise e

# ==========================================
# 6. MAIN
# ==========================================
def main():
    print("=== 🎬 Scene-by-Scene Director Pipeline (Enhanced) ===\n")
    storyboard_data = generate_storyboard()
    assemble_storyboard(storyboard_data)
    upload_to_youtube(storyboard_data)
    print("\n=== ✅ Pipeline Complete! Short is Live. ===")

if __name__ == "__main__":
    main()
