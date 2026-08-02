"""
Roblox Shorts Pipeline — Paper-Animation Edition
================================================
Visuals emulate old-school hand-drawn animators:
  • Rotoscope hand-drawn OVER Roblox characters (blocky avatars kept, ink outlines added)
  • Classic 2D cel-shading, flat colours, textured paper background
  • Real frame-by-frame motion (no Ken-Burns slideshow feel)

Engine order (per scene):
  A. FAL.ai text-to-video       [DISABLED — commented out for speed]
  B. HuggingFace text-to-video  [DISABLED — commented out for speed]
  C. Pollinations AI — 24 sequential frames, locked seed, cel-anim style  <-- ACTIVE
  D. HuggingFace FLUX images    [DISABLED — commented out for speed]
  E. Dezgo free SD images       [DISABLED — commented out for speed]
  F. Local assets (final safety net)
"""

import os
import random
import json
import requests
import asyncio
import edge_tts
import glob
import math
import numpy as np

os.environ["IMAGEMAGICK_BINARY"] = "/usr/bin/convert"

from PIL import Image, ImageEnhance
from moviepy.editor import (
    CompositeVideoClip, AudioFileClip, CompositeAudioClip,
    TextClip, concatenate_videoclips, concatenate_audioclips, ColorClip,
)
from moviepy.video.VideoClip import VideoClip
from groq import Groq
import google.oauth2.credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────────
VIDEO_W, VIDEO_H = 1080, 1920
FPS = 24
CAPTION_Y_FRAC = 0.82
CAPTION_FONTSIZE = 58
CAPTION_FONT = "Liberation-Sans-Bold"

# Paper-animation timing:
#   FRAMES_PER_SCENE  = how many drawings we generate per scene
#   FRAME_HOLD        = how long each drawing is held on screen (seconds)
#   Effective anim FPS = 1 / FRAME_HOLD  (0.4s = 2.5fps ≈ classic anime "on 3s")
FRAMES_PER_SCENE = 24          # ~10s scene / 0.4s hold = 24 drawings
FRAME_HOLD = 0.40              # feels hand-drawn without looking too jerky
FRAME_XFADE = 0.05             # tiny 50ms dissolve → still crisp cel-style hard-cut feel
PAPER_WOBBLE_PX = 6            # random 1-6px per-frame offset = hand-drawn quiver

# Progressive action beats — describe the SAME motion at 24 stages
# Pollinations reads these as "draw frame N of a continuous animation"
FRAME_STAGES = [
    "frame 1 of 24, still pose, character standing calm, eyes narrowing",
    "frame 2 of 24, character begins to shift weight, subtle tension",
    "frame 3 of 24, breath in, chest expanding, aura starts glowing faintly",
    "frame 4 of 24, hands lowering, fingers spreading, energy gathering",
    "frame 5 of 24, one leg steps back, battle stance forming",
    "frame 6 of 24, arms rising slightly, small motion blur on hands",
    "frame 7 of 24, aura brightens around body, hair starts lifting",
    "frame 8 of 24, mouth opens in shout, veins on neck visible",
    "frame 9 of 24, arms fully raised, energy sphere forming between palms",
    "frame 10 of 24, character crouches, ready to launch",
    "frame 11 of 24, explosive push-off, ground cracks below feet",
    "frame 12 of 24, mid-leap, body angled forward, cape/coat trailing",
    "frame 13 of 24, apex of jump, arm winding back for strike",
    "frame 14 of 24, arm swinging down, speed lines behind fist",
    "frame 15 of 24, strike connecting, white impact flash starting",
    "frame 16 of 24, peak impact, energy shockwave radiating outward",
    "frame 17 of 24, follow-through, body twisting from momentum",
    "frame 18 of 24, landing on one knee, dust cloud rising",
    "frame 19 of 24, slowly standing, breathing hard, aura fading",
    "frame 20 of 24, straightening up, eyes glowing with power",
    "frame 21 of 24, wind blowing hair and clothes sideways",
    "frame 22 of 24, calm exhale, small smirk forming",
    "frame 23 of 24, camera pulls back slightly, epic wide angle",
    "frame 24 of 24, final heroic pose, aura settling, dramatic hold",
]

