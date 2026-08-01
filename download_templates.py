import os
import subprocess
import glob
import urllib.request
import shutil

def download_templates():
    templates_dir = "motion_templates"
    os.makedirs(templates_dir, exist_ok=True)
    
    print("--- [Robust yt-dlp Engine] Refreshing motion templates ---")
    for old_file in glob.glob(os.path.join(templates_dir, "*.mp4")):
        try:
            os.remove(old_file)
        except Exception:
            pass
            
    # Multiple search queries per template to guarantee yt-dlp finds a match
    templates = {
        "fight.mp4": [
            "roblox blox fruits pvp short",
            "roblox anime battle gameplay vertical"
        ],
        "boss.mp4": [
            "blox fruits sea beast raid gameplay",
            "roblox boss fight mobile gameplay"
        ],
        "fly.mp4": [
            "blox fruits flight movement showcase",
            "roblox fast movement parkour vertical"
        ],
        "water.mp4": [
            "blox fruits ocean sea travel",
            "roblox water physics ocean gameplay"
        ],
        "chest.mp4": [
            "blox fruits gacha rolling fruit",
            "roblox opening loot box vertical"
        ],
        "awakening.mp4": [
            "blox fruits raid awakening max stats",
            "roblox glowing transformation effect"
        ],
        "sea.mp4": [
            "blox fruits sailing ship voyage",
            "roblox boat ocean adventure"
        ]
    }
    
    # High-motion dynamic fallback video if all search queries hit a cloud block
    fallback_video_url = "https://assets.mixkit.co/videos/preview/mixkit-digital-animation-of-screens-and-numbers-31908-large.mp4"
    fallback_path = os.path.join(templates_dir, "fallback_motion.mp4")
    
    try:
        urllib.request.urlretrieve(fallback_video_url, fallback_path)
    except Exception:
        pass

    print("--- Starting Multi-Query yt-dlp Execution ---")
    
    for filename, queries in templates.items():
        output_path = os.path.join(templates_dir, filename)
        download_success = False
        
        for query in queries:
            print(f"Trying yt-dlp query for '{filename}': {query}")
            
            cmd = [
                "yt-dlp",
                f"ytsearch1:{query}",
                "--extractor-args", "youtube:player_client=android",
                "-f", "best[ext=mp4]/best",
                "-o", output_path,
                "--max-downloads", "1",
                "--no-playlist",
                "--quiet",
                "--no-warnings"
            ]
            
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
                if result.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 5000:
                    print(f"Successfully downloaded via yt-dlp -> {output_path}")
                    download_success = True
                    break
            except Exception as e:
                print(f"Query attempt notice: {e}")
                
        # If YouTube blocks all queries from the cloud IP, use the high-motion animated fallback instead of a boring color canvas
        if not download_success:
            print(f"Cloud block on {filename}. Applying high-motion animated fallback asset.")
            if os.path.exists(fallback_path):
                shutil.copy(fallback_path, output_path)

    # Cleanup temporary fallback file
    if os.path.exists(fallback_path):
        try:
            os.remove(fallback_path)
        except Exception:
            pass

if __name__ == "__main__":
    download_templates()
