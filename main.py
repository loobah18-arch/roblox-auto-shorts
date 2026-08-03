"""
Roblox Auto-Shorts — Multi-Game Edition (v5)
============================================
What's new in v5:
  • Engine V: discovers current Hugging Face text-to-video models at runtime
              and tries live provider-backed models through Hugging Face routing.
              It uses only the HF_TOKEN and never requires a Wan/provider key.
              When free monthly credits or provider access are unavailable, it
              automatically falls back to the existing image engines.
  • All previous engines kept in cascade:
      V → text-to-video (HF, free)
      A → FLUX.1-schnell images (Together AI, optional/paid)
      B → Pollinations AI images (free, no key needed)
      L → local asset images (last resort)

Games in rotation (one per daily run, 8-game cycle):
  1. Blox Fruits        5. Doors
  2. Adopt Me!          6. Arsenal
  3. Murder Mystery 2   7. Anime Adventures
  4. Pet Simulator X    8. Brookhaven
"""

import os, time, random, json, math, requests, asyncio, edge_tts
import glob, subprocess, shutil
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Required for MoviePy TextClip on GitHub Actions Ubuntu runners.
# Without this, ImageMagick binary is not found and captions silently fail.
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
VIDEO_W, VIDEO_H = 1080, 1920
FPS              = 24
CAPTION_Y_FRAC   = 0.82
CAPTION_FONTSIZE = 58
FRAMES_PER_SCENE = 10
BLEND_STEPS      = 6

# Hugging Face text-to-video (Engine V)
# The catalog is discovered at runtime. These are only emergency fallbacks if
# the public catalog is temporarily unavailable; each is still checked by the
# Hugging Face router before use.
HF_MODELS_API        = "https://huggingface.co/api/models"
HF_MODEL_LIMIT       = 30
HF_CATALOG_TIMEOUT   = 25
HF_MODEL_STATE_FILE  = "hf_model_state.json"
HF_VIDEO_MODELS_FALLBACK = [
    "Wan-AI/Wan2.2-TI2V-5B",
    "Wan-AI/Wan2.2-T2V-A14B",
    "Wan-AI/Wan2.1-T2V-1.3B",
    "Lightricks/LTX-Video-0.9.5",
    "genmo/mochi-1-preview",
]

# Together AI (Engine A)
TOGETHER_API_URL = "https://api.together.ai/v1/images/generations"
TOGETHER_MODEL   = "black-forest-labs/FLUX.1-schnell"
TOGETHER_STEPS   = 4

# Pollinations (Engine B)
POLL_DELAY_OK    = 2
POLL_DELAY_429   = 20
POLL_MAX_RETRY   = 3
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

CINEMATIC_BASE = (
    "Cinematic 3D animation, Unreal Engine 5 render, hyper-detailed blocky Roblox aesthetic, "
    "volumetric lighting, glowing saturated colors, subsurface scattering on plastic skin, "
    "dramatic camera angle, rich cinematic shadows, masterpiece digital art"
)

FRAME_STAGES = [
    "idle standing",
    "noticing threat",
    "powering up aura",
    "charging forward",
    "mid-air leap",
    "strike impact",
    "shockwave burst",
    "landing ground",
    "dramatic aftermath",
    "triumphant pose",
]

