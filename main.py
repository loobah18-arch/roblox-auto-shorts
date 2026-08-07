import os
import json
import re
import random
import glob
import asyncio
import requests
import edge_tts
import time
import subprocess
from groq import Groq
from moviepy.editor import *
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# --- CONFIGURATION ---
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
                state = json.load(f)
                # Check for game-specific parts tracking
                if "game_parts" not in state:
                    state["game_parts"] = {get_safe_filename(g): 1 for g in GAMES}
                if "current_index" not in state or "total_videos_run" not in state:
                    return {"current_index": 0, "total_videos_run": 1, "game_parts": {get_safe_filename(g): 1 for g in GAMES}}
                return state
        except Exception:
            return {"current_index": 0, "total_videos_run": 1, "game_parts": {get_safe_filename(g): 1 for g in GAMES}}
    return {"current_index": 0, "total_videos_run": 1, "game_parts": {get_safe_filename(g): 1 for g in GAMES}}

def save_game_state(index, total_runs, game_parts):
    with open("game_state.json", "w") as f:
        json.dump({
            "current_index": index,
            "total_videos_run": total_runs,
            "game_parts": game_parts
        }, f, indent=4)

def get_story_memory(safe_game_name):
    filename = f"story_memory_{safe_game_name}.txt"
    if os.path.exists(filename):
        with open(filename, "r") as f:
            content = f.read().strip()
            if content:
                return content
    # Safe fallback to legacy story file
    if os.path.exists("story_memory.txt"):
        with open("story_memory.txt", "r") as f:
            content = f.read().strip()
            if content:
                return content
    return "No previous memory. Start a brand new epic adventure."

def save_story_memory(safe_game_name, new_memory):
    filename = f"story_memory_{safe_game_name}.txt"
    with open(filename, "w") as f:
        f.write(new_memory)

def get_character_bible(safe_game_name):
    filename = f"character_bible_{safe_game_name}.json"
    if os.path.exists(filename):
        with open(filename, "r") as f:
            content = f.read().strip()
            if content:
                return content
    # Safe fallback to global character settings
    if os.path.exists("character_bible.json"):
        with open("character_bible.json", "r") as f:
            content = f.read().strip()
            if content:
                return content
    return "No character bible found for this game."

