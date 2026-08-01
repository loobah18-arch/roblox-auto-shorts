import os
import time
import random
import requests
import urllib.parse
import asyncio
import edge_tts
from rembg import remove
from moviepy.editor import ImageClip, AudioFileClip, CompositeVideoClip, CompositeAudioClip

# Groq API Import
from groq import Groq

# Google API Imports for YouTube Upload
import google.auth.transport.requests
import google.oauth2.credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ==========================================
# 1. API & GENERATION FUNCTIONS
# ==========================================

def generate_script_with_groq():
    """Generates a dynamic, engaging script for a Roblox Short using Groq's 70B model."""
    print("Generating fresh script using Groq Llama 3.3 70B...")
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise Exception("Missing GROQ_API_KEY environment variable!")
        
    client = Groq(api_key=api_key)
    
    prompt = (
        "Write a short, high-energy YouTube Short script about Roblox Blox Fruits, "
        "focusing on a cool tip, trick, or overpowered fruit setup. "
        "Keep it under 60 words, punchy, engaging, and ready for a voiceover. "
        "Do not include any speaker labels, sound effects, or camera directions, just the pure spoken text."
    )
    
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=150,
        temperature=0.8
    )
    
    script = response.choices[0].message.content.strip()
    print(f"Generated Script: {script}")
    return script

def generate_image(prompt, filename, retries=3):
    """Fetches an image from Pollinations.ai with a retry loop to prevent API timeouts."""
    print(f"Generating: {filename}...")
    encoded_prompt = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1080&height=1920&nologo=true"
    
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                with open(filename, 'wb') as f:
                    f.write(response.content)
                print(f"Success: Saved {filename}")
                return
            else:
                print(f"Attempt {attempt + 1} failed. Server returned {response.status_code}.")
        except Exception as e:
            print(f"Attempt {attempt + 1} failed with error: {e}")
        
        time.sleep(10)
        
    raise Exception(f"Fatal Error: Failed to generate {filename} after {retries} attempts.")

async def generate_voiceover(text, output_filename):
    """Generates an Edge-TTS voiceover file."""
    print("Generating voiceover...")
    communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural", rate="+10%")
    await communicate.save(output_filename)
    print("Voiceover saved successfully.")

def create_transparent_sprite(input_filename, output_filename):
    """Uses local CPU rembg to strip the background from the character."""
    print("Stripping background from character sprite...")
    with open(input_filename, "rb") as input_file:
        transparent_data = remove(input_file.read())
        
    with open(output_filename, "wb") as out_file:
        out_file.write(transparent_data)
    print("Transparent sprite created.")

# ==========================================
# 2. VIDEO ASSEMBLY FUNCTION
# ==========================================

def assemble_video():
    """Builds the 2D puppetry, voiceover, and background music."""
    print("--- Assembling 2D Puppetry Video ---")
    
    voice_clip = AudioFileClip("voiceover.mp3")
    video_duration = voice_clip.duration
    
    bgm_folder = "bgm"
    if not os.path.exists(bgm_folder):
        raise Exception("Missing 'bgm' folder in your repository root!")
        
    mp3_files = [f for f in os.listdir(bgm_folder) if f.endswith('.mp3')]
    if not mp3_files:
        raise Exception("No .mp3 files found inside the 'bgm' folder!")
        
    random_track = random.choice(mp3_files)
    bgm_path = os.path.join(bgm_folder, random_track)
    print(f"Selected background music: {random_track}")
    
    bg_music = AudioFileClip(bgm_path)
    bg_music = bg_music.subclip(0, video_duration).volumex(0.1)
    
    final_audio = CompositeAudioClip([voice_clip, bg_music])

    background = ImageClip("background.jpg").set_duration(video_duration)
    background = background.resize(width=1080, height=1920) 
    
    character = ImageClip("character_sprite.png").set_duration(video_duration)
    character = character.resize(width=700) 
    
    def animate_character(t):
        x_position = 100 + (t * 30)       
        y_position = 1000 - (t * 20)      
        return (x_position, y_position)
        
    animated_character = character.set_position(animate_character)

    final_video = CompositeVideoClip([background, animated_character])
    final_video = final_video.set_audio(final_audio)
    
    print("Rendering final MP4 on CPU...")
    final_video.write_videofile(
        "final_short.mp4", 
        fps=24, 
        codec="libx264", 
        audio_codec="aac",
        threads=2, 
        preset="ultrafast" 
    )

# ==========================================
# 3. YOUTUBE UPLOAD FUNCTION
# ==========================================

def upload_to_youtube():
    print("--- Uploading to YouTube as a Short ---")
    
    client_id = os.getenv("CLIENT_ID")
    client_secret = os.getenv("CLIENT_SECRET")
    refresh_token = os.getenv("REFRESH_TOKEN")
    
    if not client_id or not client_secret or not refresh_token:
        print("Warning: YouTube API secrets not fully configured. Skipping upload step.")
        return

    credentials = google.oauth2.credentials.Credentials(
        None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret
    )
    
    youtube = build("youtube", "v3", credentials=credentials)
    
    body = {
        "snippet": {
            "title": "Insane Blox Fruits Setup You Need to Try! #Shorts",
            "description": "Check out this amazing Roblox Blox Fruits setup generated automatically! #Shorts #Roblox #BloxFruits",
            "tags": ["Roblox", "BloxFruits", "Shorts"],
            "categoryId": "20"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }
    
    media = MediaFileUpload("final_short.mp4", chunksize=-1, resumable=True)
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )
    
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Uploading file: {int(status.progress() * 100)}%")
            
    print(f"Upload Complete! Video ID: {response.get('id')}")

# ==========================================
# 4. MAIN EXECUTION
# ==========================================

def main():
    script = generate_script_with_groq()
    
    asyncio.run(generate_voiceover(script, "voiceover.mp3"))

    bg_prompt = "A cinematic Blox Fruits ocean landscape, vibrant colors, 8k resolution, vertical anime style"
    generate_image(bg_prompt, "background.jpg")
    
    char_prompt = "Roblox noob character using best fruit power, standing on a solid pure white background, 3d render"
    generate_image(char_prompt, "raw_character.jpg")
    
    create_transparent_sprite("raw_character.jpg", "character_sprite.png")
    
    assemble_video()
    
    upload_to_youtube()
    
    print("Pipeline complete!")

if __name__ == "__main__":
    main()
