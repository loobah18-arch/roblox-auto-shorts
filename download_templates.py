import os
import subprocess
import glob

def download_templates():
    templates_dir = "motion_templates"
    os.makedirs(templates_dir, exist_ok=True)
    
    # Wipe out old templates so yt-dlp is forced to fetch fresh ones every time
    print("--- [yt-dlp Force Engine] Clearing old templates for fresh downloads ---")
    for old_file in glob.glob(os.path.join(templates_dir, "*.mp4")):
        try:
            os.remove(old_file)
            print(f"Removed old template: {old_file}")
        except Exception as e:
            print(f"Could not remove {old_file}: {e}")
    
    templates = {
        "fight.mp4": "roblox blox fruits pvp combo gameplay vertical shorts",
        "boss.mp4": "blox fruits raid boss leviathan fight gameplay",
        "fly.mp4": "blox fruits portal light fruit flight movement fast",
        "water.mp4": "blox fruits sea beast water ocean danger",
        "chest.mp4": "blox fruits rolling gacha cousin fruit opening",
        "awakening.mp4": "blox fruits raid awakening transformation max stats",
        "sea.mp4": "blox fruits sailing boat sea event voyage"
    }
    
    print("--- Starting yt-dlp Fresh Template Fetch ---")
    
    for filename, query in templates.items():
        output_path = os.path.join(templates_dir, filename)
        print(f"Fetching fresh via yt-dlp for '{filename}' -> Query: {query}")
        
        cmd = [
            "yt-dlp",
            f"ytsearch1:{query}",
            "-f", "bestvideo[height<=1920][ext=mp4]/best[ext=mp4]/best",
            "-o", output_path,
            "--max-downloads", "1",
            "--no-playlist",
            "--quiet",
            "--no-warnings"
        ]
        
        try:
            subprocess.run(cmd, check=True)
            print(f"Successfully fetched -> {output_path}")
        except subprocess.CalledProcessError as e:
            print(f"yt-dlp warning: Could not fetch {filename} ({e}).")

if __name__ == "__main__":
    download_templates()
