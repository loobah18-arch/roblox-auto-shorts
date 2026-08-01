import os
import random
import time
import requests
import asyncio
import edge_tts
from PIL import Image
from moviepy.editor import VideoFileClip, AudioFileClip, CompositeVideoClip, CompositeAudioClip, TextClip
import moviepy.video.fx.all as vfx
from groq import Groq
import google.auth.transport.requests
import google.oauth2.credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ==========================================
# MULTI-KEY ROTATION CONFIGURATION (3 KEYS)
# ==========================================
RAPIDAPI_HOST = "viggle-ai-api-unofficial.p.rapidapi.com"
MIX_ENDPOINT = f"https://{RAPIDAPI_HOST}/v1/viggle/mix"
RESULT_ENDPOINT = f"https://{RAPIDAPI_HOST}/v1/viggle/job-results"

def get_all_api_keys():
    """Gathers all available RapidAPI keys (Key 1, 2, and 3) from environment variables."""
    available_keys = []
    for i in range(1, 4):  # Checks RAPIDAPI_KEY_1 through RAPIDAPI_KEY_3
        key = os.getenv(f"RAPIDAPI_KEY_{i}")
        if key:
            available_keys.append(key)
            
    single_key = os.getenv("RAPIDAPI_KEY")
    if single_key and not available_keys:
        available_keys.append(single_key)
        
    if not available_keys:
        raise Exception("Fatal: No RapidAPI keys found in environment variables!")
        
    random.shuffle(available_keys)
    return available_keys

# ==========================================
# 1. INFINITE STORY GENERATION
# ==========================================
def generate_infinite_script():
    """Generates an infinite story script using Groq's 70B model."""
    print("--- [Step 1/5] Generating Next Chapter via Groq Llama 3.3 70B ---")
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
    print("--- [Step 2/5] Generating Voiceover Audio ---")
    communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural", rate="+10%")
    await communicate.save(output_filename)
    print(f"Voiceover saved to {output_filename}\n")

