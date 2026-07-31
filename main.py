import os
import json
import time
import urllib.parse
import asyncio
import requests
from groq import Groq
import edge_tts
from moviepy.editor import ImageClip, AudioFileClip, TextClip, CompositeVideoClip, concatenate_videoclips

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
# 2. SCRIPT GENERATION (GROQ API)
# ==========================================
def generate_script():
    print("🤖 Requesting script from Groq API (Llama 3.3)...")
    prompt = """
    Write a 3-scene Roblox Shorts script (theme: Blox Fruits or Brookhaven). 
    Return strictly in JSON format matching this structure:
    {
      "title": "Video Title",
      "scenes": [
        {"narration": "Voiceover text here", "image_prompt": "Visual description for AI"}
      ]
    }
    """
    
    response = groq_client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model="llama-3.3-70b-versatile",
        response_format={"type": "json_object"}
    )
    
    script_data = json.loads(response.choices[0].message.content)
    print(f"📌 Title: {script_data['title']}")
    return script_data

# ==========================================
# 3. AI IMAGE DOWNLOADER (STRICT BLOCKING)
# ==========================================
def download_ai_image(prompt, output_file):
    encoded_prompt = urllib.parse.quote(f"{prompt}, 3d roblox gaming art style, high quality")
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1080&height=1920&nologo=true"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    attempt = 1
    # Infinite loop that only breaks when the task is completely successful
    while True:
        try:
            print(f"   ↳ Fetching image... (Attempt {attempt})")
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status() # Catches 404/500/502 errors
            
            with open(output_file, "wb") as f:
                f.write(response.content)
            
            print("   ✅ Image downloaded successfully! Proceeding...")
            break  # Task is done, exit the loop to move on to the next scene
            
        except Exception as e:
            print(f"   ⚠️ Connection error: {e}")
            print("   ⏳ Task incomplete. Waiting 10 seconds before retrying...")
            time.sleep(10)
            attempt += 1

# ==========================================
# 4. AUDIO GENERATION (EDGE-TTS)
# ==========================================
async def generate_audio(text, output_file):
    print(f"   ↳ Generating voiceover...")
    communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural", rate="+10%")
    await communicate.save(output_file)

# ==========================================
# 5. VIDEO ASSEMBLY (MOVIEPY)
# ==========================================
def assemble_video(script_data, output_filename="final_short.mp4"):
    print("🎬 Assembling video scenes...")
    clips = []
    
    for i, scene in enumerate(script_data["scenes"]):
        print(f"🎥 Processing Scene {i+1}/{len(script_data['scenes'])}...")
        
        image_file = f"scene_{i}.jpg"
        audio_file = f"scene_{i}.mp3"
        
        # 1. Download Media (Blocks until success)
        download_ai_image(scene["image_prompt"], image_file)
        asyncio.run(generate_audio(scene["narration"], audio_file))
        
        # 2. Load into MoviePy
        audio_clip = AudioFileClip(audio_file)
        image_clip = ImageClip(image_file).set_duration(audio_clip.duration)
        
        # 3. Add Subtitles (TextOverlay)
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
        
        # 4. Combine Video & Audio
        video_clip = CompositeVideoClip([image_clip, txt_clip]).set_audio(audio_clip)
        clips.append(video_clip)
        
    print("🎞️ Rendering final video...")
    final_video = concatenate_videoclips(clips, method="compose")
    final_video.write_videofile(output_filename, fps=24, codec="libx264", audio_codec="aac")
    print("✅ Video rendered successfully!")

# ==========================================
# 6. YOUTUBE UPLOAD (PLACEHOLDER)
# ==========================================
def upload_to_youtube(video_file, title):
    print(f"🚀 Initiating YouTube upload for: {title}")
    # Add your google-api-python-client logic here using CLIENT_ID, CLIENT_SECRET, and REFRESH_TOKEN
    # Since OAuth is configured via GitHub Secrets, you will use google.oauth2.credentials to authenticate headless.
    print("✅ Upload script completed.")

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    try:
        # Step A: Generate Script
        script = generate_script()
        
        # Step B: Render Video
        assemble_video(script, output_filename="roblox_short.mp4")
        
        # Step C: Upload to YouTube
        upload_to_youtube("roblox_short.mp4", script["title"])
        
    except Exception as e:
        print(f"❌ Pipeline failed: {e}")
        exit(1)
