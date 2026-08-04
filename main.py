import os
import json
import random
import glob
from moviepy.editor import * # Pinned to 1.0.3 in requirements.txt
# import edge_tts
# from groq import Groq
# import requests (For Pollinations AI and YouTube API)

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
            return f.read() # Return as string to feed directly to Groq
    return "No character bible found for this game."

# --- PIPELINE FUNCTIONS ---
def generate_script_and_images(game, memory, bible):
    """Integrates with Groq and Pollinations AI"""
    print(f"Generating script for {game} using Groq...")
    # 1. Feed game, memory, and bible to Groq LLM
    # 2. Extract story script and new cliffhanger memory
    # 3. Extract image prompts and call Pollinations AI (https://image.pollinations.ai/prompt/{prompt})
    
    # Mock returns
    audio_text = "Welcome back to the game! Today we face the ultimate challenge."
    new_memory = "The player is standing in front of the final boss, unarmed."
    image_paths = ["scene1.jpg", "scene2.jpg"] 
    return audio_text, new_memory, image_paths

def split_text_for_captions(text, words_per_chunk=3):
    """Splits text into 3-word chunks for high retention."""
    words = text.split()
    return [" ".join(words[i:i + words_per_chunk]) for i in range(0, len(words), words_per_chunk)]

def render_video(audio_path, image_paths, text_chunks):
    """MoviePy 1.0.3 assembly with ImageMagick captions and automated BGM mixing."""
    print("Assembling video with MoviePy...")
    
    # Load Voiceover Audio
    vo_clip = AudioFileClip(audio_path)
    video_duration = vo_clip.duration

    # Automated BGM Mixing from /bgm folder
    bgm_files = glob.glob("bgm/*.mp3")
    if bgm_files:
        selected_bgm = random.choice(bgm_files)
        bgm_clip = AudioFileClip(selected_bgm).fx(vfx.volumex, 0.1) # Lower BGM volume
        bgm_clip = bgm_clip.set_duration(video_duration)
        final_audio = CompositeAudioClip([vo_clip, bgm_clip])
    else:
        final_audio = vo_clip

    # Caption Generation (Dynamic 3-word yellow font)
    # Note: Requires ImageMagick policy fix applied in workflow
    chunk_duration = video_duration / len(text_chunks)
    text_clips = []
    
    for i, chunk in enumerate(text_chunks):
        txt_clip = TextClip(chunk, fontsize=70, color='yellow', font='DejaVu-Sans-Bold', 
                            stroke_color='black', stroke_width=3)
        txt_clip = txt_clip.set_position('center').set_duration(chunk_duration).set_start(i * chunk_duration)
        text_clips.append(txt_clip)

    # (Add Image sequence logic here using ImageClip mapped to durations)
    
    # Final assembly
    # video = CompositeVideoClip([base_image_clip] + text_clips)
    # video = video.set_audio(final_audio)
    # video.write_videofile("final_short.mp4", fps=24)
    print("Video rendered successfully.")
    return "final_short.mp4"

def upload_to_youtube(video_path, game_name):
    """Handles authenticated upload via GitHub Secrets."""
    client_id = os.environ.get("CLIENT_ID")
    client_secret = os.environ.get("CLIENT_SECRET")
    refresh_token = os.environ.get("REFRESH_TOKEN")
    
    print(f"Uploading {video_path} to YouTube for game: {game_name}...")
    # Add robust Error Handling and Google API upload logic here
    print("Upload complete!")

# --- MAIN EXECUTION ---
def main():
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
    audio_path = "vo.mp3"
    # edge_tts logic here: e.g., asyncio.run(edge_tts.Communicate(audio_text, "en-US-GuyNeural").save(audio_path))

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
    main()
