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
    """Formats game name for file mapping (e.g., 'Adopt Me!' -> 'adopt_me')"""
    return game_name.lower().replace(" ", "_").replace("!", "")

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
            return f.read()
    # Safe fallback to legacy story file
    if os.path.exists("story_memory.txt"):
        with open("story_memory.txt", "r") as f:
            return f.read()
    return "No previous memory. Start a brand new epic adventure."

def save_story_memory(safe_game_name, new_memory):
    filename = f"story_memory_{safe_game_name}.txt"
    with open(filename, "w") as f:
        f.write(new_memory)

def get_character_bible(safe_game_name):
    filename = f"character_bible_{safe_game_name}.json"
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return f.read()
    # Safe fallback to global character settings
    if os.path.exists("character_bible.json"):
        with open("character_bible.json", "r") as f:
            return f.read()
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

    print(f"Generating {len(prompts)} correlated Unreal Engine 5 visual assets via Pollinations AI...")
    style_modifier = ", Unreal Engine 5 render, hyper-realistic lighting, ray tracing, 8k resolution, cinematic composition, high-end heavy AI visual masterpiece, octane render"
    
    for i, img_prompt in enumerate(prompts):
        path = f"scene_{i}.jpg"
        # Spreading outgoing requests with human-mimicking delay to completely bypass 429 throttling limits
        if i > 0:
            delay = random.uniform(2.5, 4.5)
            print(f"Spreading API load. Sleeping for {delay:.2f} seconds before retrieving scene {i}...")
            time.sleep(delay)

        max_retries = 2
        for attempt in range(max_retries):
            try:
                enhanced_prompt = f"{img_prompt}{style_modifier}"
                safe_prompt = requests.utils.quote(enhanced_prompt)
                url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1080&height=1920&nologo=true"
                response = requests.get(url, timeout=20)
                if response.status_code == 200:
                    with open(path, 'wb') as f:
                        f.write(response.content)
                    print(f"[-] Successfully rendered asset {i} (Attempt {attempt+1})")
                    break
                else:
                    raise Exception(f"Failed status code {response.status_code}")
            except Exception as e:
                print(f"Retrieval attempt {attempt+1} failed for scene {i}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(5)  # Wait 5 seconds before retrying to clear any rate blocks
                else:
                    print(f"Pollinations AI completely timed out for scene {i}. Deploying visual fallback...")
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
        if updated_bible_data:
            filename = f"character_bible_{safe_game_name}.json"
            with open(filename, "w") as f:
                json.dump(updated_bible_data, f, indent=4)
            print(f"[+] Lore evolution successful! Updated character bible saved to {filename}")
            return True
        else:
            print("[-] Evolution pass returned invalid JSON. Leaving bible unchanged.")
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
            if updated_bible_data:
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
Style: RobloxStyle,Arial,72,&H0000FFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,6,1,2,10,10,480,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    
    events = []
    for chunk in text_chunks:
        # Split chunk into lines to handle any newlines correctly
        lines = chunk.strip().split('\n')
        words_by_line = [line.split() for line in lines]
        
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
                    line_parts.append(f"{{\\kf{final_word_dur}}}{word}")
                else:
                    line_parts.append(f"{{\\kf{word_dur_cs}}}{word}")
            karaoke_parts.append(" ".join(line_parts))
            
        # Join line parts with the ASS hard newline tag '\N'
        karaoke_text = "\\N".join(karaoke_parts)
        
        events.append(f"Dialogue: 0,{start_str},{end_str},RobloxStyle,,0,0,0,,{karaoke_text}")
        current_time = end_time
        
    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.write(ass_header)
        for event in events:
            f.write(event + "\n")
    print(f"[-] Subtitles ASS file generated: {output_ass_path}")

def render_video(audio_path, image_paths, text_chunks):
    """MoviePy assembly featuring precise lower-middle positioning and synchronized word chunk rendering."""
    print("Assembling basic video structure with MoviePy...")
    vo_clip = AudioFileClip(audio_path)
    video_duration = vo_clip.duration
    
    bgm_files = glob.glob("bgm/*.mp3")
    if bgm_files:
        selected_bgm = random.choice(bgm_files)
        bgm_clip = AudioFileClip(selected_bgm).fx(afx.volumex, 0.1)
        bgm_clip = bgm_clip.set_duration(video_duration)
        final_audio = CompositeAudioClip([vo_clip, bgm_clip])
    else:
        final_audio = vo_clip
        
    # Distribute correlated background images evenly across the timeline
    img_duration = video_duration / len(image_paths)
    image_clips = [ImageClip(img).set_duration(img_duration) for img in image_paths]
    final_video = concatenate_videoclips(image_clips, method="compose")
    final_video = final_video.set_audio(final_audio)
    
    temp_output_path = "temp_unsubbed.mp4"
    print(f"Rendering unsubbed video to {temp_output_path}...")
    final_video.write_videofile(temp_output_path, fps=24, codec="libx264", audio_codec="aac")
    
    # Generate ASS file
    ass_path = "subtitles.ass"
    generate_ass_file(text_chunks, video_duration, ass_path)
    
    output_path = "final_short.mp4"
    print("Burning highly stylized Roblox ASS subtitles via native FFmpeg filter...")
    
    # Burn subtitles using native FFmpeg video filter
    burn_command = [
        "ffmpeg", "-y",
        "-i", temp_output_path,
        "-vf", f"subtitles={ass_path}",
        "-c:a", "copy",
        output_path
    ]
    subprocess.run(burn_command, check=True)
    
    # Clean up temp assets and close clips to prevent memory/file leaks
    if os.path.exists(temp_output_path):
        os.remove(temp_output_path)
    if os.path.exists(ass_path):
        os.remove(ass_path)
        
    vo_clip.close()
    if bgm_files:
        bgm_clip.close()
    final_audio.close()
    for clip in image_clips:
        clip.close()
    final_video.close()
        
    print("Video rendered with stylized ASS subtitles successfully.")
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
        
        # Clean understandable vocal pacing matching tQOIvmcX8_I (1.05x normal speed, standard natural deep pitch)
        print("Optimizing voiceover pacing (1.05x standard speed & natural pitch)...")
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", raw_audio_path,
            "-af", "silenceremove=stop_periods=-1:stop_duration=0.3:stop_threshold=-45dB,atempo=1.05",
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
