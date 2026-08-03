"""
Roblox Auto-Shorts — Agnes 2.0 Edition (v7.3)
Powered by Agnes AI (Gemini Free Tier)
===============================================
NO PAID APIs REQUIRED. Works entirely on free services:
 • Gemini Free Tier (image + story generation)
 • Pollinations AI (free images, no key)
 • Edge-TTS (free voiceover)
 • Local assets (your own images)

Paid engines (HF, Together) are disabled by default.
"""

import os, time, random, json, math, requests, asyncio, edge_tts
import glob, subprocess, shutil, re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

os.environ["IMAGEMAGICK_BINARY"] = "/usr/bin/convert"
import numpy as np

import moviepy.audio.fx as afx
from moviepy import (
    CompositeVideoClip, AudioFileClip, CompositeAudioClip,
    TextClip, concatenate_videoclips, concatenate_audioclips,
    ColorClip, VideoFileClip, ImageClip,
)
from PIL import Image, ImageEnhance, ImageDraw, ImageFont

# ─── FREE MODE CONFIG ───────────────────────────────────────────────────────
FREE_MODE = True  # Set False only if you have paid API keys

# Try to import Gemini new SDK, but don't crash if not installed
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    print("⚠️ google-genai not installed. Run: pip install google-genai")

# ─── VIDEO CONFIG ───────────────────────────────────────────────────────────
VIDEO_W, VIDEO_H = 1080, 1920
FPS = 24
CAPTION_Y_FRAC = 0.70
CAPTION_FONTSIZE = 78
WORDS_PER_CHUNK = 4
KEN_BURNS_ZOOM = 0.30

# Free image engines (in order of preference)
FREE_IMAGE_ENGINES = ["agnes", "pollinations", "local"]

# Pollinations (completely free, no key)
POLL_DELAY_OK = 2
POLL_DELAY_429 = 25
POLL_MAX_RETRY = 4
POLL_TIMEOUT = 90

GAME_STATE_FILE = "game_state.json"

# ─── GEMINI FREE TIER SETUP ─────────────────────────────────────────────────
_AGNES_CLIENT = None

def init_agnes():
    """Initialize Agnes 2.0 AI Engine using new google-genai SDK."""
    global _AGNES_CLIENT
    if _AGNES_CLIENT is not None:
        return True
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not gemini_key or gemini_key.startswith("["):
        return False
    if GEMINI_AVAILABLE:
        try:
            # New SDK: auto-picks up GEMINI_API_KEY from environment
            _AGNES_CLIENT = genai.Client()
            return True
        except Exception as e:
            print(f"⚠️ Gemini client init failed: {e}")
            return False
    return False

def agnes_generate_image(prompt: str) -> bytes:
    """Generate image using Gemini Imagen via new google-genai SDK."""
    if not init_agnes():
        return None
    try:
        response = _AGNES_CLIENT.models.generate_content(
            model="gemini-2.0-flash-exp-image-generation",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["image", "text"]
            )
        )
        for part in response.parts:
            if part.inline_data:
                return part.inline_data.data
    except Exception as e:
        print(f" ⚠️ Agnes 2.0 image error: {e}")
    return None

def agnes_generate_story(game_config, episode_number, previous_context, character_bible):
    """Generate story using Gemini 2.0 Flash free tier via new SDK."""
    if not init_agnes():
        return None

    today = datetime.utcnow().strftime("%B %d, %Y")
    ex = game_config["scene_examples"]
    genre = game_config["genre"]

    char_desc = ""
    if character_bible:
        char_desc = json.dumps(character_bible, indent=2)

    system_instruction = (
        f"You are a viral TikTok/YouTube Shorts writer for Roblox {game_config['display_name']}. "
        f"Today's date is {today}. Write exactly 5 scenes. Scene 5 must end on a cliffhanger. "
        f"Output ONLY valid JSON — no markdown, no explanations."
    )

    prompt = f"""GAME: {game_config['display_name']} ({genre})
EPISODE: {episode_number}
PREVIOUS: {previous_context}
CHARACTERS: {char_desc}

Write a 5-scene storyboard.

Format:
{{
  "title": "Catchy episode title (max 50 chars)",
  "real_life_reference": "A trending meme or news story that fits the plot",
  "scenes": [
    {{
      "narration": "2-3 dramatic sentences. Present tense. Cliffhanger energy.",
      "query": "Short image prompt, max 10 words, no full sentences",
      "duration": 8
    }}
  ]
}}

Rules:
- Exactly 5 scenes
- Narration sounds like a viral TikTok storyteller
- Each query is SHORT (max 10 words) for image generation
- Scene 5 must end on a cliffhanger
- Keep story continuity from PREVIOUS
"""
    try:
        response = _AGNES_CLIENT.models.generate_content(
            model="gemini-2.0-flash",  # ← FIXED: was gemini-2.5-flash (404 error)
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.7,
                max_output_tokens=8192,
            )
        )
        raw = response.text.strip()
        return safe_json_loads(raw)
    except Exception as e:
        print(f" ⚠️ Gemini story error: {e}")
        return None