def load_active_model():
    """Loads the last successfully used LLM model. Defaults to llama-3.3-70b-versatile."""
    if os.path.exists("active_llm_model.txt"):
        try:
            with open("active_llm_model.txt", "r") as f:
                model_name = f.read().strip()
                if model_name:
                    return model_name
        except Exception:
            pass
    return "llama-3.3-70b-versatile"

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
    "pollinations_legacy",
    "pollinations_turbo",
    "pollinations_realism",
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
def extract_json(text):
    """Safely extracts and parses a JSON block from potentially conversational LLM output."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Search for outer curly braces
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
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

# --- PIPELINE FUNCTIONS ---
def generate_script_and_images(game, memory, bible):
    """Integrates with Groq and Pollinations AI with dynamic multi-image correlation and Unreal Engine 5 styling.
    Uses strict role separation (System and User prompts) to prevent prompt echoing and meta-instructions in voiceovers.
    Dynamically loads the last successfully used model first as a sticky model, falling back only when quota is hit.
    """
    print(f"Generating script for {game} using Groq...")
    client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    
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

    # Priority ordered sequence of stable free-tier and fallback models
    fallback_models = [
        "llama-3.3-70b-versatile",
        "llama-3.3-70b-specdec",
        "llama-3.1-8b-instant",
        "mixtral-8x7b-32768",
        "gemma2-9b-it",
        "llama3-70b-8192",
        "llama3-8b-8192"
    ]
    
    sticky_model = load_active_model()
    print(f"Sticky model loaded: {sticky_model}")
    
    valid_models = []
    if sticky_model:
        valid_models.append(sticky_model)

    print("Fetching active models from Groq...")
    try:
        active_models_data = client.models.list().data
        fetched_models = [
            m.id for m in active_models_data
            if any(term in m.id.lower() for term in ["llama", "mixtral", "gemma", "qwen"])
            and not any(neg in m.id.lower() for neg in ["guard", "embed", "moderation", "whisper", "vision"])
        ]
        # Keep fallback list at the end of valid_models to preserve order of priority
        for model in fetched_models:
            if model not in valid_models:
                valid_models.append(model)
    except Exception as e:
        print(f"Failed to fetch model list, falling back to default list. Error: {e}")
        
    for model in fallback_models:
        if model not in valid_models:
            valid_models.append(model)

    print(f"Roster of models to attempt (ordered by sticky priority): {valid_models}")

    response_data = None
    successful_model = None
    for model_id in valid_models:
        print(f"Attempting generation with model: {model_id}...")
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
            response_data = extract_json(raw_text)
            if response_data and "voiceover" in response_data:
                # Sanity check: Ensure it didn't echo prompt instructions
                voiceover_clean = response_data["voiceover"].strip()
                if "Create an intense" in voiceover_clean or " strictly between" in voiceover_clean:
                    print(f"Model {model_id} returned prompt-echoed text. Rejecting schema.")
                    continue
                print(f"Success! Model {model_id} worked perfectly.")
                successful_model = model_id
                break
            else:
                print(f"Model {model_id} returned invalid schema. Retrying next...")
        except Exception as e:
            print(f"Model {model_id} failed. Searching next... Error: {e}")
            continue

    # Fallback to local hardcoded dramatic script if Groq API goes completely dark
    if not response_data:
        print("CRITICAL: Groq API completely unresponsive. Activating Self-Healing Narrative Fallback...")
        response_data = {
            "voiceover": f"In the shadows of the {game} grid, an ancient power awakens. The players thought this was just another harmless server, but they were wrong. Legends speak of a hidden bunker beneath the city, guarded by shifting laser beams and a mystery no code can crack. As the timer counts down, a brave survivor steps forward, facing their ultimate destiny. Will they claim the awakened fruit and conquer the obby, or will the darkness consume everything they worked for? The choice is yours... but time is running out.",
            "new_memory": "The ancient bunker door creaks open, revealing a blinding neon light as a mysterious shadow steps through.",
            "image_prompts": [f"Epic Roblox {game} landscape under heavy dark sky"] * 8
        }
    else:
        # Save successfully working sticky model to persistent memory
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
        if i > 0:
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
                    elif provider == "pollinations_legacy":
                        # Bug fix: was identical to pollinations_new — now uses flux-realism as a true different model
                        url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1080&height=1920&model=flux-realism&seed={seed}&nologo=true&enhance=true"
                        response = requests.get(url, timeout=timeout)
                    elif provider == "pollinations_turbo":
                        url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1080&height=1920&model=turbo&seed={seed}&nologo=true"
                        response = requests.get(url, timeout=timeout)
                    elif provider == "pollinations_realism":
                        url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1080&height=1920&model=flux-realism&seed={seed}&nologo=true&enhance=true"
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
    """Dynamically updates the character bible based on narrative developments in the latest script."""
    print(f"Running self-evolution pass for {game_name} Character Bible...")
    client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    
    system_prompt = """You are the Lead Lore Master and Story Architect for our automated Roblox YouTube Shorts channel.
Your task is to update and evolve the Character Bible for the game based on the events that occurred in the latest episode script.

Output the FULL updated Character Bible strictly as a single valid, parsable JSON object. Do not include any conversational prefix, suffix, or formatting codes in your output. Combine the current traits with newly discovered developments, inventory gains, or relationship changes."""

    user_prompt = f"""Evolve the Character Bible for {game_name}.

CURRENT BIBLE LORE:
{current_bible_text}

LATEST EPISODE SCRIPT:
{script_text}

