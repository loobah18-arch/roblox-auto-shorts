import os
import json
import re
import random
import glob
import asyncio
import requests
import urllib.request
import edge_tts
import time
import subprocess
import shutil
from pathlib import Path
try:
    from groq import Groq
except ImportError:
    Groq = None
# moviepy import removed — pipeline uses pure FFmpeg for rendering
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# --- CONFIGURATION ---
# Live free-tier models available via the local OpenCode CLI (verified 2026-08).
# Ordered strongest-first. All 100% free — no API keys required.
OPENCODE_FREE_MODELS = [
    "opencode/nemotron-3-ultra-free",
    "opencode/nemotron-3.5-lightning-free",
    "opencode/mimo-v2.5-free",
    "opencode/hy3-free",
    "opencode/muse-spark-1.2-contributor-free"
]

GAMES = [
    "Blox Fruits",
    "Brookhaven",
    "Adopt Me!",
    "Murder Mystery 2",
    "Tower of Hell"
]

def get_safe_filename(game_name):
    """Formats game name for safe file mapping (e.g., 'Adopt Me!' -> 'adopt_me')"""
    clean_name = re.sub(r'[^a-z0-9_]', '', game_name.lower().replace(" ", "_"))
    return clean_name

# --- STATE & MEMORY MANAGEMENT ---
def load_game_state():
    if os.path.exists("game_state.json"):
        try:
            with open("game_state.json", "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"current_index": 0, "total_videos_run": 1, "game_parts": {}}

def save_game_state(current_index, total_videos_run, game_parts=None):
    if game_parts is None:
        state = load_game_state()
        game_parts = state.get("game_parts", {})
    with open("game_state.json", "w") as f:
        json.dump({
            "current_index": current_index,
            "total_videos_run": total_videos_run,
            "game_parts": game_parts
        }, f, indent=4)

def get_story_memory(safe_game_name):
    filename = f"story_memory_{safe_game_name}.txt"
    if os.path.exists(filename):
        with open(filename, "r") as f:
            content = f.read().strip()
            if content:
                return content
    return "A legendary adventure in the Roblox universe begins today."

def save_story_memory(safe_game_name, new_memory):
    filename = f"story_memory_{safe_game_name}.txt"
    with open(filename, "w") as f:
        f.write(new_memory.strip())

def get_character_bible(safe_game_name):
    filename = f"character_bible_{safe_game_name}.json"
    if os.path.exists(filename):
        try:
            with open(filename, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return json.dumps(data, indent=2)
        except Exception:
            pass
    return "No character bible found for this game."

def load_active_model():
    """Loads the last successfully used LLM model. Defaults to the strongest free OpenCode model."""
    if os.path.exists("active_llm_model.txt"):
        try:
            with open("active_llm_model.txt", "r") as f:
                model_name = f.read().strip()
                if model_name in OPENCODE_FREE_MODELS:
                    return model_name
        except Exception:
            pass
    return OPENCODE_FREE_MODELS[0]

def save_active_model(model_name):
    """Saves the successfully used LLM model name to persistent storage."""
    try:
        with open("active_llm_model.txt", "w") as f:
            f.write(model_name.strip())
        print(f"[+] Sticky model state updated: {model_name}")
    except Exception as e:
        print(f"Failed to save active model: {e}")


# --- IMAGE PROVIDER STATE MANAGEMENT ---
PROVIDERS = [
    "pollinations_new",
    "pollinations_flux_realism",
    "pollinations_turbo",
    "pollinations_flux_pro",
    "huggingface_flux"
]

def load_active_image_provider():
    """Loads the last successfully used image provider. Defaults to 'pollinations_new'."""
    if os.path.exists("active_image_provider.txt"):
        try:
            with open("active_image_provider.txt", "r") as f:
                provider_name = f.read().strip()
                if provider_name in PROVIDERS:
                    return provider_name
        except Exception:
            pass
    return "pollinations_new"

def save_active_image_provider(provider_name):
    """Saves the successfully working image provider name to persistent storage."""
    try:
        with open("active_image_provider.txt", "w") as f:
            f.write(provider_name.strip())
        print(f"[+] Sticky image provider updated: {provider_name}")
    except Exception as e:
        print(f"Failed to save active image provider: {e}")

# --- HELPER FUNCTIONS ---
VOICEOVER_MIN_WORDS = 135
VOICEOVER_MAX_WORDS = 160

def voiceover_score(data):
    """0 = voiceover within the 135-160 word spec; otherwise deviation from the range."""
    wc = len(str(data.get("voiceover", "")).split())
    if wc < VOICEOVER_MIN_WORDS:
        return VOICEOVER_MIN_WORDS - wc
    if wc > VOICEOVER_MAX_WORDS:
        return wc - VOICEOVER_MAX_WORDS
    return 0

def extract_json(text):
    """Safely extracts and parses a JSON block from potentially conversational LLM output."""
    clean = text.strip()
    clean = re.sub(r"<think>.*?</think>", "", clean, flags=re.DOTALL).strip()
    if "```json" in clean:
        clean = clean.split("```json")[1].split("```")[0].strip()
    elif "```" in clean:
        clean = clean.split("```")[1].split("```")[0].strip()
    try:
        return json.loads(clean)
    except Exception:
        match = re.search(r'\{[\s\S]*\}', clean)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
        return None

def create_fallback_image(path, index):
    """Generates a high-quality vertical geometric placeholder card using Pillow if Pollinations AI fails."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        print(f"Creating self-healing high-quality visual placeholder for scene {index}...")
        # High resolution vertical short layout (1080x1920)
        img = Image.new("RGB", (1080, 1920), color=(15, 15, 27))
        draw = ImageDraw.Draw(img)
        # Draw clean, stylized abstract background curves
        for i in range(10):
            offset = i * 60
            draw.arc([100 - offset, 400 - offset, 980 + offset, 1500 + offset], start=0, end=360, fill=(40 + i*15, 30 + i*10, 80 + i*5), width=2)
        # Draw central neon focus panel
        draw.rounded_rectangle([140, 760, 940, 1160], radius=30, fill=(30, 30, 50), outline=(0, 255, 255), width=4)
        img.save(path)
        return True
    except Exception as e:
        print(f"Pillow placeholder generation failed: {e}")
        return False

# --- OPENCODE & LLM API CALLERS ---
def query_opencode_cli(model, system_prompt, user_prompt, require_voiceover=True):
    """Priority 1: Queries local OpenCode CLI for free tier AI models. No API key needed."""
    opencode_bin = shutil.which("opencode") or str(Path.home() / ".opencode/bin/opencode")
    if opencode_bin and (Path(opencode_bin).exists() or shutil.which("opencode")):
        try:
            full_prompt = (
                f"{system_prompt}\n\n"
                f"{user_prompt}\n\n"
                "Return ONLY a single valid raw JSON object. No conversational preamble, no markdown wrappers."
            )
            res = subprocess.run(
                [opencode_bin, "run", "-m", model, full_prompt],
                capture_output=True,
                text=True,
                timeout=180
            )
            if res.returncode == 0 and res.stdout:
                parsed = extract_json(res.stdout)
                if not isinstance(parsed, dict):
                    return None
                if require_voiceover:
                    if "voiceover" in parsed:
                        vo = parsed["voiceover"].strip()
                        if not ("Create an intense" in vo or " strictly between" in vo):
                            return parsed
                    return None
                return parsed
        except Exception as e:
            print(f"[OpenCode CLI {model}] Note: {e}")
    return None

def query_llm_chat(provider, model, system_prompt, user_prompt, api_key):
    """Universal HTTP caller for OpenAI-compatible chat completion APIs (OpenCode, DeepSeek, NVIDIA, Groq)."""
    if not api_key:
        return None
    url_map = {
        "opencode": os.environ.get("OPENCODE_BASE_URL", "https://api.opencode.ai/v1/chat/completions"),
        "deepseek": "https://api.deepseek.com/chat/completions",
        "nvidia": "https://integrate.api.nvidia.com/v1/chat/completions",
        "groq": "https://api.groq.com/openai/v1/chat/completions"
    }
    url = url_map.get(provider)
    if not url:
        return None
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/loobah18-arch/roblox-auto-shorts",
        "X-Title": "Roblox Auto Shorts"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt + "\nYou MUST return ONLY a valid JSON object matching the required schema."},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 1800
    }
    if provider in ["groq", "deepseek"]:
        payload["response_format"] = {"type": "json_object"}
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "choices" in data and len(data["choices"]) > 0:
                raw_text = data["choices"][0]["message"].get("content", "")
                if raw_text:
                    parsed = extract_json(raw_text)
                    if parsed and "voiceover" in parsed:
                        vo = parsed["voiceover"].strip()
                        if not ("Create an intense" in vo or " strictly between" in vo):
                            return parsed
    except Exception as e:
        print(f"[{provider}:{model}] Generation note: {e}")
    return None

# --- PIPELINE FUNCTIONS ---
def generate_script_and_images(game, memory, bible):
    """Integrates with OpenCode (DeepSeek v4 Flash), direct DeepSeek API, NVIDIA Nemotron 3 Ultra, Groq, and Pollinations AI.
    Prioritizes top free tier models (OpenCode/DeepSeek), cascading to next best free models, then flagship proprietary tier, then Groq fast tier, and self-healing fallback.
    """
    raw_o_key = os.environ.get("OPENCODE_API_KEY", "")
    opencode_api_key = raw_o_key.strip().replace(" ", "").strip("\"'") if raw_o_key else None

    raw_n_key = os.environ.get("NVIDIA_API_KEY", "")
    nvidia_api_key = raw_n_key.strip().replace(" ", "").strip("\"'") if raw_n_key else None
    
    raw_g_key = os.environ.get("GROQ_API_KEY", "")
    groq_api_key = raw_g_key.strip().replace(" ", "").strip("\"'") if raw_g_key else None
    
    # System role enforces narrative formatting and output structure
    system_prompt = """You are a professional cinematic story narrator and Roblox lore master. Your job is to output a single JSON object containing a high-energy spoken story narrative (the voiceover), a story progress cliffhanger memory, and image prompts.

CRITICAL ROLE RULE:
The 'voiceover' field MUST ONLY contain the actual spoken, theatrical, dramatic story narration. It must NEVER repeat prompt instructions, meta-commands, introduction headings, or variables like 'Create an intense, cinematic Roblox script...'. Jump directly into the cinematic storyline as if you are reading the final script.

Output JSON format must match this schema EXACTLY:
{
  "voiceover": "Spoken dramatic narrative text (strictly between 135 to 160 words)",
  "new_memory": "Summary of the story cliffhanger for tomorrow's continuation",
  "image_prompts": ["Visual scene prompt 1", "Visual scene prompt 2", "Visual scene prompt 3", "Visual scene prompt 4", "Visual scene prompt 5", "Visual scene prompt 6", "Visual scene prompt 7", "Visual scene prompt 8"]
}"""

    # User role provides specific variables and length bounds
    user_prompt = f"""Write an intense, cinematic Roblox {game} episode narrative.

Variables:
- Active Game: Roblox {game}
- Previous Story Memory: {memory}
- Character Bible: {bible}

Episode Writing Guidelines:
- Length: Strictly between 135 to 160 words to target a 50+ second video length at standard pacing.
- Voice: Commanding, theatrical, high-stakes narration.
- Visual pacing: Provide exactly 8 distinct visual scene descriptions in 'image_prompts' that progress chronologically with your voiceover story.
- Output JSON strictly matching the system instructions."""

    # Priority Tier 1: OpenCode free models (local CLI — always free, no keys)
    opencode_free_models = OPENCODE_FREE_MODELS

    # Priority Tier 2: NVIDIA NIM models (free API key from build.nvidia.com)
    nvidia_models = [
        "nvidia/nemotron-3-ultra-550b-a55b",
        "nvidia/llama-3.1-nemotron-70b-instruct"
    ]

    # Priority Tier 3: Groq models (free tier API key from console.groq.com)
    groq_models = [
        "llama-3.3-70b-versatile",
        "deepseek-r1-distill-llama-70b",
        "openai/gpt-oss-20b"
    ]

    sticky_model = load_active_model()
    print(f"Sticky model loaded: {sticky_model}")

    best_data = None
    best_score = float("inf")
    successful_model = None
    llm_attempts = 0
    MAX_LLM_ATTEMPTS = 10

    length_reminder = (
        "\n\nCRITICAL LENGTH FIX: Your previous voiceover did not meet the required length. "
        f"Regenerate the JSON with a voiceover of STRICTLY {VOICEOVER_MIN_WORDS} to {VOICEOVER_MAX_WORDS} words."
    )

    def consider(result, model_id):
        """Records the result if it is the closest-to-spec so far. Returns True only on a perfect match."""
        nonlocal best_data, best_score, successful_model
        if not isinstance(result, dict):
            return False
        score = voiceover_score(result)
        if score < best_score:
            best_score = score
            best_data = result
            successful_model = model_id
        return score == 0

    # --- TIER 1: Best Free Tier AI Models (OpenCode CLI & HTTP) ---
    print("🧠 [Tier 1] Querying OpenCode Free Tier models (Priority 1)...")
    candidates = [sticky_model] if sticky_model in opencode_free_models else []
    for m in opencode_free_models:
        if m not in candidates:
            candidates.append(m)

    for model_id in candidates:
        if llm_attempts >= MAX_LLM_ATTEMPTS or best_score == 0:
            break
        print(f"  -> Attempting OpenCode model via CLI: {model_id}...")
        result = query_opencode_cli(model_id, system_prompt, user_prompt)
        llm_attempts += 1
        if consider(result, model_id):
            print(f"✅ Success! OpenCode model {model_id} generated story script.")
            break
        if result and llm_attempts < MAX_LLM_ATTEMPTS:
            # One bounded retry with an explicit length correction
            print(f"  -> Voiceover out of word range; retrying {model_id} with length correction...")
            result = query_opencode_cli(model_id, system_prompt + length_reminder, user_prompt)
            llm_attempts += 1
            if consider(result, model_id):
                print(f"✅ Success! OpenCode model {model_id} generated story script (after retry).")
                break

    if best_score > 0 and opencode_api_key:
        print("🧠 [Tier 1] Querying OpenCode HTTP endpoint...")
        for model_id in opencode_free_models:
            if llm_attempts >= MAX_LLM_ATTEMPTS or best_score == 0:
                break
            print(f"  -> Attempting OpenCode HTTP: {model_id}...")
            result = query_llm_chat("opencode", model_id, system_prompt, user_prompt, opencode_api_key)
            llm_attempts += 1
            if consider(result, model_id):
                print(f"✅ Success! OpenCode HTTP {model_id} generated story script.")
                break

    # --- TIER 2: Free NVIDIA NIM (free API key from build.nvidia.com) ---
    if best_score > 0 and nvidia_api_key:
        print("🧠 [Tier 2] Free tier unavailable. Escalating to current best model: NVIDIA Nemotron 3 Ultra (550B MoE)...")
        for model_id in nvidia_models:
            if llm_attempts >= MAX_LLM_ATTEMPTS or best_score == 0:
                break
            print(f"  -> Attempting NVIDIA NIM model: {model_id}...")
            result = query_llm_chat("nvidia", model_id, system_prompt, user_prompt, nvidia_api_key)
            llm_attempts += 1
            if consider(result, model_id):
                print(f"✅ Success! NVIDIA NIM model {model_id} generated story script.")
                break

    # --- TIER 3: High-Speed Groq Free Tier ---
    if best_score > 0 and groq_api_key:
        print("🧠 [Tier 3] Escalating to Groq High-Speed API...")
        for model_id in groq_models:
            if llm_attempts >= MAX_LLM_ATTEMPTS or best_score == 0:
                break
            print(f"  -> Attempting Groq model: {model_id}...")
            result = query_llm_chat("groq", model_id, system_prompt, user_prompt, groq_api_key)
            llm_attempts += 1
            if consider(result, model_id):
                print(f"✅ Success! Groq model {model_id} generated story script.")
                break

    # --- TIER 4: Self-Healing Procedural Narrative Fallback ---
    if best_data is None:
        print("⚠️ [Tier 4] All AI endpoints unreachable. Activating Self-Healing Narrative Fallback...")
        response_data = {
            "voiceover": (
                f"The shadows of the {game} grid tremble tonight, because something ancient has finally awakened. "
                "The players logged in expecting another harmless server, another easy grind, another quiet evening — but they were wrong. "
                "Deep beneath the city lies a hidden bunker, sealed for years, guarded by shifting laser beams, locked doors, "
                "and a mystery no code can crack. As the countdown ticks lower, one brave survivor steps forward while everyone else runs. "
                "They carry nothing but a rusty tool, a half-charged flashlight, and a legend whispered in the lobby for generations. "
                "Behind every corridor, the darkness watches. Behind every door, the awakened power grows stronger. "
                "Will they claim the legendary prize before the timer hits zero, or will the bunker claim them instead? "
                "The choice is theirs... but time is running out, and the grid never forgives the slow."
            ),
            "new_memory": "The ancient bunker door creaks open, revealing a blinding neon light as a mysterious shadow steps through.",
            "image_prompts": [f"Epic Roblox {game} landscape under heavy dark sky"] * 8
        }
    else:
        response_data = best_data
        if best_score > 0:
            print(f"⚠️ No model hit the {VOICEOVER_MIN_WORDS}-{VOICEOVER_MAX_WORDS} word target (best deviation: {int(best_score)} words). Using closest result.")
        if successful_model:
            save_active_model(successful_model)

    audio_text = response_data.get("voiceover", "The journey continues...")
    new_memory = response_data.get("new_memory", "To be continued...")
    prompts = response_data.get("image_prompts", ["Roblox landscape"] * 8)
    image_paths = []

    # Safeguard prompt count to always be exactly 8 to lock transition speed and video pacing
    while len(prompts) < 8:
        prompts.append("Roblox landscape, Unreal Engine 5 render")
    prompts = prompts[:8]

    print(f"Generating {len(prompts)} correlated vertical visual assets using our Auto-Healing Multi-Provider Engine...")
    
    # Load and order providers so the active one is tried first
    active_provider = load_active_image_provider()
    ordered_providers = [active_provider] + [p for p in PROVIDERS if p != active_provider]
    print(f"Image generation fallback chain (sticky first): {ordered_providers}")
    
    import hashlib
    
    for i, img_prompt in enumerate(prompts):
        path = f"scene_{i}.jpg"
        seed = random.randint(1, 999999999)
        
        # Spreading outgoing requests with delay to bypass Cloudflare burst protections
        # Only apply delay for Pollinations providers; HuggingFace has its own rate limiting
        if i > 0 and not active_provider.startswith("huggingface"):
            delay = random.uniform(30.5, 45.5)
            print(f"Spreading API load. Sleeping for {delay:.2f} seconds (optimal delay) before retrieving scene {i}...")
            time.sleep(delay)
            
        success = False
        
        # Iterate through the ordered provider fallbacks
        for provider in ordered_providers:
            print(f"Attempting scene {i} using provider: {provider}...")
            
            # 2 retries per provider
            max_retries = 2
            provider_success = False
            
            for attempt in range(max_retries):
                try:
                    # Game-specific cinematic style context for more relevant, high-quality images
                    game_style_map = {
                        "Blox Fruits": "anime-style oceanic adventure, tropical island, glowing devil fruit powers, vibrant sea",
                        "Brookhaven": "suburban cinematic drama, neon night lighting, realistic neighborhood atmosphere",
                        "Adopt Me!": "colorful pastel fantasy world, cute magical pets, glowing nursery, dreamy sky",
                        "Murder Mystery 2": "dark neon-lit mansion interior, mystery thriller, dramatic long shadows",
                        "Tower of Hell": "extreme neon obstacle course, glowing platforms, dizzying heights, sci-fi arena"
                    }
                    game_style = game_style_map.get(game, "cinematic Roblox game scene")
                    style_modifier = (
                        f", {game_style}, cinematic vertical composition, dramatic lighting, "
                        "high detail, vibrant colors, professional game art, "
                        "volumetric fog, 8k resolution, award-winning render"
                    )
                    enhanced_prompt = f"{img_prompt}{style_modifier}"

                    headers = {}
                    timeout = 60

                    # Truncate prompt to prevent URL length errors (Pollinations rejects very long URLs)
                    MAX_PROMPT_CHARS = 400
                    if len(enhanced_prompt) > MAX_PROMPT_CHARS:
                        enhanced_prompt = enhanced_prompt[:MAX_PROMPT_CHARS]
                    safe_prompt = requests.utils.quote(enhanced_prompt, safe='')

                    if provider == "pollinations_new":
                        # enhance=true uses Pollinations' free AI prompt enhancer for better results
                        url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1080&height=1920&model=flux&seed={seed}&nologo=true&enhance=true"
                        response = requests.get(url, timeout=timeout)
                    elif provider == "pollinations_flux_realism":
                        # Flux-realism model: photorealistic outputs, distinct from flux base
                        url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1080&height=1920&model=flux-realism&seed={seed}&nologo=true&enhance=true"
                        response = requests.get(url, timeout=timeout)
                    elif provider == "pollinations_turbo":
                        url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1080&height=1920&model=turbo&seed={seed}&nologo=true"
                        response = requests.get(url, timeout=timeout)
                    elif provider == "pollinations_flux_pro":
                        # Flux-pro: higher quality, slower, used as final Pollinations fallback
                        url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1080&height=1920&model=flux-pro&seed={seed}&nologo=true"
                        response = requests.get(url, timeout=timeout)
                    elif provider == "huggingface_flux":
                        hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HF_API_KEY")
                        if not hf_token:
                            raise ValueError("HF_TOKEN secret not set — skipping huggingface_flux provider")
                        headers = {"Authorization": f"Bearer {hf_token}"}
                        url = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell"
                        payload = {
                            "inputs": enhanced_prompt,
                            "parameters": {"width": 1080, "height": 1920}
                        }
                        response = requests.post(url, json=payload, headers=headers, timeout=timeout)
                    else:
                        raise ValueError(f"Unknown image provider: {provider}")
                        
                    if response.status_code == 200:
                        content_len = len(response.content)
                        if content_len < 10240:
                            raise Exception(f"Downloaded file is suspiciously small ({content_len} bytes)")
                            
                        # Check for the Pollinations rate-limit image hash
                        file_hash = hashlib.md5(response.content).hexdigest()
                        if file_hash == "2090a5dc21c32952cbf8496339752bd1":
                            raise Exception("Pollinations rate-limit placeholder image detected.")
                            
                        with open(path, 'wb') as f:
                            f.write(response.content)
                        
                        print(f"[+] Scene {i} successfully rendered by provider: {provider} (Attempt {attempt+1})")
                        provider_success = True
                        break
                    else:
                        raise Exception(f"Failed status code {response.status_code}")
                        
                except Exception as e:
                    print(f"[-] Attempt {attempt+1} failed with provider {provider}: {e}")
                    if attempt < max_retries - 1:
                        retry_delay = 15 + attempt * 10
                        print(f"Waiting {retry_delay}s before retrying provider...")
                        time.sleep(retry_delay)
            
            if provider_success:
                # Update sticky provider if we successfully switched to a new working one
                if provider != active_provider:
                    active_provider = provider
                    save_active_image_provider(provider)
                    # Re-order list so this working provider is tried first next time
                    ordered_providers = [active_provider] + [p for p in PROVIDERS if p != active_provider]
                success = True
                break
            else:
                print(f"[-] Provider {provider} exhausted. Trying next fallback provider in chain...")
                time.sleep(2) # Short pause before switching providers
                
        if not success:
            print(f"[!] WARNING: All online image providers failed for scene {i}. Deploying visual fallback...")
            create_fallback_image(path, i)
            
        image_paths.append(path)

    return audio_text, new_memory, image_paths

def evolve_character_bible(game_name, safe_game_name, script_text, current_bible_text):
    """Dynamically updates the character bible based on narrative developments in the latest script.
    Fully free: uses local OpenCode CLI models first, then Groq free tier as fallback."""
    print(f"Running self-evolution pass for {game_name} Character Bible...")

    system_prompt = """You are the Lead Lore Master and Story Architect for our automated Roblox YouTube Shorts channel.
Your task is to update and evolve the Character Bible for the game based on the events that occurred in the latest episode script.

Output the FULL updated Character Bible strictly as a single valid, parsable JSON object. Do not include any conversational prefix, suffix, or formatting codes in your output. Combine the current traits with newly discovered developments, inventory gains, or relationship changes."""

    user_prompt = f"""Evolve the Character Bible for {game_name}.

CURRENT BIBLE LORE:
{current_bible_text}

LATEST EPISODE SCRIPT:
{script_text}

Analyze the latest episode script for key updates (allies, stats, inventory fruit awakenings, etc.) and write the entire merged and updated Character Bible JSON."""

    def save_bible(updated_bible_data):
        if updated_bible_data and isinstance(updated_bible_data, dict):
            filename = f"character_bible_{safe_game_name}.json"
            with open(filename, "w") as f:
                json.dump(updated_bible_data, f, indent=4)
            print(f"[+] Lore evolution successful! Updated character bible saved to {filename}")
            return True
        return False

    # Priority 1: Free local OpenCode CLI models (no API key needed)
    sticky_model = load_active_model()
    candidates = [sticky_model] + [m for m in OPENCODE_FREE_MODELS if m != sticky_model]
    for model_id in candidates:
        print(f"  -> Attempting OpenCode CLI model: {model_id}...")
        result = query_opencode_cli(model_id, system_prompt, user_prompt, require_voiceover=False)
        if save_bible(result):
            return True

    # Priority 2: Groq free tier (only if a free API key is configured)
    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key:
        print("[-] No GROQ_API_KEY set and all OpenCode models failed. Safely keeping current bible.")
        return False

    try:
        from groq import Groq
        client = Groq(api_key=groq_api_key)
        for model_id in ["llama-3.3-70b-versatile", "openai/gpt-oss-20b"]:
            try:
                chat_completion = client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    model=model_id,
                    response_format={"type": "json_object"}
                )
                raw_text = chat_completion.choices[0].message.content
                if save_bible(extract_json(raw_text)):
                    return True
            except Exception as ex:
                print(f"[-] Groq evolution pass failed with model {model_id}: {ex}")
    except Exception as e:
        print(f"[-] Groq client unavailable: {e}")

    print("[-] All evolution providers failed. Safely keeping current bible.")
    return False

def split_text_for_captions(text, words_per_chunk=3):
    """Splits text into compact chunks to mirror high-retention short form editing styles."""
    words = text.split()
    chunks = []
    for i in range(0, len(words), words_per_chunk):
        chunk = " ".join(words[i:i + words_per_chunk])
        if len(chunk) > 18:
            middle = len(chunk) // 2
            space_idx = chunk.rfind(' ', 0, middle)
            if space_idx != -1:
                chunk = chunk[:space_idx] + "\n" + chunk[space_idx+1:]
        chunks.append(chunk)
    return chunks

# --- CAPTION STYLING & GENERATION ---
def format_time_ass(seconds):
    """Formats seconds to ASS time format (H:MM:SS.cs)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centiseconds = int(round((seconds % 1) * 100))
    if centiseconds == 100:
        centiseconds = 0
        secs += 1
        if secs == 60:
            secs = 0
            minutes += 1
            if minutes == 60:
                minutes = 0
                hours += 1
    return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"

def generate_ass_file(text_chunks, video_duration, output_ass_path, is_landscape=False):
    """Generates an Advanced SubStation Alpha (.ass) file with frame-accurate word-level karaoke timings.
    Supports both 9:16 portrait and 16:9 widescreen layouts."""
    total_words = sum(len(chunk.replace("\n", " ").split()) for chunk in text_chunks)
    current_time = 0.0
    
    if is_landscape:
        ass_header = """[Script Info]
; Script generated by Roblox Auto Shorts Engine
Title: Roblox Auto Subtitles Landscape
ScriptType: v4.00+
WrapStyle: 0
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: RobloxStyle,Impact,56,&H00FFFFFF,&H0000FFFF,&H00000000,&HA0000000,1,0,0,0,100,100,2,0,1,6,3,2,60,60,70,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    else:
        ass_header = """[Script Info]
; Script generated by Roblox Auto Shorts Engine
Title: Roblox Auto Shorts Subtitles
ScriptType: v4.00+
WrapStyle: 0
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: RobloxStyle,Impact,82,&H00FFFFFF,&H0000FFFF,&H00000000,&HA0000000,1,0,0,0,100,100,2,0,1,8,4,2,30,30,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    
    events = []
    for chunk in text_chunks:
        lines_split = chunk.strip().split('\n')
        words_by_line = [line.split() for line in lines_split]
        
        actual_word_count = sum(len(line_words) for line_words in words_by_line)
        if actual_word_count == 0:
            continue
            
        chunk_duration = (actual_word_count / total_words) * video_duration
        end_time = current_time + chunk_duration
        
        start_str = format_time_ass(current_time)
        end_str = format_time_ass(end_time)
        
        word_dur_cs = int(round((chunk_duration / actual_word_count) * 100))
        if word_dur_cs < 1:
            word_dur_cs = 1
            
        karaoke_parts = []
        words_processed = 0
        
        for line_words in words_by_line:
            line_parts = []
            for word in line_words:
                words_processed += 1
                if words_processed == actual_word_count:
                    chunk_duration_cs = int(round(chunk_duration * 100))
                    elapsed_cs = word_dur_cs * (actual_word_count - 1)
                    final_word_dur = max(1, chunk_duration_cs - elapsed_cs)
                    line_parts.append(fr"{{\kf{final_word_dur}}}{word}")
                else:
                    line_parts.append(fr"{{\kf{word_dur_cs}}}{word}")
            karaoke_parts.append(" ".join(line_parts))
            
        karaoke_text = r"\N".join(karaoke_parts)
        events.append(f"Dialogue: 0,{start_str},{end_str},RobloxStyle,,0,0,0,,{karaoke_text}")
        current_time = end_time
        
    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.write(ass_header)
        for event in events:
            f.write(event + "\n")
    print(f"[-] Subtitles ASS file generated ({'16:9 Landscape' if is_landscape else '9:16 Portrait'}): {output_ass_path}")

def generate_roblox_thumbnail(video_path, thumb_path, game_name="", part_number=1, is_landscape=False):
    """Generates a high-CTR custom thumbnail with bold curiosity text stamping."""
    try:
        clean_title = f"{game_name} - EPISODE {part_number}".upper() if game_name else "ROBLOX STORY"
        if is_landscape:
            vf = (
                f"scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,"
                f"drawbox=y=780:color=black@0.85:width=iw:height=150:t=fill,"
                f"drawbox=y=780:color=#00D2FF@0.95:width=iw:height=150:t=4,"
                f"drawtext=text='{clean_title}':fontcolor=#FFE600:fontsize=52:font='Impact':x=(w-text_w)/2:y=830"
            )
        else:
            vf = (
                f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                f"drawbox=y=1380:color=black@0.85:width=iw:height=160:t=fill,"
                f"drawbox=y=1380:color=#00D2FF@0.95:width=iw:height=160:t=4,"
                f"drawtext=text='{clean_title}':fontcolor=#FFE600:fontsize=46:font='Impact':x=(w-text_w)/2:y=1436"
            )
        subprocess.run([
            "ffmpeg", "-y",
            "-ss", "00:00:02.00",
            "-i", str(video_path),
            "-vframes", "1",
            "-vf", vf,
            "-q:v", "2",
            str(thumb_path)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(thumb_path):
            print(f"[+] Custom thumbnail generated: {thumb_path}")
    except Exception as te:
        print(f"[-] Thumbnail notice: {te}")

def render_video(audio_path, image_paths, text_chunks, is_landscape=False, output_path=None, game_name="", part_number=1):
    """Pure FFmpeg pipeline with Ken Burns pan/zoom per scene, audio mixing, subtitle burn, and thumbnail generation.
    Supports both 9:16 vertical Short and 16:9 widescreen Normal Video."""
    print(f"Assembling {'16:9 Landscape Normal Video' if is_landscape else '9:16 Portrait Short'} with Ken Burns motion effects via FFmpeg...")

    if not image_paths:
        raise ValueError("render_video received empty image_paths list — cannot build video without scenes.")

    # Get audio duration using ffprobe (no MoviePy dependency needed)
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
        capture_output=True, text=True, check=True
    )
    video_duration = float(result.stdout.strip())

    img_duration = video_duration / len(image_paths)
    scene_files = []

    # Cycle through 8 Ken Burns directions for visual variety
    kb_directions = [
        "zoom_in_center", "pan_right", "zoom_out_center",
        "pan_left", "zoom_in_topleft", "pan_up",
        "zoom_in_bottomright", "pan_down"
    ]

    res_w, res_h = (1920, 1080) if is_landscape else (1080, 1920)

    print(f"Applying Ken Burns pan/zoom to each scene ({res_w}x{res_h})...")
    for i, img_path in enumerate(image_paths):
        scene_out = f"scene_kb_{'ls_' if is_landscape else ''}{i}.mp4"
        direction = kb_directions[i % len(kb_directions)]
        frames = max(1, int(img_duration * 30))  # 30fps
        d_str = f"{img_duration:.4f}"
        fade_out_start = max(0.0, img_duration - 0.3)

        if direction == "zoom_in_center":
            zp = f"zoompan=z='min(zoom+0.0015,1.5)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={res_w}x{res_h}:fps=30"
        elif direction == "zoom_out_center":
            zp = f"zoompan=z='if(lte(zoom,1.0),1.5,max(zoom-0.0015,1.0))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={res_w}x{res_h}:fps=30"
        elif direction == "pan_right":
            zp = f"zoompan=z=1.3:x='min(iw/zoom/2+iw*0.2*on/{frames},iw-iw/zoom)':y='ih/2-(ih/zoom/2)':d={frames}:s={res_w}x{res_h}:fps=30"
        elif direction == "pan_left":
            zp = f"zoompan=z=1.3:x='max(iw/zoom/2-iw*0.2*on/{frames},0)':y='ih/2-(ih/zoom/2)':d={frames}:s={res_w}x{res_h}:fps=30"
        elif direction == "pan_up":
            zp = f"zoompan=z=1.3:x='iw/2-(iw/zoom/2)':y='max(ih/zoom/2-ih*0.2*on/{frames},0)':d={frames}:s={res_w}x{res_h}:fps=30"
        elif direction == "pan_down":
            zp = f"zoompan=z=1.3:x='iw/2-(iw/zoom/2)':y='min(ih/zoom/2+ih*0.2*on/{frames},ih-ih/zoom)':d={frames}:s={res_w}x{res_h}:fps=30"
        elif direction == "zoom_in_topleft":
            zp = f"zoompan=z='min(zoom+0.0015,1.5)':x=0:y=0:d={frames}:s={res_w}x{res_h}:fps=30"
        else:  # zoom_in_bottomright
            zp = f"zoompan=z='min(zoom+0.0015,1.5)':x='iw-iw/zoom':y='ih-ih/zoom':d={frames}:s={res_w}x{res_h}:fps=30"

        # Pre-scale to output dims to ensure exact aspect ratio
        vf_chain = f"scale={res_w}:{res_h}:force_original_aspect_ratio=increase,crop={res_w}:{res_h},{zp},fade=t=in:st=0:d=0.3,fade=t=out:st={fade_out_start:.4f}:d=0.3"

        scene_result = subprocess.run([
            "ffmpeg", "-y", "-loop", "1", "-i", img_path,
            "-vf", vf_chain,
            "-t", d_str,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", "30", scene_out
        ], capture_output=True, text=True)
        if scene_result.returncode != 0:
            print(f"[!] FFmpeg scene {i} failed:\n{scene_result.stderr[-2000:]}")
            raise subprocess.CalledProcessError(scene_result.returncode, "ffmpeg", scene_result.stderr)
        print(f"[+] Ken Burns applied to scene {i} ({direction} @ {res_w}x{res_h})")
        scene_files.append(scene_out)

    # Concatenate all Ken Burns scene clips into one silent video
    concat_list = f"concat_list_{'ls' if is_landscape else 'pt'}.txt"
    with open(concat_list, "w") as f:
        for sf in scene_files:
            f.write(f"file '{sf}'\n")

    temp_video_noaudio = f"temp_video_noaudio_{'ls' if is_landscape else 'pt'}.mp4"
    print(f"Concatenating all scenes ({'16:9' if is_landscape else '9:16'})...")
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_list, "-c", "copy", temp_video_noaudio
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Mix BGM with voiceover using FFmpeg directly
    bgm_files = glob.glob("bgm/*.mp3")
    temp_output_path = f"temp_unsubbed_{'ls' if is_landscape else 'pt'}.mp4"
    if bgm_files:
        selected_bgm = random.choice(bgm_files)
        print(f"Mixing BGM: {selected_bgm} at 8% volume...")
        subprocess.run([
            "ffmpeg", "-y",
            "-i", temp_video_noaudio,
            "-i", audio_path,
            "-stream_loop", "-1", "-i", selected_bgm,
            "-filter_complex",
            "[2:a]volume=0.08[bgm];[1:a][bgm]amix=inputs=2:duration=first:normalize=0[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-shortest",
            temp_output_path
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.run([
            "ffmpeg", "-y", "-i", temp_video_noaudio, "-i", audio_path,
            "-c:v", "copy", "-c:a", "aac", "-shortest", temp_output_path
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Generate and burn ASS subtitles using absolute path to avoid libass resolution issues
    ass_path = os.path.abspath(f"subtitles_{'ls' if is_landscape else 'pt'}.ass")
    generate_ass_file(text_chunks, video_duration, ass_path, is_landscape=is_landscape)

    if output_path is None:
        output_path = "final_video_169.mp4" if is_landscape else "final_short.mp4"
        
    print(f"Burning subtitles via FFmpeg libass ({'16:9 Landscape' if is_landscape else '9:16 Portrait'})...")
    esc_ass_path = ass_path.replace("\\", "/").replace(":", "\\:")
    try:
        sub_result = subprocess.run([
            "ffmpeg", "-y",
            "-i", temp_output_path,
            "-vf", f"subtitles='{esc_ass_path}'",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "copy",
            output_path
        ], capture_output=True, text=True)
        if sub_result.returncode != 0:
            print(f"[!] Subtitle burn failed:\n{sub_result.stderr[-2000:]}")
            raise subprocess.CalledProcessError(sub_result.returncode, "ffmpeg", sub_result.stderr)
    finally:
        # Clean up all temporary files safely
        for sf in scene_files:
            if os.path.exists(sf):
                os.remove(sf)
        for tmp in [concat_list, temp_video_noaudio, temp_output_path, ass_path]:
            if os.path.exists(tmp):
                os.remove(tmp)

    # Generate custom thumbnail
    thumb_path = f"thumb_{os.path.splitext(output_path)[0]}.jpg"
    generate_roblox_thumbnail(output_path, thumb_path, game_name, part_number, is_landscape=is_landscape)

    print(f"Video ({'16:9 Landscape' if is_landscape else '9:16 Portrait'}) rendered successfully: {output_path}")
    return output_path

def upload_to_youtube(video_path, game_name, part_number, is_short=True):
    """Handles authenticated upload using GitHub Secrets Refresh Token for Short (9:16) or Normal Video (16:9)."""
    print(f"Preparing to upload {video_path} to YouTube ({'Short 9:16' if is_short else 'Normal Video 16:9'}) for: {game_name} Part {part_number}...")
    client_id = os.environ.get("CLIENT_ID")
    client_secret = os.environ.get("CLIENT_SECRET")
    refresh_token = os.environ.get("REFRESH_TOKEN")
    
    if not all([client_id, client_secret, refresh_token]):
        print(f"⚠️ Notice: Missing YouTube API credentials in environment variables. Completed dry-run render for {'Short' if is_short else 'Normal Video'}.")
        return None
        
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret
    )
    youtube = build('youtube', 'v3', credentials=creds)
    safe_name = get_safe_filename(game_name)
    
    if is_short:
        title = f"{game_name} - Part {part_number} #roblox #shorts #{safe_name}"
        description = f"The saga continues in {game_name} Part {part_number}. Like and subscribe for the next chapter!\n\n#roblox #shorts #gaming #{safe_name}"
        tags = ['roblox', game_name, 'shorts', 'robloxshorts', safe_name]
    else:
        title = f"{game_name} - Episode {part_number} | Full Roblox Story"
        description = f"""The story continues in {game_name} Episode {part_number}!

Follow the full lore, dramatic twists, and unforgettable Roblox story adventures.

👍 Like the video if you enjoyed!
💬 Leave a comment with your favorite character or theories for the next episode!
🔔 Subscribe and turn on notifications for daily new Roblox lore and animated story episodes!

#roblox #robloxstory #gaming #robloxedit #{safe_name}
"""
        tags = ['roblox', game_name, 'robloxstory', 'robloxgaming', safe_name, 'storytime', 'robloxanimation']
    
    body = {
        'snippet': {
            'title': title[:100],
            'description': description,
            'tags': tags[:15],
            'categoryId': '20'  # Gaming
        },
        'status': {
            'privacyStatus': os.environ.get('PRIVACY_STATUS', 'public'),
            'selfDeclaredMadeForKids': False
        }
    }
    
    print(f"Initiating YouTube upload stream ({'Short' if is_short else 'Normal Video'})...")
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype='video/mp4')
    request = youtube.videos().insert(
        part='snippet,status',
        body=body,
        media_body=media
    )
    
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Uploaded {int(status.progress() * 100)}%...")
            
    video_id = response.get('id')
    if is_short:
        print(f"SUCCESS! Short uploaded perfectly. YouTube Video ID: {video_id} (URL: https://youtube.com/shorts/{video_id})")
    else:
        print(f"SUCCESS! Normal Video uploaded perfectly. YouTube Video ID: {video_id} (URL: https://youtube.com/watch?v={video_id})")

    # Upload custom thumbnail if present
    thumb_path = f"thumb_{os.path.splitext(video_path)[0]}.jpg"
    if os.path.exists(thumb_path):
        try:
            print(f"Uploading custom thumbnail for {video_id}...")
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumb_path, mimetype='image/jpeg')
            ).execute()
            print("✅ Custom thumbnail uploaded successfully!")
        except Exception as te:
            print(f"Thumbnail upload notice: {te}")

    return video_id

# --- MAIN EXECUTION ---
async def main():
    state = load_game_state()
    current_index = state.get("current_index", 0)
    total_runs = state.get("total_videos_run", 1)
    game_parts = state.get("game_parts", {})
    
    current_game = GAMES[current_index]
    safe_game_name = get_safe_filename(current_game)
    
    # Initialize game-specific tracking if missing
    if safe_game_name not in game_parts:
        game_parts[safe_game_name] = 1
    current_part = game_parts[safe_game_name]
    
    print(f"--- Starting Daily Pipeline for: {current_game} (Part {current_part}) ---")
    memory = get_story_memory(safe_game_name)
    bible = get_character_bible(safe_game_name)
    
    # Wrapping rendering and uploading inside a self-healing try block
    try:
        audio_text, new_memory, image_paths = generate_script_and_images(current_game, memory, bible)
        save_story_memory(safe_game_name, new_memory)
        
        # Self-evolve Character Bible based on the newly generated script
        evolve_character_bible(current_game, safe_game_name, audio_text, bible)
        
        print("Generating Deep Voiceover via Edge-TTS...")
        raw_audio_path = "vo_raw.mp3"
        audio_path = "vo.mp3"
        
        # Stable deep narrator config using ChristopherNeural
        communicate = edge_tts.Communicate(audio_text, "en-US-ChristopherNeural")
        await communicate.save(raw_audio_path)
        
        # Studio-quality audio chain: silence trim → speed → dynamic compression → loudness normalize
        print("Optimizing voiceover (1.05x speed, dynamic compression, loudness normalization)...")
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", raw_audio_path,
            "-af", (
                "silenceremove=stop_periods=-1:stop_duration=0.3:stop_threshold=-45dB,"
                "atempo=1.05,"
                "acompressor=threshold=0.089:ratio=4:attack=5:release=50:makeup=2,"
                "loudnorm=I=-14:LRA=11:TP=-1.5"
            ),
            audio_path
        ]
        subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Clean up raw audio
        if os.path.exists(raw_audio_path):
            os.remove(raw_audio_path)
            
        text_chunks = split_text_for_captions(audio_text, words_per_chunk=3)
        
        # 1. Render 9:16 Short
        final_short_path = render_video(audio_path, image_paths, text_chunks, is_landscape=False, game_name=current_game, part_number=current_part)
        
        # 2. Render 16:9 Widescreen Normal Video
        final_landscape_path = render_video(audio_path, image_paths, text_chunks, is_landscape=True, game_name=current_game, part_number=current_part)
        
        # 3. Dual Upload to YouTube
        upload_to_youtube(final_short_path, current_game, current_part, is_short=True)
        upload_to_youtube(final_landscape_path, current_game, current_part, is_short=False)
        
    except Exception as e:
        print(f"CRITICAL ERROR encountered during run: {e}")
        print("Pipeline is executing Safe Recovery protocol to advance rotation safely...")
        
    # Regardless of failure or success, advance game state indices to prevent a permanent blocking brick of the daily workflow
    next_index = (current_index + 1) % len(GAMES)
    next_runs = total_runs + 1
    # Increment this specific game's part tracker
    game_parts[safe_game_name] = current_part + 1
    
    save_game_state(next_index, next_runs, game_parts)
    print(f"Pipeline complete. Next game in rotation: {GAMES[next_index]}")

if __name__ == "__main__":
    asyncio.run(main())
