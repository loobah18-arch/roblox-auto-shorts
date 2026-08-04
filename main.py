import os
import json
import random
import glob
import asyncio
import requests
import edge_tts
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
                if "current_index" not in state or "total_videos_run" not in state:
                    return {"current_index": 0, "total_videos_run": 1}
                return state
        except Exception:
            return {"current_index": 0, "total_videos_run": 1}
    return {"current_index": 0, "total_videos_run": 1}

def save_game_state(index, total_runs):
    with open("game_state.json", "w") as f:
        json.dump({"current_index": index, "total_videos_run": total_runs}, f, indent=4)

def get_story_memory(safe_game_name):
    filename = f"story_memory_{safe_game_name}.txt"
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return f.read()
    # Safe fallback to global story memory
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
    # Safe fallback to global character bible
    if os.path.exists("character_bible.json"):
        with open("character_bible.json", "r") as f:
            return f.read()
    return "No character bible found for this game."

def generate_fallback_image(prompt, path):
    """Generates an abstract high-quality geometric background with scene details using Pillow as a self-healing fallback."""
    try:
        from PIL import Image, ImageDraw
        # Create a beautiful vertical 1080x1920 abstract gradient-style card
        img = Image.new("RGB", (1080, 1920), color=(15, 15, 25))
        draw = ImageDraw.Draw(img)
        # Cool ambient tech circles to avoid a boring black screen
        draw.ellipse([200, 400, 880, 1080], fill=(30, 30, 50), outline=(50, 50, 80), width=5)
        draw.ellipse([400, 1200, 680, 1480], fill=(25, 25, 40), outline=(40, 40, 60), width=3)
        draw.rectangle([50, 50, 1030, 1870], outline=(70, 70, 100), width=8)
        img.save(path)
        print(f"[Self-Healing] Abstract visual card generated successfully at {path}")
    except Exception as e:
        print(f"[Self-Healing] PIL fallback failed: {e}. Writing raw fallback image bytes.")
        try:
            with open(path, 'wb') as f:
                f.write(b'')
        except Exception:
            pass

