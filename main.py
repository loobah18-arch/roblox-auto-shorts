import os
import re
import asyncio
import urllib.parse
import urllib.request
import edge_tts
from groq import Groq
from moviepy.editor import ImageClip, AudioFileClip, CompositeVideoClip, CompositeAudioClip
from moviepy.audio.fx.all import volumex

# ==========================================
# 1. NARRATIVE GENERATION (Llama 3.3 70B)
# ==========================================
def generate_script_and_prompt(api_key, memory_path="story_memory.txt"):
    client = Groq(api_key=api_key)
    
    # Load previous episode memory for narrative continuity
    memory = ""
    if os.path.exists(memory_path):
        with open(memory_path, "r") as f:
            memory = f.read().strip()

    system_prompt = (
        "You are a fast-paced Roblox Shorts storyteller. "
        "Create an engaging 50-second script for a Roblox story (Blox Fruits/Brookhaven). "
        "Output strictly in this format without additional text:\n"
        "SCRIPT: [Your high-energy voiceover text]\n"
        "IMAGE_PROMPT: [Visual description for AI image generator, Unreal Engine 5, cinematic lighting, 8k resolution]\n"
        "NEW_MEMORY: [1-2 sentences summarizing this episode to remember for tomorrow]"
    )
    
    user_prompt = "Write the next daily Roblox short."
    if memory:
        user_prompt += f" Previous episode context: {memory}"

    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.7
    )
    
    response_text = completion.choices[0].message.content
    
    # Regex parsing to extract structural elements cleanly
    script_match = re.search(r"SCRIPT:\s*(.*?)(?=\nIMAGE_PROMPT:|\nNEW_MEMORY:|$)", response_text, re.DOTALL | re.IGNORECASE)
    prompt_match = re.search(r"IMAGE_PROMPT:\s*(.*?)(?=\nNEW_MEMORY:|$)", response_text, re.DOTALL | re.IGNORECASE)
    memory_match = re.search(r"NEW_MEMORY:\s*(.*?)$", response_text, re.DOTALL | re.IGNORECASE)
    
    script_text = script_match.group(1).strip() if script_match else "Welcome back to another crazy Roblox story!"
    image_prompt = prompt_match.group(1).strip() if prompt_match else "Roblox character in a cinematic landscape, Unreal Engine 5, 8k resolution"
    new_memory = memory_match.group(1).strip() if memory_match else memory
    
    # Save updated memory for the next workflow run
    with open(memory_path, "w") as f:
        f.write(new_memory)
        
    return script_text, image_prompt

# ==========================================
# 2. IMAGE GENERATION (Pollinations.ai)
# ==========================================
def download_image(prompt, output_file="generated_image.png"):
    encoded_prompt = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1080&height=1920&nologo=true"
    
    headers = {'User-Agent': 'Mozilla/5.0'}
    req = urllib.request.Request(url, headers=headers)
    
    try:
        with urllib.request.urlopen(req) as response, open(output_file, 'wb') as out_file:
            out_file.write(response.read())
        print(f"Image successfully generated and saved to {output_file}")
    except Exception as e:
        print(f"Error fetching image from Pollinations.ai: {e}")
        raise e

# ==========================================
# 3. AUDIO & VOICEOVER (Edge-TTS Masking)
# ==========================================
async def generate_voiceover(text, output_file="voiceover.mp3"):
    # rate="+10%" increases speed for high-energy commentator masking
    communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural", rate="+10%")
    await communicate.save(output_file)

# ==========================================
# 4. VIDEO ASSEMBLY (Ken Burns + Ducking)
# ==========================================
def assemble_video(image_path, voice_path, bgm_path, output_path="final_short.mp4"):
    voice_clip = AudioFileClip(voice_path)
    
    # Match background music to voiceover duration
    bgm_clip = AudioFileClip(bgm_path).subclip(0, voice_clip.duration)
    
    # Duck background music volume down to 10%
    ducked_bgm = bgm_clip.fx(volumex, 0.1)
    
    # Composite voiceover and ducked background audio
    final_audio = CompositeAudioClip([ducked_bgm, voice_clip])
    duration = voice_clip.duration
    
    # Load base image and fit to 1080 width
    base_clip = ImageClip(image_path).resize(width=1080)
    
    # Dynamic Ken Burns zoom: expands by 2% per second
    moving_clip = (
        base_clip
        .resize(lambda t: 1 + 0.02 * t)
        .set_position(('center', 'center'))
        .set_duration(duration)
    )
    
    # Render in strict 1080x1920 vertical Shorts aspect ratio
    final_video = CompositeVideoClip(
        [moving_clip], 
        size=(1080, 1920)
    ).set_audio(final_audio)
    
    final_video.write_videofile(
        output_path, 
        fps=24, 
        codec="libx264", 
        audio_codec="aac",
        preset="ultrafast",
        threads=4
    )

# ==========================================
# 5. MAIN PIPELINE EXECUTION
# ==========================================
def main():
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
    if not GROQ_API_KEY:
        print("Error: GROQ_API_KEY environment variable is not set.")
        return
        
    print("--- STEP 1: Generating Script & Prompts (Llama 3.3 70B) ---")
    script, image_prompt = generate_script_and_prompt(GROQ_API_KEY)
    print(f"Generated Script:\n{script}\n")
    print(f"Generated Image Prompt:\n{image_prompt}\n")
    
    print("--- STEP 2: Generating Voiceover (Edge-TTS) ---")
    asyncio.run(generate_voiceover(script, "voiceover.mp3"))
    
    print("--- STEP 3: Downloading Visuals (Pollinations.ai) ---")
    download_image(image_prompt, "generated_image.png")
    
    print("--- STEP 4: Assembling Final Video (MoviePy Engine) ---")
    # Ensure 'background_music.mp3' is placed in your repository root directory
    if os.path.exists("background_music.mp3"):
        assemble_video("generated_image.png", "voiceover.mp3", "background_music.mp3", "final_short.mp4")
        print("Pipeline Complete! 'final_short.mp4' is ready for upload.")
    else:
        print("Warning: 'background_music.mp3' not found in repo root. Assembly skipped.")

if __name__ == "__main__":
    main()