# ─── ROBLOX GAME CATALOG ────────────────────────────────────────────────────
ROBLOX_GAMES = {
    "blox_fruits": {
        "display_name": "Blox Fruits",
        "genre": "action RPG, open-world sea adventure",
        "image_style": (
            "Roblox Blox Fruits game, blocky low-poly 3D avatar, "
            "tropical colorful sea island world, vivid neon fruit powers, "
            "plastic shiny textures, dramatic ocean background"
        ),
        "hashtags": ["#BloxFruits", "#Roblox", "#Shorts", "#Gaming"],
        "scene_examples": [
            "Luffy blox fruits dough awakening sea battle",
            "Shanks blox fruits sword clash island boss",
            "Mysterious Figure blox fruits aura reveal",
            "max level pvp fruit showdown cliffhanger",
        ],
        "starter_context": (
            "A new pirate wakes up on Starter Island with no fruit power. "
            "Legendary Devil Fruits wait in the sea."
        ),
    },
    "adopt_me": {
        "display_name": "Adopt Me!",
        "genre": "trading, pet collecting, family roleplay",
        "image_style": (
            "Roblox Adopt Me! game, blocky cute 3D avatar, "
            "colorful pastel Adoption Island world, adorable pixel pets, "
            "bright cheerful neighborhood, neon trade signs"
        ),
        "hashtags": ["#AdoptMe", "#Roblox", "#Shorts", "#Gaming"],
        "scene_examples": [
            "rare neon unicorn pet trade Adopt Me island",
            "shadow dragon scam drama Adopt Me school",
            "legendary pet hatch egg reveal Adopt Me",
            "mega neon fly ride pet auction cliffhanger",
        ],
        "starter_context": (
            "A new player joins Adopt Me with a starter egg. "
            "The Neon Shadow Dragon is rumored at the trading plaza."
        ),
    },
    "murder_mystery_2": {
        "display_name": "Murder Mystery 2",
        "genre": "thriller, whodunit, survival horror",
        "image_style": (
            "Roblox Murder Mystery 2 game, blocky detective avatar, "
            "dark moody map with neon lighting, knife glint effects, "
            "sheriff badge glow, dramatic shadows, tense atmosphere"
        ),
        "hashtags": ["#MM2", "#MurderMystery2", "#Roblox", "#Shorts"],
        "scene_examples": [
            "sheriff chasing murderer MM2 dark warehouse",
            "innocent discovers body MM2 haunted mansion",
            "murderer reveal plot twist MM2 school map",
            "last survivor sheriff showdown MM2 cliffhanger",
        ],
        "starter_context": (
            "A new Murder Mystery 2 game starts on a dark stormy map. "
            "Nobody knows who the murderer is yet."
        ),
    },
    "pet_simulator_x": {
        "display_name": "Pet Simulator X",
        "genre": "idle collecting, pet evolution, trading battles",
        "image_style": (
            "Roblox Pet Simulator X game, blocky avatar, "
            "colorful floating islands coin world, giant glowing pets, "
            "rainbow explosion effects, huge coin stacks, vivid neon background"
        ),
        "hashtags": ["#PetSimX", "#PetSimulatorX", "#Roblox", "#Shorts"],
        "scene_examples": [
            "giant rainbow unicorn pet destroy coins PSX island",
            "exclusive titanic cat unboxing surprise PSX",
            "dark matter pet reveal trading arena PSX",
            "world record pet damage cliffhanger PSX boss",
        ],
        "starter_context": (
            "A new collector enters Pet Simulator X with a basic dog pet. "
            "Rumors of a Titanic Dark Matter cat spread."
        ),
    },
    "doors": {
        "display_name": "Doors",
        "genre": "horror survival, puzzle escape",
        "image_style": (
            "Roblox Doors game, blocky horror avatar, "
            "dark eerie hotel corridor, flickering neon lights, "
            "glowing red entity eyes, dramatic shadow horror atmosphere"
        ),
        "hashtags": ["#RobloxDoors", "#Doors", "#Roblox", "#Shorts"],
        "scene_examples": [
            "Rush entity sprint Door 50 Doors horror hotel",
            "Seek floor chase escape Doors dark corridor",
            "Figure encounter library Door 100 Doors survival",
            "Ambush entity jumpscare Doors cliffhanger finale",
        ],
        "starter_context": (
            "Players enter the haunted Hotel in Roblox Doors. "
            "The lights flicker at Door 1. Something watches."
        ),
    },
    "arsenal": {
        "display_name": "Arsenal",
        "genre": "FPS action, kill streaks, weapon unlocks",
        "image_style": (
            "Roblox Arsenal FPS game, blocky soldier avatar, "
            "colorful fast-paced arena map, neon gun effects, "
            "kill streak explosion, bright vivid game arena"
        ),
        "hashtags": ["#RobloxArsenal", "#Arsenal", "#Roblox", "#Shorts"],
        "scene_examples": [
            "insane 360 no-scope Arsenal FPS arena final kill",
            "golden knife unlock Arsenal locker room reveal",
            "juggernaut last kill Arsenal rooftop showdown",
            "clutch 1v5 win Arsenal tournament finals cliffhanger",
        ],
        "starter_context": (
            "A new soldier joins their first Arsenal ranked match. "
            "The Golden Knife kill is 1 point away."
        ),
    },
    "anime_adventures": {
        "display_name": "Anime Adventures",
        "genre": "tower defense, anime crossover, wave survival",
        "image_style": (
            "Roblox Anime Adventures game, blocky anime-style 3D avatar, "
            "colorful tower defense map, glowing anime unit effects, "
            "massive energy beam attacks, vivid neon skill explosions"
        ),
        "hashtags": ["#AnimeAdventures", "#Roblox", "#Shorts", "#Gaming"],
        "scene_examples": [
            "secret 6-star unit summon Anime Adventures reveal",
            "final wave boss destroy Anime Adventures tower map",
            "ultra instinct unit evolution Anime Adventures arena",
            "legendary crossover unit unlocked cliffhanger Anime Adventures",
        ],
        "starter_context": (
            "A new commander places first units in Anime Adventures. "
            "Wave 50 is incoming. A secret 6-star summon appears."
        ),
    },
    "brookhaven": {
        "display_name": "Brookhaven RP",
        "genre": "social roleplay, drama, life simulation",
        "image_style": (
            "Roblox Brookhaven RP game, blocky avatar, "
            "colorful suburban neighborhood world, luxury mansion background, "
            "sports cars, school setting, bright cheerful town atmosphere"
        ),
        "hashtags": ["#Brookhaven", "#BrookhavenRP", "#Roblox", "#Shorts"],
        "scene_examples": [
            "secret millionaire reveal Brookhaven luxury mansion",
            "high school drama rivalry Brookhaven school hallway",
            "undercover agent mission Brookhaven town bank",
            "shocking plot twist family reunion Brookhaven cliffhanger",
        ],
        "starter_context": (
            "A mysterious resident moves into the most expensive house "
            "in Brookhaven. Their secret past is unknown."
        ),
    },
}

