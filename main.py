import os
import json
import asyncio
import time
import random
import requests
import textwrap
import edge_tts
from PIL import Image, ImageDraw, ImageFont
from google import genai
from google.genai import types
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# 1. Initialize Gemini API Client
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))

# Pre-written local backup scripts if Gemini API quota is fully exhausted
FALLBACK_CONCEPTS = [
    {
        "game_chosen": "Brookhaven RP",
        "title": "Secret Bunker Location in Brookhaven! 😱 #Shorts #Roblox",
        "description": "How to find the secret agency bunker in Brookhaven RP! #Roblox #Gaming #Brookhaven",
        "scenes": [
            {"visual_prompt": "Roblox avatar standing outside Brookhaven hospital, mysterious mood, vertical 9:16", "narration": "Did you know there is a secret underground agency bunker in Brookhaven?"},
            {"visual_prompt": "Roblox avatar walking through hospital wall into hidden corridor, vertical 9:16", "narration": "First go to the hospital and head straight up to the top floor corner."},
            {"visual_prompt": "Roblox character grabbing secret blue keycard hidden behind cabinet, vertical 9:16", "narration": "Grab the secret blue keycard hidden behind the bookshelf."},
            {"visual_prompt": "Futuristic underground glowing red room in Roblox, vertical 9:16", "narration": "Now head under the lake and use the card to unlock the secret lab!"},
            {"visual_prompt": "Roblox character posing with shocked expression in glowing room, vertical 9:16", "narration": "Subscribe for more secret Roblox locations!"}
        ]
    },
    {
        "game_chosen": "Blox Fruits",
        "title": "How to Find Mirage Island in Blox Fruits Fast! 🏝️ #Shorts #Roblox",
        "description": "Quick guide to spawning Mirage Island in Roblox Blox Fruits! #Roblox #BloxFruits",
        "scenes": [
            {"visual_prompt": "Roblox boat driving through dark foggy ocean in Blox Fruits, vertical 9:16", "narration": "Struggling to find Mirage Island in Blox Fruits? Here is the fastest trick."},
            {"visual_prompt": "Roblox characters sailing together in Third Sea ocean, vertical 9:16", "narration": "First make sure you are sailing in Danger Level 4 or higher in Third Sea."},
            {"visual_prompt": "Full moon glowing over foggy ocean in Roblox game, vertical 9:16", "narration": "Wait until full moon night and have at least 3 players on the boat."},
            {"visual_prompt": "Mysterious glowing island rising from dark water in Roblox, vertical 9:16", "narration": "The island will spawn directly ahead in the fog. Search the highest peak for the mirror fractal!"},
            {"visual_prompt": "Roblox character holding rare glowing fruit victoriously, vertical 9:16", "narration": "Subscribe for more Blox Fruits tips!"}
        ]
    }
]