# ==========================================
# 2. VIGGLE AI 3D MOTION TRANSFER WITH COMPRESSION & AUTO-FALLBACK
# ==========================================
def trigger_viggle_render():
    """Compresses assets, selects a motion template, and maps the character using Viggle API with failover."""
    print("--- [Step 3/5] Triggering Viggle AI 3D Motion Rendering ---")
    
    char_path = "assets/character.png"
    motion_dir = "motion_templates"
    
    if not os.path.exists(char_path):
        raise Exception("Missing 'assets/character.png' image file!")
        
    if not os.path.exists(motion_dir):
        os.makedirs(motion_dir, exist_ok=True)
        raise Exception(f"Missing '{motion_dir}' folder. Add at least one MP4 motion template!")
        
    templates = [f for f in os.listdir(motion_dir) if f.endswith('.mp4')]
    if not templates:
        raise Exception(f"No MP4 templates found in '{motion_dir}'!")
        
    chosen_template = os.path.join(motion_dir, random.choice(templates))
    print(f"Selected Motion Template: {chosen_template}")
    
    # AUTO-COMPRESS CHARACTER IMAGE
    compressed_char_path = "temp_character.png"
    img = Image.open(char_path)
    img.thumbnail((720, 720))
    img.save(compressed_char_path, "PNG")
    
    # AUTO-COMPRESS & RESIZE MOTION TEMPLATE VIDEO
    compressed_template_path = "temp_motion.mp4"
    print("Compressing motion template for API payload limits...")
    vid_clip = VideoFileClip(chosen_template)
    if vid_clip.duration > 12:
        vid_clip = vid_clip.subclip(0, 12)
    vid_resized = vid_clip.resize(height=720)
    vid_resized.write_videofile(
        compressed_template_path, fps=24, codec="libx264", audio_codec="aac", 
        preset="ultrafast", bitrate="800k", logger=None
    )
    vid_clip.close()
    vid_resized.close()

    available_keys = get_all_api_keys()
    job_id = None
    working_key = None
    
    for idx, key in enumerate(available_keys):
        headers = {
            "x-rapidapi-key": key,
            "x-rapidapi-host": RAPIDAPI_HOST
        }
        try:
            print(f"Attempting request with RapidAPI Key slot #{idx + 1}...")
            with open(compressed_char_path, 'rb') as img_file, open(compressed_template_path, 'rb') as vid_file:
                files = {
                    'image_file': ('character.png', img_file, 'image/png'),
                    'video_file': ('motion.mp4', vid_file, 'video/mp4')
                }
                response = requests.post(
                    MIX_ENDPOINT, 
                    headers=headers, 
                    files=files
                )
                
                if response.status_code == 429:
                    print(f"Key slot #{idx + 1} quota exhausted (429). Falling back to next key...")
                    continue
                
                if response.status_code != 200:
                    print(f"API Error Response: {response.text}")
                    
                response.raise_for_status()
                data = response.json()
                job_id = data.get("job_id")
                working_key = key
                print(f"Success with Key slot #{idx + 1}! Job ID: {job_id}")
                break
                
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                print(f"Key slot #{idx + 1} quota exhausted (429). Falling back to next key...")
                continue
            raise e
            
    # Cleanup temporary compressed files
    if os.path.exists(compressed_char_path):
        os.remove(compressed_char_path)
    if os.path.exists(compressed_template_path):
        os.remove(compressed_template_path)
        
    if not job_id or not working_key:
        raise Exception("Fatal: All RapidAPI keys have exceeded their quotas or failed!")
        
    headers = {
        "x-rapidapi-key": working_key,
        "x-rapidapi-host": RAPIDAPI_HOST
    }
    
    print("Polling for render completion...")
    while True:
        res = requests.post(RESULT_ENDPOINT, headers=headers, json={"job_id": job_id})
        if res.status_code != 200:
            print(f"Polling Error Response: {res.text}")
        res.raise_for_status()
        data = res.json()
        
        status = data.get("status")
        completed = data.get("completed", False)
        video_url = data.get("video_url")
        
        if (status == "success" or completed) and video_url:
            print("Render complete! Downloading AI 3D video...")
            vid_res = requests.get(video_url)
            vid_res.raise_for_status()
            
            output_path = "viggle_raw.mp4"
            with open(output_path, 'wb') as f:
                f.write(vid_res.content)
            print("Successfully saved viggle_raw.mp4\n")
            return output_path
            
        elif status in ["failed", "error"]:
            raise Exception(f"Viggle processing failed: {data}")
            
        print("Status: Processing... Waiting 15 seconds.")
        time.sleep(15)

# ==========================================
# 3. VIDEO ASSEMBLY (CAPTIONS & LOOPING)
# ==========================================
def assemble_video(script, viggle_video_path):
    print("--- [Step 4/5] Assembling Final MP4 Video ---")
    
    voice_clip = AudioFileClip("voiceover.mp3")
    target_duration = voice_clip.duration
    
    base_video = VideoFileClip(viggle_video_path).resize((1080, 1920))
    looped_video = vfx.loop(base_video, duration=target_duration)
    
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
        audio_codec="aac", threads=2, preset="ultrafast"
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
            "description": f"{script_snippet}\n\n#Shorts #Roblox #BloxFruits #Animation",
            "tags": ["Roblox", "BloxFruits", "Shorts", "Animation", "3D"],
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
    print("=== Starting 3D YouTube Shorts Automation Pipeline ===\n")
    
    script = generate_infinite_script()
    asyncio.run(generate_voiceover(script, "voiceover.mp3"))
    viggle_output = trigger_viggle_render()
    assemble_video(script, viggle_output)
    upload_to_youtube(script)
    
    print("=== Pipeline Complete! 3D Short is Live. ===")

if __name__ == "__main__":
    main()