GAME_ORDER = list(ROBLOX_GAMES.keys())

NEGATIVE_PROMPT = (
    "flat lighting,dull colors,2D,anime lineart,realistic human proportions,"
    "photograph,ugly,pixelated,low resolution,dark background,monochrome,horror faces,"
    "sketch,watermark,text overlay,blurry,realistic skin,detailed human anatomy"
)

ASSET_DIR = "assets"
ALL_ASSETS = [
    "roblox_landscape.jpg", "ancient_island.jpg", "jungle_island.jpg",
    "ocean_battle.jpg", "fortress.jpg", "volcano_island.jpg",
    "underwater_city.jpg", "sea.jpg", "monster_mutation.jpg",
]

KEN_BURNS_CONFIGS = [
    {"zoom": "in", "pan": "center"},
    {"zoom": "out", "pan": "center"},
    {"zoom": "in", "pan": "top"},
    {"zoom": "in", "pan": "bottom"},
    {"zoom": "out", "pan": "center"},
]

# ─── GAME STATE ─────────────────────────────────────────────────────────────
def load_game_state():
    if os.path.exists(GAME_STATE_FILE):
        try:
            with open(GAME_STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"game_index": 0, "episode_counts": {g: 0 for g in GAME_ORDER}}

def save_game_state(state):
    with open(GAME_STATE_FILE, "w") as f:
        json.dump(state, f, indent=4)

