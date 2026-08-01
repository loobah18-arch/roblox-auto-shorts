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
                
                # Trick the markdown parser by replacing "hxxps" with "https" at runtime
                safe_pexels_url = f"hxxps://[api.pexels.com/videos/search?query=](https://api.pexels.com/videos/search?query=){requests.utils.quote(clean_query)}&per_page=1&orientation=portrait"
                pexels_url = safe_pexels_url.replace("hxxps", "https")
                
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
    
    print("Rendering final dynamic story MP4...")
    final_video.write_videofile(
        "final_short.mp4", fps=24, codec="libx264", 
        audio_codec="aac", threads=2, preset="ultrafast", logger=None
    )
    print("Video assembly complete: final_short.mp4 created.\n")

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
        print("ERROR: YouTube API secrets are missing or empty! Check your GitHub Repository Secrets.")
        return

    try:
        # Trick the markdown parser by replacing "hxxps" with "https" at runtime
        safe_token_uri = "hxxps://[oauth2.googleapis.com/token](https://oauth2.googleapis.com/token)".replace("hxxps", "https")
        
        credentials = google.oauth2.credentials.Credentials(
            None, refresh_token=refresh_token, token_uri=safe_token_uri,
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
                
        # Trick the markdown parser by replacing "hxxps" with "https" at runtime
        safe_youtube_url = f"hxxps://[youtube.com/shorts/](https://youtube.com/shorts/){response.get('id')}".replace("hxxps", "https")
        print(f"Upload Successful! Video ID: {response.get('id')}\nURL: {safe_youtube_url}")
        
    except Exception as e:
        print(f"CRITICAL ERROR during YouTube Upload: {e}")
        raise e

# ==========================================
# 5. MAIN EXECUTION
# ==========================================
def main():
    print("=== Starting Dual-Engine Director Pipeline ===\n")
    
    script, queries = generate_script_and_queries()
    asyncio.run(generate_voiceover(script, "voiceover.mp3"))
    clip_paths = fetch_dynamic_clips(queries)
    assemble_video(script, clip_paths)
    upload_to_youtube(script)
    
    print("=== Pipeline Complete! Short is Live. ===")

if __name__ == "__main__":
    main()
