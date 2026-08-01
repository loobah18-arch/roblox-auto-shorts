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
# 1. INFINITE STORY & ASSET GENERATION
# ==========================================

def generate_infinite_script():
    """Generates an infinite, serialized, absurd, and catchy story script using Groq's 70B model."""
    print("Generating next chapter of the infinite Blox Fruits saga...")
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise Exception("Missing GROQ_API_KEY environment variable!")
        
    client = Groq(api_key=api_key)
    
    # Read previous memory context if it exists
    history_file = "story_memory.txt"
    previous_context = "This is Episode 1 of the saga. Start with a massive, mind-blowing hook about Roblox Blox Fruits."
    
    if os.path.exists(history_file):
        with open(history_file, "r") as f:
            content = f.read().strip()
            if content:
                previous_context = content

    prompt = f"""
    You are an unhinged, viral AI director creating an infinite, serialized epic saga about Roblox Blox Fruits for YouTube Shorts.
    
    PREVIOUS EPISODE CONTEXT:
    {previous_context}
    
    YOUR TASK:
    Write the NEXT immediate part of this story. It must continue EXACTLY where the previous episode left off. 
    
    RULES FOR THE SCRIPT:
    1. **Absurd & Catchy:** Include bizarre plot twists, ridiculous item/fruit combinations (e.g., fighting a Sea Beast while eating a kilo fruit underwater), and peak meme energy.
    2. **Length & Pacing:** Keep it between 130 and 150 words so the voiceover runs for strictly over 50 seconds. Fast-paced, punchy, zero fluff.
    3. **The Cliffhanger:** You MUST end the script on a jaw-dropping, completely absurd cliffhanger so viewers are desperate for tomorrow's part.
    4. **Format:** Output ONLY the pure spoken text. No speaker labels, no scene directions, no sound effect tags.
    """
    
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=400,
        temperature=0.9
    )
    
    new_script = response.choices[0].message.content.strip()
    
    # Save current script/context back to memory for tomorrow's run
    with open(history_file, "w") as f:
        f.write(new_script)
        
    print(f"Generated Script: {new_script}")
    return new_script

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
# 2. VIDEO ASSEMBLY FUNCTION (50+ SECONDS)
# ==========================================

def assemble_video():
    """Builds the 2D puppetry, voiceover, and loops background music to match 50s+ duration."""
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
    
    # Loop background music if it's shorter than the 50s+ voiceover
    if bg_music.duration < video_duration:
        bg_music = bg_music.loop(duration=video_duration)
    else:
        bg_music = bg_music.subclip(0, video_duration)
        
    bg_music = bg_music.volumex(0.1)
    
    final_audio = CompositeAudioClip([voice_clip, bg_music])

    background = ImageClip("background.jpg").set_duration(video_duration)
    background = background.resize(width=1080, height=1920) 
    
    character = ImageClip("character_sprite.png").set_duration(video_duration)
    character = character.resize(width=700) 
    
    def animate_character(t):
        x_position = 100 + (t * 15)       
        y_position = 1000 - (t * 8)      
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
            "title": "The Infinite Blox Fruits Saga! #Shorts",
            "description": "Continuing the wild, unhinged Blox Fruits journey daily! #Shorts #Roblox #BloxFruits",
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
    script = generate_infinite_script()
    
    asyncio.run(generate_voiceover(script, "voiceover.mp3"))

    bg_prompt = "A cinematic chaotic Blox Fruits ocean landscape, vibrant colors, 8k resolution, vertical anime style"
    generate_image(bg_prompt, "background.jpg")
    
    char_prompt = "A classic blocky Roblox noob character, low-poly 3D game model, yellow skin, blue shirt, standing on a solid pure white background"
    generate_image(char_prompt, "raw_character.jpg")
    
    create_transparent_sprite("raw_character.jpg", "character_sprite.png")
    
    assemble_video()
    
    upload_to_youtube()
    
    print("Pipeline complete!")

if __name__ == "__main__":
    main()