def advance_game_state(state):
    state["game_index"] = (state["game_index"] + 1) % len(GAME_ORDER)

def get_current_game(state):
    return GAME_ORDER[state["game_index"] % len(GAME_ORDER)]

def game_memory_file(game_slug):
    return f"story_memory_{game_slug}.txt"

def game_bible_file(game_slug):
    return f"character_bible_{game_slug}.json"

# ─── UTILITIES ──────────────────────────────────────────────────────────────
def clean_env(val):
    if not val:
        return ""
    val = val.strip()
    if val.startswith("[") and "]" in val:
        val = val.split("]")[0].lstrip("[")
    return val.strip("'\"")

def find_font():
    candidates = [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    result = subprocess.run(
        ["find", "/usr/share/fonts", "-name", "*.ttf", "-type", "f"],
        capture_output=True, text=True,
    )
    fonts = [l.strip() for l in result.stdout.splitlines() if l.strip()]
    return fonts[0] if fonts else None

def pick_local_asset():
    pool = [os.path.join(ASSET_DIR, f) for f in ALL_ASSETS
            if os.path.exists(os.path.join(ASSET_DIR, f))]
    return random.choice(pool) if pool else None

def safe_json_loads(raw_text, default=None):
    text = raw_text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        fixed = text.replace("'", '"').replace("\n", " ")
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass
    return default

def get_next_version_filename(base_name="final_short", ext=".mp4"):
    existing = glob.glob(f"{base_name}_v*.{ext}")
    if not existing:
        return f"{base_name}_v1.{ext}"
    nums = []
    for f in existing:
        match = re.search(rf'{base_name}_v(\d+)\.{ext}$', f)
        if match:
            nums.append(int(match.group(1)))
    next_num = max(nums, default=0) + 1
    return f"{base_name}_v{next_num}.{ext}"

# ─── KEN BURNS ──────────────────────────────────────────────────────────────
def compile_ken_burns_video(img_path, duration, out_path, zoom="in", pan="center"):
    total_frames = max(int(duration * FPS), 1)
    zoom_range = KEN_BURNS_ZOOM
    delta = zoom_range / total_frames

    if zoom == "in":
        z_expr = f"min(zoom+{delta:.8f},1.{int(zoom_range*100):02d})"
    else:
        z_expr = f"if(eq(on,1),1.{int(zoom_range*100):02d},max(zoom-{delta:.8f},1.0))"

    if pan == "center":
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
    elif pan == "top":
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = f"max(ih*0.05,ih/2-(ih/zoom/2)-ih*0.25*(1-on/{total_frames}))"
    else:
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = f"min(ih*0.70,ih/2-(ih/zoom/2)+ih*0.20*(1-on/{total_frames}))"

    vf = (
        f"scale={VIDEO_W * 2}:{VIDEO_H * 2},"
        f"zoompan="
        f"z='{z_expr}':"
        f"x='{x_expr}':"
        f"y='{y_expr}':"
        f"d={total_frames}:"
        f"s={VIDEO_W}x{VIDEO_H}:"
        f"fps={FPS}"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", img_path,
        "-vf", vf,
        "-t", str(duration),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "20",
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Ken Burns ffmpeg failed:\n{result.stderr[:400]}")
    print(f" ✅ Ken Burns done: {out_path}")

def _write_blank_video(out_path, duration):
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=black:s={VIDEO_W}x{VIDEO_H}:r={FPS}",
        "-t", str(duration),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        out_path,
    ]
    subprocess.run(cmd, capture_output=True)

# ─── FREE IMAGE ENGINES ─────────────────────────────────────────────────────
def fetch_pollinations_image(base_query, game_config, out_dir, prefix):
    """100% free image generation via Pollinations AI."""
    scene_seed = random.randint(10_000, 9_999_999)
    neg_enc = requests.utils.quote(NEGATIVE_PROMPT)
    style = game_config["image_style"]
    prompt = f"{style}, {base_query}, dramatic action scene, 9:16 portrait"
    encoded = requests.utils.quote(prompt[:400])
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width=1080&height=1920&nologo=true"
        f"&seed={scene_seed}&model=flux&negative={neg_enc}"
    )
    out_path = os.path.join(out_dir, f"{prefix}_pol.jpg")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://pollinations.ai/",
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
    }

    for attempt in range(1, POLL_MAX_RETRY + 1):
        try:
            print(f" 🌸 Pollinations attempt {attempt}/{POLL_MAX_RETRY}...")
            resp = requests.get(url, headers=headers, timeout=POLL_TIMEOUT, stream=True)

            if resp.status_code == 429:
                wait = POLL_DELAY_429 * attempt
                print(f" ⏳ Rate limited — waiting {wait}s...")
                time.sleep(wait)
                continue

            if resp.status_code == 200 and "image" in resp.headers.get("content-type", ""):
                with open(out_path, "wb") as f:
                    for chunk in resp.iter_content(8192):
                        f.write(chunk)
                size_kb = os.path.getsize(out_path) // 1024
                if size_kb > 5:
                    print(f" ✅ Pollinations: {size_kb} KB")
                    time.sleep(POLL_DELAY_OK)
                    return out_path
                print(f" ⚠️ Tiny response ({size_kb} KB) — retrying...")

            time.sleep(8)
        except requests.exceptions.Timeout:
            print(f" ⏳ Timeout — waiting 30s...")
            time.sleep(30)
        except Exception as e:
            print(f" ⚠️ Error: {e}")
            time.sleep(5)

    print(" ❌ Pollinations failed")
    return None

