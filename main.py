import os
import json
import asyncio
import time
import urllib.parse
import requests
import edge_tts
from moviepy.editor import ImageClip, CompositeVideoClip, AudioFileClip, TextClip, concatenate_videoclips
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

def get_backup_script():
    """Fallback script to guarantee video generation even if AI services are down."""
    return {
        "game_chosen": "Brookhaven RP",
        "title": "Secret Bunker Location in Brookhaven! 😱 #Shorts #Roblox",
        "description": "Uncovering the secret hidden location in Brookhaven RP! #Roblox #Gaming #Shorts",
        "scenes": [
            {
                "visual_prompt": "Roblox player standing in front of Brookhaven hospital entrance at night",
                "narration": "Did you know there is a top secret room hidden deep inside Brookhaven?"
            },
            {
                "visual_prompt": "Roblox avatar crawling through a dark hidden wall vent behind hospital cabinet",
                "narration": "Head over to the hospital and crawl behind the wall vents on the top floor."
            },
            {
                "visual_prompt": "Roblox secret lab with glowing green hazmat suits and emergency monitors",
                "narration": "Follow the dark corridor until you find the secret abandoned lab room!"
            },
            {
                "visual_prompt": "Roblox character pressing a glowing red button on a computer console",
                "narration": "Pressing the red button on the wall unlocks the secret hazmat suit storage."
            },
            {
                "visual_prompt": "Roblox character wearing glowing green hazmat suit doing a victory dance in Brookhaven",
                "narration": "Share this secret trick with your friends before it gets patched!"
            }
        ]
    }

def generate_script_and_scenes():
    """Uses Groq API (or keyless Pollinations AI as fallback) to pick a Roblox game and generate a script."""
    prompt = """
    Randomly select ONE popular game from this list of top Roblox games:
    - Brookhaven RP
    - Blox Fruits
    - Murder Mystery 2
    - Adopt Me!
    - Doors
    - Dress to Impress

    Create an engaging 5-scene story (around 8 to 10 seconds per scene) strictly focused on that chosen game's iconic secrets, gameplay, or tricks.

    Return STRICTLY valid JSON format with this exact structure:
    {
      "game_chosen": "Name of the chosen game",
      "title": "Catchy YouTube Title #Shorts #Roblox",
      "description": "Fun video description with hashtags #Roblox #Gaming",
      "scenes": [
        {
          "visual_prompt": "3D blocky Roblox render prompt for scene 1, vibrant, high detail, vertical 9:16",
          "narration": "Voiceover line for scene 1"
        },
        {
          "visual_prompt": "3D blocky Roblox render prompt for scene 2, vibrant, high detail, vertical 9:16",
          "narration": "Voiceover line for scene 2"
        },
        {
          "visual_prompt": "3D blocky Roblox render prompt for scene 3, vibrant, high detail, vertical 9:16",
          "narration": "Voiceover line for scene 3"
        },
        {
          "visual_prompt": "3D blocky Roblox render prompt for scene 4, vibrant, high detail, vertical 9:16",
          "narration": "Voiceover line for scene 4"
        },
        {
          "visual_prompt": "3D blocky Roblox render prompt for scene 5, vibrant, high detail, vertical 9:16",
          "narration": "Voiceover line for scene 5"
        }
      ]
    }
    """

    # 1. Primary Attempt: Groq API (Free, high quota, ultra-fast)
    groq_api_key = os.environ.get("GROQ_API_KEY")
    if groq_api_key:
        print("🤖 Requesting script from Groq API (Llama 3.3)...")
        groq_url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {groq_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"}
        }
        
        try:
            res = requests.post(groq_url, headers=headers, json=payload, timeout=20)
            if res.status_code == 200:
                content = res.json()["choices"][0]["message"]["content"]
                return json.loads(content)
            else:
                print(f"⚠️ Groq API Error ({res.status_code}): {res.text}")
        except Exception as e:
            print(f"⚠️ Groq API request failed: {e}")

    # 2. Secondary Fallback: Pollinations Text AI (100% Free, NO API KEY required)
    print("🤖 Attempting keyless generation via Pollinations Text AI...")
    try:
        pollination_url = "https://text.pollinations.ai/"
        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "jsonMode": True,
            "seed": int(time.time())
        }
        res = requests.post(pollination_url, json=payload, timeout=30)
        if res.status_code == 200:
            return json.loads(res.text)
    except Exception as e:
        print(f"⚠️ Pollinations Text AI failed: {e}")

    # 3. Final Fallback: Local Script
    print("⚠️ All AI endpoints failed or unconfigured. Using local backup script!")
    return get_backup_script()

