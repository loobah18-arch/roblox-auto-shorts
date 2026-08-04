import os
import json
import time
import random
import urllib.parse
import asyncio
import requests
from groq import Groq
import edge_tts
from moviepy.editor import ImageClip, AudioFileClip, TextClip, CompositeVideoClip, concatenate_videoclips, CompositeAudioClip
import moviepy.audio.fx.all as afx

# Google API Imports for YouTube Upload
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# ==========================================
# 1. ENVIRONMENT & CONFIGURATION
# ==========================================
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")

# Initialize Groq Client
groq_client = Groq(api_key=GROQ_API_KEY)

# ==========================================
# 2. GAME ROTATION SYSTEM
# ==========================================
def get_next_game():
    games = ["Blox Fruits", "Brookhaven", "Adopt Me!", "Murder Mystery 2", "Tower of Hell"]
    state_file = "game_state.json"
    
    last_index = -1
    if os.path.exists(state_file):
        try:
            with open(state_file, "r") as f:
                state = json.load(f)
                last_index = state.get("last_game_index", -1)
        except Exception:
            pass
            
    next_index = (last_index + 1) % len(games)
    next_game = games[next_index]
    
    with open(state_file, "w") as f:
        json.dump({"last_game_index": next_index, "current_game": next_game}, f)
        
    return next_game

# ==========================================
# 3. SCRIPT GENERATION (DYNAMIC STORY MODE)
# ==========================================
def generate_script(game_name):
    print(f"🤖 Requesting script from Groq API for game: {game_name}...")
    
    safe_name = game_name.replace(' ', '_').replace('!', '').lower()
    memory_file = f"story_memory_{safe_name}.txt"
    bible_file = f"character_bible_{safe_name}.json"
    
    memory_context = f"Start a fresh, brand new exciting story in {game_name}."
    bible_context = "Use standard Roblox character tropes."
    
    if os.path.exists(memory_file):
        with open(memory_file, "r") as f:
            content = f.read().strip()
            if content:
                memory_context = content
                
    if os.path.exists(bible_file):
        with open(bible_file, "r") as f:
            bible_context = f.read()

    prompt = f"""
    Write a 3-scene YouTube Shorts script for the Roblox game: {game_name}.
    
    Character Bible: {bible_context}
    Previous Story Context (continue from this): {memory_context}
    
    RULES:
    1. Start immediately with action (Do NOT say "Welcome to...").
    2. The story must be exciting and end with a cliffhanger!
    3. Ask the viewer a question at the end.
    4. Return strictly in JSON format matching this structure:
    {{
      "title": "Video Title",
      "scenes": [
        {{"narration": "Voiceover text here", "image_prompt": "Visual description for AI image generation, 3d roblox style"}}
      ],
      "new_memory": "Write a 1-sentence summary of THIS episode here so the AI remembers it for the next video."
    }}
    """
    
    response = groq_client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model="llama-3.3-70b-versatile",
        response_format={"type": "json_object"}
    )
    
    script_data = json.loads(response.choices[0].message.content)
    print(f"📌 Title: {script_data['title']}")
    
    for scene in script_data["scenes"]:
        scene["narration"] = scene["narration"].replace("blocks fruits", "Blox Fruits").replace("Bloxs Fruits", "Blox Fruits")
    
    if "new_memory" in script_data:
        print(f"💾 Saving Story Memory for {game_name} Tomorrow: {script_data['new_memory']}")
        with open(memory_file, "w") as f:
            f.write(script_data["new_memory"])
            
    return script_data, game_name

# ==========================================
# 4. AI IMAGE DOWNLOADER
# ==========================================
def download_ai_image(prompt, output_file):
    encoded_prompt = urllib.parse.quote(f"{prompt}, 3d roblox gaming art style, high quality")
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1080&height=1920&nologo=true"
    
    headers = {"User-Agent": "Mozilla/5.0"}
    attempt = 1
    while True:
        try:
            print(f"   ↳ Fetching image... (Attempt {attempt})")
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status() 
            with open(output_file, "wb") as f:
                f.write(response.content)
            print("   ✅ Image downloaded successfully!")
            break  
        except Exception as e:
            print(f"   ⚠️ Connection error: {e}, retrying in 10s...")
            time.sleep(10)
            attempt += 1

# ==========================================
# 5. AUDIO GENERATION (EDGE-TTS)
# ==========================================
async def generate_audio(text, output_file):
    print(f"   ↳ Generating voiceover...")
    communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural", rate="+10%")
    await communicate.save(output_file)

