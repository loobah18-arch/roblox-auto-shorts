"""
Roblox Auto-Shorts — Frame-Compile Edition
==========================================
Each scene's images are written as individual JPEG frame files and compiled
into video by ffmpeg at 24fps — exactly like a game engine or animation
software does it.

  8 images per scene × 4 scenes = 32 Pollinations requests (~30-40 min)
  Each image is held for (scene_duration / 8) × 24 = N video frames
  e.g. 6-second scene → 8 images → each image = 18 video frames = 0.75s hold
  Result: 8fps animation rate playing inside a 24fps video

  Cross-dissolve frames written between source images so transitions are
  smooth rather than hard-cut (pixel blend across 6 intermediate frames).

Engine order:
  C. Pollinations AI  ← PRIMARY  (free, no key)
  D. Dezgo SD         ← FALLBACK (free, no key)
  E. Local assets     ← LAST RESORT
"""

import os, time, random, json, math, requests, asyncio, edge_tts
import glob, subprocess, shutil
import numpy as np

os.environ["IMAGEMAGICK_BINARY"] = "/usr/bin/convert"

from PIL import Image, ImageEnhance
from moviepy.editor import (
    CompositeVideoClip, AudioFileClip, CompositeAudioClip,
    TextClip, concatenate_videoclips, concatenate_audioclips,
    ColorClip, VideoFileClip,
)
from groq import Groq
import google.oauth2.credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
VIDEO_W, VIDEO_H  = 1080, 1920
FPS               = 24
CAPTION_Y_FRAC    = 0.82
CAPTION_FONTSIZE  = 58
CAPTION_FONT      = "Liberation-Sans-Bold"

# 8 source images per scene — compiled as real frames at 24fps
# e.g. 6s scene: 8 images × 18 frames each = 144 frames total @ 24fps
FRAMES_PER_SCENE  = 8

# Crossfade: N blend frames written between every pair of source images
# Makes hard cuts look like smooth animation transitions
BLEND_STEPS       = 6   # 6 intermediate frames = 0.25s smooth crossfade @ 24fps

# Pollinations back-off
POLL_DELAY_OK     = 2
POLL_DELAY_429    = 20
POLL_MAX_RETRY    = 3
POLL_TIMEOUT      = 90

# ─────────────────────────────────────────────────────────────────────────────
# ROBLOX STYLE PROMPTS
# ─────────────────────────────────────────────────────────────────────────────
ROBLOX_STYLE_VARIANTS = [
    ("Roblox Blox Fruits game screenshot, blocky low-poly 3D avatar, "
     "bright colorful island world, vivid saturated game colors, "
     "plastic shiny textures, dramatic sky"),
    ("Roblox Blox Fruits gameplay render, blocky character model with accessories, "
     "colorful tropical game environment, bright game lighting, Roblox studio aesthetic"),
    ("Roblox animated cutscene, blocky avatar with outfit and hat, "
     "vivid Blox Fruits world, bright ocean and island background, "
     "game-accurate blocky proportions"),
    ("Roblox Blox Fruits official art style, colorful blocky characters, "
     "bright neon energy effects, tropical sea battle environment, "
     "game screenshot composition"),
]

NEGATIVE_PROMPT = (
    "realistic,photorealistic,detailed human face,anime lineart,manga,"
    "dark background,monochrome,horror,photograph,detailed anatomy,painting,sketch"
)

# 8 short frame stage descriptors — kept SHORT so locked seed keeps
# character consistent between frames (long text changes character design)
FRAME_STAGES = [
    "idle standing",
    "noticing threat, tense",
    "powering up, aura glow",
    "charging forward, rush",
    "mid-air attack leap",
    "strike impact, shockwave",
    "landing from impact",
    "dramatic aftermath pose",
]

