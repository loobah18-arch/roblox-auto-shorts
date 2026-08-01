import os
import random
import json
import subprocess
import requests
import asyncio
import edge_tts
import glob
import urllib.request
import re

# Fix MoviePy ImageMagick path detection on GitHub Actions Ubuntu runners
os.environ["IMAGEMAGICK_BINARY"] = "/usr/bin/convert"

from moviepy.editor import VideoFileClip, ImageClip, CompositeVideoClip, AudioFileClip, CompositeAudioClip, TextClip, concatenate_videoclips, ColorClip
import moviepy.video.fx.all as vfx
from groq import Groq
import google.auth.transport.requests
import google.oauth2.credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

def clean_env(val):
    """Sanitizes environment variables to remove accidental markdown wrappers or brackets."""
    if not val:
        return ""
    val = val.strip()
    if val.startswith("[") and "]" in val:
        val = val.split("]")[0].lstrip("[")
    return val.strip("'\"")

# ==========================================
# 1. GROQ SCRIPT & DYNAMIC QUERY GENERATOR
# ==========================================
def generate_script_and_queries():
    """Generates the story script and custom search queries via Groq."""
    print("--- [Step 1/5] Groq Directing Script & Visual Queries ---")
    api_key = clean_env(os.getenv("GROQ_API_KEY"))
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
    1. Write the NEXT immediate part of this story (between 130 and 150 words). Absurd, catchy, meme energy, ending on a cliffhanger.
    2. Generate exactly 5 distinct, high-energy search queries to find vertical gameplay clips that visually match the action happening in this specific story segment.
    
    You MUST output your response strictly as a JSON object with this exact structure, with no markdown formatting around it (no ```json):
    {{
      "script": "The full story text here...",
      "queries": [
        "query 1 matching early part of story",
        "query 2 matching middle part",
        "query 3 matching climax",
        "query 4 matching twist",
        "query 5 matching ending cliffhanger"
      ]
    }}
    """
    
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=500,
        temperature=0.9
    )
    
    raw_response = response.choices[0].message.content.strip()
    
    if raw_response.startswith("```"):
        raw_response = raw_response.split("```")[1]
        if raw_response.startswith("json"):
            raw_response = raw_response[4:]
    raw_response = raw_response.strip()
    
    data = json.loads(raw_response)
    script = data["script"]
    queries = data["queries"]
    
    with open(history_file, "w") as f:
        f.write(script)
        
    print(f"Generated Script:\n{script}\n")
    print(f"Generated Dynamic Queries: {queries}\n")
    return script, queries

async def generate_voiceover(text, output_filename):
    """Generates an Edge-TTS voiceover file."""
    print("--- [Step 2/5] Generating Voiceover Audio ---")
    communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural", rate="+10%")
    await communicate.save(output_filename)
    print(f"Voiceover saved to {output_filename}\n")

# ==========================================
# 2. DUAL-ENGINE CLIP FETCHING (yt-dlp + Pexels API)
# ==========================================
def fetch_dynamic_clips(queries):
    """Downloads clips using yt-dlp first, falling back to Pexels API if blocked."""
    print("--- [Step 3/5] Dual-Engine Clip Fetching (yt-dlp + Pexels API) ---")
    templates_dir = "motion_templates"
    os.makedirs(templates_dir, exist_ok=True)
    
    for old_file in glob.glob(os.path.join(templates_dir, "*.mp4")):
        try:
            os.remove(old_file)
        except Exception:
            pass
            
    downloaded_clips = []
    pexels_api_key = clean_env(os.getenv("PEXELS_API_KEY"))

    for i, query in enumerate(queries):
        clip_filename = f"clip_{i+1}.mp4"
        output_path = os.path.join(templates_dir, clip_filename)
        success = False
        
        # --- Engine 1: yt-dlp ---
        print(f"Trying yt-dlp for clip {i+1} -> Query: {query}")
        cmd = [
            "yt-dlp",
            f"ytsearch1:{query} roblox shorts",
            "--extractor-args", "youtube:player_client=android",
            "-f", "best[ext=mp4]/best",
            "-o", output_path,
            "--max-downloads", "1",
            "--no-playlist",
            "--quiet",
            "--no-warnings"
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
            if result.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 5000:
                downloaded_clips.append(output_path)
                print(f"yt-dlp succeeded for clip {i+1}")
                success = True
        except Exception as e:
            print(f"yt-dlp notice: {e}")
            
        # --- Engine 2: Pexels API Fallback ---
        if not success and pexels_api_key:
            print(f"yt-dlp blocked. Falling back to Pexels API for query: {query}")
            try:
                headers = {"Authorization": pexels_api_key}
                clean_query = "gaming action motion background" if "roblox" in query.lower() or "blox" in query.lower() else query
                
                pexels_url = f"[https://api.pexels.com/videos/search?query=](https://api.pexels.com/videos/search?query=){requests.utils.quote(clean_query)}&per_page=1&orientation=portrait"
                
                response = requests.get(pexels_url, headers=headers, timeout=15)
                data = response.json()
                videos = data.get("videos", [])
                if videos:
                    video_files = videos[0].get("video_files", [])
                    download_url = None
                    for vf in video_files:
                        if vf.get("file_type") == "video/mp4":
                            download_url = vf.get("link")
                            break
                    if download_url:
                        urllib.request.urlretrieve(download_url, output_path)
                        if os.path.exists(output_path) and os.path.getsize(output_path) > 5000:
                            downloaded_clips.append(output_path)
                            print(f"Pexels API successfully downloaded clip {i+1}")
                            success = True
            except Exception as pex_err:
                print(f"Pexels API fallback error: {pex_err}")
                
        # --- Emergency Fallback ---
        if not success:
            print(f"Creating local motion background fallback for clip {i+1}")
            try:
                fb_clip = ColorClip(size=(1080, 1920), color=(15, 18, 30), duration=10)
                fb_clip.write_videofile(output_path, fps=24, codec="libx264", audio=False, logger=None)
                downloaded_clips.append(output_path)
            except Exception:
                pass
                
    return downloaded_clips

# ==========================================
# 3. DYNAMIC MOTION ASSEMBLY & EDITING
# ==========================================
def assemble_video(script, clip_paths):
    print("--- [Step 4/5] Assembling Video with Dynamic Zoom Motion ---")
    
    voice_clip = AudioFileClip("voiceover.mp3")
    target_duration = voice_clip.duration
    
    sentences = [s.strip() for s in script.replace("!", ".").replace("?", ".").split(".") if s.strip()]
    total_words = sum(len(s.split()) for s in sentences) or 1
    
    if not clip_paths:
        fallback_path = os.path.join("motion_templates", "emergency_fallback.mp4")
        os.makedirs("motion_templates", exist_ok=True)
        fb_clip = ColorClip(size=(1080, 1920), color=(15, 18, 30), duration=10)
        fb_clip.write_videofile(fallback_path, fps=24, codec="libx264", audio=False, logger=None)
        clip_paths = [fallback_path]

    video_segments = []
    caption_clips = []
    current_time = 0.0
    
    clip_index = 0
    for i, sentence in enumerate(sentences):
        sentence_words = len(sentence.split())
        