# ==========================================
# 6. DYNAMIC SUBTITLE ENGINE (FIXED SYNC & WORD BREAKING)
# ==========================================
def create_dynamic_subtitles(text, audio_duration):
    words = text.split()
    chunk_size = 3 
    chunks = [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]
    
    # Calculate total characters to weight the timing of each text popup
    total_chars = sum(len(c) for c in chunks)
    
    txt_clips = []
    current_start_time = 0
    
    for chunk in chunks:
        # Give longer text chunks more time on screen so it stays perfectly synced with the voice
        chunk_duration = (len(chunk) / max(total_chars, 1)) * audio_duration
        
        txt_clip = TextClip(
            chunk, 
            fontsize=85, # Reduced to prevent ImageMagick from splitting words
            color='yellow', 
            font='DejaVu-Sans-Bold',
            stroke_color='black',
            stroke_width=5,
            method='caption',
            align='center', # Ensures multiple lines center properly
            size=(950, None)
        ).set_position('center').set_start(current_start_time).set_duration(chunk_duration)
        
        txt_clips.append(txt_clip)
        current_start_time += chunk_duration
        
    return txt_clips

# ==========================================
# 7. VIDEO ASSEMBLY & BGM MIXER
# ==========================================
def assemble_video(script_data, output_filename="final_short.mp4"):
    print("🎬 Assembling video scenes...")
    clips = []
    
    for i, scene in enumerate(script_data["scenes"]):
        print(f"🎥 Processing Scene {i+1}/{len(script_data['scenes'])}...")
        
        image_file = f"scene_{i}.jpg"
        audio_file = f"scene_{i}.mp3"
        
        download_ai_image(scene["image_prompt"], image_file)
        asyncio.run(generate_audio(scene["narration"], audio_file))
        
        audio_clip = AudioFileClip(audio_file)
        
        image_clip = (ImageClip(image_file)
                      .resize(height=1920)
                      .crop(x_center=1080/2, width=1080)
                      .set_duration(audio_clip.duration))
        
        subtitle_clips = create_dynamic_subtitles(scene["narration"], audio_clip.duration)
        
        video_clip = CompositeVideoClip([image_clip] + subtitle_clips).set_audio(audio_clip)
        clips.append(video_clip)
        
    print("🎞️ Rendering final video sequence...")
    final_video = concatenate_videoclips(clips, method="compose")
    
    bgm_folder = "bgm"
    if os.path.exists(bgm_folder):
        bgm_files = [f for f in os.listdir(bgm_folder) if f.endswith(('.mp3', '.wav'))]
        if bgm_files:
            bgm_path = os.path.join(bgm_folder, random.choice(bgm_files))
            print(f"🎵 Mixing background music: {bgm_path}")
            
            bgm_clip = AudioFileClip(bgm_path).fx(afx.volumex, 0.1)
            bgm_clip = afx.audio_loop(bgm_clip, duration=final_video.duration)
            
            final_audio = CompositeAudioClip([final_video.audio, bgm_clip])
            final_video = final_video.set_audio(final_audio)
        else:
            print("⚠️ No audio files found in 'bgm' folder. Proceeding without music.")
    else:
        print("⚠️ 'bgm' folder not found. Proceeding without music.")

    final_video.write_videofile(output_filename, fps=24, codec="libx264", audio_codec="aac")
    print("✅ Video rendered successfully!")

# ==========================================
# 8. YOUTUBE UPLOAD
# ==========================================
def upload_to_youtube(video_path, title, game_choice):
    print(f"🚀 Authenticating YouTube API...")
    
    if not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN]):
        raise ValueError("Missing YouTube OAuth secrets!")

    try:
        creds = Credentials(
            token=None,
            refresh_token=REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET
        )
        youtube = build("youtube", "v3", credentials=creds)

        safe_tag = game_choice.replace(' ', '')
        tags = ["Roblox", "Shorts", "Gaming", "RobloxEdit", safe_tag]
        if game_choice == "Blox Fruits":
            tags.append("BloxFruitsStory")

        description = f"{title}\n\nWhat do you think? Let me know in the comments!\n\n#Roblox #RobloxShorts #Gaming #{safe_tag}"
        safe_title = f"{title} #Shorts"[:100]

        body = {
            "snippet": {
                "title": safe_title,
                "description": description,
                "tags": tags,
                "categoryId": "20" 
            },
            "status": {
                "privacyStatus": "public", 
                "selfDeclaredMadeForKids": False
            }
        }

        print(f"📡 Uploading '{safe_title}' to YouTube...")
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
        
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        response = request.execute()
        print(f"🎉 Upload successful! Link: https://youtube.com/shorts/{response.get('id')}")

    except HttpError as e:
        print(f"❌ YouTube API Error: {e.resp.status}")
        raise e  
    except Exception as e:
        print(f"❌ Upload Failed: {e}")
        raise e

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    try:
        current_game = get_next_game()
        print(f"🎲 Selected Game for Today: {current_game}")
        
        script, game_choice = generate_script(current_game)
        assemble_video(script, output_filename="roblox_short.mp4")
        upload_to_youtube("roblox_short.mp4", script["title"], game_choice)
        
    except Exception as e:
        print(f"❌ Pipeline failed: {e}")
        exit(1)