ASSET_DIR = "assets"
ASSET_MAP = {
    "island":["ancient_island.jpg","jungle_island.jpg","volcano_island.jpg"],
    "jungle":["jungle_island.jpg"],
    "volcano":["volcano_island.jpg"],
    "ancient":["ancient_island.jpg"],
    "fortress":["fortress.jpg"],
    "ocean":["ocean_battle.jpg","sea.jpg"],
    "sea":["sea.jpg","ocean_battle.jpg"],
    "battle":["ocean_battle.jpg","fortress.jpg"],
    "underwater":["underwater_city.jpg"],
    "city":["underwater_city.jpg"],
    "monster":["monster_mutation.jpg"],
    "mutation":["monster_mutation.jpg"],
    "roblox":["roblox_landscape.jpg"],
    "landscape":["roblox_landscape.jpg"],
}
ALL_ASSETS = [
    "roblox_landscape.jpg","ancient_island.jpg","jungle_island.jpg",
    "ocean_battle.jpg","fortress.jpg","volcano_island.jpg",
    "underwater_city.jpg","sea.jpg","monster_mutation.jpg",
]

# ─────────────────────────────────────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────────────────────────────────────
def clean_env(val):
    if not val: return ""
    val = val.strip()
    if val.startswith("[") and "]" in val:
        val = val.split("]")[0].lstrip("[")
    return val.strip("'\"")

def pick_assets_for_query(query, count=FRAMES_PER_SCENE):
    q = query.lower()
    matched = []
    for kw, files in ASSET_MAP.items():
        if kw in q: matched.extend(files)
    if not matched: matched = ALL_ASSETS[:]
    random.shuffle(matched)
    selected = list(dict.fromkeys(matched))[:count]
    pool = [f for f in ALL_ASSETS if f not in selected]
    random.shuffle(pool)
    while len(selected) < count and pool:
        selected.append(pool.pop())
    return [os.path.join(ASSET_DIR, f) for f in selected
            if os.path.exists(os.path.join(ASSET_DIR, f))]

def load_and_fit(path):
    """Load image → resize to 1080×1920 cover crop → boost saturation."""
    pil = Image.open(path).convert("RGB")
    scale = max(VIDEO_W / pil.width, VIDEO_H / pil.height)
    pil = pil.resize((int(pil.width*scale), int(pil.height*scale)), Image.LANCZOS)
    x0 = (pil.width  - VIDEO_W) // 2
    y0 = (pil.height - VIDEO_H) // 2
    pil = pil.crop((x0, y0, x0+VIDEO_W, y0+VIDEO_H))
    pil = ImageEnhance.Brightness(pil).enhance(1.05)
    pil = ImageEnhance.Contrast(pil).enhance(1.12)
    pil = ImageEnhance.Color(pil).enhance(1.20)
    return np.array(pil)

# ─────────────────────────────────────────────────────────────────────────────
# FRAME COMPILER — the core of the new animation system
# ─────────────────────────────────────────────────────────────────────────────
def compile_frames_to_video(img_paths, duration, out_path):
    """
    Writes source images + crossfade blend frames as individual JPEG files,
    then calls ffmpeg to compile them into a silent .mp4 at 24fps.

    Layout for 3 source images with BLEND_STEPS=6:
      [img0] [blend01×6] [img1] [blend12×6] [img2]
      Total unique frames = 3 + 2×6 = 15

    Each "hold" frame is repeated to fill the target duration.
    """
    if not img_paths:
        # Generate a plain dark clip and return it as a file
        _write_blank_video(out_path, duration)
        return

    # Load all source images
    arrays = [load_and_fit(p) for p in img_paths]
    n = len(arrays)

    # Build the full frame sequence (source + blends)
    frame_sequence = []
    for i, arr in enumerate(arrays):
        frame_sequence.append(arr)
        if i < n - 1:
            nxt = arrays[i + 1]
            for step in range(1, BLEND_STEPS + 1):
                alpha = step / (BLEND_STEPS + 1)
                blend = (arr.astype(np.float32) * (1 - alpha)
                         + nxt.astype(np.float32) * alpha).astype(np.uint8)
                frame_sequence.append(blend)

    total_unique = len(frame_sequence)
    total_video_frames = max(int(duration * FPS), total_unique)

    # Spread unique frames across video frames — each source frame repeated equally
    frames_per_unique = total_video_frames / total_unique

    frame_dir = out_path.replace(".mp4", "_frames")
    os.makedirs(frame_dir, exist_ok=True)

    print(f"    🖼  Writing {total_unique} unique frames → "
          f"{total_video_frames} video frames @ {FPS}fps ...")

    video_frame_idx = 0
    for unique_idx, arr in enumerate(frame_sequence):
        # How many video frames does this unique frame occupy?
        start = round(unique_idx * frames_per_unique)
        end   = round((unique_idx + 1) * frames_per_unique)
        count = max(1, end - start)
        pil   = Image.fromarray(arr)
        for _ in range(count):
            pil.save(
                os.path.join(frame_dir, f"f{video_frame_idx:07d}.jpg"),
                quality=92,
            )
            video_frame_idx += 1

    # Compile with ffmpeg
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(FPS),
        "-i", os.path.join(frame_dir, "f%07d.jpg"),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "22",
        "-t", str(duration),   # trim to exact scene duration
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr}")

    shutil.rmtree(frame_dir)
    print(f"    ✅ Scene video compiled: {out_path}")