def fetch_agnes_image(base_query, game_config, out_dir, prefix):
    """Free image generation via Gemini Imagen 3."""
    print(" 🎨 Agnes 2.0 Imagen Engine...")
    style = game_config["image_style"]
    prompt = f"High quality digital art: {style}, {base_query}. Cinematic lighting, vibrant colors, 9:16 vertical format, game screenshot style."

    img_bytes = agnes_generate_image(prompt)
    if not img_bytes:
        return None

    out_path = os.path.join(out_dir, f"{prefix}_gemini.jpg")
    with open(out_path, "wb") as f:
        f.write(img_bytes)
    size_kb = os.path.getsize(out_path) // 1024
    print(f" ✅ Agnes 2.0: {size_kb} KB")
    return out_path

def fetch_scene_visual(scene, idx, game_config, work_dir):
    """Free-only visual cascade: Gemini → Pollinations → Local."""
    base_query = scene["query"]
    dur = scene.get("duration", 10)
    prefix = f"scene_{idx + 1}"
    out_path = os.path.join(work_dir, f"{prefix}_visual.mp4")
    kb = KEN_BURNS_CONFIGS[idx % len(KEN_BURNS_CONFIGS)]

    # Engine 1: Gemini (free tier)
    if not FREE_MODE or init_agnes():
        img_path = fetch_agnes_image(base_query, game_config, work_dir, prefix)
        if img_path:
            try:
                compile_ken_burns_video(img_path, dur, out_path, **kb)
                return VideoFileClip(out_path)
            except Exception as e:
                print(f" ⚠️ Ken Burns failed on Gemini image: {e}")
                print(" ↩ Gemini failed — trying Pollinations...")
        else:
            print(" ⏭️ Agnes 2.0 image not available")
    else:
        print(" ⏭️ Agnes 2.0 not available (no API key)")

    # Engine 2: Pollinations (always free)
    img_path = fetch_pollinations_image(base_query, game_config, work_dir, prefix)
    if img_path:
        try:
            compile_ken_burns_video(img_path, dur, out_path, **kb)
            return VideoFileClip(out_path)
        except Exception as e:
            print(f" ⚠️ Ken Burns failed on Pollinations: {e}")
            print(" ↩ Pollinations failed — using local assets...")

    # Engine 3: Local assets (guaranteed free)
    local_path = pick_local_asset()
    if local_path:
        try:
            compile_ken_burns_video(local_path, dur, out_path, **kb)
            return VideoFileClip(out_path)
        except Exception as e:
            print(f" ⚠️ Ken Burns failed on local: {e}")

    # Last resort: black
    print(" ⚠️ All engines failed — black placeholder")
    _write_blank_video(out_path, dur)
    return VideoFileClip(out_path)

