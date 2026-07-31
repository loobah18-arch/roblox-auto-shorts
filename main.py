import os
import json
import time
import urllib.parse
import asyncio
import requests
from groq import Groq
import edge_tts
from moviepy.editor import ImageClip, AudioFileClip, TextClip, CompositeVideoClip, concatenate_videoclips

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
        
        download_ai_image(scene["image_prompt"], image_file)
        asyncio.run(generate_audio(scene["narration"], audio_file))
        
        audio_clip = AudioFileClip(audio_file)
        image_clip = ImageClip(image_file).set_duration(audio_clip.duration)
        
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
def upload_to_youtube(video_path, title):
    print(f"🚀 Authenticating YouTube API...")
    
    # Check if we have the necessary secrets
    if not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN]):
        raise ValueError("Missing YouTube OAuth secrets in GitHub Environment! Cannot upload.")

    try:
        # 1. Authenticate using the refresh token stored in GitHub Secrets
        creds = Credentials(
            token=None,
            refresh_token=REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET
        )
        youtube = build("youtube", "v3", credentials=creds)

        # 2. Prepare the video metadata for YouTube Shorts
        description = f"{title}\n\nWhat do you think of this Roblox trick? Let me know in the comments!\n\n#Roblox #RobloxShorts #Gaming #BloxFruits #Brookhaven"
        # Truncate title to YouTube's 100 character limit just in case
        safe_title = f"{title} #Shorts"[:100]

        body = {
            "snippet": {
                "title": safe_title,
                "description": description,
                "tags": ["Roblox", "Shorts", "Gaming", "Blox Fruits", "Brookhaven"],
                "categoryId": "20" # 20 is the Gaming category ID
            },
            "status": {
                "privacyStatus": "public", # Change to "private" if you want to review before going live
                "selfDeclaredMadeForKids": False
            }
        }

        print(f"📡 Uploading '{safe_title}' to YouTube...")
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
        
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )
        
        # Execute the upload request
        response = request.execute()
        print(f"🎉 Upload successful! Video ID: {response.get('id')}")
        print(f"🔗 Link: https://youtube.com/shorts/{response.get('id')}")

    except HttpError as e:
        print(f"❌ YouTube API Error: {e.resp.status}")
        print(e.content.decode('utf-8'))
        raise e  # Force the pipeline to crash so GitHub shows a red X
    except Exception as e:
        print(f"❌ Upload Failed: {e}")
        raise e

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