# Paper / cel-animation style prompts — one is picked per scene for consistency
PAPER_STYLE_VARIANTS = [
    ("hand-drawn cel animation frame, rotoscoped over blocky Roblox avatar, "
     "thick black ink outlines, flat cel-shading with 2-tone lighting, "
     "textured off-white paper background with faint pencil lines, "
     "classic 90s anime look, Studio Ghibli x Roblox aesthetic"),
    ("traditional 2D animation cel, Roblox blocky character drawn by hand, "
     "clean ink lineart, flat vivid colours, subtle paper grain texture, "
     "hand-painted background, old-school Saturday-morning cartoon style"),
    ("frame from a hand-drawn animated short, Roblox avatar redrawn as 2D anime, "
     "bold black outlines, cel-shaded flat colours, aged paper texture, "
     "visible pencil under-sketch marks, retro cel animation aesthetic"),
    ("rotoscope animation drawn over Roblox 3D game footage, ink pen linework, "
     "flat gouache-style colour fills, warm beige paper background, "
     "slight registration wobble like real hand-drawn frames"),
]

ASSET_DIR = "assets"
ASSET_MAP = {
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

def pick_assets_for_query(query, count=FRAMES_PER_SCENE):
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
# CHARACTER-AWARE PROMPT BUILDER  (paper-animation edition)
# ──────────────────────────────────────────────────────────────────────────────
def build_paper_prompt(query, narration, character_bible, frame_stage, paper_style):
    """
    Builds a Pollinations prompt that:
      1. Injects the paper/cel-anim style
      2. Injects character clothing/features from the bible
      3. Adds the CURRENT progressive frame beat (frame N of 24)
    Everything else (scene content, camera) stays constant across all 24 frames
    so we get true animation, not a slideshow.
    """
    narration_lower = narration.lower()
    mentioned_chars = []
    for char_name, char_data in character_bible.items():
        if char_name.lower() in narration_lower:
            clothes = char_data.get("clothes", "")
            features = char_data.get("facial_features", "")
            mentioned_chars.append(f"{char_name} ({clothes}, {features})")

    char_part = ""
    if mentioned_chars:
        char_part = "featuring " + " and ".join(mentioned_chars) + ", "

    return (
        f"{paper_style}, {char_part}{query}, {frame_stage}, "
        "consistent character design, same background, same camera angle, "
        "vertical portrait 9:16 composition, no watermarks, no text overlay"
    )

# ──────────────────────────────────────────────────────────────────────────────
# PAPER GRADING — warm paper tone + slight desaturation
# ──────────────────────────────────────────────────────────────────────────────
def _paper_grade(pil_img):
    img = pil_img.convert("RGB")
    img = ImageEnhance.Brightness(img).enhance(1.02)
    img = ImageEnhance.Contrast(img).enhance(1.10)
    img = ImageEnhance.Color(img).enhance(0.92)   # slight desat for cel look
    return img

# ──────────────────────────────────────────────────────────────────────────────
# PAPER-ANIMATION CLIP — hard-cut frames + tiny wobble = hand-drawn feel
# ──────────────────────────────────────────────────────────────────────────────
def build_paper_animation_clip(img_paths, duration):
    """
    Old-school animator style:
      - Each drawing held for FRAME_HOLD seconds (default 0.4s)
      - Tiny per-frame pixel wobble simulates hand-drawn registration jitter
      - Loops the frame sequence if scene is longer than frames × hold
      - Uses hard cuts (or 50ms micro-dissolve) — NO Ken-Burns pan/zoom
    """
    if not img_paths:
        return ColorClip(size=(VIDEO_W, VIDEO_H),
                         color=(245, 235, 215),   # warm paper cream
                         duration=duration)

    print(f"    🖌 Loading {len(img_paths)} hand-drawn frames...")
    frames = []
    for path in img_paths:
        pil = _paper_grade(Image.open(path).convert("RGB"))
        # Fit to 1080x1920, cover-crop centre
        scale = max(VIDEO_W / pil.width, VIDEO_H / pil.height)
        sw, sh = int(pil.width * scale), int(pil.height * scale)
        pil = pil.resize((sw, sh), Image.LANCZOS)
        x0 = (sw - VIDEO_W) // 2
        y0 = (sh - VIDEO_H) // 2
        pil = pil.crop((x0, y0, x0 + VIDEO_W, y0 + VIDEO_H))
        frames.append(np.array(pil))

    n = len(frames)
    # Per-frame random wobble offsets — locked at build time so it's deterministic
    wobbles = [(random.randint(-PAPER_WOBBLE_PX, PAPER_WOBBLE_PX),
                random.randint(-PAPER_WOBBLE_PX, PAPER_WOBBLE_PX))
               for _ in range(n)]

    # Paper cream background so wobble edges don't show black
    bg = np.full((VIDEO_H, VIDEO_W, 3), (245, 235, 215), dtype=np.uint8)

    def make_frame(t):
        # Which drawing are we on?
        idx = int(t / FRAME_HOLD) % n
        frame = frames[idx]
        dx, dy = wobbles[idx]

        # Micro-dissolve into next frame (last FRAME_XFADE of each hold)
        into_next = (t % FRAME_HOLD) - (FRAME_HOLD - FRAME_XFADE)
        if into_next > 0 and idx + 1 < n:
            alpha = into_next / FRAME_XFADE
            nxt = frames[(idx + 1) % n]
            frame = (frame.astype(np.float32) * (1 - alpha)
                     + nxt.astype(np.float32) * alpha).astype(np.uint8)

        # Apply wobble by pasting onto paper bg
        canvas = bg.copy()
        x1 = max(0, dx);   x2 = min(VIDEO_W, VIDEO_W + dx)
        y1 = max(0, dy);   y2 = min(VIDEO_H, VIDEO_H + dy)
        sx1 = max(0, -dx); sx2 = sx1 + (x2 - x1)
        sy1 = max(0, -dy); sy2 = sy1 + (y2 - y1)
        canvas[y1:y2, x1:x2] = frame[sy1:sy2, sx1:sx2]
        return canvas

    clip = VideoClip(make_frame, duration=duration)
    clip.fps = FPS
    return clip

# ══════════════════════════════════════════════════════════════════════════════
# DISABLED ENGINES  (kept in file, easy to re-enable — just uncomment)
# ══════════════════════════════════════════════════════════════════════════════
# ── ENGINE A — FAL.AI text-to-video  [DISABLED] ───────────────────────────────
# def fetch_fal_video(prompt, out_path, api_keys):
#     ...  (original code in git history commit 0527f61 — restore to bring back)
#
# ── ENGINE B — HuggingFace text-to-video  [DISABLED] ──────────────────────────
# def fetch_hf_video(prompt, out_path, api_keys):
#     ...
#
# ── ENGINE D — HuggingFace FLUX images  [DISABLED] ────────────────────────────
# def fetch_huggingface_image(prompt, out_path, api_keys):
#     ...
#
# ── ENGINE E — Dezgo images  [DISABLED] ───────────────────────────────────────
# def fetch_dezgo_image(prompt, out_path):
#     ...

# ──────────────────────────────────────────────────────────────────────────────
# ENGINE C — POLLINATIONS: 24 sequential paper-animation frames  (ACTIVE)
# ──────────────────────────────────────────────────────────────────────────────
def fetch_pollinations_paper_frames(base_query, narration, character_bible,
                                    count, out_dir, prefix):
    """
    Generates `count` consecutive drawings for ONE scene.
    All frames share:
      • The same locked seed  → same character, same background, same angle
      • The same paper/cel-anim style  → consistent art direction
    Only the frame stage differs → real motion instead of slideshow.
    """
    scene_seed = random.randint(10_000, 9_999_999)
    paper_style = random.choice(PAPER_STYLE_VARIANTS)
    print(f"    🎲 Scene seed locked: {scene_seed}")
    print(f"    🎨 Style: {paper_style[:60]}...")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://pollinations.ai/",
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
    }

    paths = []
    for i in range(count):
        stage = FRAME_STAGES[i % len(FRAME_STAGES)]
        prompt = build_paper_prompt(base_query, narration, character_bible,
                                    stage, paper_style)
        encoded = requests.utils.quote(prompt)
        url = (
            f"https://image.pollinations.ai/prompt/{encoded}"
            f"?width=1080&height=1920&nologo=true&seed={scene_seed}&model=flux"
        )
        out_path = os.path.join(out_dir, f"{prefix}_{i:02d}.jpg")
        try:
            resp = requests.get(url, headers=headers, timeout=90, stream=True)
            if (resp.status_code == 200
                    and "image" in resp.headers.get("content-type", "")):
                with open(out_path, "wb") as f:
                    for chunk in resp.iter_content(8192):
                        f.write(chunk)
                if os.path.exists(out_path) and os.path.getsize(out_path) > 5000:
                    print(f"    ✅ Frame {i + 1:02d}/{count}")
                    paths.append(out_path)
                    continue
            print(f"    ⚠️ Frame {i + 1:02d} failed "
                  f"(status {resp.status_code}) — skipping.")
        except Exception as e:
            print(f"    ⚠️ Frame {i + 1:02d} error: {e} — skipping.")
    return paths

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
    print("    ⚠️ Caption rendering failed — skipping.")
    return None

