import os
import time
import shutil
import requests
import asyncio
import edge_tts
from groq import Groq
from gradio_client import Client, handle_file
from moviepy.editor import VideoFileClip, AudioFileClip, CompositeAudioClip, ImageClip
import moviepy.video.fx.all as vfx

# --- CONFIGURATION ---
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
YT_REFRESH_TOKEN = os.environ.get("YT_REFRESH_TOKEN")
# Make sure to handle OAuth setup via Google API client here as you did before

def generate_script(topic):
    print("📝 Generating script with Groq...")
    client = Groq(api_key=GROQ_API_KEY)
    response = client.chat.completions.create(
        messages=[{"role": "user", "content": f"Write a 30-second YouTube Short script about {topic}."}],
        model="llama3-8b-8192",
    )
    return response.choices[0].message.content

def generate_image(prompt, output_path="scene.jpg"):
    print("🎨 Fetching 9:16 image from Pollinations AI...")
    url = f"https://image.pollinations.ai/prompt/{prompt}?width=1080&height=1920&nologo=true"
    response = requests.get(url)
    with open(output_path, "wb") as f:
        f.write(response.content)
    return output_path

def animate_image_free(image_path, output_video_path="animated_scene.mp4"):
    print("🪄 Animating image using Hugging Face (Stable Video Diffusion)...")
    try:
        client = Client("stabilityai/stable-video-diffusion")
        
        # Passes the static image into the Gradio web UI programmatically
        result = client.predict(
            image=handle_file(image_path),
            motion_bucket_id=127,
            noise_aug_strength=0.02,
            api_name="/video"
        )
        
        # Gradio returns the path to the generated temporary video file
        # SVD returns a dictionary or a direct string depending on space version; 
        # index 0 of the result is typically the video output path
        video_temp_path = result[0]['video'] if isinstance(result, tuple) else result
        
        shutil.move(video_temp_path, output_video_path)
        print(f"✅ Animation successful! Saved to {output_video_path}")
        return output_video_path
        
    except Exception as e:
        print(f"⚠️ Animation failed (Server might be busy): {e}")
        return None

async def generate_tts(text, output_path="voiceover.mp3"):
    print("🗣️ Generating voiceover with edge-tts...")
    communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural")
    await communicate.save(output_path)
    return output_path

def assemble_video(animated_video_path, static_image_path, audio_path, output_path="final_short.mp4"):
    print("🎬 Assembling final YouTube Short...")
    
    audio_clip = AudioFileClip(audio_path)
    
    # Check if the animation succeeded. If not, fallback to the static image.
    if animated_video_path and os.path.exists(animated_video_path):
        video_clip = VideoFileClip(animated_video_path)
        # AI videos are 2-4 seconds. Loop the video to match the TTS duration.
        video_clip = video_clip.fx(vfx.loop, duration=audio_clip.duration)
    else:
        print("⚠️ Using static image fallback for assembly.")
        video_clip = ImageClip(static_image_path).set_duration(audio_clip.duration)

    # Force 9:16 resolution for YouTube Shorts
    video_clip = (video_clip
                  .resize(height=1920)
                  .crop(x_center=1080/2, width=1080)
                  .set_audio(audio_clip))
                  
    # (Optional) Add your background music logic here via CompositeAudioClip

    video_clip.write_videofile(
        output_path, 
        fps=24, 
        codec="libx264", 
        audio_codec="aac"
    )
    return output_path

def main():
    # 1. Update Story Memory (Blox Fruits or Brookhaven)
    topic = "a rare Blox Fruits hidden secret"
    
    # 2. Generate Content
    script = generate_script(topic)
    image_path = generate_image("Roblox Blox Fruits cinematic epic lighting")
    
    # 3. Animate (NEW STEP)
    animated_path = animate_image_free(image_path)
    
    # 4. Generate Audio
    asyncio.run(generate_tts(script))
    
    # 5. Assemble
    final_video = assemble_video(animated_path, image_path, "voiceover.mp3")
    
    # 6. Upload to YouTube via Data API v3 (Using your existing OAuth logic)
    print("🚀 Ready to upload to YouTube!")
    # upload_to_youtube(final_video, title="Blox Fruits Secret! #shorts")

if __name__ == "__main__":
    main()