# ─────────────────────────────────────────────────────────────────────────────
# LOCAL ASSET FALLBACK
# ─────────────────────────────────────────────────────────────────────────────
ASSET_DIR  = "assets"
ALL_ASSETS = [
    "roblox_landscape.jpg", "ancient_island.jpg", "jungle_island.jpg",
    "ocean_battle.jpg", "fortress.jpg", "volcano_island.jpg",
    "underwater_city.jpg", "sea.jpg", "monster_mutation.jpg",
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
        "game_index": 0,
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
    """Locate an available .ttf font path for MoviePy v2."""
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


def pick_local_assets(count=FRAMES_PER_SCENE):
    pool = [os.path.join(ASSET_DIR, f) for f in ALL_ASSETS
            if os.path.exists(os.path.join(ASSET_DIR, f))]
    if not pool:
        return []
    random.shuffle(pool)
    while len(pool) < count:
        pool *= 2
    return pool[:count]


def load_and_fit(path):
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
# FRAME COMPILER  (image sequence → mp4)
# ─────────────────────────────────────────────────────────────────────────────
def compile_frames_to_video(img_paths, duration, out_path):
    if not img_paths:
        _write_blank_video(out_path, duration)
        return

    arrays = [load_and_fit(p) for p in img_paths]
    n      = len(arrays)

    frame_seq = []
    for i, arr in enumerate(arrays):
        frame_seq.append(arr)
        if i < n - 1:
            nxt = arrays[i + 1]
            for step in range(1, BLEND_STEPS + 1):
                alpha = step / (BLEND_STEPS + 1)
                blend = (arr.astype(np.float32) * (1 - alpha)
                         + nxt.astype(np.float32) * alpha).astype(np.uint8)
                frame_seq.append(blend)

    total_unique       = len(frame_seq)
    total_video_frames = max(int(duration * FPS), total_unique)
    frames_per_unique  = total_video_frames / total_unique

    frame_dir = out_path.replace(".mp4", "_frames")
    os.makedirs(frame_dir, exist_ok=True)
    print(f"    🖼  {total_unique} unique frames → {total_video_frames} video frames @ {FPS}fps")

    # BUG FIX: always clean up frame_dir even if ffmpeg fails (was leaking
    # hundreds of JPG files per failed scene, risking runner disk exhaustion)
    try:
        vfi = 0
        for uid, arr in enumerate(frame_seq):
            start = round(uid * frames_per_unique)
            end   = round((uid + 1) * frames_per_unique)
            cnt   = max(1, end - start)
            pil   = Image.fromarray(arr)
            for _ in range(cnt):
                pil.save(os.path.join(frame_dir, f"f{vfi:07d}.jpg"), quality=92)
                vfi += 1

        cmd = [
            "ffmpeg", "-y", "-framerate", str(FPS),
            "-i", os.path.join(frame_dir, "f%07d.jpg"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-preset", "ultrafast", "-crf", "23", "-t", str(duration), out_path,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"ffmpeg compile failed:\n{res.stderr}")
        print(f"    ✅ Scene compiled: {out_path}")
    finally:
        shutil.rmtree(frame_dir, ignore_errors=True)


def _write_blank_video(out_path, duration):
    frame_dir = out_path.replace(".mp4", "_blank_frames")
    os.makedirs(frame_dir, exist_ok=True)
    # BUG FIX: use try/finally so frame_dir is always cleaned up
    try:
        Image.new("RGB", (VIDEO_W, VIDEO_H), (10, 10, 30)).save(
            os.path.join(frame_dir, "f0000000.jpg"))
        subprocess.run([
            "ffmpeg", "-y", "-loop", "1",
            "-i", os.path.join(frame_dir, "f0000000.jpg"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-t", str(duration), "-r", str(FPS), out_path,
        ], capture_output=True)
    finally:
        shutil.rmtree(frame_dir, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
# PROMPT BUILDER
# ─────────────────────────────────────────────────────────────────────────────
def build_image_prompt(query, narration, character_bible, frame_stage, game_config):
    narration_lower = narration.lower()
    char_parts = []
    for name, data in character_bible.items():
        if name.lower() in narration_lower:
            parts = [f"{name} Roblox blocky avatar"]
            if data.get("body_color"):       parts.append(data["body_color"])
            if data.get("clothes"):          parts.append(f"wearing {data['clothes']}")
            if data.get("accessories"):      parts.append(f"equipped with {data['accessories']}")
            if data.get("facial_features"):  parts.append(f"face: {data['facial_features']}")
            if data.get("aura_color"):       parts.append(f"surrounded by {data['aura_color']}")
            if data.get("signature_weapon"): parts.append(f"wielding {data['signature_weapon']}")
            char_parts.append(", ".join(parts))

    char_part = (" | ".join(char_parts) + " | ") if char_parts else ""
    return (
        f"{CINEMATIC_BASE}, {game_config['image_style']}, "
        f"{char_part}{query}, {frame_stage}, "
        "same character same background same camera angle, "
        "9:16 vertical portrait, no watermarks, no UI overlay"
    )


# ─────────────────────────────────────────────────────────────────────────────
# ENGINE V — HUGGING FACE ROUTED TEXT-TO-VIDEO
# Models are discovered from the live Hub catalog and filtered to models with
# live inference-provider mappings. The HF router may use monthly credits;
# availability and pricing can change. A failed/empty credit response falls
# through to the existing free image pipeline.
# ─────────────────────────────────────────────────────────────────────────────
_HF_MODEL_CACHE = None
_HF_SEARCH_FAILED_THIS_RUN = False


def load_hf_model_state():
    """Load the last model that successfully generated a scene."""
    if not os.path.exists(HF_MODEL_STATE_FILE):
        return {}
    try:
        with open(HF_MODEL_STATE_FILE) as f:
            state = json.load(f)
        model_id = state.get("working_model")
        return {"working_model": model_id} if isinstance(model_id, str) else {}
    except (OSError, ValueError, TypeError):
        return {}


def save_hf_model_state(model_id):
    """Persist only a model that has just produced a valid video."""
    with open(HF_MODEL_STATE_FILE, "w") as f:
        json.dump({"working_model": model_id}, f, indent=4)


def clear_hf_model_state():
    """Forget a model after it stops working so the next attempt can search."""
    save_hf_model_state("")


def discover_hf_video_models(hf_token, exclude_model=None):
    """Return live provider-backed text-to-video model IDs from the Hub.

    The endpoint is public, but the token is sent when available so the
    catalog request behaves consistently with the later inference request.
    No provider API key is used here.
    """
    global _HF_MODEL_CACHE
    if _HF_MODEL_CACHE is not None:
        return [model for model in _HF_MODEL_CACHE if model != exclude_model]

    headers = {"Accept": "application/json"}
    if hf_token:
        headers["Authorization"] = f"Bearer {hf_token}"
    params = {
        "inference_provider": "all",
        "pipeline_tag": "text-to-video",
        "expand": "inferenceProviderMapping",
        "limit": HF_MODEL_LIMIT,
    }
    discovered = []
    catalog_succeeded = False

    try:
        resp = requests.get(
            HF_MODELS_API, params=params, headers=headers,
            timeout=HF_CATALOG_TIMEOUT,
        )
        if resp.status_code == 200:
            catalog_succeeded = True
            for item in resp.json():
                model_id = item.get("id") or item.get("modelId")
                mappings = item.get("inferenceProviderMapping") or []
                live = [
                    mapping for mapping in mappings
                    if mapping.get("status") == "live"
                    and mapping.get("task") == "text-to-video"
                    and mapping.get("type", "single-model") == "single-model"
                ]
                tags = {str(tag).lower() for tag in item.get("tags", [])}
                if model_id and live and "lora" not in tags:
                    discovered.append({
                        "id": model_id,
                        "trending": item.get("trendingScore", 0) or 0,
                        "downloads": item.get("downloads", 0) or 0,
                    })
    except Exception as exc:
        print(f"    ⚠️  Hugging Face catalog lookup failed: {exc}")

    # Prefer lightweight/current candidates before very large models. The
    # catalog still controls whether a model is eligible; this only prevents
    # an expensive 14B/large model from being tried before a smaller option.
    preferred = [
        "Wan-AI/Wan2.1-T2V-1.3B",
        "Lightricks/LTX-Video-0.9.5",
        "Lightricks/LTX-Video-0.9.8-13B-distilled",
        "Wan-AI/Wan2.2-TI2V-5B",
        "Wan-AI/Wan2.2-T2V-A14B",
        "genmo/mochi-1-preview",
    ]
    rank = {model_id: index for index, model_id in enumerate(preferred)}
    discovered.sort(
        key=lambda item: (
            rank.get(item["id"], len(preferred)),
            -float(item["trending"]),
            -int(item["downloads"]),
        )
    )
    models = [item["id"] for item in discovered]

    # Use the static list only during a catalog outage. If the live catalog
    # successfully reports no eligible models, respect that result and skip
    # video rather than trying stale models.
    if not catalog_succeeded:
        for model_id in HF_VIDEO_MODELS_FALLBACK:
            if model_id not in models:
                models.append(model_id)

    _HF_MODEL_CACHE = models
    print(f"    🔎 Hugging Face video candidates: {', '.join(models[:8]) or 'none'}")
    return [model for model in models if model != exclude_model]


def _save_hf_video_bytes(video_bytes, duration, out_path):
    if not video_bytes or len(video_bytes) < 10_000:
        return False

    raw_path = out_path.replace(".mp4", "_hf_raw.mp4")
    with open(raw_path, "wb") as f:
        f.write(video_bytes)

    # Provider outputs vary in size/aspect ratio. Normalize every result to
    # the vertical format used by the rest of the pipeline.
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",
        "-i", raw_path,
        "-vf", (
            "scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920"
        ),
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
        print(f"    ⚠️  Hugging Face video conversion failed: {res.stderr[:240]}")
        return False
    return os.path.exists(out_path) and os.path.getsize(out_path) > 10_000


class _HFBillingError(Exception):
    """Raised when the account lacks Inference Provider billing access.

    This is a permanent account-level block (not a per-model failure), so
    there is no point trying further models — bail out of the whole HF engine.

    Cause: either a read-only token (needs 'Make calls to serverless
    Inference API' scope) OR no HuggingFace PRO / billing credits set up.
    The providers that require billing are third parties routed through HF
    (fal-ai, replicate, wavespeed, etc.).
    """


def _try_hf_video_model(prompt, duration, out_path, hf_token, model_id):
    """Try one routed model and return whether it produced a valid MP4.

    Raises _HFBillingError if the account-level 403 fires so the caller
    can immediately abort the whole engine rather than retrying all models.
    """
    print(f"    🎬 [Engine V] HF routed video → {model_id}")
    try:
        client = InferenceClient(provider="auto", api_key=hf_token)
        video_bytes = client.text_to_video(prompt[:500], model=model_id)
        if hasattr(video_bytes, "read"):
            video_bytes = video_bytes.read()
        if _save_hf_video_bytes(video_bytes, duration, out_path):
            print(f"    ✅ HF video success with {model_id} ({duration:.1f}s)")
            return True
        print(f"    ⚠️  {model_id} returned no usable video.")
    except Exception as exc:
        message = str(exc).replace("\n", " ")
        # Detect account-level billing/permission block.
        # "Inference Providers" in the 403 body is HuggingFace's specific
        # wording for this error — distinct from a single model being
        # unavailable. Re-raise so fetch_hf_video aborts immediately.
        if "403" in message and "Inference Provider" in message:
            print(
                "    ❌ HF Inference Providers blocked (403). "
                "Fix: create a new HF token with 'Make calls to serverless "
                "Inference API' scope, AND ensure your HF account has billing "
                "or PRO enabled. Skipping all remaining HF models."
            )
            raise _HFBillingError(message)
        print(f"    ⚠️  {model_id} unavailable: {message[:240]}")
    return False


def fetch_hf_video(prompt, duration, out_path, hf_token):
    """Try the saved model first; search only after it stops working."""
    global _HF_SEARCH_FAILED_THIS_RUN
    if _HF_SEARCH_FAILED_THIS_RUN:
        print("    ⏭️  Hugging Face unavailable for this run — using Pollinations.")
        return False

    saved_model = load_hf_model_state().get("working_model", "")
    if saved_model:
        print(f"    💾 Saved HF model: {saved_model} (no catalog search)")
        if _try_hf_video_model(prompt, duration, out_path, hf_token, saved_model):
            return True
        print("    🔄 Saved HF model failed — searching for a replacement...")
        clear_hf_model_state()
    else:
        print("    🔎 No saved HF model — searching the live catalog...")

    models = discover_hf_video_models(hf_token, exclude_model=saved_model or None)
    if not models:
        _HF_SEARCH_FAILED_THIS_RUN = True
        print("    ℹ️  No live Hugging Face text-to-video models were found.")
        return False

    for model_id in models[:8]:
        try:
            if _try_hf_video_model(prompt, duration, out_path, hf_token, model_id):
                save_hf_model_state(model_id)
                return True
        except _HFBillingError:
            # Account-level block — no point trying remaining models.
            clear_hf_model_state()
            _HF_SEARCH_FAILED_THIS_RUN = True
            return False

    clear_hf_model_state()
    _HF_SEARCH_FAILED_THIS_RUN = True
    print("    ❌ All current HF video candidates failed; using Pollinations/image engines.")
    return False


# ─────────────────────────────────────────────────────────────────────────────
# ENGINE A — TOGETHER AI FLUX.1-schnell  (optional, paid)
# ─────────────────────────────────────────────────────────────────────────────
def fetch_together_frames(base_query, narration, character_bible,
                          count, out_dir, prefix, api_key, game_config):
    print(f"    🚀 [Engine A] Together AI FLUX.1-schnell — {count} frames...")
    scene_seed = random.randint(10_000, 9_999_999)
    print(f"    🎲 Seed: {scene_seed}")

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    paths   = []

    for i in range(count):
        stage    = FRAME_STAGES[i % len(FRAME_STAGES)]
        prompt   = build_image_prompt(base_query, narration, character_bible, stage, game_config)
        out_path = os.path.join(out_dir, f"{prefix}_tog_{i:02d}.jpg")

        payload = {
            "model": TOGETHER_MODEL, "prompt": prompt,
            "negative_prompt": NEGATIVE_PROMPT,
            "steps": TOGETHER_STEPS, "n": 1,
            "seed": scene_seed, "width": 1080, "height": 1920,
        }

        success = False
        for attempt in range(1, 4):
            try:
                resp = requests.post(TOGETHER_API_URL, json=payload,
                                     headers=headers, timeout=120)
                if resp.status_code == 429:
                    wait = 30 * attempt
                    print(f"    ⏳ Frame {i+1:02d} 429 (attempt {attempt}/3) — sleeping {wait}s...")
                    time.sleep(wait)
                    continue
                if resp.status_code == 200:
                    img_data = resp.json().get("data", [{}])[0]
                    b64      = img_data.get("b64_json")
                    img_url  = img_data.get("url")
                    if b64:
                        import base64
                        with open(out_path, "wb") as f:
                            f.write(base64.b64decode(b64))
                    elif img_url:
                        r2 = requests.get(img_url, timeout=60)
                        with open(out_path, "wb") as f:
                            f.write(r2.content)
                    else:
                        print(f"    ⚠️  Frame {i+1:02d}: no image in response")
                        break
                    if os.path.getsize(out_path) > 5000:
                        print(f"    ✅ Together frame {i+1:02d}/{count}")
                        paths.append(out_path)
                        success = True
                        break
                    time.sleep(5)
                    continue
                print(f"    ⚠️  Frame {i+1:02d} HTTP {resp.status_code}: {resp.text[:120]}")
                time.sleep(10)
            except requests.exceptions.Timeout:
                print(f"    ⚠️  Frame {i+1:02d} timeout (attempt {attempt}/3) — sleeping 30s...")
                time.sleep(30)
            except Exception as e:
                print(f"    ⚠️  Frame {i+1:02d} error: {e} — retrying 10s...")
                time.sleep(10)

        if not success:
            print(f"    ❌ Frame {i+1:02d} failed after 3 attempts.")
        elif i < count - 1:
            time.sleep(1)

    return paths


# ─────────────────────────────────────────────────────────────────────────────
# ENGINE B — POLLINATIONS AI  (free, no key needed)
# ─────────────────────────────────────────────────────────────────────────────
def _fetch_one_pollinations_frame(args):
    """Fetch a single Pollinations frame. Runs inside ThreadPoolExecutor."""
    i, url, out_path = args
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"),
        "Referer": "https://pollinations.ai/",
        "Accept":  "image/webp,image/apng,image/*,*/*;q=0.8",
    }
    for attempt in range(1, POLL_MAX_RETRY + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=POLL_TIMEOUT, stream=True)
            if resp.status_code == 429:
                time.sleep(POLL_DELAY_429)
                continue
            if (resp.status_code == 200
                    and "image" in resp.headers.get("content-type", "")):
                with open(out_path, "wb") as f:
                    for chunk in resp.iter_content(8192):
                        f.write(chunk)
                if os.path.getsize(out_path) > 5000:
                    return (i, out_path, True)
            time.sleep(5)
        except requests.exceptions.Timeout:
            time.sleep(10)
        except Exception:
            time.sleep(5)
    return (i, out_path, False)


def fetch_pollinations_frames(base_query, narration, character_bible,
                              count, out_dir, prefix, game_config):
    # One seed per scene: small +i*1000 offset nudges the pose without
    # changing the character's outfit, colours, or proportions across frames.
    scene_seed = random.randint(10_000, 9_999_999)
    neg_enc    = requests.utils.quote(NEGATIVE_PROMPT)
    print(f"    🌸 [Engine B] Pollinations AI — {count} frames IN PARALLEL  |  seed: {scene_seed}")

    tasks = []
    for i in range(count):
        stage    = FRAME_STAGES[i % len(FRAME_STAGES)]
        prompt   = build_image_prompt(base_query, narration, character_bible, stage, game_config)
        encoded  = requests.utils.quote(prompt)
        seed     = scene_seed + i * 1000
        url      = (f"https://image.pollinations.ai/prompt/{encoded}"
                    f"?width=1080&height=1920&nologo=true"
                    f"&seed={seed}&model=flux&negative={neg_enc}")
        out_path = os.path.join(out_dir, f"{prefix}_pol_{i:02d}.jpg")
        tasks.append((i, url, out_path))

    results = [None] * count
    with ThreadPoolExecutor(max_workers=count) as pool:
        futures = {pool.submit(_fetch_one_pollinations_frame, t): t[0] for t in tasks}
        for fut in as_completed(futures):
            i, out_path, ok = fut.result()
            stage = FRAME_STAGES[i % len(FRAME_STAGES)]
            if ok:
                print(f"    ✅ Frame {i+1:02d}/{count} — [{stage}]")
                results[i] = out_path
            else:
                print(f"    ❌ Frame {i+1:02d}/{count} failed after {POLL_MAX_RETRY} attempts.")

    return [p for p in results if p is not None]


# ─────────────────────────────────────────────────────────────────────────────
# CAPTION  (MoviePy v2 — font must be a file path)
# ─────────────────────────────────────────────────────────────────────────────
_FONT_PATH = None


def make_caption_clip(text, duration):
    global _FONT_PATH
    if _FONT_PATH is None:
        _FONT_PATH = find_font()
    if _FONT_PATH is None:
        print("    ⚠️  No system font found — captions skipped.")
        return None
    try:
        txt = TextClip(
            text=text, font=_FONT_PATH, font_size=CAPTION_FONTSIZE,
            color="white", stroke_color="black", stroke_width=4,
            size=(VIDEO_W - 100, None), method="caption", text_align="center",
        )
        return (txt
                .with_duration(duration)
                .with_position(("center", int(VIDEO_H * CAPTION_Y_FRAC))))
    except Exception as e:
        print(f"    ⚠️  Caption failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# SCENE VISUAL — full engine cascade  V → A → B → local
# ─────────────────────────────────────────────────────────────────────────────
def fetch_scene_visual(scene, scene_idx, character_bible, work_dir, game_config):
    query     = scene["query"]
    narration = scene["narration"]
    dur       = scene.get("duration", 10)
    out_path  = os.path.join(work_dir, f"scene_{scene_idx}_visual.mp4")

    hf_token     = clean_env(os.getenv("HF_TOKEN"))
    together_key = clean_env(os.getenv("TOGETHER_API_KEY"))

    # ── Engine V: HuggingFace text-to-video ──────────────────────────────────
    if hf_token:
        print(f"\n    ▶ Engine V: HuggingFace text-to-video...")
        # Build a short natural-language video prompt from the query + game style
        video_prompt = (
            f"Roblox Shorts cinematic scene: {query}. "
            f"{game_config['image_style']}. "
            "Blocky avatar characters, vivid neon colors, dramatic action, "
            "vertical 9:16 frame, no text overlays."
        )
        if fetch_hf_video(video_prompt, dur, out_path, hf_token):
            return VideoFileClip(out_path)
        print("    ↩  Engine V failed — trying Engine A/B...")
    else:
        print("    ℹ️  HF_TOKEN not set — skipping Engine V (text-to-video).")

    # ── Engine A: Together AI images ─────────────────────────────────────────
    paths = []
    if together_key:
        print(f"\n    ▶ Engine A: Together AI — {FRAMES_PER_SCENE} frames for {dur:.1f}s...")
        paths = fetch_together_frames(
            query, narration, character_bible,
            FRAMES_PER_SCENE, work_dir, f"s{scene_idx}",
            together_key, game_config,
        )
    else:
        print("    ℹ️  TOGETHER_API_KEY not set — skipping Engine A.")

    # ── Engine B: Pollinations images ────────────────────────────────────────
    if not paths:
        print(f"\n    ▶ Engine B: Pollinations AI — {FRAMES_PER_SCENE} frames...")
        paths = fetch_pollinations_frames(
            query, narration, character_bible,
            FRAMES_PER_SCENE, work_dir, f"s{scene_idx}", game_config,
        )

    # ── Local assets: last resort ────────────────────────────────────────────
    if not paths:
        print("    📁 All image engines failed — using local assets.")
        paths = pick_local_assets(count=FRAMES_PER_SCENE)

    # BUG FIX: wrap compile in try/except — an ffmpeg failure previously raised
    # RuntimeError which propagated all the way up and killed the entire pipeline.
    # Now we fall back to a blank clip so the rest of the scenes still render.
    try:
        compile_frames_to_video(paths, dur, out_path)
        return VideoFileClip(out_path)
    except Exception as e:
        print(f"    ⚠️  Frame compile failed: {e} — using blank fallback clip.")
        _write_blank_video(out_path, dur)
        return VideoFileClip(out_path)


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

    prompt = f"""
You are a viral AI content director making YouTube Shorts about Roblox {game_config['display_name']}.
Today's date is {today}.

GAME: {game_config['display_name']}
GENRE: {genre}
EPISODE: {episode_number}

PREVIOUS EPISODE CONTEXT (continue directly from here):
{previous_context}

EXISTING CHARACTER BIBLE:
{character_context}

YOUR TASK:
Write the NEXT episode as exactly 5 scenes (~200-220 words total, ~40-44 words per scene).
Each scene narration MUST be 2-3 full sentences so the voiceover fills ~10-12 seconds.
Rules:
1. Continue the story DIRECTLY from the previous episode context.
   The viewer watched the last episode — do NOT restart the story.
2. End on a CLIFFHANGER so viewers want to see the next episode.
3. Each scene needs a visual QUERY describing exactly what to render.
4. Weave in at least ONE real-life reference relevant to {today} —
   a trending meme, viral gaming moment, current internet trend, or
   real-world event parallel. Make it feel current and relatable.

CHARACTER BIBLE RULES — CRITICAL:
Describe EVERY character with ALL 7 fields using Roblox avatar language ONLY.
NEVER use realistic words like "dark robes", "glowing eyes", or "black hair".
ALWAYS use Roblox decal names, accessory item names, and avatar part colors.

Required fields:
- clothes: full outfit in Roblox item names (shirt color, pants, vest, shoes)
- facial_features: Roblox face decal name + placement
- accessories: ALL accessories with colors (hat, back, neck, shoulder)
- aura_color: power aura color and particle effects
- body_color: blocky skin color + avatar height
- signature_weapon: weapon or ability with visual description
- personality: 2-3 words

Output ONLY valid JSON, no markdown fences:
{{
  "title": "Catchy episode title with episode number",
  "game": "{game_config['display_name']}",
  "real_life_reference": "One sentence describing the real-life trend/event you referenced",
  "scenes": [
    {{"narration": "Two or three full dramatic sentences for scene 1.", "query": "{ex[0]}", "duration": 11}},
    {{"narration": "Two or three full dramatic sentences for scene 2.", "query": "{ex[1]}", "duration": 11}},
    {{"narration": "Two or three full dramatic sentences for scene 3.", "query": "{ex[2]}", "duration": 11}},
    {{"narration": "Two or three full dramatic sentences for scene 4.", "query": "{ex[3]}", "duration": 11}},
    {{"narration": "Two or three full dramatic sentences, massive cliffhanger.", "query": "{ex[0]} epic finale cliffhanger", "duration": 11}}
  ],
  "character_bible": {{
    "CharacterName": {{
      "clothes": "red straw hat accessory, open red vest shirt, blue knee-length pants, sandal shoes",
      "facial_features": "determined smile face decal, scar decal under left eye",
      "accessories": "straw hat accessory (yellow), wanted poster back accessory",
      "aura_color": "bright red-orange flame aura with ember particles",
      "body_color": "light tan blocky skin, medium height Roblox avatar",
      "signature_weapon": "giant rubber-stretched fist, gear fourth paw shockwave",
      "personality": "reckless, loud, heroic"
    }}
  }}
}}
"""

    resp = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2200, temperature=0.92,
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
        raise ValueError(f"Groq response truncated. Last 100 chars: {raw[-100:]}")

    data = json.loads(raw)

    open(mem_file, "w").write(" ".join(s["narration"] for s in data["scenes"]))
    json.dump(data.get("character_bible", {}), open(bible_file, "w"), indent=4)

    print(f"🎮 Game: {data.get('game', game_config['display_name'])}")
    print(f"🎬 Title: {data.get('title')}")
    print(f"📰 Real-life reference: {data.get('real_life_reference', 'none')}")
    print(f"📌 {len(data['scenes'])} scenes.\n")
    return data


# ─────────────────────────────────────────────────────────────────────────────
# 2. VOICEOVER
# ─────────────────────────────────────────────────────────────────────────────
async def generate_voiceover(text, out_file):
    await edge_tts.Communicate(text, "en-US-ChristopherNeural", rate="+10%").save(out_file)


# ─────────────────────────────────────────────────────────────────────────────
# 3. ASSEMBLY  (MoviePy v2 syntax)
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

        visual  = fetch_scene_visual(scene, idx, character_bible, work_dir, game_config)
        visual  = visual.with_duration(actual_dur)
        caption = make_caption_clip(narration, actual_dur)
        layers  = [visual] + ([caption] if caption else [])

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
            bg = concatenate_audioclips([bg] * loops).subclipped(0, dur)
        else:
            bg = bg.subclipped(0, dur)
        # BUG FIX: MoviePy v2 renamed volumex() → multiply_volume()
        # with_volume_scaled() does not exist in v2 and crashes at this step
        final_audio = CompositeAudioClip([
            combined_voice,
            bg.multiply_volume(0.10),
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
        None, refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id, client_secret=client_secret,
    )
    yt    = build("youtube", "v3", credentials=creds, cache_discovery=False)
    title = storyboard_data.get("title", f"{game_config['display_name']} EP{episode_number}")
    hook  = storyboard_data["scenes"][0]["narration"]
    ref   = storyboard_data.get("real_life_reference", "")
    tags  = list(dict.fromkeys(
        game_config["hashtags"] + ["#Roblox", "#Shorts", "#Gaming"]
    ))

    body = {
        "snippet": {
            "title":       f"{title} #Shorts"[:100],
            "description": (
                f"{hook}\n\n"
                f"Game: {game_config['display_name']} | Episode {episode_number}\n"
                + (f"Reference: {ref}\n\n" if ref else "\n")
                + " ".join(game_config["hashtags"])
            ),
            "tags":       [t.lstrip("#") for t in tags],
            "categoryId": "20",
        },
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
    }

    media    = MediaFileUpload("final_short.mp4", chunksize=-1, resumable=True)
    req      = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = req.next_chunk()
        if status:
            print(f"    ⏳ {int(status.progress() * 100)}%")

    print(f"🎉 Uploaded! https://youtube.com/shorts/{response.get('id')}")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    print("=" * 62)
    print("  Roblox Auto-Shorts — Multi-Game Edition v5")
    print("  8 Games · Per-game Memory · Live HF Video Discovery")
    print("=" * 62 + "\n")

    hf_token     = clean_env(os.getenv("HF_TOKEN"))
    together_key = clean_env(os.getenv("TOGETHER_API_KEY"))

    print("─── Engine Status ───────────────────────────────────────")
    print(f"  Engine V (live HF video):    {'✅ active' if hf_token else '⬜ skipped (no HF_TOKEN)'}")
    print(f"  Engine A (Together AI):      {'✅ active' if together_key else '⬜ skipped (no TOGETHER_API_KEY)'}")
    print(f"  Engine B (Pollinations):     ✅ always active (free)")
    print("─────────────────────────────────────────────────────────\n")

    state       = load_game_state()
    game_slug   = get_current_game(state)
    game_config = ROBLOX_GAMES[game_slug]

    state["episode_counts"] = state.get("episode_counts", {g: 0 for g in GAME_ORDER})
    state["episode_counts"][game_slug] = state["episode_counts"].get(game_slug, 0) + 1
    episode_number = state["episode_counts"][game_slug]

    next_idx  = (state["game_index"] + 1) % len(GAME_ORDER)
    next_game = ROBLOX_GAMES[GAME_ORDER[next_idx]]["display_name"]

    print(f"🎮 Game this run:  {game_config['display_name']}")
    print(f"📺 Episode number: {episode_number}")
    print(f"🔄 Next run:       {next_game}\n")

    advance_game_state(state)
    # BUG FIX: save state immediately after advancing — if the pipeline crashes
    # during assembly or upload, the new game index is preserved so the next
    # run starts on the correct game instead of repeating this one
    save_game_state(state)

    storyboard = generate_storyboard(game_slug, game_config, episode_number)
    assemble_storyboard(storyboard, game_slug, game_config)
    upload_to_youtube(storyboard, game_config, episode_number)

    print("\n🏁 Pipeline complete.")


if __name__ == "__main__":
    main()