# ─── VOICEOVER (FREE) ───────────────────────────────────────────────────────
async def generate_voiceover(text, out_file):
    comm = edge_tts.Communicate(text, voice="en-US-ChristopherNeural", rate="+10%")
    await comm.save(out_file)

# ─── STORYBOARD (FREE) ──────────────────────────────────────────────────────
def generate_storyboard(game_slug, game_config, episode_number):
    """Generate storyboard using free APIs only."""

    mem_file = game_memory_file(game_slug)
    bible_file = game_bible_file(game_slug)

    previous_context = game_config["starter_context"]
    character_bible = {}

    if os.path.exists(mem_file):
        try:
            with open(mem_file) as f:
                c = f.read().strip()
                if c:
                    previous_context = c
        except Exception:
            pass

    if os.path.exists(bible_file):
        try:
            with open(bible_file) as f:
                character_bible = json.load(f)
        except Exception:
            try:
                with open(bible_file) as f:
                    raw = f.read().strip()
                    if raw:
                        character_bible = {"description": raw}
            except Exception:
                pass

    # Try Gemini first (free tier)
    if init_agnes():
        try:
            print(" 🤖 Agnes 2.0 Story Director (free tier) for story...")
            result = agnes_generate_story(game_config, episode_number, previous_context, character_bible)
            if result and "scenes" in result:
                print(f" ✅ Agnes 2.0 story: {result.get('title', '?')}")
                return result
        except Exception as e:
            print(f" ⚠️ Agnes 2.0 story failed: {e}")
    else:
        print(" ⏭️ Agnes 2.0 not available (set GEMINI_API_KEY for AI stories)")

    # Template fallback (always works, 100% free)
    print(" 📋 Using template storyboard (free, no AI needed)")
    ex = game_config["scene_examples"]
    return {
        "title": f"{game_config['display_name']} Adventure Ep {episode_number}",
        "real_life_reference": "A mysterious new challenge appears",
        "scenes": [
            {
                "narration": f"Welcome back to {game_config['display_name']}! Something incredible is about to happen that nobody saw coming.",
                "query": ex[0] if len(ex) > 0 else f"{game_config['display_name']} action scene",
                "duration": 8
            },
            {
                "narration": "The adventure continues with unexpected twists and turns that keep everyone on the edge of their seat.",
                "query": ex[1] if len(ex) > 1 else f"{game_config['display_name']} dramatic scene",
                "duration": 8
            },
            {
                "narration": "Things are getting intense. Can our hero survive this impossible challenge? The odds are stacked against them.",
                "query": ex[2] if len(ex) > 2 else f"{game_config['display_name']} intense scene",
                "duration": 8
            },
            {
                "narration": "A shocking revelation changes everything we thought we knew. The truth is finally revealed.",
                "query": ex[3] if len(ex) > 3 else ex[0] if len(ex) > 0 else f"{game_config['display_name']} reveal scene",
                "duration": 8
            },
            {
                "narration": "The cliffhanger ending leaves everyone speechless. What happens next? Subscribe to find out in the next episode!",
                "query": ex[0] if len(ex) > 0 else f"{game_config['display_name']} cliffhanger",
                "duration": 8
            },
        ]
    }

