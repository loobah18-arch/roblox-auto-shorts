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

from moviepy.editor import VideoFileClip, ImageClip, CompositeVideoClip, AudioFileClip, CompositeAudioClip, TextClip, concatenate_videoclips, concatenate_audioclips, ColorClip
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

def get_safe_url(service_type):
    """Builds URLs safely at runtime using character lists to bypass parser injection."""
    if service_type == "google_token":
        return "".join(['h', 't', 't', 'p', 's', ':', '/', '/', 'o', 'a', 'u', 't', 'h', '2', '.', 'g', 'o', 'o', 'g', 'l', 'e', 'a', 'p', 'i', 's', '.', 'c', 'o', 'm', '/', 't', 'o', 'k', 'e', 'n'])
    elif service_type == "youtube_short":
        return "".join(['h', 't', 't', 'p', 's', ':', '/', '/', 'y', 'o', 'u', 't', 'u', 'b', 'e', '.', 'c', 'o', 'm', '/', 's', 'h', 'o', 'r', 't', 's', '/'])
    return ""

# ==========================================
# 1. GROQ SCENE-BY-SCENE DIRECTOR & MEMORY
# ==========================================
def generate_storyboard():
    """Generates structured scenes (narration + precise visual query) and maintains character continuity via Groq."""
    print("--- [Step 1/5] Groq Scene-by-Scene Directing & Character Memory ---")
    api_key = clean_env(os.getenv("GROQ_API_KEY"))
    if not api_key:
        raise Exception("Missing GROQ_API_KEY environment variable!")
        
    client = Groq(api_key=api_key)
    
    history_file = "story_memory.txt"
    bible_file = "character_bible.json"
    
    previous_context = "This is Episode 1 of the saga. Start with a massive, mind-breaking hook about Roblox Blox Fruits."
    character_context = "{}"

    if os.path.exists(history_file):
        with open(history_file, "r") as f:
            content = f.read().strip()
            if content:
                previous_context = content
                
    if os.path.exists(bible_file):
        with open(bible_file, "r") as f:
            bible_content = f.read().strip()
            if bible_content:
                character_context = bible_content

    prompt = f"""
    You are an unhinged, viral AI director creating an infinite, serialized epic saga about Roblox Blox Fruits or Jujutsu Zero for YouTube Shorts.
    
    PREVIOUS EPISODE CONTEXT:
    {previous_context}
    
    CURRENT CHARACTER BIBLE (Features, Clothes, Personality):
    {character_context}
    
    YOUR TASK:
    1. Write the NEXT immediate part of this story split into exactly 4 detailed sequential scenes. Total word count across all scenes should be around 130-150 words. End on a massive cliffhanger.
    2. For EACH scene, provide a highly specific search query describing the exact visual gameplay or motion background that matches that specific sentence.
    3. UPDATE THE CHARACTER BIBLE! If a character changes clothes or gets a power-up, update their traits. Otherwise, carry current traits forward.
    
    You MUST output your response strictly as a JSON object with this exact structure, with no markdown formatting around it (no ```json):
    {{
      "title": "Catchy Short Title",
      "scenes": [
        {{
          "narration": "Script line for scene 1...",
          "query": "Roblox Blox Fruits dough awakening showcase gameplay",
          "duration": 10
        }},
        {{
          "narration": "Script line for scene 2...",
          "query": "Roblox Jujutsu Zero domain expansion combat",
          "duration": 10
        }},
        {{
          "narration": "Script line for scene 3...",
          "query": "Roblox Blox Fruits max level PVP bounty hunt",
          "duration": 10
        }},
        {{
          "narration": "Script line for scene 4...",
          "query": "Roblox funny glitch meme moment cinematic",
          "duration": 10
        }}
      ],
      "character_bible": {{
        "CharacterName1": {{
          "facial_features": "Description of face...",
          "clothes": "Current outfit...",
          "personality": "Core traits..."
        }}
      }}
    }}
    """
    
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1000,
        temperature=0.9
    )
    
    raw_response = response.choices[0].message.content.strip()
    
    if raw_response.startswith("```"):
        raw_response = raw_response.split("```")[1]
        if raw_response.startswith("json"):
            raw_response = raw_response[4:]
    raw_response = raw_response.strip()
    
    data = json.loads(raw_response)
    
    full_script_text = " ".join([scene["narration"] for scene in data["scenes"]])
    with open(history_file, "w") as f:
        f.write(full_script_text)
        
    with open(bible_file, "w") as f:
        json.dump(data.get("character_bible", {}), f, indent=4)
        
    print(f"🎬 Story Title: {data.get('title')}\n")
    print(f"📌 Generated {len(data['scenes'])} Structured Scenes successfully.\n")
    
    return data