# --- PIPELINE FUNCTIONS ---
def generate_script_and_images(game, memory, bible):
    """Integrates with Groq and Pollinations AI with dynamic multi-image correlation and Unreal Engine 5 styling."""
    print(f"Generating script for {game} using Groq...")
    client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    
    # Game-specific storytelling guidelines to keep stories highly immersive and engaging
    game_guidelines = {
        "blox fruits": "Write an intense anime-style saga. Focus on leveling, grinding bounty, unlocking rare devil fruits (like Dough, Shadow, or Dragon), and battling toxic bounty hunters in the Third Sea.",
        "brookhaven": "Write a suspenseful roleplay mystery. Focus on bank robberies, secret tunnels, creepy modern mansions, and mysterious figures whispering under the neighborhood lights.",
        "adopt me!": "Write a high-stakes trade negotiation or neon egg drama. Focus on legendary pets (like Frost Dragon or owl), the anxiety of a trust-trade, and building a dream neon mansion.",
        "murder mystery 2": "Write a heart-pounding psychological obby/slasher. Focus on the terrifying panic of being an Innocent hiding in the shadows, a Sheriff trying to find the gun, or a cold-blooded Murderer stalking with a Godly knife.",
        "tower of hell": "Write a funny, highly relatable rage-obby story. Focus on shifty lasers, low gravity, speed power-ups, and the hilarious agony of falling from the very top section all the way back to the start with zero checkpoints."
    }
    
    safe_game = game.lower().strip()
    guideline = game_guidelines.get(safe_game, "Write an epic, high-stakes Roblox adventure story with cliffhangers.")
    
    prompt = f"""
    Create an intense, highly engaging, and cinematic Roblox {game} script (strictly between 110 to 135 words to achieve a 50+ second final duration at natural speaking pacing) told in a commanding, epic voice.
    Theme Guidelines: {guideline}
    Previous Story Memory (for continuity): {memory}
    Character Bible: {bible}
    
    Provide exactly 8 distinct visual scene descriptions so the background imagery continuously correlates with the narrative progression of this longer story.
    Output JSON strictly in this format:
    {{
      "voiceover": "Script text here (must be 110-135 words, highly engaging and theatrical, no brackets or stage directions)",
      "new_memory": "A summary cliffhanger memory of today's events for tomorrow's continuation",
      "image_prompts": ["Prompt 1", "Prompt 2", "Prompt 3", "Prompt 4", "Prompt 5", "Prompt 6", "Prompt 7", "Prompt 8"]
    }}
    """
    
    print("Fetching active models from Groq for auto-rotation and fallback...")
    try:
        active_models_data = client.models.list().data
        valid_models = [
            m.id for m in active_models_data
            if any(kw in m.id.lower() for kw in ["llama", "mixtral", "gemma", "qwen"])
        ]
    except Exception as e:
        print(f"Failed to fetch model list, using hardcoded fallbacks. Error: {e}")
        valid_models = []

    # Sequence of known free-tier and low-cost active models as reliable fallback buffers
    fallbacks = [
        "llama-3.3-70b-specdec",
        "llama-3.3-70b-versatile",
        "llama-3.1-70b-versatile",
        "llama-3.1-8b-instant",
        "mixtral-8x7b-32768",
        "gemma2-9b-it"
    ]
    for fb in fallbacks:
        if fb not in valid_models:
            valid_models.append(fb)

    response_data = None
    for model_id in valid_models:
        print(f"Attempting generation with model: {model_id}...")
        try:
            chat_completion = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=model_id,
                response_format={"type": "json_object"}
            )
            response_data = json.loads(chat_completion.choices[0].message.content)
            print(f"Success! Model {model_id} worked perfectly.")
            break
        except Exception as e:
            print(f"Model {model_id} failed. Searching next... Error: {e}")
            continue

    if not response_data:
        # Ultimate self-healing fallback to prevent any run failure or actions crash
        print("[Self-Healing] All Groq API models failed or rate-limited. Activating safe story fail-safe...")
        response_data = {
            "voiceover": f"In the dark virtual world of Roblox {game}, a hidden force began to rise. Every block shifted, every code line cracked under the pressure. We had to move fast. There was no turning back now. But as the gate opened, the ultimate challenge appeared before us. The final boss stood waiting. To be continued...",
            "new_memory": f"The heroes faced the final boss of Roblox {game} as the virtual world cracked.",
            "image_prompts": [f"Roblox {game} epic cinematic world, unreal engine 5 render"] * 8
        }

    audio_text = response_data.get("voiceover", "The journey continues...")
    new_memory = response_data.get("new_memory", "To be continued...")
    prompts = response_data.get("image_prompts", ["Roblox landscape"] * 8)
    image_paths = []
    
    print(f"Generating {len(prompts)} correlated Unreal Engine 5 visual assets via Pollinations AI...")
    style_modifier = ", Unreal Engine 5 render, hyper-realistic lighting, ray tracing, 8k resolution, cinematic composition, high-end heavy AI visual masterpiece, octane render"
    for i, img_prompt in enumerate(prompts):
        try:
            enhanced_prompt = f"{img_prompt}{style_modifier}"
            safe_prompt = requests.utils.quote(enhanced_prompt)
            url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1080&height=1920&nologo=true"
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                path = f"scene_{i}.jpg"
                with open(path, 'wb') as f:
                    f.write(response.content)
                image_paths.append(path)
            else:
                raise Exception(f"Bad response code: {response.status_code}")
        except Exception as e:
            print(f"[Self-Healing] Pollinations AI failed for prompt {i}. Generating PIL fallback. Error: {e}")
            path = f"scene_{i}.jpg"
            generate_fallback_image(img_prompt, path)
            image_paths.append(path)

    return audio_text, new_memory, image_paths

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
                chunk = chunk[:space_idx] + "\\n" + chunk[space_idx+1:]
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
            
        # Join line parts with the ASS hard newline tag '\\N'
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
    
    # Clean up temp assets
    if os.path.exists(temp_output_path):
        os.remove(temp_output_path)
    if os.path.exists(ass_path):
        os.remove(ass_path)
        
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
    current_game = GAMES[current_index]
    safe_game_name = get_safe_filename(current_game)
    
    print(f"--- Starting Daily Pipeline for: {current_game} (Part {total_runs}) ---")
    memory = get_story_memory(safe_game_name)
    bible = get_character_bible(safe_game_name)
    
    audio_text, new_memory, image_paths = generate_script_and_images(current_game, memory, bible)
    save_story_memory(safe_game_name, new_memory)
    
    print("Generating Deep Voiceover via Edge-TTS...")
    raw_audio_path = "vo_raw.mp3"
    audio_path = "vo.mp3"
    
    try:
        # Stable deep narrator config using ChristopherNeural
        communicate = edge_tts.Communicate(audio_text, "en-US-ChristopherNeural")
        await communicate.save(raw_audio_path)
    except Exception as e:
        print(f"[Self-Healing] Edge-TTS failed to connect or save. Writing absolute silent fallback waveform. Error: {e}")
        # Build 5-second placeholder raw silent wav using ffmpeg if TTS fails
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "5", raw_audio_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Apply voice effects: relaxed syllable silence removal and extremely clear, understandably paced 1.05x speedup
    print("Optimizing voiceover pacing (1.05x natural speed, pitch-perfect)...")
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
    
    upload_to_youtube(final_video_path, current_game, total_runs)
    
    next_index = (current_index + 1) % len(GAMES)
    next_runs = total_runs + 1
    save_game_state(next_index, next_runs)
    print(f"Pipeline complete. Next game in rotation: {GAMES[next_index]}")

if __name__ == "__main__":
    asyncio.run(main())
