import os
import subprocess

def download_templates():
    templates_dir = "motion_templates"
    os.makedirs(templates_dir, exist_ok=True)
    
    # Priority mapping optimized for yt-dlp searches
    templates = {
        "fight.mp4": "roblox blox fruits pvp combo gameplay vertical shorts",
        "boss.mp4": "blox fruits raid boss leviathan fight gameplay",
        "fly.mp4": "blox fruits portal light fruit flight movement fast",
        "water.mp4": "blox fruits sea beast water ocean danger",
        "chest.mp4": "blox fruits rolling gacha cousin fruit opening",
        "awakening.mp4": "blox fruits raid awakening transformation max stats",
        "sea.mp4": "blox fruits sailing boat sea event voyage"
    }
    
    print("--- [yt-dlp Priority Engine] Fetching Contextual Gameplay ---")
    
    for filename, query in templates.items():
        output_path = os.path.join(templates_dir, filename)
        
        # Always refresh/prioritize yt-dlp fetching if file is missing or too small
        if os.path.exists(output_path) and os.path.getsize(output_path) > 50000:
            print(f"Template {filename} already exists. Skipping download.")
            continue
            
        print(f"Prioritizing yt-dlp search for '{filename}' -> Query: {query}")
        
        # yt-dlp command optimized for fast, vertical-friendly video retrieval
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
            print(f"Successfully fetched via yt-dlp -> {output_path}")
        except subprocess.CalledProcessError as e:
            print(f"yt-dlp warning: Could not fetch {filename} ({e}). Fallback mechanism will apply.")

if __name__ == "__main__":
    download_templates()