async def generate_scene_voiceover(text, output_filename):
    """Generates an Edge-TTS voiceover file for an individual scene."""
    communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural", rate="+10%")
    await communicate.save(output_filename)

# ==========================================
# 2. TRIPLE-ENGINE CLIP FETCHING PER SCENE
# ==========================================
def fetch_clip_for_query(query, clip_filename, youtube_client):
    """Searches via YouTube API, downloads with yt-dlp, falling back to Pollinations AI if blocked."""
    templates_dir = "motion_templates"
    os.makedirs(templates_dir, exist_ok=True)
    output_path = os.path.join(templates_dir, clip_filename)
    success = False
    yt_dlp_target = None
    
    # --- Engine 1: YouTube Data API Search ---
    if youtube_client:
        print(f"🔎 Searching YouTube Data API for: '{query}'")
        try:
            request = youtube_client.search().list(
                q=f"{query} roblox shorts",
                part="snippet",
                type="video",
                maxResults=1,
                videoDuration="short"
            )
            response = request.execute()
            items = response.get("items", [])
            
            if items:
                video_id = items[0]["id"]["videoId"]
                yt_dlp_target = f"[https://www.youtube.com/watch?v=](https://www.youtube.com/watch?v=){video_id}"
        except Exception as e:
            pass
    
    if not yt_dlp_target:
        yt_dlp_target = f"ytsearch1:{query} roblox shorts"
    
    # --- Engine 2: yt-dlp Download ---
    print(f"📥 Running yt-dlp -> Target: {yt_dlp_target}")
    cmd = [
        "yt-dlp",
        yt_dlp_target,
        "--extractor-args", "youtube:player_client=ios,web,android",
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
            print(f"✅ yt-dlp succeeded.")
            return output_path
    except Exception as e:
        print(f"⚠️ yt-dlp blocked or failed.")
        
    # --- Engine 3: Free AI Image Generation Fallback ---
    print(f"🔄 yt-dlp blocked. Falling back to Free AI Generation for scene...")
    try:
        clean_query = requests.utils.quote(f"Anime style {query} cinematic lighting")
        ai_image_url = f"[https://image.pollinations.ai/prompt/](https://image.pollinations.ai/prompt/){clean_query}?width=1080&height=1920&nologo=true"
        
        image_path = os.path.join(templates_dir, f"ai_{clip_filename}.jpg")
        urllib.request.urlretrieve(ai_image_url, image_path)
        
        if os.path.exists(image_path):
            img_clip = ImageClip(image_path).set_duration(10)
            img_clip.write_videofile(output_path, fps=24, codec="libx264", logger=None)
            if os.path.exists(output_path):
                print(f"✅ AI Generation fallback created clip successfully.")
                return output_path
    except Exception as ai_err:
        print(f"⚠️ AI Generation fallback error: {ai_err}")
        
    # --- Emergency Fallback (Dark Blue Screen) ---
    print(f"⚠️ All engines failed. Creating fallback background.")
    try:
        fb_clip = ColorClip(size=(1080, 1920), color=(15, 18, 30), duration=10)
        fb_clip.write_videofile(output_path, fps=24, codec="libx264", audio=False, logger=None)
        return output_path
    except Exception:
        return None

# ==========================================
# 3. SCENE-BY-SCENE ASSEMBLY & EDITING
# ==========================================
def assemble_storyboard(storyboard_data):
    print("--- [Step 3/5] Processing and Assembling Scenes ---")
    
    youtube_api_key = clean_env(os.getenv("YOUTUBE_API_KEY"))
    youtube_client = None
    if youtube_api_key:
        try:
            youtube_client = build('youtube', 'v3', developerKey=youtube_api_key, cache_discovery=False)
        except Exception:
            pass

    video_segments = []
    audio_segments = []
    
    templates_dir = "motion_templates"
    os.makedirs(templates_dir, exist_ok=True)
    for old_file in glob.glob(os.path.join(templates_dir, "*.mp4")):
        try:
            os.remove(old_file)
        except Exception:
            pass

    for idx, scene in enumerate(storyboard_data["scenes"]):
        narration = scene["narration"]
        query = scene["query"]
        print(f"\n🎬 Processing Scene {idx + 1}: '{query}'")
        
        audio_filename = f"scene_{idx + 1}.mp3"
        asyncio.run(generate_scene_voiceover(narration, audio_filename))
        scene_audio = AudioFileClip(audio_filename)
        dur = scene_audio.duration
        audio_segments.append(scene_audio)

        clip_path = fetch_clip_for_query(query, f"clip_{idx + 1}.mp4", youtube_client)
        
        try:
            sub_clip = VideoFileClip(clip_path)
            max_start = max(0, sub_clip.duration - dur)
            start_t = random.uniform(0, max_start) if max_start > 0 else 0
            end_t = min(start_t + dur, sub_clip.duration)
            snippet = sub_clip.subclip(start_t, end_t).resize(height=1920)
            
            if snippet.w > 1080:
                x_center = snippet.w / 2
                snippet = snippet.crop(x1=x_center - 540, x2=x_center + 540, y1=0, y2=1920)
            
            if idx % 2 == 0:
                snippet = snippet.resize(lambda t, d=dur: 1.0 + 0.12 * (t / d))
            else:
                snippet = snippet.resize(lambda t, d=dur: 1.12 - 0.12 * (t / d))
                
            snippet = snippet.set_duration(dur).set_audio(scene_audio)
        except Exception:
            snippet = ColorClip(size=(1080, 1920), color=(15, 18, 30), duration=dur).set_audio(scene_audio)
        
        try:
            txt_clip = TextClip(
                narration, font="Liberation-Sans", fontsize=55, color='yellow', 
                stroke_color='black', stroke_width=4, size=(950, None), method='caption'
            )
            txt_clip = txt_clip.set_start(0).set_duration(dur).set_position(('center', 1400))
            composite_scene = CompositeVideoClip([snippet, txt_clip])
        except Exception:
            composite_scene = snippet
            
        video_segments.append(composite_scene)

    print("\n--- [Step 4/5] Stitched Rendering Final MP4 ---")
    final_base_video = concatenate_videoclips(video_segments)
    
    bgm_folder = "bgm"
    if not os.path.exists(bgm_folder):
        os.makedirs(bgm_folder, exist_ok=True)
    mp3_files = [f for f in os.listdir(bgm_folder) if f.endswith('.mp3')]
    
    combined_voice = concatenate_audioclips(audio_segments) if len(audio_segments) > 1 else audio_segments[0]
    target_duration = combined_voice.duration

    if mp3_files:
        bg_music = AudioFileClip(os.path.join(bgm_folder, random.choice(mp3_files)))
        if bg_music.duration < target_duration:
            bg_music = vfx.loop(bg_music, duration=target_duration)
        else:
            bg_music = bg_music.subclip(0, target_duration)
        bg_music = bg_music.volumex(0.12)
        final_audio = CompositeAudioClip([combined_voice, bg_music])
    else:
        final_audio = combined_voice
        
    final_base_video = final_base_video.set_audio(final_audio)
    
    print("Rendering final dynamic story MP4...")
    final_base_video.write_videofile(
        "final_short.mp4", fps=24, codec="libx264", 
        audio_codec="aac", threads=2, preset="ultrafast", logger=None
    )
    print("✅ Video assembly complete: final_short.mp4 created.\n")

# ==========================================
# 4. YOUTUBE UPLOAD FUNCTION
# ==========================================
def upload_to_youtube(storyboard_data):
    print("--- [Step 5/5] Uploading to YouTube Channel as Short ---")
    
    client_id = clean_env(os.getenv("CLIENT_ID"))
    client_secret = clean_env(os.getenv("CLIENT_SECRET"))
    refresh_token = clean_env(os.getenv("REFRESH_TOKEN"))
    
    if not client_id or not client_secret or not refresh_token:
        print("🚨 ERROR: YouTube API secrets are missing or empty!")
        return

    try:
        token_uri_str = get_safe_url("google_token")
        
        credentials = google.oauth2.credentials.Credentials(
            None, refresh_token=refresh_token, token_uri=token_uri_str,
            client_id=client_id, client_secret=client_secret
        )
        
        youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
        title = storyboard_data.get("title", "Blox Fruits Madness!")
        first_scene_text = storyboard_data["scenes"][0]["narration"]
        
        body = {
            "snippet": {
                "title": f"{title} #Shorts",
                "description": f"{first_scene_text}\n\n#Shorts #Roblox #BloxFruits #Gaming",
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
                print(f"⏳ Uploading file: {int(status.progress() * 100)}%")
                
        base_short_url = get_safe_url("youtube_short")
        final_video_url = f"{base_short_url}{response.get('id')}"
        print(f"🎉 Upload Successful! Video ID: {response.get('id')}\nURL: {final_video_url}")
        
    except Exception as e:
        print(f"🚨 CRITICAL ERROR during YouTube Upload: {e}")
        raise e

# ==========================================
# 5. MAIN EXECUTION
# ==========================================
def main():
    print("=== Starting Scene-by-Scene Director Pipeline ===\n")
    
    storyboard_data = generate_storyboard()
    assemble_storyboard(storyboard_data)
    upload_to_youtube(storyboard_data)
    
    print("=== Pipeline Complete! Short is Live. ===")

if __name__ == "__main__":
    main()