# ─── CAPTIONS ───────────────────────────────────────────────────────────────
_FONT_PATH = None

def make_caption_clips(text, duration):
    global _FONT_PATH
    if _FONT_PATH is None:
        _FONT_PATH = find_font()
    if _FONT_PATH is None:
        print(" ⚠️ No font found — captions skipped")
        return []

    words = text.split()
    chunks = [
        " ".join(words[i: i + WORDS_PER_CHUNK])
        for i in range(0, len(words), WORDS_PER_CHUNK)
    ]
    if not chunks:
        return []

    time_per_chunk = duration / len(chunks)
    clips = []

    for ci, chunk in enumerate(chunks):
        start = ci * time_per_chunk
        try:
            txt = TextClip(
                text=chunk,
                font=_FONT_PATH,
                font_size=CAPTION_FONTSIZE,
                color="white",
                stroke_color="black",
                stroke_width=5,
                size=(VIDEO_W - 80, None),
                method="caption",
                text_align="center",
            )
            clips.append(
                txt
                .with_start(start)
                .with_duration(time_per_chunk - 0.05)
                .with_position(("center", int(VIDEO_H * CAPTION_Y_FRAC)))
            )
        except Exception as e:
            print(f" ⚠️ Caption error: {e}")

    print(f" 💬 {len(clips)} caption chunks")
    return clips

# ─── THUMBNAIL ──────────────────────────────────────────────────────────────
def generate_thumbnail(video_path, storyboard_data, out_path="thumbnail.jpg"):
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-ss", "00:00:01",
            "-vframes", "1",
            "-q:v", "2",
            out_path,
        ]
        subprocess.run(cmd, capture_output=True)

        if not os.path.exists(out_path):
            return None

        img = Image.open(out_path).convert("RGB")
        draw = ImageDraw.Draw(img)

        title = storyboard_data.get("title", "Roblox Short!")
        font_path = find_font()
        if font_path:
            try:
                font = ImageFont.truetype(font_path, 60)
            except:
                font = ImageFont.load_default()
        else:
            font = ImageFont.load_default()

        text = f"{title} #Shorts"
        x, y = VIDEO_W // 2, VIDEO_H // 3

        for dx, dy in [(-2,-2), (-2,2), (2,-2), (2,2), (0,-2), (0,2), (-2,0), (2,0)]:
            draw.text((x+dx, y+dy), text, font=font, fill="black", anchor="mm")
        draw.text((x, y), text, font=font, fill="white", anchor="mm")

        img.save(out_path, quality=95)
        print(f" ✅ Thumbnail: {out_path}")
        return out_path
    except Exception as e:
        print(f" ⚠️ Thumbnail failed: {e}")
        return None

