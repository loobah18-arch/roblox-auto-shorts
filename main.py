import os
import time
import random
import requests
import urllib.parse
import asyncio
import edge_tts
from rembg import remove
from moviepy.editor import (
    ImageClip, AudioFileClip, CompositeVideoClip, 
    CompositeAudioClip, TextClip, concatenate_videoclips
)

# Groq API Import
from groq import Groq

# Google API Imports for YouTube Upload
import google.auth.transport.requests
import google.oauth2.credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ==========================================
# 1. INFINITE STORY & SCENE GENERATION
# ==========================================

def generate_infinite_script():
    """Generates an infinite story script and dynamic visual scene prompts using Groq's 70B model."""
    print("Generating next chapter and visual scenes using Groq Llama 3.3 70B...")
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise Exception("Missing GROQ_API_KEY environment variable!")
        
    client = Groq(api_key=api_key)
    
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
    
    You must output your response in TWO sections separated strictly by "---VISUALS---":
    
    Section 1: The spoken script. Keep it between 130 and 150 words (50+ seconds). Absurd, catchy, meme energy, ending on a jaw-dropping cliffhanger. Pure spoken text only, no labels or sound effects.
    
    ---VISUALS---
    
    Section 2: Provide **5 distinct**, highly detailed image generation prompts separated by semicolons (;) that visually match the progression of this specific script from start to finish. Make them cinematic, vertical 9:16 anime style.
    """
    
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=500,
        temperature=0.9
    )
    
    full_response = response.choices[0].message.content.strip()
    
    if "---VISUALS---" in full_response:
        parts = full_response.split("---VISUALS---")
        script = parts[0].strip()
        visual_prompts_text = parts[1].strip()
        visual_prompts = [p.strip() for p in visual_prompts_text.split(";") if p.strip()]
    else:
        script = full_response
        visual_prompts = [
            "A chaotic Blox Fruits ocean battle, vibrant anime style, vertical",
            "A wild monster mutation in Roblox style, neon lighting, vertical",
            "A surreal sci-fi dimension with floating islands, vertical 8k",
            "An intense anime sword fight in Roblox, dynamic action, vertical",
            "A massive explosion of energy on a Roblox island, epic lighting, vertical"
        ]
        
    # Fallback if prompts are missing
    while len(visual_prompts) < 5:
        visual_prompts.append("A surreal Roblox anime landscape, vertical 8k")
        
    # Save script back to memory for tomorrow's run
    with open(history_file, "w") as f:
        f.write(script)
        
    print(f"Generated Script: {script}")
    print(f"Generated Visual Prompts: {visual_prompts[:5]}")
    return script, visual_prompts[:5]

def generate_image(prompt, filename, retries=3):
    """Fetches an image from Pollinations.ai with a retry loop."""
    print(f"Generating: {filename} with prompt: {prompt}")
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
# 2. VIDEO ASSEMBLY WITH MULTI-SCENE & CAPTIONS
# ==========================================

def assemble_video(script, num_scenes=5):
    """Builds a dynamic multi-scene video based on background images and burns captions."""
    print(f"--- Assembling Multi-Scene Video with {num_scenes} Scenes & Captions ---")
    
    voice_clip = AudioFileClip("voiceover.mp3")
    video_duration = voice_clip.duration
    
    # 1. Background Music Mixing
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
    if bg_music.duration < video_duration:
        bg_music = bg_music.loop(duration=video_duration)
    else:
        bg_music = bg_music.subclip(0, video_duration)
        
    bg_music = bg_music.volumex(0.1)
    final_audio = CompositeAudioClip([voice_clip, bg_music])

    # 2. Dynamic Background Assembly (Splits duration across available background images)
    scene_duration = video_duration / float(num_scenes)
    scene_clips = []
    
    for i in range(1, num_scenes + 1):
        img_path = f"background_{i}.jpg"
        if os.path.exists(img_path):
            clip = ImageClip(img_path).set_duration(scene_duration).resize(width=1080, height=1920)
            scene_clips.append(clip)
        else:
            if scene_clips:
                scene_clips.append(scene_clips[-1].set_duration(scene_duration))
            else:
                dummy = ImageClip("background_1.jpg").set_duration(scene_duration).resize(width=1080, height=1920)
                scene_clips.append(dummy)
            
    animated_background = concatenate_videoclips(scene_clips)

    # 3. Character Animation Layer
    character = ImageClip("character_sprite.png").set_duration(video_duration)
    character = character.resize(width=700) 
    
    def animate_character(t):
        x_position = 100 + (t * 15)       
        y_position = 1000 - (t * 8)      
        return (x_position, y_position)
        
    animated_character = character.set_position(animate_character)

    # 4. Dynamic Subtitles / Captions Generation
    sentences = [s.strip() for s in script.replace("!", ".").replace("?", ".").split(".") if s.strip()]
    chunk_duration = video_duration / max(len(sentences), 1)
    
    caption_clips = []
    for i, sentence in enumerate(sentences):
        start_t = i * chunk_duration
        end_t = min((i + 1) * chunk_duration, video_duration)
        dur = max(end_t - start_t, 1.0)
        
        try:
            txt_clip = TextClip(
                sentence, 
                fontsize=50, 
                color='yellow', 
                font='Arial-Bold', 
                stroke_color='black', 
                stroke_width=3, 
                size=(950, None), 
                method='caption'
            )
            txt_clip = txt_clip.set_start(start_t).set_duration(dur).set_position(('center', 1450))
            caption_clips.append(txt_clip)
        except Exception as e:
            print(f"Warning: Could not create caption clip: {e}")

    # 5. Composite and Render
    elements = [animated_background, animated_character] + caption_clips
    final_video = CompositeVideoClip(elements)
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
            "description": "Continuing the wild, unhinged Blox Fruits journey daily with dynamic scenes and captions! #Shorts #Roblox #BloxFruits",
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
    # 1. Generate infinite story script and 5 visual scene prompts
    script, visual_prompts = generate_infinite_script()
    
    # 2. Generate Voiceover (50+ seconds duration target)
    asyncio.run(generate_voiceover(script, "voiceover.mp3"))

    # 3. Dynamically generate and save each background image for multi-scene switching
    for i, prompt_text in enumerate(visual_prompts, start=1):
        generate_image(prompt_text, f"background_{i}.jpg")
    
    # 4. Generate character sprite
    char_prompt = "A classic blocky Roblox noob character, low-poly 3D game model, yellow skin, blue shirt, standing on a solid pure white background"
    generate_image(char_prompt, "raw_character.jpg")
    create_transparent_sprite("raw_character.jpg", "character_sprite.png")
    
    # 5. Assemble video with multi-scenes and dynamic captions
    assemble_video(script, num_scenes=len(visual_prompts))
    
    # 6. Upload to YouTube
    upload_to_youtube()
    
    print("Pipeline complete!")

if __name__ == "__main__":
    main()
