import os
import json
import time
import urllib.parse
import asyncio
import requests
import random
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
# 2. SCRIPT GENERATION (DYNAMIC STORY MODE)
# ==========================================
def generate_script():
    print("🤖 Requesting script from Groq API (Llama 3.3)...")
    
    # 1. Randomly decide which game to feature today
    game_choice = random.choice(["Blox Fruits", "Brookhaven"])
    print(f"🎲 Selected Theme for Today: {game_choice}")
    
    if game_choice == "Blox Fruits":
        # Read the story memory from yesterday
        previous_story = "A young pirate just arrived in the first sea." # Default starting point
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
        # Brookhaven - Random Chaos
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
    
    # 2. Fix spelling errors in the text before rendering
    for scene in script_data["scenes"]:
        scene["narration"] = scene["narration"].replace("blocks fruits", "Blox Fruits").replace("Bloxs Fruits", "Blox Fruits")
    
    # 3. Save the memory for tomorrow (if it was a Blox Fruits episode)
    if game_choice == "Blox Fruits" and "summary" in script_data:
        print(f"💾 Saving Story Memory for Tomorrow: {script_data['summary']}")
        with open("story_memory.txt", "w") as f:
            f.write(script_data["summary"])
            
    return script_data, game_choice

# ==========================================
# 3. AI IMAGE DOWNLOADER
# ==========================================
def download_ai_image(prompt, output_file):
    # Added vertical aspect ratio directly to the Pollinations URL
    encoded_prompt = urllib.parse.quote(f"{prompt}, 3d roblox gaming art style, high quality")
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1080&height=1920&nologo=true"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    attempt = 1
    while True:
        try:
            print(f"   ↳ Fetching image... (Attempt {attempt})")
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status() 
            
            with open(output_file, "wb") as f:
                f.write(response.content)
            
            print("   ✅ Image downloaded successfully! Proceeding...")
            break  
            
        except Exception as e:
            print(f"   ⚠️ Connection error: {e}")
            print("   ⏳ Task incomplete. Waiting 10 seconds before retrying...")
            time.sleep(10)
            attempt += 1

# ==========================================
# 4. AUDIO GENERATION
# ==========================================
async def generate_audio(text, output_file):
    print(f"   ↳ Generating voiceover...")
    communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural", rate="+10%")
    await communicate.save(output_file)

# ==========================================
# 5. VIDEO ASSEMBLY (WITH 9:16 CROP FIX)
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
        
        # EXACT 9:16 CROP FIX
        # Resize height to 1920, then crop width to 1080 from the exact center
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
        raise ValueError("Missing YouTube OAuth secrets in GitHub Environment! Cannot upload.")

    try:
        creds = Credentials(
            token=None,
            refresh_token=REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET
        )
        youtube = build("youtube", "v3", credentials=creds)

        # Dynamic Tags based on the game
        tags = ["Roblox", "Shorts", "Gaming", "RobloxEdit"]
        if game_choice == "Blox Fruits":
            tags.extend(["BloxFruits", "BloxFruitsStory"])
        else:
            tags.extend(["Brookhaven", "BrookhavenRP"])

        description = f"{title}\n\nWhat do you think of this? Let me know in the comments!\n\n#{tags[4]} #Roblox #RobloxShorts #Gaming"
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
        
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )
        
        response = request.execute()
        print(f"🎉 Upload successful! Video ID: {response.get('id')}")
        print(f"🔗 Link: https://youtube.com/shorts/{response.get('id')}")

    except HttpError as e:
        print(f"❌ YouTube API Error: {e.resp.status}")
        print(e.content.decode('utf-8'))
        raise e  
    except Exception as e:
        print(f"❌ Upload Failed: {e}")
        raise e

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    try:
        # Step A: Generate Script & Determine Game
        script, game_choice = generate_script()
        
        # Step B: Render Video
        assemble_video(script, output_filename="roblox_short.mp4")
        
        # Step C: Upload to YouTube
        upload_to_youtube("roblox_short.mp4", script["title"], game_choice)
        
    except Exception as e:
        print(f"❌ Pipeline failed: {e}")
        exit(1)