def _write_blank_video(out_path, duration):
    """Write a plain dark video clip as a fallback."""
    total = max(1, int(duration * FPS))
    frame_dir = out_path.replace(".mp4", "_blank_frames")
    os.makedirs(frame_dir, exist_ok=True)
    blank = Image.new("RGB", (VIDEO_W, VIDEO_H), (10, 10, 30))
    blank.save(os.path.join(frame_dir, "f0000000.jpg"))
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", os.path.join(frame_dir, "f0000000.jpg"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-t", str(duration), "-r", str(FPS),
        out_path,
    ]
    subprocess.run(cmd, capture_output=True)
    shutil.rmtree(frame_dir)

# ─────────────────────────────────────────────────────────────────────────────
# PROMPT BUILDER
# ─────────────────────────────────────────────────────────────────────────────
def build_roblox_prompt(query, narration, character_bible, frame_stage, style):
    narration_lower = narration.lower()
    char_parts = []
    for name, data in character_bible.items():
        if name.lower() in narration_lower:
            clothes = data.get("clothes", "")
            char_parts.append(f"{name} Roblox avatar wearing {clothes}")
    char_part = (", ".join(char_parts) + ", ") if char_parts else ""
    return (
        f"{style}, {char_part}{query}, {frame_stage}, "
        "same character same background same camera angle, "
        "9:16 vertical portrait, no watermarks, no UI text"
    )

# ─────────────────────────────────────────────────────────────────────────────
# ENGINE C — POLLINATIONS
# ─────────────────────────────────────────────────────────────────────────────
def fetch_pollinations_frames(base_query, narration, character_bible,
                              count, out_dir, prefix):
    scene_seed  = random.randint(10_000, 9_999_999)
    style       = random.choice(ROBLOX_STYLE_VARIANTS)
    neg_enc     = requests.utils.quote(NEGATIVE_PROMPT)

    print(f"    🎲 Seed: {scene_seed}  |  Style: {style[:55]}...")

    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0.0.0 Safari/537.36"),
        "Referer": "https://pollinations.ai/",
        "Accept":  "image/webp,image/apng,image/*,*/*;q=0.8",
    }

    paths = []
    for i in range(count):
        stage   = FRAME_STAGES[i % len(FRAME_STAGES)]
        prompt  = build_roblox_prompt(base_query, narration, character_bible,
                                      stage, style)
        encoded = requests.utils.quote(prompt)
        url = (f"https://image.pollinations.ai/prompt/{encoded}"
               f"?width=1080&height=1920&nologo=true"
               f"&seed={scene_seed}&model=flux&negative={neg_enc}")
        out_path = os.path.join(out_dir, f"{prefix}_{i:02d}.jpg")

        success = False
        for attempt in range(1, POLL_MAX_RETRY + 1):
            try:
                resp = requests.get(url, headers=headers,
                                    timeout=POLL_TIMEOUT, stream=True)
                if resp.status_code == 429:
                    print(f"    ⏳ Frame {i+1:02d} 429 "
                          f"(attempt {attempt}/{POLL_MAX_RETRY}) — "
                          f"sleeping {POLL_DELAY_429}s...")
                    time.sleep(POLL_DELAY_429)
                    continue
                if (resp.status_code == 200
                        and "image" in resp.headers.get("content-type", "")):
                    with open(out_path, "wb") as f:
                        for chunk in resp.iter_content(8192):
                            f.write(chunk)
                    if os.path.getsize(out_path) > 5000:
                        print(f"    ✅ Frame {i+1:02d}/{count}")
                        paths.append(out_path)
                        success = True
                        break
                    time.sleep(5)
                    continue
                print(f"    ⚠️  Frame {i+1:02d} HTTP {resp.status_code} — retrying 10s...")
                time.sleep(10)
            except requests.exceptions.Timeout:
                print(f"    ⚠️  Frame {i+1:02d} timeout "
                      f"(attempt {attempt}/{POLL_MAX_RETRY}) — sleeping 30s...")
                time.sleep(30)
            except Exception as e:
                print(f"    ⚠️  Frame {i+1:02d} error: {e} — retrying 10s...")
                time.sleep(10)

        if success and i < count - 1:
            time.sleep(POLL_DELAY_OK)
        elif not success:
            print(f"    ❌ Frame {i+1:02d} gave up after {POLL_MAX_RETRY} attempts.")

    return paths

