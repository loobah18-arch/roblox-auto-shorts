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

def get_safe_url(service_type):
    """Builds URLs safely at runtime using character lists to bypass parser injection."""
    if service_type == "google_token":
        return "".join(['h', 't', 't', 'p', 's', ':', '/', '/', 'o', 'a', 'u', 't', 'h', '2', '.', 'g', 'o', 'o', 'g', 'l', 'e', 'a', 'p', 'i', 's', '.', 'c', 'o', 'm', '/', 't', 'o', 'k', 'e', 'n'])
    elif service_type == "youtube_short":
        return "".join(['h', 't', 't', 'p', 's', ':', '/', '/', 'y', 'o', 'u', 't', 'u', 'b', 'e', '.', 'c', 'o', 'm', '/', 's', 'h', 'o', 'r', 't', 's', '/'])
    return ""

# ==========================================
# 1. GROQ SCRIPT, QUERIES & CHARACTER MEMORY
# ==========================================
def generate_script_and_queries():
    """Generates the story script, search queries, and maintains character continuity via Groq."""
    print("--- [Step 1/5] Groq Directing Script, Queries, and Character Memory ---")
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
    You are an unhinged, viral AI director creating an infinite, serialized epic saga about Roblox Blox Fruits for YouTube Shorts.
    
    PREVIOUS EPISODE CONTEXT:
    {previous_context}
    
    CURRENT CHARACTER BIBLE (Features, Clothes, Personality):
    {character_context}
    
    YOUR TASK:
    1. Write the NEXT immediate part of this story (between 130 and 150 words). Absurd, catchy, meme energy, ending on a cliffhanger. Use the Character Bible to keep descriptions consistent!
    2. Generate exactly 5 distinct, high-energy search queries to find vertical gameplay or aesthetic motion clips that visually match the action.
    3. UPDATE THE CHARACTER BIBLE! If a character changes clothes, gets a scar, etc., update their traits. Otherwise, carry current traits forward.
    
    You MUST output your response strictly as a JSON object with this exact structure, with no markdown formatting around it (no ```json):
    {{
      "script": "The full story text here...",
      "queries": [
        "query 1", "query 2", "query 3", "query 4", "query 5"
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
        max_tokens=800,
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
    updated_bible = data.get("character_bible", {})
    
    with open(history_file, "w") as f:
        f.write(script)
        
    with open(bible_file, "w") as f:
        json.dump(updated_bible, f, indent=4)
        
    print(f"Generated Script:\n{script}\n")
    print(f"Generated Dynamic Queries: {queries}\n")
    print(f"Updated Character Bible: {json.dumps(updated_bible, indent=2)}\n")
    
    return script, queries

async def generate_voiceover(text, output_filename):
    """Generates an Edge-TTS voiceover file."""
    print("--- [Step 2/5] Generating Voiceover Audio ---")
    communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural", rate="+10%")
    await communicate.save(output_filename)
    print(f"Voiceover saved to {output_filename}\n")

# ==========================================
# 2. TRIPLE-ENGINE CLIP FETCHING (YouTube API -> yt-dlp -> Free AI Gen)
# ==========================================
def fetch_dynamic_clips(queries):
    """Searches via YouTube API, downloads with yt-dlp, falling back to Free AI Image Gen if blocked."""
    print("--- [Step 3/5] Triple-Engine Clip Fetching (YouTube API + yt-dlp + Free AI Gen) ---")
    templates_dir = "motion_templates"
    os.makedirs(templates_dir, exist_ok=True)
    
    for old_file in glob.glob(os.path.join(templates_dir, "*.mp4")):
        try:
            os.remove(old_file)
        except Exception:
            pass
            
    downloaded_clips = []
    youtube_api_key = clean_env(os.getenv("YOUTUBE_API_KEY"))
    
    youtube_client = None
    if youtube_api_key:
        try:
            youtube_client = build('youtube', 'v3', developerKey=youtube_api_key, cache_discovery=False)
        except Exception as e:
            print(f"⚠️ Warning: Could not build YouTube Data API client: {e}")

    for i, query in enumerate(queries):
        clip_filename = f"clip_{i+1}.mp4"
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
        print(f"📥 Running yt-dlp for clip {i+1} -> Target: {yt_dlp_target}")
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
                downloaded_clips.append(output_path)
                print(f"✅ yt-dlp succeeded for clip {i+1}")
                success = True
        except Exception as e:
            print(f"⚠️ yt-dlp blocked or failed.")
            
        # --- Engine 3: Free AI Image Generation Fallback (Bulletproof) ---
        if not success:
            print(f"🔄 yt-dlp blocked. Falling back to Free AI Generation for clip {i+1}...")
            try:
                # Use Pollinations AI (Free, no API key required) to generate an image based on the query
                clean_query = requests.utils.quote(f"Anime style {query} cinematic lighting")
                ai_image_url = f"[https://image.pollinations.ai/prompt/](https://image.pollinations.ai/prompt/){clean_query}?width=1080&height=1920&nologo=true"
                
                image_path = os.path.join(templates_dir, f"ai_img_{i+1}.jpg")
                urllib.request.urlretrieve(ai_image_url, image_path)
                
                if os.path.exists(image_path):
                    # Convert the generated image into a 10-second video clip
                    img_clip = ImageClip(image_path).set_duration(10)
                    img_clip.write_videofile(output_path, fps=24, codec="libx264", logger=None)
                    
                    if os.path.exists(output_path):
                        downloaded_clips.append(output_path)
                        print(f"✅ AI Generation successfully created fallback clip {i+1}")
                        success = True
            except Exception as ai_err:
                print(f"⚠️ AI Generation fallback error: {ai_err}")
                
        # --- Emergency Fallback (The Dark Blue Screen) ---
        if not success:
            print(f"⚠️ All engines failed. Creating dark blue motion background for clip {i+1}")
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
    
    sentences = [s.strip() for s in script.replace("!", ".").replace("?", ".").replace(",", ".").split(".") if s.strip() and len(s.strip()) > 1]
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
        dur = max((sentence_words / total_words) * target_duration, 1.5)
        
        current_clip_path = clip_paths[clip_index % len(clip_paths)]
        clip_index += 1
        
        try:
            sub_clip = VideoFileClip(current_clip_path)
            max_start = max(0, sub_clip.duration - dur)
            start_t = random.uniform(0, max_start) if max_start > 0 else 0
            end_t = min(start_t + dur, sub_clip.duration)
            snippet = sub_clip.subclip(start_t, end_t).resize(height=1920)
            if snippet.w > 1080:
                x_center = snippet.w / 2
                snippet = snippet.crop(x1=x_center - 540, x2=x_center + 540, y1=0, y2=1920)
            
            c_dur = snippet.duration
            if i % 2 == 0:
                snippet = snippet.resize(lambda t, d=c_dur: 1.0 + 0.12 * (t / d))
            else:
                snippet = snippet.resize(lambda t, d=c_dur: 1.12 - 0.12 * (t / d))
                
            video_segments.append(snippet)
        except Exception:
            fallback_bg = ColorClip(size=(1080, 1920), color=(15, 18, 30), duration=dur)
            video_segments.append(fallback_bg)
        
        try:
            txt_clip = TextClip(
                sentence, font="Liberation-Sans", fontsize=60, color='yellow', 
                stroke_color='black', stroke_width=4, size=(950, None), method='caption'
            )
            txt_clip = txt_clip.set_start(current_time).set_duration(dur).set_position(('center', 1400))
            caption_clips.append(txt_clip)
        except Exception:
            pass
            
        current_time += dur

    final_base_video = concatenate_videoclips(video_segments)
    
    if final_base_video.duration > target_duration:
        final_base_video = final_base_video.subclip(0, target_duration)
    
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
        
    final_base_video = final_base_video.set_audio(final_audio)
    final_video = CompositeVideoClip([final_base_video] + caption_clips)
    
    print("🎬 Rendering final dynamic story MP4...")
    final_video.write_videofile(
        "final_short.mp4", fps=24, codec="libx264", 
        audio_codec="aac", threads=2, preset="ultrafast", logger=None
    )
    print("✅ Video assembly complete: final_short.mp4 created.\n")

# ==========================================
# 4. YOUTUBE UPLOAD FUNCTION (WITH DEBUG & TRACE)
# ==========================================
def upload_to_youtube(script_snippet):
    print("--- [Step 5/5] Uploading to YouTube Channel as Short ---")
    
    client_id = clean_env(os.getenv("CLIENT_ID"))
    client_secret = clean_env(os.getenv("CLIENT_SECRET"))
    refresh_token = clean_env(os.getenv("REFRESH_TOKEN"))
    
    print(f"Debug Check -> CLIENT_ID loaded: {bool(client_id)} (Length: {len(client_id)})")
    print(f"Debug Check -> CLIENT_SECRET loaded: {bool(client_secret)} (Length: {len(client_secret)})")
    print(f"Debug Check -> REFRESH_TOKEN loaded: {bool(refresh_token)} (Length: {len(refresh_token)})")
    
    if not client_id or not client_secret or not refresh_token:
        print("🚨 ERROR: YouTube API secrets are missing or empty! Check your GitHub Repository Secrets.")
        return

    try:
        token_uri_str = get_safe_url("google_token")
        
        credentials = google.oauth2.credentials.Credentials(
            None, refresh_token=refresh_token, token_uri=token_uri_str,
            client_id=client_id, client_secret=client_secret
        )
        
        youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
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
    print("=== Starting Triple-Engine Director Pipeline ===\n")
    
    script, queries = generate_script_and_queries()
    asyncio.run(generate_voiceover(script, "voiceover.mp3"))
    clip_paths = fetch_dynamic_clips(queries)
    assemble_video(script, clip_paths)
    upload_to_youtube(script)
    
    print("=== Pipeline Complete! Short is Live. ===")

if __name__ == "__main__":
    main()
