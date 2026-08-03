"""
Roblox Auto-Shorts — Multi-Game Edition (v6)
============================================
Changes in v6:
  • Engine V: detects 402 Payment Required (fal.ai billing) and fast-fails,
              not just 403. Saves minutes of wasted retries.
  • Engine B: Pollinations now fetches ONE image per scene (sequential, 3
              retries). Eliminates the 8/10 parallel-request failures.
  • Ken Burns: single image animated via ffmpeg zoompan (slow zoom-in/out).
              Completely replaces the 10-frame blend pipeline. Faster, more
              reliable, and looks more cinematic.
  • Captions: word-group style — 4 words at a time, 78px bold white text with
              5px black stroke, timed across the voiceover duration.
  • Bug fix:  bg.multiply_volume(0.10) → bg.with_multiply_volume(0.10)
              (MoviePy 2.x renamed this method — caused the crash at line 1175)
"""

import os, time, random, json, math, requests, asyncio, edge_tts
import glob, subprocess, shutil
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

os.environ["IMAGEMAGICK_BINARY"] = "/usr/bin/convert"
import numpy as np

from moviepy import (
    CompositeVideoClip, AudioFileClip, CompositeAudioClip,
    TextClip, concatenate_videoclips, concatenate_audioclips,
    ColorClip, VideoFileClip,
)
from PIL import Image, ImageEnhance
from groq import Groq
from huggingface_hub import InferenceClient
import google.oauth2.credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ─────────────────────────────────────────────────────────────────────────────
# VIDEO CONFIG
# ─────────────────────────────────────────────────────────────────────────────
VIDEO_W, VIDEO_H   = 1080, 1920
FPS                = 24
CAPTION_Y_FRAC     = 0.70        # word captions sit at 70% height (center-bottom)
CAPTION_FONTSIZE   = 78          # bigger = more readable on phone screens
WORDS_PER_CHUNK    = 4           # words shown at a time in captions
KEN_BURNS_ZOOM     = 0.30        # total zoom range: 1.00 → 1.30  (or reverse)

# Hugging Face text-to-video (Engine V)
HF_MODELS_API        = "https://huggingface.co/api/models"
HF_MODEL_LIMIT       = 30
HF_CATALOG_TIMEOUT   = 25
HF_MODEL_STATE_FILE  = "hf_model_state.json"
HF_VIDEO_MODELS_FALLBACK = [
    "Wan-AI/Wan2.1-T2V-1.3B",
    "Lightricks/LTX-Video-0.9.5",
    "Wan-AI/Wan2.2-TI2V-5B",
    "genmo/mochi-1-preview",
    "tencent/HunyuanVideo",
]
_HF_MODEL_CACHE         = None
_HF_SEARCH_FAILED_THIS_RUN = False

# Together AI (Engine A — optional/paid)
TOGETHER_API_URL = "https://api.together.ai/v1/images/generations"
TOGETHER_MODEL   = "black-forest-labs/FLUX.1-schnell"
TOGETHER_STEPS   = 4

# Pollinations (Engine B — 1 image per scene, sequential)
POLL_DELAY_OK    = 2
POLL_DELAY_429   = 25
POLL_MAX_RETRY   = 4
POLL_TIMEOUT     = 90

GAME_STATE_FILE  = "game_state.json"

