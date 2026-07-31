import os
import json
import time
import urllib.parse
import asyncio
import requests
import random
from groq import Groq
import edge_tts
from moviepy.editor import ImageClip, AudioFileClip, TextClip, CompositeVideoClip, concatenate_videoclips, CompositeAudioClip
from moviepy.audio.fx.all import volumex, audio_loop

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
# 2. SCRIPT GENERATION (DYNAMIC STORY MODE)
# ==========================================
def generate_script():
    print("🤖 Requesting script from Groq API (Llama 3.3)...")
    
    game_choice = random.choice(["Blox Fruits", "Brookhaven"])
    print(f"🎲 Selected Theme for Today: {game_choice}")
    
    if game_choice == "Blox Fruits":
        previous_story = "A young pirate just arrived in the first sea." 
        if os.path.exists("story_memory.txt"):
            with open("story_memory.txt", "r") as f:
                content = f.read().strip()
                if content:
                    previous_story = content
                    
        prompt = f"""
        Write a 3-scene YouTube Short script about Roblox Blox Fruits. 
        This is an ongoing episodic story. Here is a summary of the last episode: "{previous_story}"
        
        Write the NEXT episode in the story.
        RULES:
        1. Start immediately with action (Do NOT say "Welcome to...").
        2. Use correct spelling ("Blox Fruits").
        3. End with a cliffhanger and ask the viewer a question!
        4. Return strictly in JSON format matching this structure:
        {{
          "title": "Video Title",
          "scenes": [
            {{"narration": "Voiceover text here", "image_prompt": "Visual description for AI"}}
          ],
          "summary": "Write a 1-sentence summary of THIS episode here so the AI remembers it for tomorrow."
        }}
        """
    else:
        prompt = """
        Write a 3-scene YouTube Short script about a completely random, hilarious, and chaotic scenario in Roblox Brookhaven.
        Make it a self-contained story.
        RULES:
        1. Start immediately with a crazy hook (Do NOT say "Welcome to...").
        2. Make the situation bizarre (e.g., a secret agent bank robbery, alien invasion at the hospital, etc.).
        3. End by asking the viewer what they would do in this situation!
        4. Return strictly in JSON format matching this structure:
        {{
          "title": "Video Title",
          "scenes": [
            {{"narration": "Voiceover text here", "image_prompt": "Visual description for AI"}}
          ]
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
    
    if game_choice == "Blox Fruits" and "summary" in script_data:
        print(f"💾 Saving Story Memory for Tomorrow: {script_data['summary']}")
        with open("story_memory.txt", "w") as f:
            f.write(script_data["summary"])
            
    return script_data, game_choice

# ==========================================
# 3. AI IMAGE DOWNLOADER
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
            print(f"   ⚠️ Connection error: {e}, retrying...")
            time.sleep(10)
            attempt += 1

# ==========================================
# 4. AUDIO GENERATION & BACKGROUND MUSIC
# ==========================================
async def generate_audio(text, output_file):
    communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural", rate="+10%")
    await communicate.save(output_file)

def add_background_music(voiceover_path, output_audio_path):
    print("🎵 Adding random background music...")
    
    # List of royalty-free, copyright-safe gaming background tracks (direct URLs)
    background_tracks = [
        "https://cdn.pixabay.com/download/audio/2022/05/27/audio_1808fbf756.mp3?filename=cyberpunk-2099-107016.mp3",
        "https://cdn.pixabay.com/download/audio/2022/01/18/audio_d0a13f69d2.mp3?filename=action-sport-rock-trailer-straight-to-the-top-10486.mp3",
        "https://cdn.pixabay.com/download/audio/2022/03/15/audio_c8c2a737f8.mp3?filename=gaming-funk-10469.mp3"
    ]
    
    selected_track_url = random.choice(background_tracks)
    music_file = "temp_music.mp3"
    
    try:
        # Download the random music track
        res = requests.get(selected_track_url, timeout=20)
        with open(music_file, "wb") as f:
            f.write(res.content)
            
        # Load audio clips
        tts_clip = AudioFileClip(voiceover_path)
        music_clip = AudioFileClip(music_file).fx(volumex, 0.1) # 10% volume so voice is clear
        
        # Loop music to match video length and trim
        music_clip = audio_loop(music_clip, duration=tts_clip.duration)
        
        # Mix background music and voiceover together
        final_audio = CompositeAudioClip([music_clip, tts_clip])
        final_audio.write_audiofile(output_audio_path, fps=44100, logger=None)
        
        tts_clip.close()
        music_clip.close()
        print("✅ Background music successfully mixed!")
        
    except Exception as e:
        print(f"⚠️ Failed to add background music ({e}), using voiceover only.")
        # Fallback to just the voiceover if download fails
        os.rename(voiceover_path, output_audio_path)

# ==========================================
# 5. VIDEO ASSEMBLY
# ==========================================
def assemble_video(script_data, output_filename="final_short.mp4"):
    print("🎬 Assembling video scenes...")
    clips = []
    
    for i, scene in enumerate(script_data["scenes"]):
        print(f"🎥 Processing Scene {i+1}/{len(script_data['scenes'])}...")
        
        image_file = f"scene_{i}.jpg"
        raw_audio_file = f"raw_audio_{i}.mp3"
        final_audio_file = f"scene_{i}.mp3"
        
        download_ai_image(scene["image_prompt"], image_file)
        asyncio.run(generate_audio(scene["narration"], raw_audio_file))
        
        # Add background music to this scene's voiceover
        add_background_music(raw_audio_file, final_audio_file)
        
        audio_clip = AudioFileClip(final_audio_file)
        
        image_clip = (ImageClip(image_file)
                      .resize(height=1920)
                      .crop(x_center=1080/2, width=1080)
                      .set_duration(audio_clip.duration))
        
        txt_clip = TextClip(
            scene["narration"], 
            fontsize=70, 
            color='white', 
            font='DejaVu-Sans-Bold',
            stroke_color='black',
            stroke_width=3,
            method='caption',
            size=(900, None)
        ).set_position('center').set_duration(audio_clip.duration)
        
        video_clip = CompositeVideoClip([image_clip, txt_clip]).set_audio(audio_clip)
        clips.append(video_clip)
        
    print("🎞️ Rendering final video...")
    final_video = concatenate_videoclips(clips, method="compose")
    final_video.write_videofile(output_filename, fps=24, codec="libx264", audio_codec="aac")
    print("✅ Video rendered successfully!")

# ==========================================
# 6. YOUTUBE UPLOAD
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

        tags = ["Roblox", "Shorts", "Gaming", "RobloxEdit"]
        if game_choice == "Blox Fruits":
            tags.extend(["BloxFruits", "BloxFruitsStory"])
        else:
            tags.extend(["Brookhaven", "BrookhavenRP"])

        description = f"{title}\n\nWhat do you think? Let me know in the comments!\n\n#Roblox #RobloxShorts #Gaming"
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
        script, game_choice = generate_script()
        assemble_video(script, output_filename="roblox_short.mp4")
        upload_to_youtube("roblox_short.mp4", script["title"], game_choice)
    except Exception as e:
        print(f"❌ Pipeline failed: {e}")
        exit(1)
