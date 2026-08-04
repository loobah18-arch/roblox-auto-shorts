import os
import json
import random
import glob
import asyncio
import requests
import edge_tts
from groq import Groq
from moviepy.editor import *

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# --- CONFIGURATION ---
GAMES = [
    "Blox Fruits", 
    "Brookhaven", 
    "Adopt Me!", 
    "Murder Mystery 2", 
    "Tower of Hell"
]

def get_safe_filename(game_name):
    """Formats game name for file mapping (e.g., 'Adopt Me!' -> 'adopt_me')"""
    return game_name.lower().replace(" ", "_").replace("!", "")

# --- STATE & MEMORY MANAGEMENT ---
def load_game_state():
    if os.path.exists("game_state.json"):
        try:
            with open("game_state.json", "r") as f:
                state = json.load(f)
                if "current_index" not in state or "total_videos_run" not in state:
                    return {"current_index": 0, "total_videos_run": 1}
                return state
        except Exception:
            return {"current_index": 0, "total_videos_run": 1}
    return {"current_index": 0, "total_videos_run": 1}

def save_game_state(index, total_runs):
    with open("game_state.json", "w") as f:
        json.dump({"current_index": index, "total_videos_run": total_runs}, f, indent=4)

def get_story_memory(safe_game_name):
    filename = f"story_memory_{safe_game_name}.txt"
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return f.read()
    return "No previous memory. Start a brand new epic adventure."

def save_story_memory(safe_game_name, new_memory):
    filename = f"story_memory_{safe_game_name}.txt"
    with open(filename, "w") as f:
        f.write(new_memory)

def get_character_bible(safe_game_name):
    filename = f"character_bible_{safe_game_name}.json"
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return f.read() 
    return "No character bible found for this game."

# --- PIPELINE FUNCTIONS ---
def generate_script_and_images(game, memory, bible):
    """Integrates with Groq and Pollinations AI with dynamic multi-image correlation and Unreal Engine 5 styling."""
    print(f"Generating script for {game} using Groq...")
    client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    
    prompt = f"""
    Create an intense, cinematic 30-second YouTube Short script for Roblox {game} told in a commanding, epic voice.
    Previous Story Memory: {memory}
    Character Bible: {bible}
    
    Provide 5 distinct visual scene descriptions so the background imagery continuously correlates with the narrative progression.
    
    Output JSON strictly in this format:
    {{
        "voiceover": "Script text here",
        "new_memory": "Cliffhanger for tomorrow here",
        "image_prompts": ["Prompt 1", "Prompt 2", "Prompt 3", "Prompt 4", "Prompt 5"]
    }}
    """
    
    print("Fetching active models from Groq...")
    try:
        active_models_data = client.models.list().data
        valid_models = [
            m.id for m in active_models_data 
            if "llama" in m.id.lower() or "mixtral" in m.id.lower() or "qwen" in m.id.lower()
        ]
    except Exception as e:
        print(f"Failed to fetch model list, falling back to default. Error: {e}")
        valid_models = ["meta-llama/llama-4-scout-17b-16e-instruct", "llama-3.1-8b-instant", "openai/gpt-oss-20b"]

    response_data = None
    for model_id in valid_models:
        print(f"Attempting generation with model: {model_id}...")
        try:
            chat_completion = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=model_id,
                response_format={"type": "json_object"}
            )
            response_data = json.loads(chat_completion.choices[0].message.content)
            print(f"Success! Model {model_id} worked perfectly.")
            break  
        except Exception as e:
            print(f"Model {model_id} failed. Searching next... Error: {e}")
            continue  
            
    if not response_data:
        raise Exception("Fatal Error: Could not find any working Groq models.")
    
    audio_text = response_data.get("voiceover", "The journey continues...")
    new_memory = response_data.get("new_memory", "To be continued...")
    prompts = response_data.get("image_prompts", ["Roblox landscape"] * 5)
    
    image_paths = []
    print(f"Generating {len(prompts)} correlated Unreal Engine 5 visual assets via Pollinations AI...")
    style_modifier = ", Unreal Engine 5 render, hyper-realistic lighting, ray tracing, 8k resolution, cinematic composition, high-end heavy AI visual masterpiece, octane render"
    
    for i, img_prompt in enumerate(prompts):
        enhanced_prompt = f"{img_prompt}{style_modifier}"
        safe_prompt = requests.utils.quote(enhanced_prompt)
        url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1080&height=1920&nologo=true"
        
        response = requests.get(url)
        path = f"scene_{i}.jpg"
        with open(path, 'wb') as f:
            f.write(response.content)
        image_paths.append(path)
        
    return audio_text, new_memory, image_paths

def split_text_for_captions(text, words_per_chunk=3):
    """Splits text into compact chunks to mirror high-retention short form editing styles."""
    words = text.split()
    chunks = []
    for i in range(0, len(words), words_per_chunk):
        chunk = " ".join(words[i:i + words_per_chunk])
        if len(chunk) > 18:
            middle = len(chunk) // 2
            space_idx = chunk.rfind(' ', 0, middle)
            if space_idx != -1:
                chunk = chunk[:space_idx] + "\n" + chunk[space_idx+1:]
        chunks.append(chunk)
    return chunks

