import os
import time
import requests
import urllib.parse
import asyncio
import edge_tts
from rembg import remove
from moviepy.editor import ImageClip, AudioFileClip, CompositeVideoClip, CompositeAudioClip

# ==========================================
# 1. API & GENERATION FUNCTIONS
# ==========================================

def generate_image(prompt, filename, retries=3):
    """Fetches an image from Pollinations.ai with a retry loop to prevent API timeouts."""
    print(f"Generating: {filename}...")
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
        
        time.sleep(10) # Wait 10 seconds before retrying
        
    raise Exception(f"Fatal Error: Failed to generate {filename} after {retries} attempts.")

async def generate_voiceover(text, output_filename):
    """Generates an Edge-TTS voiceover file."""
    print("Generating voiceover...")
    # Using ChristopherNeural (+10% speed) as requested in your stack
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
# 2. VIDEO ASSEMBLY FUNCTION
# ==========================================

def assemble_video():
    """Builds the 2D puppetry, voiceover, and background music."""
    print("--- Assembling 2D Puppetry Video ---")
    
    # 1. Load Audio
    voice_clip = AudioFileClip("voiceover.mp3")
    video_duration = voice_clip.duration
    
    # Load background music and loop/trim it to match voiceover length
    if not os.path.exists("background_music.mp3"):
        raise Exception("Missing 'background_music.mp3' in your repository root!")
        
    bg_music = AudioFileClip("background_music.mp3")
    # If the music is shorter than the video, it needs looping. 
    # For a simple setup, just subclip it assuming the music file is longer than the Short.
    bg_music = bg_music.subclip(0, video_duration).volumex(0.1) # Duck volume to 10%
    
    final_audio = CompositeAudioClip([voice_clip, bg_music])

    # 2. Load Visuals
    background = ImageClip("background.jpg").set_duration(video_duration)
    background = background.resize(width=1080, height=1920) 
    
    character = ImageClip("character_sprite.png").set_duration(video_duration)
    character = character.resize(width=700) 
    
    # 3. Animation Logic: Character slides right and bounces up slightly
    def animate_character(t):
        x_position = 100 + (t * 30)       
        y_position = 1000 - (t * 20)      
        return (x_position, y_position)
        
    animated_character = character.set_position(animate_character)

    # 4. Composite and Render
    final_video = CompositeVideoClip([background, animated_character])
    final_video = final_video.set_audio(final_audio)
    
    print("Rendering final MP4 on CPU...")
    # Safe rendering settings for GitHub Actions
    final_video.write_videofile(
        "final_short.mp4", 
        fps=24, 
        codec="libx264", 
        audio_codec="aac",
        threads=2, 
        preset="ultrafast" 
    )

# ==========================================
# 3. MAIN EXECUTION
# ==========================================

def main():
    # Example script (Replace with Groq generation in the future)
    script = "What is up guys? Today we are looking at the absolute best spirit fruit in Blox Fruits. You won't believe how overpowered this setup is."
    
    # Generate Voiceover
    asyncio.run(generate_voiceover(script, "voiceover.mp3"))

    # Generate Visuals
    bg_prompt = "A cinematic Blox Fruits ocean landscape, vibrant colors, 8k resolution, vertical anime style"
    generate_image(bg_prompt, "background.jpg")
    
    char_prompt = "Roblox noob character using best spirit fruit power, standing on a solid pure white background, 3d render"
    generate_image(char_prompt, "raw_character.jpg")
    
    # Process Sprite
    create_transparent_sprite("raw_character.jpg", "character_sprite.png")
    
    # Assemble final video
    assemble_video()
    print("Pipeline complete! Video saved as final_short.mp4")

if __name__ == "__main__":
    main()