# 2. Audio Generator
async def generate_voiceover(text, filename):
    tts = edge_tts.Communicate(text, "en-US-ChristopherNeural")
    await tts.save(filename)

# 3. Download AI Image Helper
def download_ai_image(prompt, output_file):
    encoded_prompt = urllib.parse.quote(f"{prompt}, 3d roblox gaming art style")
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1080&height=1920&nologo=true"
    response = requests.get(url, timeout=30)
    if response.status_code == 200:
        with open(output_file, "wb") as f:
            f.write(response.content)
    else:
        raise Exception(f"Failed to fetch image from Pollinations API (Status code: {response.status_code})")

# 4. Assemble and Concatenate All Scenes
def build_full_short(concept_data, output_filename="final_short.mp4"):
    scene_clips = []
    
    for idx, scene in enumerate(concept_data["scenes"]):
        audio_file = f"audio_{idx}.mp3"
        image_file = f"image_{idx}.jpg"
        
        print(f"🎬 Processing Scene {idx + 1}/{len(concept_data['scenes'])}...")
        
        asyncio.run(generate_voiceover(scene["narration"], audio_file))
        download_ai_image(scene["visual_prompt"], image_file)
        
        audio_clip = AudioFileClip(audio_file)
        duration = audio_clip.duration + 0.3
        
        img_clip = ImageClip(image_file).set_duration(duration)
        
        try:
            txt_clip = TextClip(
                scene["narration"],
                fontsize=40,
                color='yellow',
                font='DejaVu-Sans-Bold',
                method='caption',
                size=(900, 300)
            ).set_position(('center', 'bottom')).set_duration(duration)
            combined_scene = CompositeVideoClip([img_clip, txt_clip]).set_audio(audio_clip)
        except Exception as e:
            print(f"⚠️ Subtitle render fallback applied: {e}")
            combined_scene = img_clip.set_audio(audio_clip)
            
        scene_clips.append(combined_scene)
    
    print("🎥 Concatenating all scenes into one full Short...")
    final_video = concatenate_videoclips(scene_clips, method="compose")
    final_video.write_videofile(output_filename, fps=24, codec="libx264", audio_codec="aac")

# 5. YouTube API Upload
def upload_to_youtube(video_path, title, description):
    creds = Credentials(
        token=None,
        refresh_token=os.environ["REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["CLIENT_ID"],
        client_secret=os.environ["CLIENT_SECRET"]
    )
    youtube = build("youtube", "v3", credentials=creds)
    
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": ["Roblox", "Shorts", "Gaming", "Brookhaven", "BloxFruits", "MM2", "Doors"],
            "categoryId": "20"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    print(f"🎉 Successfully posted! Video ID: {response.get('id')}")

if __name__ == "__main__":
    print("🤖 Selecting a Roblox game and writing story scenes...")
    concept = generate_script_and_scenes()
    print(f"📌 Game Selected: {concept.get('game_chosen', 'Popular Roblox Game')}")
    print(f"📌 Title: {concept['title']}")
    
    print("📹 Assembling 5-scene video...")
    build_full_short(concept)
    
    print("🚀 Uploading 50-60 second Short to YouTube...")
    upload_to_youtube("final_short.mp4", concept["title"], concept["description"])