# ─────────────────────────────────────────────────────────────────────────────
# ENGINE D — DEZGO FALLBACK
# ─────────────────────────────────────────────────────────────────────────────
def fetch_dezgo_frames(base_query, narration, character_bible,
                       count, out_dir, prefix):
    print(f"    🔄 Dezgo fallback: {count} frames...")
    headers = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36")}
    narration_lower = narration.lower()
    char_parts = []
    for name, data in character_bible.items():
        if name.lower() in narration_lower:
            char_parts.append(f"{name} Roblox avatar wearing {data.get('clothes','')}")
    char_str = (", ".join(char_parts) + ", ") if char_parts else ""

    paths = []
    for i in range(count):
        stage = FRAME_STAGES[i % len(FRAME_STAGES)]
        prompt = (f"Roblox Blox Fruits game screenshot, blocky 3D avatar, "
                  f"bright colorful game world, {char_str}{base_query}, {stage}, "
                  "9:16 portrait, no watermarks")
        out_path = os.path.join(out_dir, f"{prefix}_dz_{i:02d}.jpg")
        for attempt in range(1, 3):
            try:
                resp = requests.post(
                    "https://api.dezgo.com/text2image",
                    data={"prompt": prompt,
                          "negative_prompt": "realistic,photorealistic,anime,dark,human face",
                          "model": "dreamshaper_8",
                          "width": 540, "height": 960,
                          "steps": 25, "guidance": 7.5},
                    headers=headers, timeout=60,
                )
                if resp.status_code == 200 and len(resp.content) > 5000:
                    with open(out_path, "wb") as f: f.write(resp.content)
                    print(f"    ✅ Dezgo frame {i+1:02d}/{count}")
                    paths.append(out_path)
                    break
                time.sleep(8)
            except Exception as e:
                print(f"    ⚠️  Dezgo frame {i+1:02d}: {e}")
                time.sleep(8)
        time.sleep(2)
    return paths

# ─────────────────────────────────────────────────────────────────────────────
# CAPTION
# ─────────────────────────────────────────────────────────────────────────────
def make_caption_clip(text, duration):
    for font in (CAPTION_FONT, "Liberation-Sans"):
        try:
            txt = TextClip(text, font=font, fontsize=CAPTION_FONTSIZE,
                           color="white", stroke_color="black", stroke_width=4,
                           size=(VIDEO_W-100, None), method="caption", align="center")
            return txt.set_duration(duration).set_position(
                ("center", int(VIDEO_H * CAPTION_Y_FRAC)))
        except Exception:
            continue
    return None

# ─────────────────────────────────────────────────────────────────────────────
# SCENE VISUAL — fetches images then compiles to video file
# ─────────────────────────────────────────────────────────────────────────────
def fetch_scene_visual(scene, scene_idx, character_bible, work_dir):
    query, narration, dur = scene["query"], scene["narration"], scene.get("duration", 10)
    scene_video_path = os.path.join(work_dir, f"scene_{scene_idx}_visual.mp4")

    # Engine C: Pollinations
    print(f"    🎬 [Engine C] Pollinations — {FRAMES_PER_SCENE} frames for {dur:.1f}s scene...")
    paths = fetch_pollinations_frames(query, narration, character_bible,
                                      FRAMES_PER_SCENE, work_dir, f"p{scene_idx}")
    if not paths:
        print("    📡 Pollinations 0 frames — trying Dezgo...")
        paths = fetch_dezgo_frames(query, narration, character_bible,
                                   FRAMES_PER_SCENE, work_dir, f"d{scene_idx}")
    if not paths:
        print("    📁 All engines failed — using local assets.")
        paths = pick_assets_for_query(query, count=FRAMES_PER_SCENE)

    compile_frames_to_video(paths, dur, scene_video_path)
    return VideoFileClip(scene_video_path)

