
import os
import subprocess

def download_templates():
    templates_dir = "motion_templates"
    os.makedirs(templates_dir, exist_ok=True)
    
    templates = {
        "fight.mp4": "blox fruits pvp fight combo short",
        "boss.mp4": "blox fruits raid boss fight leviathan",
        "fly.mp4": "blox fruits portal light fruit flight movement",
        "water.mp4": "blox fruits sea beast water damage",
        "chest.mp4": "blox fruits rolling fruit gacha cousin",
        "awakening.mp4": "blox fruits raid awakening transformation",
        "sea.mp4": "blox fruits sailing sea event boat"
    }
    
    print("--- Starting Automated Blox Fruits Template Downloader ---")
    
    for filename, query in templates.items():
        output_path = os.path.join(templates_dir, filename)
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            print(f"Skipping {filename}: already exists.")
            continue
            
        print(f"Fetching template for '{filename}' using query: {query}")
        cmd = [
            "yt-dlp",
            f"ytsearch1:{query}",
            "-f", "bestvideo[height<=1080][ext=mp4]/best[ext=mp4]/best",
            "-o", output_path,
            "--max-downloads", "1",
            "--no-playlist",
            "--quiet"
        ]
        
        try:
            subprocess.run(cmd, check=True)
            print(f"Successfully downloaded -> {output_path}")
        except subprocess.CalledProcessError as e:
            print(f"Error downloading {filename}: {e}")

if __name__ == "__main__":
    download_templates()
