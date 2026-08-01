import os
import random
import time
import json
import requests
import asyncio
import edge_tts

# Fix MoviePy ImageMagick path detection on GitHub Actions Ubuntu runners to prevent exit code 1 crashes
os.environ["IMAGEMAGICK_BINARY"] = "/usr/bin/convert"

from moviepy.editor import VideoFileClip, ImageClip, CompositeVideoClip, AudioFileClip, CompositeAudioClip, TextClip
import moviepy.video.fx.all as vfx
from groq import Groq
import google.auth.transport.requests
import google.oauth2.credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ==========================================
# 1. INFINITE STORY GENERATION (GROQ)
# ==========================================
def generate_infinite_script():
    """Generates an infinite story script using Groq's 70B model."""
    print("--- [Step 1/4] Generating Next Chapter via Groq Llama 3.3 70B ---")
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise Exception("Missing GROQ_API_KEY environment variable!")
        
    client = Groq(api_key=api_key)
    history_file = "story_memory.txt"
    previous_context = "This is Episode 1 of the saga. Start with a massive, mind-breaking hook about Roblox Blox Fruits."
    
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
    Keep it between 130 and 150 words. Absurd, catchy, meme energy, ending on a jaw-dropping cliffhanger. 
    Output purely the spoken text, no labels, no sound effect notes.
    """
    
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=300,
        temperature=0.9
    )
    
    script = response.choices[0].message.content.strip()
    
    with open(history_file, "w") as f:
        f.write(script)
        
    print(f"Generated Script:\n{script}\n")
    return script

async def generate_voiceover(text, output_filename):
    """Generates an Edge-TTS voiceover file."""
    print("--- [Step 2/4] Generating Voiceover Audio ---")
    communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural", rate="+10%")
    await communicate.save(output_filename)
    print(f"Voiceover saved to {output_filename}\n")

# ==========================================
# 2. LOCAL GAMEPLAY TEMPLATE SELECTION
# ==========================================
def select_gameplay_clip():
    """Selects a random pre-recorded Roblox MP4 clip from the local motion_templates folder."""
    print("--- [Step 3/4] Selecting Local Gameplay from motion_templates ---")
    templates_dir = "motion_templates"
    
    if not os.path.exists(templates_dir):
        os.makedirs(templates_dir, exist_ok=True)
        raise Exception(f"Missing '{templates_dir}' folder. Add at least one Roblox MP4 clip!")
        
    clips = [f for f in os.listdir(templates_dir) if f.endswith('.mp4')]
    if not clips:
        raise Exception(f"No MP4 files found in '{templates_dir}' folder!")
        
    chosen_clip = os.path.join(templates_dir, random.choice(clips))
    print(f"Selected Gameplay Clip: {chosen_clip}\n")
    return chosen_clip

# ==========================================
# 3. VIDEO ASSEMBLY (GAMEPLAY + AUDIO + CAPTIONS)
# ==========================================
def assemble_video(script, gameplay_path):
    print("--- [Step 4/4] Assembling Final MP4 Video ---")
    
    voice_clip = AudioFileClip("voiceover.mp3")
    target_duration = voice_clip.duration
    
    base_video = VideoFileClip(gameplay_path)
    base_video = base_video.resize(height=1920)
    
    if base_video.duration < target_duration:
        looped_video = vfx.loop(base_video, duration=target_duration)
    else:
        looped_video = base_video.subclip(0, target_duration)
        
    if looped_video.w > 1080:
        x_center = looped_video.w / 2
        looped_video = looped_video.crop(x1=x_center - 540, x2=x_center + 540, y1=0, y2=1920)
    
    bgm_folder = "bgm"
    if not os.path.exists(bgm_folder):
        os.makedirs(bgm_folder, exist_ok=True)
    mp3_files = [f for f in os.listdir(bgm_folder) if f.endswith('.mp3')]
    
    if mp3_files:
        bg_music = AudioFileClip(os.path.join(bgm_folder, random.choice(mp3_files)))
        if bg_music.duration < target_duration:
            bg_music = vfx.loop(bg_music, duration=target_duration)
        else:
            bg_music = bg_music.subclip(0, target_duration)
        bg_music = bg_music.volumex(0.12)
        final_audio = CompositeAudioClip([voice_clip, bg_music])
    else:
        final_audio = voice_clip
        
    looped_video = looped_video.set_audio(final_audio)

    sentences = [s.strip() for s in script.replace("!", ".").replace("?", ".").split(".") if s.strip()]
    chunk_duration = target_duration / max(len(sentences), 1)
    
    caption_clips = []
    for i, sentence in enumerate(sentences):
        start_t = i * chunk_duration
        end_t = min((i + 1) * chunk_duration, target_duration)
        dur = max(end_t - start_t, 1.0)
        
        try:
            txt_clip = TextClip(
                sentence, fontsize=60, color='yellow', 
                stroke_color='black', stroke_width=4, size=(950, None), method='caption'
            )
            txt_clip = txt_clip.set_start(start_t).set_duration(dur).set_position(('center', 1400))
            caption_clips.append(txt_clip)
        except Exception:
            pass

    final_video = CompositeVideoClip([looped_video] + caption_clips)
    print("Rendering final MP4...")
    final_video.write_videofile(
        "final_short.mp4", fps=24, codec="libx264", 
        audio_codec="aac", threads=2, preset="ultrafast", logger=None
    )
    print("Video assembly complete: final_short.mp4 created.\n")

# ==========================================
# 4. YOUTUBE UPLOAD FUNCTION
# ==========================================
def upload_to_youtube(script_snippet):
    print("--- [Step 5/5] Uploading to YouTube Channel as Short ---")
    
    client_id = os.getenv("CLIENT_ID")
    client_secret = os.getenv("CLIENT_SECRET")
    refresh_token = os.getenv("REFRESH_TOKEN")
    
    if not client_id or not client_secret or not refresh_token:
        print("Warning: YouTube API secrets missing. Skipping upload step.")
        return

    credentials = google.oauth2.credentials.Credentials(
        None, refresh_token=refresh_token, token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id, client_secret=client_secret
    )
    
    youtube = build("youtube", "v3", credentials=credentials)
    
    title_words = script_snippet.split()[:7]
    dynamic_title = " ".join(title_words) if title_words else "Blox Fruits Madness!"
    
    body = {
        "snippet": {
            "title": f"{dynamic_title}... #Shorts",
            "description": f"{script_snippet}\n\n#Shorts #Roblox #BloxFruits #Gaming",
            "tags": ["Roblox", "BloxFruits", "Shorts", "Gaming", "Gameplay"],
            "categoryId": "20"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }
    
    media = MediaFileUpload("final_short.mp4", chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Uploading file: {int(status.progress() * 100)}%")
            
    print(f"Upload Successful! Video ID: {response.get('id')}\nURL: https://youtube.com/shorts/{response.get('id')}")

# ==========================================
# 5. MAIN EXECUTION
# ==========================================
def main():
    print("=== Starting Hybrid Gameplay Pipeline ===\n")
    
    script = generate_infinite_script()
    asyncio.run(generate_voiceover(script, "voiceover.mp3"))
    chosen_gameplay = select_gameplay_clip()
    assemble_video(script, chosen_gameplay)
    upload_to_youtube(script)
    
    print("=== Pipeline Complete! Short is Live. ===")

if __name__ == "__main__":
    main()