# ─────────────────────────────────────────────────────────────────────────────
# 1. GROQ STORYBOARD
# ─────────────────────────────────────────────────────────────────────────────
def generate_storyboard():
    print("─── [1/5] Groq Story Director ───")
    api_key = clean_env(os.getenv("GROQ_API_KEY"))
    if not api_key:
        raise Exception("Missing GROQ_API_KEY!")

    client = Groq(api_key=api_key)
    history_file, bible_file = "story_memory.txt", "character_bible.json"

    previous_context = "Episode 1. Start with a shocking hook about Roblox Blox Fruits."
    character_context = "{}"

    if os.path.exists(history_file):
        c = open(history_file).read().strip()
        if c: previous_context = c
    if os.path.exists(bible_file):
        b = open(bible_file).read().strip()
        if b: character_context = b

    prompt = f"""
You are an unhinged, viral AI director for a serialized Roblox Blox Fruits YouTube Shorts saga.

PREVIOUS EPISODE CONTEXT:
{previous_context}

CHARACTER BIBLE:
{character_context}

TASK: Write the NEXT part of the story as exactly 4 scenes (~130-150 words total). End on a cliffhanger.
Each scene needs a visual QUERY with CHARACTER NAMES and Roblox setting.

IMPORTANT: In character_bible describe characters using Roblox avatar terms ONLY:
outfit colors, hat type, accessory names (e.g. "red vest, straw hat accessory, scar face decal").
Do NOT use realistic descriptions like "dark robes" or "glowing eyes" — those make the AI generate
a realistic dark character instead of a blocky Roblox avatar.

Output ONLY this JSON (no markdown fences):
{{
  "title": "Short catchy title",
  "scenes": [
    {{"narration": "...", "query": "Luffy roblox blox fruits dough awakening sea battle", "duration": 10}},
    {{"narration": "...", "query": "Shanks Big Mom roblox blox fruits boss fight", "duration": 10}},
    {{"narration": "...", "query": "Mysterious Figure roblox blox fruits aura reveal", "duration": 10}},
    {{"narration": "...", "query": "Luffy roblox blox fruits max level pvp cliffhanger", "duration": 10}}
  ],
  "character_bible": {{
    "CharacterName": {{
      "clothes": "red vest, straw hat accessory",
      "facial_features": "scar face decal under left eye",
      "personality": "determined"
    }}
  }}
}}
"""
    resp = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1800, temperature=0.92,
    )
    raw = resp.choices[0].message.content.strip()
    if "```" in raw:
        parts = raw.split("```")
        if len(parts) >= 3:
            raw = parts[1]
            if raw.startswith("json"): raw = raw[4:]
            raw = raw.strip()
    if not raw.endswith("}"):
        raise ValueError(f"Groq response truncated. Last 100: {raw[-100:]}")

    data = json.loads(raw)
    open(history_file, "w").write(" ".join(s["narration"] for s in data["scenes"]))
    json.dump(data.get("character_bible", {}), open(bible_file, "w"), indent=4)
    print(f"🎬 Title: {data.get('title')}")
    print(f"📌 {len(data['scenes'])} scenes.\n")
    return data

# ─────────────────────────────────────────────────────────────────────────────
# 2. VOICEOVER
# ─────────────────────────────────────────────────────────────────────────────
async def generate_voiceover(text, out_file):
    await edge_tts.Communicate(text, "en-US-ChristopherNeural", rate="+10%").save(out_file)