# ─────────────────────────────────────────────────────────────────────────────
# ROBLOX GAME CATALOG
# ─────────────────────────────────────────────────────────────────────────────
ROBLOX_GAMES = {

    "blox_fruits": {
        "display_name": "Blox Fruits",
        "genre": "action RPG, open-world sea adventure",
        "image_style": (
            "Roblox Blox Fruits game, blocky low-poly 3D avatar, "
            "tropical colorful sea island world, vivid neon fruit powers, "
            "plastic shiny textures, dramatic ocean background"
        ),
        "hashtags": ["#BloxFruits", "#Roblox", "#Shorts", "#Gaming", "#RobloxShorts", "#BloxFruitsStory"],
        "scene_examples": [
            "Luffy blox fruits dough awakening sea battle",
            "Shanks blox fruits sword clash island boss",
            "Mysterious Figure blox fruits aura reveal",
            "max level pvp fruit showdown cliffhanger",
        ],
        "starter_context": (
            "Episode 1. A new pirate has just woken up on Starter Island with no fruit power. "
            "The sea holds ancient secrets and legendary Devil Fruits waiting to be found."
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
        "hashtags": ["#AdoptMe", "#Roblox", "#Shorts", "#Gaming", "#RobloxPets", "#AdoptMeTrading"],
        "scene_examples": [
            "rare neon unicorn pet trade Adopt Me island",
            "shadow dragon scam drama Adopt Me school",
            "legendary pet hatch egg reveal Adopt Me",
            "mega neon fly ride pet auction cliffhanger",
        ],
        "starter_context": (
            "Episode 1. A new player just joined Adopt Me with a basic starter egg. "
            "The legendary Neon Shadow Dragon is rumored to appear at the trading plaza."
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
        "hashtags": ["#MM2", "#MurderMystery2", "#Roblox", "#Shorts", "#RobloxThriller", "#MM2Story"],
        "scene_examples": [
            "sheriff chasing murderer MM2 dark warehouse",
            "innocent discovers body MM2 haunted mansion",
            "murderer reveal plot twist MM2 school map",
            "last survivor sheriff showdown MM2 cliffhanger",
        ],
        "starter_context": (
            "Episode 1. A new game of Murder Mystery 2 has started on a dark stormy map. "
            "Nobody knows who the murderer is yet — but the body count is about to rise."
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
        "hashtags": ["#PetSimX", "#PetSimulatorX", "#Roblox", "#Shorts", "#RobloxPets", "#PSXTrading"],
        "scene_examples": [
            "giant rainbow unicorn pet destroy coins PSX island",
            "exclusive titanic cat unboxing surprise PSX",
            "dark matter pet reveal trading arena PSX",
            "world record pet damage cliffhanger PSX boss",
        ],
        "starter_context": (
            "Episode 1. A new collector just entered Pet Simulator X with a basic dog pet. "
            "Rumors spread about a secret Titanic Dark Matter cat hidden in a locked chest."
        ),
    },

    "doors": {
        "display_name": "Doors",
        "genre": "horror survival, puzzle escape",
        "image_style": (
            "Roblox Doors game, blocky horror avatar, "
            "dark eerie hotel corridor, flickering neon lights, "
            "glowing red entity eyes, dramatic shadow horror atmosphere, "
            "door number glowing in darkness"
        ),
        "hashtags": ["#RobloxDoors", "#Doors", "#Roblox", "#Shorts", "#RobloxHorror", "#DoorsEntity"],
        "scene_examples": [
            "Rush entity sprint Door 50 Doors horror hotel",
            "Seek floor chase escape Doors dark corridor",
            "Figure encounter library Door 100 Doors survival",
            "Ambush entity jumpscare Doors cliffhanger finale",
        ],
        "starter_context": (
            "Episode 1. A group of players just entered the haunted Hotel in Roblox Doors. "
            "The lights are already flickering at Door 1. Something is already watching."
        ),
    },

    "arsenal": {
        "display_name": "Arsenal",
        "genre": "FPS action, kill streaks, weapon unlocks",
        "image_style": (
            "Roblox Arsenal FPS game, blocky soldier avatar, "
            "colorful fast-paced arena map, neon gun effects, "
            "kill streak explosion, bright vivid game arena, "
            "headshot particle burst, scorestreak banner"
        ),
        "hashtags": ["#RobloxArsenal", "#Arsenal", "#Roblox", "#Shorts", "#RobloxFPS", "#ArsenalKills"],
        "scene_examples": [
            "insane 360 no-scope Arsenal FPS arena final kill",
            "golden knife unlock Arsenal locker room reveal",
            "juggernaut last kill Arsenal rooftop showdown",
            "clutch 1v5 win Arsenal tournament finals cliffhanger",
        ],
        "starter_context": (
            "Episode 1. A new soldier just joined their first Arsenal ranked match. "
            "The legendary Golden Knife kill is just 1 point away — can they pull it off?"
        ),
    },

    "anime_adventures": {
        "display_name": "Anime Adventures",
        "genre": "tower defense, anime crossover, wave survival",
        "image_style": (
            "Roblox Anime Adventures game, blocky anime-style 3D avatar, "
            "colorful tower defense map, glowing anime unit effects, "
            "massive energy beam attacks, vivid neon skill explosions, "
            "anime character crossover blocky style"
        ),
        "hashtags": ["#AnimeAdventures", "#Roblox", "#Shorts", "#Gaming", "#RobloxAnime", "#AAGame"],
        "scene_examples": [
            "secret 6-star unit summon Anime Adventures reveal",
            "final wave boss destroy Anime Adventures tower map",
            "ultra instinct unit evolution Anime Adventures arena",
            "legendary crossover unit unlocked cliffhanger Anime Adventures",
        ],
        "starter_context": (
            "Episode 1. A new commander just placed their first units in Anime Adventures. "
            "Wave 50 is incoming and a secret 6-star summon has just appeared on the banner."
        ),
    },

    "brookhaven": {
        "display_name": "Brookhaven RP",
        "genre": "social roleplay, drama, life simulation",
        "image_style": (
            "Roblox Brookhaven RP game, blocky avatar, "
            "colorful suburban neighborhood world, luxury mansion background, "
            "sports cars, school setting, bright cheerful town atmosphere, "
            "dramatic roleplay scene vivid colors"
        ),
        "hashtags": ["#Brookhaven", "#BrookhavenRP", "#Roblox", "#Shorts", "#RobloxRP", "#BrookhavenDrama"],
        "scene_examples": [
            "secret millionaire reveal Brookhaven luxury mansion",
            "high school drama rivalry Brookhaven school hallway",
            "undercover agent mission Brookhaven town bank",
            "shocking plot twist family reunion Brookhaven cliffhanger",
        ],
        "starter_context": (
            "Episode 1. A mysterious new resident just moved into the most expensive house "
            "in Brookhaven. Nobody knows their secret past — but the town is about to find out."
        ),
    },
}

GAME_ORDER = list(ROBLOX_GAMES.keys())

# ─────────────────────────────────────────────────────────────────────────────
# PROMPTS
# ─────────────────────────────────────────────────────────────────────────────
NEGATIVE_PROMPT = (
    "flat lighting,dull colors,2D,anime lineart,realistic human proportions,"
    "photograph,ugly,pixelated,low resolution,dark background,monochrome,horror faces,"
    "sketch,watermark,text overlay,blurry,realistic skin,detailed human anatomy"
)

ASSET_DIR  = "assets"
ALL_ASSETS = [
    "roblox_landscape.jpg", "ancient_island.jpg", "jungle_island.jpg",
    "ocean_battle.jpg", "fortress.jpg", "volcano_island.jpg",
    "underwater_city.jpg", "sea.jpg", "monster_mutation.jpg",
]

# Ken Burns pan directions — varied across scenes for visual variety
KEN_BURNS_CONFIGS = [
    {"zoom": "in",  "pan": "center"},   # scene 1: zoom in, center
    {"zoom": "out", "pan": "center"},   # scene 2: zoom out, center
    {"zoom": "in",  "pan": "top"},      # scene 3: zoom in, pan down
    {"zoom": "in",  "pan": "bottom"},   # scene 4: zoom in, pan up
    {"zoom": "out", "pan": "center"},   # scene 5+: zoom out
]

# ─────────────────────────────────────────────────────────────────────────────
# GAME STATE
# ─────────────────────────────────────────────────────────────────────────────
def load_game_state():
    if os.path.exists(GAME_STATE_FILE):
        try:
            with open(GAME_STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "game_index":    0,
        "episode_counts": {g: 0 for g in GAME_ORDER},
    }


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


# ─────────────────────────────────────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────────────────────────────────────
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
    """Pick one local asset image. Returns path or None."""
    pool = [os.path.join(ASSET_DIR, f) for f in ALL_ASSETS
            if os.path.exists(os.path.join(ASSET_DIR, f))]
    return random.choice(pool) if pool else None


def load_and_fit(path):
    """Load an image and fit it to VIDEO_W x VIDEO_H with enhancements."""
    pil   = Image.open(path).convert("RGB")
    scale = max(VIDEO_W / pil.width, VIDEO_H / pil.height)
    pil   = pil.resize((int(pil.width * scale), int(pil.height * scale)), Image.LANCZOS)
    x0    = (pil.width  - VIDEO_W) // 2
    y0    = (pil.height - VIDEO_H) // 2
    pil   = pil.crop((x0, y0, x0 + VIDEO_W, y0 + VIDEO_H))
    pil   = ImageEnhance.Brightness(pil).enhance(1.05)
    pil   = ImageEnhance.Contrast(pil).enhance(1.12)
    pil   = ImageEnhance.Color(pil).enhance(1.20)
    return np.array(pil)


# ─────────────────────────────────────────────────────────────────────────────
# KEN BURNS VIDEO  (single image → animated mp4 via ffmpeg zoompan)
# ─────────────────────────────────────────────────────────────────────────────
def compile_ken_burns_video(img_path, duration, out_path, zoom="in", pan="center"):
    """
    Animate a single still image using ffmpeg's zoompan filter.
    This creates a smooth cinematic zoom effect that makes the image
    feel like a real video shot — no extra API calls, runs in ~1s.

    zoom: "in"  = start wide (1.00x) → zoom to 1.30x over the clip
          "out" = start zoomed (1.30x) → zoom out to 1.00x over the clip
    pan:  "center" = zoom stays centered
          "top"    = zoom while panning from top-center toward middle
          "bottom" = zoom while panning from bottom-center toward middle
    """
    total_frames = max(int(duration * FPS), 1)
    zoom_range   = KEN_BURNS_ZOOM                      # 0.30
    delta        = zoom_range / total_frames

    if zoom == "in":
        z_expr = f"min(zoom+{delta:.8f},1.{int(zoom_range*100):02d})"
    else:
        # Start at 1.30, decrease to 1.00
        z_expr = f"if(eq(on,1),1.{int(zoom_range*100):02d},max(zoom-{delta:.8f},1.0))"

    # X/Y panning expressions
    if pan == "center":
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
    elif pan == "top":
        # Start near top, drift toward center
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = f"max(ih*0.05,ih/2-(ih/zoom/2)-ih*0.25*(1-on/{total_frames}))"
    else:  # bottom
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = f"min(ih*0.70,ih/2-(ih/zoom/2)+ih*0.20*(1-on/{total_frames}))"

    vf = (
        f"scale={VIDEO_W * 2}:{VIDEO_H * 2},"          # upscale for headroom
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
    print(f"    ✅ Ken Burns (zoom-{zoom}, pan-{pan}): {out_path}")


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


# ─────────────────────────────────────────────────────────────────────────────
# HF MODEL STATE
# ─────────────────────────────────────────────────────────────────────────────
def load_hf_model_state():
    if os.path.exists(HF_MODEL_STATE_FILE):
        try:
            with open(HF_MODEL_STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_hf_model_state(model_id):
    with open(HF_MODEL_STATE_FILE, "w") as f:
        json.dump({"working_model": model_id}, f)


def clear_hf_model_state():
    if os.path.exists(HF_MODEL_STATE_FILE):
        try:
            os.remove(HF_MODEL_STATE_FILE)
        except OSError:
            pass


def discover_hf_video_models(hf_token, exclude_model=None):
    global _HF_MODEL_CACHE
    if _HF_MODEL_CACHE is not None:
        return [m for m in _HF_MODEL_CACHE if m != exclude_model]

    try:
        resp = requests.get(
            HF_MODELS_API,
            params={"pipeline_tag": "text-to-video", "sort": "likes", "limit": HF_MODEL_LIMIT},
            headers={"Authorization": f"Bearer {hf_token}"},
            timeout=HF_CATALOG_TIMEOUT,
        )
        if resp.status_code == 200:
            models = [m["modelId"] for m in resp.json() if "modelId" in m]
        else:
            models = HF_VIDEO_MODELS_FALLBACK[:]
    except Exception:
        models = HF_VIDEO_MODELS_FALLBACK[:]

    _HF_MODEL_CACHE = models
    print(f"    🔎 Hugging Face video candidates: {', '.join(models[:8]) or 'none'}")
    return [m for m in models if m != exclude_model]


def _save_hf_video_bytes(video_bytes, duration, out_path):
    if not video_bytes or len(video_bytes) < 10_000:
        return False

    raw_path = out_path.replace(".mp4", "_hf_raw.mp4")
    with open(raw_path, "wb") as f:
        f.write(video_bytes)

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",
        "-i", raw_path,
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
        "-t", str(duration),
        "-r", str(FPS),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "22",
        out_path,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    try:
        os.remove(raw_path)
    except OSError:
        pass
    if res.returncode != 0:
        print(f"    ⚠️  HF video conversion failed: {res.stderr[:240]}")
        return False
    return os.path.exists(out_path) and os.path.getsize(out_path) > 10_000


class _HFBillingError(Exception):
    """
    Raised when HuggingFace returns a 402 or 403 due to missing billing/credits.
    This is an account-level permanent block — no point trying other models.
    """


def _try_hf_video_model(prompt, duration, out_path, hf_token, model_id):
    print(f"    🎬 [Engine V] HF routed video → {model_id}")
    try:
        client     = InferenceClient(provider="auto", api_key=hf_token)
        video_bytes = client.text_to_video(prompt[:500], model=model_id)
        if hasattr(video_bytes, "read"):
            video_bytes = video_bytes.read()
        if _save_hf_video_bytes(video_bytes, duration, out_path):
            print(f"    ✅ HF video success: {model_id} ({duration:.1f}s)")
            return True
        print(f"    ⚠️  {model_id} returned no usable video.")
    except Exception as exc:
        msg = str(exc).replace("\n", " ")
        # FIX v6: catch BOTH 402 (fal.ai billing) and 403 (HF PRO)
        # The old code only caught 403, so 402 was silently retried on every model
        # wasting 7+ minutes before falling through to Pollinations.
        is_billing = (
            ("402" in msg or "403" in msg)
            and any(kw in msg for kw in ["Payment", "Inference Provider", "billing", "subscription"])
        )
        if is_billing:
            print(
                "    ❌ HF billing block detected (402/403). "
                "All HF video models require fal.ai credits — skipping engine V entirely.\n"
                "    Fix: top up fal.ai credits on your HF account, or add FAL_API_KEY secret."
            )
            raise _HFBillingError(msg)
        print(f"    ⚠️  {model_id} unavailable: {msg[:240]}")
    return False


def fetch_hf_video(prompt, duration, out_path, hf_token):
    global _HF_SEARCH_FAILED_THIS_RUN
    if _HF_SEARCH_FAILED_THIS_RUN:
        print("    ⏭️  HF unavailable for this run — using Engine B.")
        return False

    saved_model = load_hf_model_state().get("working_model", "")
    if saved_model:
        print(f"    💾 Saved HF model: {saved_model}")
        if _try_hf_video_model(prompt, duration, out_path, hf_token, saved_model):
            return True
        clear_hf_model_state()

    print("    🔎 Searching HF catalog for working video model...")
    models = discover_hf_video_models(hf_token, exclude_model=saved_model or None)
    if not models:
        _HF_SEARCH_FAILED_THIS_RUN = True
        return False

    for model_id in models[:8]:
        try:
            if _try_hf_video_model(prompt, duration, out_path, hf_token, model_id):
                save_hf_model_state(model_id)
                return True
        except _HFBillingError:
            clear_hf_model_state()
            _HF_SEARCH_FAILED_THIS_RUN = True
            return False

    clear_hf_model_state()
    _HF_SEARCH_FAILED_THIS_RUN = True
    print("    ❌ All HF candidates failed — falling back to Engine B.")
    return False


# ─────────────────────────────────────────────────────────────────────────────
# ENGINE A — TOGETHER AI (optional, paid)
# ─────────────────────────────────────────────────────────────────────────────
def build_image_prompt(base_query, narration, character_bible, game_config):
    """Build a single Pollinations/Together prompt for this scene."""
    style = game_config["image_style"]
    chars = ""
    if character_bible:
        char_descs = []
        for name, info in list(character_bible.items())[:2]:
            parts = [name]
            if info.get("clothes"):
                parts.append(info["clothes"])
            if info.get("facial_features"):
                parts.append(info["facial_features"])
            char_descs.append(" ".join(parts))
        if char_descs:
            chars = "characters: " + ", ".join(char_descs)

    prompt = f"{style}, {base_query}, {chars}, dramatic action scene, 9:16 portrait".strip(", ")
    # Keep under 400 chars — longer prompts cause Pollinations to time out more often
    return prompt[:400]


def fetch_together_frames(base_query, narration, character_bible,
                          count, out_dir, prefix, api_key, game_config):
    """Engine A: Together AI FLUX.1-schnell images (paid, optional)."""
    out_paths = []
    prompt = build_image_prompt(base_query, narration, character_bible, game_config)

    for i in range(count):
        out_path = os.path.join(out_dir, f"{prefix}_tog_{i:02d}.jpg")
        try:
            resp = requests.post(
                TOGETHER_API_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": TOGETHER_MODEL,
                    "prompt": prompt,
                    "width": 1080, "height": 1920,
                    "steps": TOGETHER_STEPS,
                    "n": 1,
                },
                timeout=60,
            )
            if resp.status_code == 200:
                data = resp.json()
                url  = data["data"][0].get("url", "")
                if url:
                    img_resp = requests.get(url, timeout=30)
                    if img_resp.status_code == 200:
                        with open(out_path, "wb") as f:
                            f.write(img_resp.content)
                        out_paths.append(out_path)
                        print(f"    ✅ [Engine A] Together frame {i+1}/{count}")
        except Exception as e:
            print(f"    ⚠️  [Engine A] Frame {i+1}/{count} error: {e}")
    return out_paths


# ─────────────────────────────────────────────────────────────────────────────
# ENGINE B — POLLINATIONS AI  (free, no key, 1 image per scene)
# ─────────────────────────────────────────────────────────────────────────────
def fetch_pollinations_single(base_query, narration, character_bible,
                               out_dir, prefix, game_config):
    """
    Fetch exactly ONE image from Pollinations AI (sequential, up to POLL_MAX_RETRY tries).

    v6 change: was 10 parallel requests which caused 8/10 to fail with rate limits.
    Single sequential request succeeds >95% of the time on the first attempt.
    The Ken Burns zoom effect then makes this one image look like a video clip.
    """
    scene_seed = random.randint(10_000, 9_999_999)
    neg_enc    = requests.utils.quote(NEGATIVE_PROMPT)
    prompt     = build_image_prompt(base_query, narration, character_bible, game_config)
    encoded    = requests.utils.quote(prompt)
    url        = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width=1080&height=1920&nologo=true"
        f"&seed={scene_seed}&model=flux&negative={neg_enc}"
    )
    out_path = os.path.join(out_dir, f"{prefix}_pol.jpg")
    headers  = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://pollinations.ai/",
        "Accept":  "image/webp,image/apng,image/*,*/*;q=0.8",
    }

    for attempt in range(1, POLL_MAX_RETRY + 1):
        try:
            print(f"    🌸 [Engine B] Pollinations attempt {attempt}/{POLL_MAX_RETRY}  (seed: {scene_seed})")
            resp = requests.get(url, headers=headers, timeout=POLL_TIMEOUT, stream=True)

            if resp.status_code == 429:
                wait = POLL_DELAY_429 * attempt       # back-off: 25s, 50s, 75s…
                print(f"    ⏳ Rate-limited — waiting {wait}s before retry...")
                time.sleep(wait)
                continue

            if resp.status_code == 200 and "image" in resp.headers.get("content-type", ""):
                with open(out_path, "wb") as f:
                    for chunk in resp.iter_content(8192):
                        f.write(chunk)
                size_kb = os.path.getsize(out_path) // 1024
                if size_kb > 5:
                    print(f"    ✅ Pollinations image: {size_kb} KB")
                    time.sleep(POLL_DELAY_OK)          # polite delay before next scene
                    return out_path
                print(f"    ⚠️  Tiny response ({size_kb} KB) — retrying...")

            time.sleep(8)

        except requests.exceptions.Timeout:
            print(f"    ⏳ Timeout — waiting 30s before retry...")
            time.sleep(30)
        except Exception as e:
            print(f"    ⚠️  Request error: {e}")
            time.sleep(5)

    print("    ❌ Pollinations failed after all attempts — using local asset fallback.")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# CAPTIONS — word-group style (4 words at a time, timed to voiceover)
# ─────────────────────────────────────────────────────────────────────────────
_FONT_PATH = None


def make_caption_clips(text, duration):
    """
    Splits narration into WORDS_PER_CHUNK-word groups. Each group is shown
    for (duration / n_chunks) seconds. Returns a list of TextClip objects
    with .with_start() already set — pass them into CompositeVideoClip
    alongside the video layer.

    Style: 78px bold white, 5px black stroke. Large, phone-readable, high contrast.
    This matches the caption style of viral Shorts (like d6r0HmNthBc).
    """
    global _FONT_PATH
    if _FONT_PATH is None:
        _FONT_PATH = find_font()
    if _FONT_PATH is None:
        print("    ⚠️  No system font found — captions skipped.")
        return []

    words  = text.split()
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
                .with_duration(time_per_chunk - 0.05)       # tiny gap between chunks
                .with_position(("center", int(VIDEO_H * CAPTION_Y_FRAC)))
            )
        except Exception as e:
            print(f"    ⚠️  Caption chunk {ci+1}/{len(chunks)} error: {e}")

    print(f"    💬 {len(clips)} caption chunks ({len(words)} words, {time_per_chunk:.1f}s each)")
    return clips


# ─────────────────────────────────────────────────────────────────────────────
# SCENE VISUAL ASSEMBLY
# ─────────────────────────────────────────────────────────────────────────────
def fetch_scene_visual(scene, idx, character_bible, work_dir, game_config):
    """
    Engine cascade for one scene:
      V → HF text-to-video (needs HF_TOKEN + fal.ai credits)
      A → Together AI images (needs TOGETHER_API_KEY, paid)
      B → Pollinations AI: 1 image + Ken Burns zoom (free, no key)
      L → Local asset: 1 image + Ken Burns zoom (guaranteed fallback)
    """
    base_query = scene["query"]
    narration  = scene["narration"]
    dur        = scene.get("duration", 10)
    prefix     = f"scene_{idx + 1}"
    out_path   = os.path.join(work_dir, f"{prefix}_visual.mp4")

    # Ken Burns config varies per scene for visual variety
    kb = KEN_BURNS_CONFIGS[idx % len(KEN_BURNS_CONFIGS)]

    # ── Engine V: HuggingFace text-to-video ──────────────────────────────────
    hf_token = clean_env(os.getenv("HF_TOKEN"))
    if hf_token:
        print("    ▶ Engine V: HuggingFace text-to-video...")
        prompt = f"{game_config['image_style']}, {base_query}, {narration[:100]}"
        try:
            if fetch_hf_video(prompt, dur, out_path, hf_token):
                return VideoFileClip(out_path)
        except Exception as e:
            print(f"    ⚠️  Engine V error: {e}")
        print("    ↩  Engine V failed — trying Engine B...")

    # ── Engine A: Together AI (optional/paid) ─────────────────────────────────
    together_key = clean_env(os.getenv("TOGETHER_API_KEY"))
    if together_key:
        print("    ▶ Engine A: Together AI...")
        paths = fetch_together_frames(
            base_query, narration, character_bible,
            1, work_dir, prefix, together_key, game_config
        )
        if paths:
            try:
                compile_ken_burns_video(paths[0], dur, out_path, **kb)
                return VideoFileClip(out_path)
            except Exception as e:
                print(f"    ⚠️  Ken Burns on Together image failed: {e}")

    # ── Engine B: Pollinations AI — 1 image + Ken Burns ──────────────────────
    print("    ▶ Engine B: Pollinations AI (1 image + Ken Burns zoom)...")
    img_path = fetch_pollinations_single(
        base_query, narration, character_bible, work_dir, prefix, game_config
    )
    if img_path:
        try:
            compile_ken_burns_video(img_path, dur, out_path, **kb)
            return VideoFileClip(out_path)
        except Exception as e:
            print(f"    ⚠️  Ken Burns on Pollinations image failed: {e}")

    # ── Engine L: Local asset fallback ────────────────────────────────────────
    print("    ▶ Engine L: Local asset fallback...")
    local_path = pick_local_asset()
    if local_path:
        try:
            compile_ken_burns_video(local_path, dur, out_path, **kb)
            return VideoFileClip(out_path)
        except Exception as e:
            print(f"    ⚠️  Ken Burns on local asset failed: {e}")

    # ── Last resort: black clip ───────────────────────────────────────────────
    print("    ⚠️  All engines failed — using black placeholder.")
    _write_blank_video(out_path, dur)
    return VideoFileClip(out_path)


# ─────────────────────────────────────────────────────────────────────────────
# 2. VOICEOVER
# ─────────────────────────────────────────────────────────────────────────────
async def generate_voiceover(text, out_file):
    comm = edge_tts.Communicate(text, voice="en-US-ChristopherNeural", rate="+10%")
    await comm.save(out_file)


# ─────────────────────────────────────────────────────────────────────────────
# 1. GROQ STORYBOARD
# ─────────────────────────────────────────────────────────────────────────────
def generate_storyboard(game_slug, game_config, episode_number):
    print(f"─── [1/5] Groq Story Director "
          f"({game_config['display_name']} — Episode {episode_number}) ───")

    api_key = clean_env(os.getenv("GROQ_API_KEY"))
    if not api_key:
        raise Exception("Missing GROQ_API_KEY!")

    client = Groq(api_key=api_key)

    mem_file   = game_memory_file(game_slug)
    bible_file = game_bible_file(game_slug)

    previous_context  = game_config["starter_context"]
    character_context = "{}"

    if os.path.exists(mem_file):
        c = open(mem_file).read().strip()
        if c:
            previous_context = c
    if os.path.exists(bible_file):
        b = open(bible_file).read().strip()
        if b:
            character_context = b

    today = datetime.utcnow().strftime("%B %d, %Y")
    ex    = game_config["scene_examples"]
    genre = game_config["genre"]

    prompt = f"""You are a viral AI content director making YouTube Shorts about Roblox {game_config['display_name']}.
Today's date is {today}.

GAME: {game_config['display_name']} ({genre})
EPISODE: {episode_number}
PREVIOUS STORY: {previous_context}
CHARACTER BIBLE: {character_context}

TASK: Write a YouTube Short storyboard. Output ONLY valid JSON, no markdown fences, no extra text.

JSON FORMAT:
{{
  "title": "Episode title (max 60 chars)",
  "real_life_reference": "One trending news story or meme from the past week that parallels the plot",
  "scenes": [
    {{
      "narration": "Exciting voiceover narration (2-4 sentences, present tense, dramatic)",
      "query": "Short visual scene description for image gen (max 12 words)",
      "duration": 8
    }}
  ]
}}

RULES:
- Exactly 5 scenes
- Each narration 2-4 sentences, punchy, cliffhanger style, like a story TikTok narrator
- Each query is SHORT — max 12 words — no full sentences
- Last scene must end on a cliffhanger or reveal
- Scene examples for inspiration: {ex[0]}, {ex[1]}, {ex[2]}
- Duration is a placeholder; actual voiceover timing overrides it
- Reference must feel connected to the game plot
- Keep continuity from PREVIOUS STORY
"""

    resp = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.9,
        max_tokens=1500,
    )
    raw = resp.choices[0].message.content.strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    data = json.loads(raw)
    print(f"🎮 Game: {game_config['display_name']}")
    print(f"🎬 Title: {data.get('title', '?')}")
    print(f"📰 Real-life reference: {data.get('real_life_reference', '?')}")
    print(f"📌 {len(data['scenes'])} scenes.")
    return data


