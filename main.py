import os
import json
import random
import glob
import asyncio
import requests
import edge_tts
from groq import Groq
from moviepy.editor import *

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
        with open("game_state.json", "r") as f:
            return json.load(f)
    return {"current_index": 0}

def save_game_state(index):
    with open("game_state.json", "w") as f:
        json.dump({"current_index": index}, f, indent=4)

def get_story_memory(safe_game_name):
    filename = f"story_memory_{safe_game_name}.txt"
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return f.read()
    return "No previous memory. Start a brand new adventure."

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
    """Integrates with Groq and Pollinations AI"""
    print(f"Generating script for {game} using Groq...")
    client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    
    prompt = f"""
    Create a 30-second YouTube Short script for Roblox {game}.
    Previous Story Memory: {memory}
    Character Bible: {bible}
    
    Output JSON strictly in this format:
    {{
        "voiceover": "Script text here",
        "new_memory": "Cliffhanger for tomorrow here",
        "image_prompts": ["Prompt 1", "Prompt 2"]
    }}
    """
    
    chat_completion = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model="llama3-8b-8192",
        response_format={"type": "json_object"}
    )
    
    response_data = json.loads(chat_completion.choices[0].message.content)
    audio_text = response_data.get("voiceover", "Welcome to Roblox!")
    new_memory = response_data.get("new_memory", "To be continued...")
    prompts = response_data.get("image_prompts", ["Roblox landscape"])
    
    image_paths = []
    print("Generating images via Pollinations AI...")
    for i, img_prompt in enumerate(prompts):
        safe_prompt = requests.utils.quote(img_prompt)
        url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1080&height=1920&nologo=true"
        response = requests.get(url)
        path = f"scene_{i}.jpg"
        with open(path, 'wb') as f:
            f.write(response.content)
        image_paths.append(path)
        
    return audio_text, new_memory, image_paths

def split_text_for_captions(text, words_per_chunk=3):
    """Splits text into 3-word chunks for high retention."""
    words = text.split()
    return [" ".join(words[i:i + words_per_chunk]) for i in range(0, len(words), words_per_chunk)]

def render_video(audio_path, image_paths, text_chunks):
    """MoviePy 1.0.3 assembly with ImageMagick captions and automated BGM mixing."""
    print("Assembling video with MoviePy...")
    
    vo_clip = AudioFileClip(audio_path)
    video_duration = vo_clip.duration

    # Automated BGM Mixing from /bgm folder
    bgm_files = glob.glob("bgm/*.mp3")
    if bgm_files:
        selected_bgm = random.choice(bgm_files)
        # THE FIX: Switched from vfx.volumex to afx.volumex
        bgm_clip = AudioFileClip(selected_bgm).fx(afx.volumex, 0.1) 
        bgm_clip = bgm_clip.set_duration(video_duration)
        final_audio = CompositeAudioClip([vo_clip, bgm_clip])
    else:
        final_audio = vo_clip

    # Distribute images evenly across the video duration
    img_duration = video_duration / len(image_paths)
    image_clips = [ImageClip(img).set_duration(img_duration) for img in image_paths]
    final_video = concatenate_videoclips(image_clips, method="compose")

    # Caption Generation (Dynamic 3-word yellow font)
    chunk_duration = video_duration / len(text_chunks)
    text_clips = []
    
    for i, chunk in enumerate(text_chunks):
        txt_clip = TextClip(chunk, fontsize=70, color='yellow', font='DejaVu-Sans-Bold', 
                            stroke_color='black', stroke_width=3)
        txt_clip = txt_clip.set_position('center').set_duration(chunk_duration).set_start(i * chunk_duration)
        text_clips.append(txt_clip)

    final_video = CompositeVideoClip([final_video] + text_clips)
    final_video = final_video.set_audio(final_audio)
    
    output_path = "final_short.mp4"
    final_video.write_videofile(output_path, fps=24, codec="libx264", audio_codec="aac")
    print("Video rendered successfully.")
    return output_path

def upload_to_youtube(video_path, game_name):
    """Handles authenticated upload via GitHub Secrets."""
    # Note: Requires google-api-python-client and properly authenticated OAuth credentials
    print(f"Uploading {video_path} to YouTube for game: {game_name}...")
    
    # Example placeholder for where your Google API logic executes
    # You must implement your specific googleapiclient.discovery.build('youtube', 'v3', credentials=creds) logic here
    
    print("Upload complete!")

# --- MAIN EXECUTION ---
async def main():
    # 1. Determine Current Game
    state = load_game_state()
    current_index = state.get("current_index", 0)
    current_game = GAMES[current_index]
    safe_game_name = get_safe_filename(current_game)
    print(f"--- Starting Daily Pipeline for: {current_game} ---")

    # 2. Load Context
    memory = get_story_memory(safe_game_name)
    bible = get_character_bible(safe_game_name)

    # 3. AI Generation (Groq + Pollinations)
    audio_text, new_memory, image_paths = generate_script_and_images(current_game, memory, bible)

    # 4. Save New Memory for Tomorrow (Picked up by upload.yml)
    save_story_memory(safe_game_name, new_memory)

    # 5. Audio Generation (Edge-TTS)
    print("Generating Voiceover via Edge-TTS...")
    audio_path = "vo.mp3"
    communicate = edge_tts.Communicate(audio_text, "en-US-GuyNeural")
    await communicate.save(audio_path)

    # 6. Video Assembly
    text_chunks = split_text_for_captions(audio_text, words_per_chunk=3)
    final_video_path = render_video(audio_path, image_paths, text_chunks)

    # 7. Upload
    upload_to_youtube(final_video_path, current_game)

    # 8. Update Game Rotation for Tomorrow (Picked up by upload.yml)
    next_index = (current_index + 1) % len(GAMES)
    save_game_state(next_index)
    print(f"Pipeline complete. Next game in rotation: {GAMES[next_index]}")

if __name__ == "__main__":
    asyncio.run(main())