# ─────────────────────────────────────────────────────────────────────────────
# 3. ASSEMBLY
# ─────────────────────────────────────────────────────────────────────────────
def assemble_storyboard(storyboard_data):
    print("─── [3/5] Scene Assembly ───")

    work_dir = "motion_templates"
    os.makedirs(work_dir, exist_ok=True)
    for f in glob.glob(os.path.join(work_dir, "*")):
        try: os.remove(f)
        except: pass

    character_bible = {}
    if os.path.exists("character_bible.json"):
        try: character_bible = json.load(open("character_bible.json"))
        except: pass

    video_segments, audio_segments = [], []

    for idx, scene in enumerate(storyboard_data["scenes"]):
        narration = scene["narration"]
        print(f"\n🎬 Scene {idx+1}/{len(storyboard_data['scenes'])}: {scene['query']}")

        # Voiceover
        audio_file = f"scene_{idx+1}.mp3"
        asyncio.run(generate_voiceover(narration, audio_file))
        scene_audio = AudioFileClip(audio_file)
        actual_dur = scene_audio.duration
        scene["duration"] = actual_dur
        audio_segments.append(scene_audio)
        print(f"    🔊 Voiceover: {actual_dur:.1f}s")

        # Visual — images compiled as frames
        visual = fetch_scene_visual(scene, idx, character_bible, work_dir)
        visual = visual.set_duration(actual_dur)

        # Caption
        caption = make_caption_clip(narration, actual_dur)
        layers  = [visual] + ([caption] if caption else [])

        scene_clip = (CompositeVideoClip(layers, size=(VIDEO_W, VIDEO_H))
                      .set_duration(actual_dur)
                      .set_audio(scene_audio))
        video_segments.append(scene_clip)

    print("\n─── [4/5] Final Render ───")
    final_video = concatenate_videoclips(video_segments, method="compose")

    bgm_folder = "bgm"
    os.makedirs(bgm_folder, exist_ok=True)
    mp3_files = [f for f in os.listdir(bgm_folder) if f.endswith(".mp3")]
    combined_voice = (concatenate_audioclips(audio_segments)
                      if len(audio_segments) > 1 else audio_segments[0])

    if mp3_files:
        bg = AudioFileClip(os.path.join(bgm_folder, random.choice(mp3_files)))
        dur = combined_voice.duration
        if bg.duration < dur:
            loops = math.ceil(dur / bg.duration)
            bg = concatenate_audioclips([bg] * loops).subclip(0, dur)
        else:
            bg = bg.subclip(0, dur)
        final_audio = CompositeAudioClip([combined_voice, bg.volumex(0.10)])
    else:
        final_audio = combined_voice

    final_video = final_video.set_audio(final_audio)
    print("🎞  Rendering final_short.mp4 ...")
    final_video.write_videofile(
        "final_short.mp4", fps=FPS,
        codec="libx264", audio_codec="aac",
        threads=4, preset="fast", logger=None,
    )
    print("✅ Render complete.\n")

# ─────────────────────────────────────────────────────────────────────────────
# 5. YOUTUBE UPLOAD
# ─────────────────────────────────────────────────────────────────────────────
def upload_to_youtube(storyboard_data):
    print("─── [5/5] YouTube Upload ───")
    client_id     = clean_env(os.getenv("CLIENT_ID"))
    client_secret = clean_env(os.getenv("CLIENT_SECRET"))
    refresh_token = clean_env(os.getenv("REFRESH_TOKEN"))

    if not all([client_id, client_secret, refresh_token]):
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
            "title": f"{title} #Shorts",
            "description": f"{hook}\n\n#Shorts #Roblox #BloxFruits #Gaming #RobloxShorts",
            "tags": ["Roblox","BloxFruits","Shorts","Gaming","Roblox Shorts","Animation"],
            "categoryId": "20",
        },
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
    }
    media    = MediaFileUpload("final_short.mp4", chunksize=-1, resumable=True)
    req      = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = req.next_chunk()
        if status: print(f"    ⏳ {int(status.progress()*100)}%")
    print(f"🎉 Uploaded! https://youtube.com/shorts/{response.get('id')}")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    print("="*60)
    print("  Roblox Auto-Shorts — Frame-Compile Edition")
    print("="*60 + "\n")
    storyboard = generate_storyboard()
    assemble_storyboard(storyboard)
    upload_to_youtube(storyboard)
    print("\n🏁 Pipeline complete.")

if __name__ == "__main__":
    main()