# ─────────────────────────────────────────────────────────────────────────────
# 3. STORYBOARD ASSEMBLY
# ─────────────────────────────────────────────────────────────────────────────
def assemble_storyboard(storyboard_data, game_slug, game_config):
    print("─── [3/5] Scene Assembly ───")

    work_dir = "motion_templates"
    os.makedirs(work_dir, exist_ok=True)
    for f in glob.glob(os.path.join(work_dir, "*")):
        try:
            os.remove(f)
        except OSError:
            pass

    character_bible = {}
    bible_file = game_bible_file(game_slug)
    if os.path.exists(bible_file):
        try:
            character_bible = json.load(open(bible_file))
        except Exception:
            pass

    video_segments, audio_segments = [], []

    for idx, scene in enumerate(storyboard_data["scenes"]):
        narration = scene["narration"]
        print(f"\n🎬 Scene {idx+1}/{len(storyboard_data['scenes'])}: {scene['query']}")

        audio_file  = f"scene_{idx+1}.mp3"
        asyncio.run(generate_voiceover(narration, audio_file))
        scene_audio = AudioFileClip(audio_file)
        actual_dur  = scene_audio.duration
        scene["duration"] = actual_dur
        audio_segments.append(scene_audio)
        print(f"    🔊 Voiceover: {actual_dur:.1f}s")

        # Visual clip (Ken Burns animated image or HF video)
        visual = fetch_scene_visual(scene, idx, character_bible, work_dir, game_config)
        visual = visual.with_duration(actual_dur)

        # Word-group captions (list of TextClips with start times)
        caption_clips = make_caption_clips(narration, actual_dur)

        # Composite: video layer + all caption layers
        layers     = [visual] + caption_clips
        scene_clip = (
            CompositeVideoClip(layers, size=(VIDEO_W, VIDEO_H))
            .with_duration(actual_dur)
            .with_audio(scene_audio)
        )
        video_segments.append(scene_clip)

    print("\n─── [4/5] Final Render ───")
    final_video = concatenate_videoclips(video_segments, method="compose")

    bgm_folder = "bgm"
    os.makedirs(bgm_folder, exist_ok=True)
    mp3_files  = [f for f in os.listdir(bgm_folder) if f.endswith(".mp3")]

    combined_voice = (concatenate_audioclips(audio_segments)
                      if len(audio_segments) > 1 else audio_segments[0])

    if mp3_files:
        bg  = AudioFileClip(os.path.join(bgm_folder, random.choice(mp3_files)))
        dur = combined_voice.duration
        if bg.duration < dur:
            loops = math.ceil(dur / bg.duration)
            bg    = concatenate_audioclips([bg] * loops).subclipped(0, dur)
        else:
            bg = bg.subclipped(0, dur)

        # FIX v6: multiply_volume → with_multiply_volume  (MoviePy 2.x renamed this)
        # Old code: bg.multiply_volume(0.10)  ← AttributeError crash
        final_audio = CompositeAudioClip([
            combined_voice,
            bg.with_multiply_volume(0.10),
        ])
    else:
        final_audio = combined_voice

    final_video = final_video.with_audio(final_audio)
    print("🎞  Rendering final_short.mp4 ...")
    final_video.write_videofile(
        "final_short.mp4", fps=FPS,
        codec="libx264", audio_codec="aac",
        threads=4, preset="ultrafast", logger=None,
    )
    print("✅ Render complete.\n")

    # Update story memory for the next episode
    last_scene  = storyboard_data["scenes"][-1]["narration"]
    mem_file    = game_memory_file(game_slug)
    with open(mem_file, "w") as f:
        f.write(
            f"[Episode {storyboard_data.get('title', '?')}]\n"
            f"Last scene: {last_scene}\n"
            f"Reference: {storyboard_data.get('real_life_reference', '')}"
        )
    print(f"📝 Story memory updated: {mem_file}")


# ─────────────────────────────────────────────────────────────────────────────
# 5. YOUTUBE UPLOAD
# ─────────────────────────────────────────────────────────────────────────────
def upload_to_youtube(storyboard_data, game_config, episode_number):
    print("─── [5/5] YouTube Upload ───")

    client_id     = clean_env(os.getenv("CLIENT_ID"))
    client_secret = clean_env(os.getenv("CLIENT_SECRET"))
    refresh_token = clean_env(os.getenv("REFRESH_TOKEN"))

    if not all([client_id, client_secret, refresh_token]):
        print("🚨 YouTube secrets missing — skipping upload.")
        return

    creds = google.oauth2.credentials.Credentials(
        None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