def render_video(audio_path, image_paths, text_chunks):
    """MoviePy assembly featuring precise lower-middle positioning and synchronized word chunk rendering."""
    print("Assembling video with MoviePy...")
    
    vo_clip = AudioFileClip(audio_path)
    video_duration = vo_clip.duration

    bgm_files = glob.glob("bgm/*.mp3")
    if bgm_files:
        selected_bgm = random.choice(bgm_files)
        bgm_clip = AudioFileClip(selected_bgm).fx(afx.volumex, 0.1) 
        bgm_clip = bgm_clip.set_duration(video_duration)
        final_audio = CompositeAudioClip([vo_clip, bgm_clip])
    else:
        final_audio = vo_clip

    # Distribute correlated background images evenly across the timeline
    img_duration = video_duration / len(image_paths)
    image_clips = [ImageClip(img).set_duration(img_duration) for img in image_paths]
    final_video = concatenate_videoclips(image_clips, method="compose")

    # Precise chunk timing mapping
    total_words = sum(len(chunk.split()) for chunk in text_chunks)
    text_clips = []
    current_time = 0.0
    
    for chunk in text_chunks:
        word_count = len(chunk.split())
        chunk_duration = (word_count / total_words) * video_duration
        
        txt_clip = TextClip(
            chunk, 
            fontsize=65, 
            color='yellow', 
            font='Liberation-Sans-Bold', 
            stroke_color='black', 
            stroke_width=4
        )
        # Positioned cleanly in the lower-middle block of the screen
        txt_clip = txt_clip.set_position(('center', 0.68), relative=True).set_duration(chunk_duration).set_start(current_time)
        text_clips.append(txt_clip)
        current_time += chunk_duration

    final_video = CompositeVideoClip([final_video] + text_clips)
    final_video = final_video.set_audio(final_audio)
    
    output_path = "final_short.mp4"
    final_video.write_videofile(output_path, fps=24, codec="libx264", audio_codec="aac")
    print("Video rendered successfully.")
    return output_path

def upload_to_youtube(video_path, game_name, part_number):
    """Handles authenticated upload using GitHub Secrets Refresh Token with clean titles omitting 'AI Story'."""
    print(f"Preparing to upload {video_path} to YouTube for: {game_name} Part {part_number}...")
    
    client_id = os.environ.get("CLIENT_ID")
    client_secret = os.environ.get("CLIENT_SECRET")
    refresh_token = os.environ.get("REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        raise Exception("CRITICAL: Missing YouTube API credentials in environment variables.")

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret
    )

    youtube = build('youtube', 'v3', credentials=creds)

    safe_name = get_safe_filename(game_name)
    title = f"{game_name} - Part {part_number} #roblox #shorts #{safe_name}"
    description = f"The saga continues in {game_name} Part {part_number}. Like and subscribe for the next chapter!"
    
    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': ['roblox', game_name, 'shorts', 'robloxshorts', safe_name],
            'categoryId': '20' 
        },
        'status': {
            'privacyStatus': 'public',
            'selfDeclaredMadeForKids': False
        }
    }

    print("Initiating YouTube upload stream...")
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype='video/mp4')

    request = youtube.videos().insert(
        part=','.join(body.keys()),
        body=body,
        media_body=media
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Uploaded {int(status.progress() * 100)}%...")

    print(f"SUCCESS! Video uploaded perfectly. YouTube Video ID: {response['id']}")

# --- MAIN EXECUTION ---
async def main():
    state = load_game_state()
    current_index = state.get("current_index", 0)
    total_runs = state.get("total_videos_run", 1)
    
    current_game = GAMES[current_index]
    safe_game_name = get_safe_filename(current_game)
    print(f"--- Starting Daily Pipeline for: {current_game} (Part {total_runs}) ---")

    memory = get_story_memory(safe_game_name)
    bible = get_character_bible(safe_game_name)

    audio_text, new_memory, image_paths = generate_script_and_images(current_game, memory, bible)
    save_story_memory(safe_game_name, new_memory)

    print("Generating Deep Voiceover via Edge-TTS...")
    audio_path = "vo.mp3"
    
    # Stable deep narrator config using ChristopherNeural
    communicate = edge_tts.Communicate(audio_text, "en-US-ChristopherNeural")
    await communicate.save(audio_path)

    text_chunks = split_text_for_captions(audio_text, words_per_chunk=3)
    final_video_path = render_video(audio_path, image_paths, text_chunks)

    upload_to_youtube(final_video_path, current_game, total_runs)

    next_index = (current_index + 1) % len(GAMES)
    next_runs = total_runs + 1
    save_game_state(next_index, next_runs)
    print(f"Pipeline complete. Next game in rotation: {GAMES[next_index]}")

if __name__ == "__main__":
    asyncio.run(main())