# ──────────────────────────────────────────────────────────────────────────────
# SCENE VISUAL FETCHER — Pollinations-only pipeline
# ──────────────────────────────────────────────────────────────────────────────
def fetch_scene_visual(scene, scene_idx, character_bible, templates_dir):
    query = scene["query"]
    narration = scene["narration"]
    dur = scene.get("duration", 10)

    frames_needed = max(6, math.ceil(dur / FRAME_HOLD))
    frames_needed = min(frames_needed, FRAMES_PER_SCENE)

    print(f"    🎬 Pollinations paper-anim: generating "
          f"{frames_needed} hand-drawn frames for {dur:.1f}s scene...")

    poll_paths = fetch_pollinations_paper_frames(
        query, narration, character_bible,
        count=frames_needed,
        out_dir=templates_dir,
        prefix=f"paper_{scene_idx}",
    )
    if poll_paths:
        print(f"    ✅ {len(poll_paths)} drawings ready → "
              f"building paper-animation clip.")
        return build_paper_animation_clip(poll_paths, dur)

    print(f"    📁 Pollinations failed — falling back to local assets.")
    asset_paths = pick_assets_for_query(query, count=6)
    if asset_paths:
        return build_paper_animation_clip(asset_paths, dur)

    return ColorClip(size=(VIDEO_W, VIDEO_H),
                     color=(245, 235, 215), duration=dur)

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
You are an unhinged, viral AI director for a serialized Roblox Blox Fruits YouTube Shorts saga.

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
    {{"narration": "Scene 3 text...", "query": "Mysterious Figure roblox blox fruits dark aura reveal", "duration": 10}},
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
        max_tokens=1800,
        temperature=0.92,
    )

    raw = resp.choices[0].message.content.strip()

    if "```" in raw:
        parts = raw.split("```")
        if len(parts) >= 3:
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

    if not raw.endswith("}"):
        raise ValueError(
            f"Groq response appears truncated (does not end with '}}').\n"
            f"Last 100 chars: {raw[-100:]}"
        )

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

    templates_dir = "motion_templates"
    os.makedirs(templates_dir, exist_ok=True)
    for f in glob.glob(os.path.join(templates_dir, "*")):
        try:
            os.remove(f)
        except Exception:
            pass

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

        audio_file = f"scene_{idx + 1}.mp3"
        asyncio.run(generate_voiceover(narration, audio_file))
        scene_audio = AudioFileClip(audio_file)
        actual_dur = scene_audio.duration
        scene["duration"] = actual_dur
        audio_segments.append(scene_audio)
        print(f"    🔊 Voiceover: {actual_dur:.1f}s")

        visual = fetch_scene_visual(
            scene, idx, character_bible, templates_dir
        ).set_duration(actual_dur)

        caption = make_caption_clip(narration, actual_dur)
        layers = [visual]
        if caption:
            layers.append(caption)

        scene_clip = CompositeVideoClip(layers, size=(VIDEO_W, VIDEO_H))
        scene_clip = (scene_clip
                      .set_duration(actual_dur)
                      .set_audio(scene_audio))

        video_segments.append(scene_clip)

    print("\n─── [4/5] Final Render ───")
    final_video = concatenate_videoclips(video_segments, method="compose")

    bgm_folder = "bgm"
    os.makedirs(bgm_folder, exist_ok=True)
    mp3_files = [f for f in os.listdir(bgm_folder) if f.endswith(".mp3")]
    combined_voice = (
        concatenate_audioclips(audio_segments)
        if len(audio_segments) > 1 else audio_segments[0]
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

    print("🎞 Rendering final_short.mp4 ...")
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

    client_id = clean_env(os.getenv("CLIENT_ID"))
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
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    title = storyboard_data.get("title", "Blox Fruits Madness!")
    hook = storyboard_data["scenes"][0]["narration"]

    body = {
        "snippet": {
            "title": f"{title} #Shorts",
            "description": f"{hook}\n\n#Shorts #Roblox #BloxFruits #Gaming #RobloxShorts #Animation",
            "tags": ["Roblox", "BloxFruits", "Shorts", "Gaming",
                     "Roblox Shorts", "Blox Fruits", "Animation"],
            "categoryId": "20",
        },
        "status": {
            "privacyStatus": "public", "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload("final_short.mp4", chunksize=-1, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = req.next_chunk()
        if status:
            print(f"    ⏳ Uploading: {int(status.progress() * 100)}%")

    print(f"🎉 Uploaded! https://youtube.com/shorts/{response.get('id')}")

# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  Roblox Auto-Shorts — Paper-Animation Edition")
    print("=" * 60 + "\n")

    storyboard = generate_storyboard()
    assemble_storyboard(storyboard)
    upload_to_youtube(storyboard)

    print("\n🏁 Pipeline complete.")

if __name__ == "__main__":
    main()