Analyze the latest episode script for key updates (allies, stats, inventory fruit awakenings, etc.) and write the entire merged and updated Character Bible JSON."""
    
    # Try the loaded sticky model
    model_id = load_active_model()
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
        updated_bible_data = extract_json(raw_text)
        if updated_bible_data and isinstance(updated_bible_data, dict):
            filename = f"character_bible_{safe_game_name}.json"
            with open(filename, "w") as f:
                json.dump(updated_bible_data, f, indent=4)
            print(f"[+] Lore evolution successful! Updated character bible saved to {filename}")
            return True
        else:
            print("[-] Evolution pass returned invalid JSON object structure. Leaving bible unchanged.")
    except Exception as e:
        print(f"[-] Self-evolution pass failed with model {model_id}: {e}. Trying fallback 'llama-3.3-70b-versatile'...")
        try:
            chat_completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                model="llama-3.3-70b-versatile",
                response_format={"type": "json_object"}
            )
            raw_text = chat_completion.choices[0].message.content
            updated_bible_data = extract_json(raw_text)
            if updated_bible_data and isinstance(updated_bible_data, dict):
                filename = f"character_bible_{safe_game_name}.json"
                with open(filename, "w") as f:
                    json.dump(updated_bible_data, f, indent=4)
                print(f"[+] Lore evolution successful! Updated character bible saved to {filename}")
                return True
        except Exception as ex:
            print(f"[-] Fallback self-evolution pass failed: {ex}. Safely keeping current bible.")
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

def generate_ass_file(text_chunks, video_duration, output_ass_path="subtitles.ass"):
    """Generates Aegisub Advanced Substation Alpha (.ass) subtitles with Roblox-style word-by-word karaoke highlight."""
    total_words = sum(len(chunk.replace("\n", " ").split()) for chunk in text_chunks)
    current_time = 0.0
    
    # Yellow primary fill for active highlights, solid white secondary for unhighlighted, thick black outline
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
Style: RobloxStyle,Impact,78,&H0000FFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,2,0,1,7,3,2,10,10,500,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    
    events = []
    for chunk in text_chunks:
        # Split chunk into lines to handle any newlines correctly
        lines_split = chunk.strip().split('\n')
        words_by_line = [line.split() for line in lines_split]
        
        actual_word_count = sum(len(line_words) for line_words in words_by_line)
        if actual_word_count == 0:
            continue
            
        chunk_duration = (actual_word_count / total_words) * video_duration
        end_time = current_time + chunk_duration
        
        start_str = format_time_ass(current_time)
        end_str = format_time_ass(end_time)
        
        # Base duration per word in centiseconds (1/100 of a second)
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
                    # Ensure the final word duration matches the chunk duration exactly
                    chunk_duration_cs = int(round(chunk_duration * 100))
                    elapsed_cs = word_dur_cs * (actual_word_count - 1)
                    final_word_dur = max(1, chunk_duration_cs - elapsed_cs)
                    line_parts.append(fr"{{\kf{final_word_dur}}}{word}")
                else:
                    line_parts.append(fr"{{\kf{word_dur_cs}}}{word}")
            karaoke_parts.append(" ".join(line_parts))
            
        # Join line parts with the ASS hard newline tag '\N'
        karaoke_text = r"\N".join(karaoke_parts)
        
        # Clean ASS karaoke dialogue line without conflicting fade tags
        events.append(f"Dialogue: 0,{start_str},{end_str},RobloxStyle,,0,0,0,{karaoke_text}")
        current_time = end_time
        
    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.write(ass_header)
        for event in events:
            f.write(event + "\n")
    print(f"[-] Subtitles ASS file generated: {output_ass_path}")

def render_video(audio_path, image_paths, text_chunks):
    """Pure FFmpeg pipeline with Ken Burns pan/zoom per scene, audio mixing, and subtitle burn.
    Replaces MoviePy with direct FFmpeg calls for higher quality 30fps output."""
    print("Assembling video with Ken Burns motion effects via FFmpeg...")

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

    print("Applying Ken Burns pan/zoom to each scene...")
    for i, img_path in enumerate(image_paths):
        scene_out = f"scene_kb_{i}.mp4"
        direction = kb_directions[i % len(kb_directions)]
        frames = max(1, int(img_duration * 30))  # 30fps
        d_str = f"{img_duration:.4f}"
        fade_out_start = max(0.0, img_duration - 0.3)

        if direction == "zoom_in_center":
            zp = f"zoompan=z='min(zoom+0.0015,1.5)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps=30"
        elif direction == "zoom_out_center":
            zp = f"zoompan=z='if(lte(zoom,1.0),1.5,max(zoom-0.0015,1.0))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps=30"
        elif direction == "pan_right":
            zp = f"zoompan=z=1.3:x='min(iw/zoom/2+iw*0.2*time/{d_str},iw-iw/zoom)':y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps=30"
        elif direction == "pan_left":
            zp = f"zoompan=z=1.3:x='max(iw/zoom/2-iw*0.2*time/{d_str},0)':y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps=30"
        elif direction == "pan_up":
            zp = f"zoompan=z=1.3:x='iw/2-(iw/zoom/2)':y='max(ih/zoom/2-ih*0.2*time/{d_str},0)':d={frames}:s=1080x1920:fps=30"
        elif direction == "pan_down":
            zp = f"zoompan=z=1.3:x='iw/2-(iw/zoom/2)':y='min(ih/zoom/2+ih*0.2*time/{d_str},ih-ih/zoom)':d={frames}:s=1080x1920:fps=30"
        elif direction == "zoom_in_topleft":
            zp = f"zoompan=z='min(zoom+0.0015,1.5)':x=0:y=0:d={frames}:s=1080x1920:fps=30"
        else:  # zoom_in_bottomright
            zp = f"zoompan=z='min(zoom+0.0015,1.5)':x='iw-iw/zoom':y='ih-ih/zoom':d={frames}:s=1080x1920:fps=30"

        # Pre-scale to 1080x1920 to optimize zoompan performance and ensure exact aspect ratio
        vf_chain = f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,{zp},fade=t=in:st=0:d=0.3,fade=t=out:st={fade_out_start:.4f}:d=0.3"

        subprocess.run([
            "ffmpeg", "-y", "-loop", "1", "-i", img_path,
            "-vf", vf_chain,
            "-t", d_str,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", "30", scene_out
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[+] Ken Burns applied to scene {i} ({direction})")
        scene_files.append(scene_out)

    # Concatenate all Ken Burns scene clips into one silent video
    concat_list = "concat_list.txt"
    with open(concat_list, "w") as f:
        for sf in scene_files:
            f.write(f"file '{sf}'\n")

    temp_video_noaudio = "temp_video_noaudio.mp4"
    print("Concatenating all scenes...")
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_list, "-c", "copy", temp_video_noaudio
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Mix BGM with voiceover using FFmpeg directly
    bgm_files = glob.glob("bgm/*.mp3")
    temp_output_path = "temp_unsubbed.mp4"
    if bgm_files:
        selected_bgm = random.choice(bgm_files)
        print(f"Mixing BGM: {selected_bgm} at 8% volume...")
        subprocess.run([
            "ffmpeg", "-y",
            "-i", temp_video_noaudio,
            "-i", audio_path,
            "-stream_loop", "-1", "-i", selected_bgm,
            "-filter_complex",
            "[2:a]volume=0.08[bgm];[1:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-shortest",
            temp_output_path
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.run([
            "ffmpeg", "-y", "-i", temp_video_noaudio, "-i", audio_path,
            "-c:v", "copy", "-c:a", "aac", "-shortest", temp_output_path
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Generate and burn ASS subtitles
    ass_path = "subtitles.ass"
    generate_ass_file(text_chunks, video_duration, ass_path)

    output_path = "final_short.mp4"
    print("Burning Impact font subtitles via FFmpeg...")
    subprocess.run([
        "ffmpeg", "-y",
        "-i", temp_output_path,
        "-vf", f"subtitles={ass_path}",
        "-c:a", "copy",
        output_path
    ], check=True)

    # Clean up all temporary files
    for sf in scene_files:
        if os.path.exists(sf):
            os.remove(sf)
    for tmp in [concat_list, temp_video_noaudio, temp_output_path, ass_path]:
        if os.path.exists(tmp):
            os.remove(tmp)

    print("Video rendered with Ken Burns effects and stylized subtitles successfully.")
    return output_path

def upload_to_youtube(video_path, game_name, part_number):
    """Handles authenticated upload using GitHub Secrets Refresh Token with clean titles omitting 'AI Story'."""
    print(f"Preparing to upload {video_path} to YouTube for: {game_name} Part {part_number}...")
    client_id = os.environ.get("CLIENT_ID")
    client_secret = os.environ.get("CLIENT_SECRET")
    refresh_token = os.environ.get("REFRESH_TOKEN")
    
    if not all([client_id, client_secret, refresh_token]):
        raise Exception("CRITICAL: Missing YouTube API credentials in environment variables.")
        
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret
    )
    youtube = build('youtube', 'v3', credentials=creds)
    safe_name = get_safe_filename(game_name)
    title = f"{game_name} - Part {part_number} #roblox #shorts #{safe_name}"
    description = f"The saga continues in {game_name} Part {part_number}. Like and subscribe for the next chapter!"
    
    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': ['roblox', game_name, 'shorts', 'robloxshorts', safe_name],
            'categoryId': '20'
        },
        'status': {
            'privacyStatus': 'public',
            'selfDeclaredMadeForKids': False
        }
    }
    
    print("Initiating YouTube upload stream...")
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype='video/mp4')
    request = youtube.videos().insert(
        part=','.join(body.keys()),
        body=body,
        media_body=media
    )
    
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Uploaded {int(status.progress() * 100)}%...")
    print(f"SUCCESS! Video uploaded perfectly. YouTube Video ID: {response['id']}")

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
        final_video_path = render_video(audio_path, image_paths, text_chunks)
        
        # Final step: upload to YouTube
        upload_to_youtube(final_video_path, current_game, current_part)
        
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