# ─── ASSEMBLY ───────────────────────────────────────────────────────────────
def assemble_storyboard(storyboard_data, game_slug, game_config):
    print("─── [3/4] Scene Assembly ───")

    work_dir = "motion_templates"
    os.makedirs(work_dir, exist_ok=True)
    for f in glob.glob(os.path.join(work_dir, "*")):
        try:
            os.remove(f)
        except OSError:
            pass

    video_segments, audio_segments = [], []
    temp_audio_files = []

    for idx, scene in enumerate(storyboard_data["scenes"]):
        narration = scene["narration"]
        print(f"\n 🎬 Scene {idx+1}/{len(storyboard_data['scenes'])}")

        audio_file = f"scene_{idx+1}.mp3"
        temp_audio_files.append(audio_file)

        print(" 🔊 Generating voiceover...")
        asyncio.run(generate_voiceover(narration, audio_file))
        scene_audio = AudioFileClip(audio_file)
        actual_dur = scene_audio.duration
        scene["duration"] = actual_dur
        audio_segments.append(scene_audio)
        print(f" ✅ Voiceover: {actual_dur:.1f}s")

        print(" 🎨 Generating visual...")
        visual = fetch_scene_visual(scene, idx, game_config, work_dir)
        visual = visual.with_duration(actual_dur)

        caption_clips = make_caption_clips(narration, actual_dur)

        layers = [visual] + caption_clips
        scene_clip = (
            CompositeVideoClip(layers, size=(VIDEO_W, VIDEO_H))
            .with_duration(actual_dur)
            .with_audio(scene_audio)
        )
        video_segments.append(scene_clip)

    print("\n─── [4/4] Final Render ───")
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
            bg = concatenate_audioclips([bg] * loops).subclipped(0, dur)
        else:
            bg = bg.subclipped(0, dur)

        final_audio = CompositeAudioClip([
            combined_voice,
            bg.with_effects([afx.MultiplyVolume(factor=0.10)]),
        ])
    else:
        final_audio = combined_voice

    final_video = final_video.with_audio(final_audio)

    output_file = get_next_version_filename("final_short", "mp4")
    print(f" 🎞 Rendering {output_file}...")
    final_video.write_videofile(
        output_file, fps=FPS,
        codec="libx264", audio_codec="aac",
        threads=4, preset="ultrafast", logger=None,
    )
    print(f" ✅ Done: {output_file}")

    # Thumbnail
    generate_thumbnail(output_file, storyboard_data)

    # Update memory
    mem_file = game_memory_file(game_slug)
    episode_title = storyboard_data.get('title', f'Episode {len(storyboard_data["scenes"])}')
    all_scenes = "\n".join([f"Scene {i+1}: {s['narration'][:80]}..."
                            for i, s in enumerate(storyboard_data["scenes"])])
    with open(mem_file, "w") as f:
        f.write(
            f"[{episode_title}]\n"
            f"Ref: {storyboard_data.get('real_life_reference', '')}\n"
            f"{all_scenes}\n"
        )
    print(f" 📝 Memory saved")

    # Cleanup
    for audio_file in temp_audio_files:
        try:
            if os.path.exists(audio_file):
                os.remove(audio_file)
        except OSError:
            pass
    print(" 🧹 Cleaned up temp files")

    return output_file

# ─── MAIN ───────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print(" Roblox Auto-Shorts — Agnes 2.0 Edition v7.3")
    print(" Powered by Agnes AI (Gemini Free Tier)")
    print("=" * 60)

    # Check what's available
    has_gemini = init_agnes()
    has_assets = os.path.exists(ASSET_DIR) and any(os.path.exists(os.path.join(ASSET_DIR, f)) for f in ALL_ASSETS)
    has_bgm = os.path.exists("bgm") and any(f.endswith(".mp3") for f in os.listdir("bgm") if os.path.exists("bgm"))

    print(f"\n 💎 Agnes 2.0 AI Engine (Gemini Free Tier): {'YES' if has_gemini else 'NO — set GEMINI_API_KEY'}")
    print(f" 🖼 Local assets: {'YES' if has_assets else 'NO — add images to assets/ folder'}")
    print(f" 🎵 Background music: {'YES' if has_bgm else 'NO — add MP3s to bgm/ folder'}")
    print(f" 🌸 Pollinations (free images): ALWAYS AVAILABLE")
    print()

    if not has_gemini and not has_assets:
        print("⚠️ WARNING: No Gemini key AND no local assets.")
        print(" Pollinations will be used, but quality may vary.")
        print(" For best results: set GEMINI_API_KEY or add images to assets/")
        print()

    state = load_game_state()
    game_slug = get_current_game(state)
    game_config = ROBLOX_GAMES[game_slug]

    state["episode_counts"].setdefault(game_slug, 0)
    state["episode_counts"][game_slug] += 1
    episode_number = state["episode_counts"][game_slug]

    print(f"🎮 Game: {game_config['display_name']} | Episode {episode_number}\n")

    print("─── [1/4] Story Generation ───")
    storyboard = generate_storyboard(game_slug, game_config, episode_number)
    print(f"🎬 Title: {storyboard.get('title', '?')}")
    print(f"📰 Reference: {storyboard.get('real_life_reference', '?')}")
    print(f"📌 {len(storyboard['scenes'])} scenes\n")

    output_file = assemble_storyboard(storyboard, game_slug, game_config)

    advance_game_state(state)
    save_game_state(state)

    print(f"\n🏁 Complete! Video: {output_file}")
    print("📤 Upload manually to YouTube, or set YouTube OAuth credentials for auto-upload.")

if __name__ == "__main__":
    main()
