import os
import subprocess
import glob
import urllib.request

def download_templates():
    templates_dir = "motion_templates"
    os.makedirs(templates_dir, exist_ok=True)
    
    print("--- [Multi-Platform Engine] Clearing old templates ---")
    for old_file in glob.glob(os.path.join(templates_dir, "*.mp4")):
        try:
            os.remove(old_file)
        except Exception:
            pass
            
    # Multi-source dictionary: yt-dlp will try these sequentially across platforms
    templates = {
        "fight.mp4": [
            "ytsearch1:roblox blox fruits pvp combo gameplay shorts",
            "https://www.tiktok.com/tag/bloxfruits"
        ],
        "boss.mp4": [
            "ytsearch1:blox fruits raid boss leviathan fight",
            "https://www.tiktok.com/discover/blox-fruits-boss"
        ],
        "fly.mp4": [
            "ytsearch1:blox fruits portal light fruit flight",
        ],
        "water.mp4": [
            "ytsearch1:blox fruits sea beast water ocean",
        ],
        "chest.mp4": [
            "ytsearch1:blox fruits rolling gacha fruit opening",
        ],
        "awakening.mp4": [
            "ytsearch1:blox fruits raid awakening max",
        ],
        "sea.mp4": [
            "ytsearch1:blox fruits sailing boat sea event"
        ]
    }
    
    universal_fallback = "https://www.w3schools.com/html/mov_bbb.mp4"

    print("--- Starting Multi-Platform yt-dlp Fetch ---")
    
    for filename, sources in templates.items():
        output_path = os.path.join(templates_dir, filename)
        download_success = False
        
        for source in sources:
            print(f"Trying source for '{filename}' -> {source}")
            
            cmd = [
                "yt-dlp",
                source,
                "--extractor-args", "youtube:player_client=android",
                "-f", "best[ext=mp4]/best",
                "-o", output_path,
                "--max-downloads", "1",
                "--no-playlist",
                "--quiet",
                "--no-warnings"
            ]
            
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
                if result.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                    print(f"Successfully fetched from source -> {output_path}")
                    download_success = True
                    break
            except Exception as e:
                print(f"Source attempt notice: {e}")
                
        if not download_success:
            print(f"All platform sources failed for {filename}. Applying resilient container fallback.")
            try:
                urllib.request.urlretrieve(universal_fallback, output_path)
            except Exception:
                pass

if __name__ == "__main__":
    download_templates()