def generate_script_and_scenes():
    """Uses Gemini to pick a top Roblox game and write a 5-scene story, falling back to local scripts if API quota is exhausted."""
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
        {"visual_prompt": "3D blocky Roblox render prompt for scene 1, vertical 9:16", "narration": "Voiceover line for scene 1"},
        {"visual_prompt": "3D blocky Roblox render prompt for scene 2, vertical 9:16", "narration": "Voiceover line for scene 2"},
        {"visual_prompt": "3D blocky Roblox render prompt for scene 3, vertical 9:16", "narration": "Voiceover line for scene 3"},
        {"visual_prompt": "3D blocky Roblox render prompt for scene 4, vertical 9:16", "narration": "Voiceover line for scene 4"},
        {"visual_prompt": "3D blocky Roblox render prompt for scene 5, vertical 9:16", "narration": "Voiceover line for scene 5"}
      ]
    }
    """
    
    models_to_try = [
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-flash",
        "gemini-1.5-flash-8b"
    ]
    
    for model_name in models_to_try:
        print(f"🤖 Attempting script generation with model: {model_name}...")
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )
                return json.loads(response.text)
            except Exception as e:
                error_str = str(e)
                print(f"⚠️ Error on {model_name}: {error_str[:120]}...")
                if any(k in error_str.upper() for k in ["429", "RESOURCE_EXHAUSTED", "QUOTA"]):
                    time.sleep(5)
                break

    print("⚠️ Gemini API daily quota exhausted across all models. Switching to local backup script!")
    return random.choice(FALLBACK_CONCEPTS)

# 2. Audio Generator
async def generate_voiceover(text, filename):
    tts = edge_tts.Communicate(text, "en-US-ChristopherNeural")
    await tts.save(filename)

# 3. Image Generator
def download_ai_image(prompt, output_file):
    encoded_prompt = requests.utils.quote(f"{prompt}, 3d roblox gaming art style")
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1080&height=1920&nologo=true"
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=30)
    if response.status_code == 200:
        with open(output_file, "wb") as f:
            f.write(response.content)
    else:
        raise Exception(f"Failed image fetch with status: {response.status_code}")

# 4. Burn Subtitles onto Image (Pillow-based, crash-proof on GitHub Actions)
def add_subtitles_to_image(image_path, text, output_path):
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    width, height = img.size

    # Try loading Linux system DejaVu font, fallback to standard
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 50)
    except IOError:
        font = ImageFont.load_default()

    wrapped_text = textwrap.fill(text, width=22)
    bbox = draw.multiline_textbbox((0, 0), wrapped_text, font=font, align="center")
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    x = (width - text_w) // 2
    y = height - text_h - 280

    # Draw black outline/shadow for readability
    stroke = 4
    for adj_x in range(-stroke, stroke + 1):
        for adj_y in range(-stroke, stroke + 1):
            draw.multiline_text((x + adj_x, y + adj_y), wrapped_text, font=font, fill="black", align="center")

    # Draw main yellow text
    draw.multiline_text((x, y), wrapped_text, font=font, fill="yellow", align="center")
    img.save(output_path)

# 5. Build Video Short
def build_full_short(concept_data, output_filename="final_short.mp4"):
    scene_clips = []
    
    for idx, scene in enumerate(concept_data["scenes"]):
        audio_file = f"audio_{idx}.mp3"
        image_file = f"image_{idx}.jpg"
        sub_image_file = f"sub_image_{idx}.jpg"
        
        print(f"🎬 Processing Scene {idx + 1}/5...")
        asyncio.run(generate_voiceover(scene["narration"], audio_file))
        download_ai_image(scene["visual_prompt"], image_file)
        add_subtitles_to_image(image_file, scene["narration"], sub_image_file)
        
        audio_clip = AudioFileClip(audio_file)
        duration = audio_clip.duration + 0.3
        
        img_clip = ImageClip(sub_image_file).set_duration(duration).set_audio(audio_clip)
        scene_clips.append(img_clip)
    
    print("🎥 Assembling final video clip...")
    final_video = concatenate_videoclips(scene_clips, method="compose")
    final_video.write_videofile(output_filename, fps=24, codec="libx264", audio_codec="aac")
    
    # Cleanup memory
    final_video.close()
    for clip in scene_clips:
        clip.close()

# 6. YouTube API Upload
def upload_to_youtube(video_path, title, description):
    client_id = os.environ.get("YOUTUBE_CLIENT_ID") or os.environ.get("CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET") or os.environ.get("CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN") or os.environ.get("REFRESH_TOKEN")

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret
    )
    youtube = build("youtube", "v3", credentials=creds)
    
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": ["Roblox", "Shorts", "Gaming"],
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
    print(f"🎉 Posted successfully! Video ID: {response.get('id')}")

if __name__ == "__main__":
    print("🤖 Selecting Roblox game story concept...")
    concept = generate_script_and_scenes()
    print(f"📌 Game Selected: {concept.get('game_chosen')}")
    print(f"📌 Title: {concept['title']}")
    
    build_full_short(concept)
    upload_to_youtube("final_short.mp4", concept["title"], concept["description"])
