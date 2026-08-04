# 🤖 Automated Roblox Shorts Engine

An advanced, zero-maintenance video rendering and publishing pipeline designed to generate, style, and upload episodic 9:16 vertical shorts for popular Roblox titles autonomously. Powered by **Groq LLaMA models**, **Pollinations AI**, **Edge-TTS**, and **FFmpeg**, this engine runs daily on GitHub Actions without any local hardware dependencies.

---

## 🚀 Architecture & Core Features

```
[GitHub Actions Run]
       │
       ├──► State Manager (Rotate Game & Load Memory)
       │
       ├──► Groq API (Script Generation & Scene Prompts)
       │
       ├──► Pollinations AI (8x Unreal Engine 5 Renders)
       │
       ├──► Edge-TTS (Raw Voiceover Generation)
       │
       ├──► FFmpeg Audio Filter (Trim Silence, Speed to 1.15x, Raise Pitch)
       │
       ├──► Subtitle Engine (Generate Word-Level Karaoke ASS Style)
       │
       ├──► FFmpeg Video Filter (Burn Subtitles & Mix Background BGM)
       │
       └──► YouTube Data API v3 (Automatic Video Upload)
```

### 1. Game-Specific Storytelling & Episodic Memory
The engine rotates daily through five top Roblox games, injecting custom gameplay tropes and lore bibles into the scripting prompts:
*   **Blox Fruits:** High-stakes devil fruit grinding, bounties, and awakening.
*   **Brookhaven:** Neighborhood suspense, bank robberies, and hidden bunkers.
*   **Adopt Me!:** Neon pet trading drama, home design, and trust-trade security.
*   **Murder Mystery 2:** Intense survival psychological thriller (Sheriff vs. Murderer).
*   **Tower of Hell:** Gravity-shifting, laser obby, and hilarious checkpoint-less rage.

To maintain narrative continuity across daily uploads, the engine writes back an episodic **story memory** text file for each game, ensuring that tomorrow’s generation starts exactly where today's cliffhanger ended.

### 2. High-Retention Audio & Pacing (The 1.15x Balanced Pitch)
Viral rants require hyper-dense speech and rapid delivery. The audio post-processing module handles this through a single-pass FFmpeg audio filter graph:
*   **Silence Trimming:** Automatically crops out breathing and pauses where volume falls below `-45dB` for more than `0.3` seconds (`300ms`), preserving starting/ending consonants.
*   **Pitch-Shift Speedup (1.15x + Chipmunk)**: Chose a 1.15x overall pacing speed combined with an energetic pitch raise. By running `asetrate=44100*1.1` (which speeds up and pitch-shifts the voiceover by 1.1x) alongside `atempo=1.05`, we achieve an exact `1.155x` speed multiplier while keeping the audio fully understandable and maintaining the signature community sound.

### 3. Styled Word-by-Word Karaoke Subtitles (ASS Format)
Unlike standard SubRip (`.srt`) formats, this engine generates **Advanced Substation Alpha (`.ass`)** subtitles. The stylesheet utilizes custom styling parameters to create the signature modern short-form layout:
*   **Roblox Cartoon Aesthetic:** Features bold, heavy-weight lettering, standard bottom-center lower-third positioning, and a thick black outline (`Outline=6`) to ensure high contrast and readable safe zones.
*   **Karaoke Highlighting:** Spun up in pure Python, our parser breaks chunks down line-by-line and generates accurate progressive highlight sweeps (`\kf` tags), transforming raw white subtitles into bright yellow exactly as each syllable is voiced.

### 4. Zero-Hassle ImageMagick Bypass
Standard rendering pipelines like MoviePy rely on local installations of ImageMagick (`TextClip` engines) to burn text overlays, which is notorious for causing permission errors and slow render times on headless linux servers. This engine **bypasses ImageMagick completely**:
1. MoviePy compiles the background images and mixes the audio tracks into a temporary raw video file.
2. The engine uses a local **FFmpeg subprocess** to burn the generated `.ass` subtitle script directly onto the frame buffers.
3. This shifts the rendering overhead from heavy CPU-bound image manipulation to native C-compiled video codecs, resulting in near-instant rendering on standard GitHub Actions runners!

---

## 🛠️ GitHub Repository Directory Layout

Make sure your repository has the following layout to avoid missing path errors:

```text
├── .github/
│   └── workflows/
│       └── upload.yml          # The schedule runner configuration
├── bgm/
│   └── track1.mp3              # Place any background .mp3 tracks here
├── .gitignore                  # Media-safe exclusions file
├── character_bible.json        # Global fallback character settings
├── character_bible_adopt_me.json
├── character_bible_blox_fruits.json
├── game_state.json             # Stores active rotation index and run count
├── main.py                     # The main automation script
└── requirements.txt            # Python environment packages
```

---

## 🚀 Step-by-Step Local & Production Workflow

### Step 1: Set Up Your Dependencies
Run these commands in your console to initialize your workspace:

```bash
# Clone and enter directory
git clone https://github.com/loobah18-arch/roblox-auto-shorts.git
cd roblox-auto-shorts

# Initialize virtual environment
python3 -m venv venv
source venv/bin/activate

# Install requirements
pip install -r requirements.txt
```

### Step 2: Configure Your Environment Secrets
Create a `.env` file (local testing) or populate your GitHub Repository Secrets with:

| Secret Name | Description |
| :--- | :--- |
| `GROQ_API_KEY` | Your LLaMA-based Groq inference token. |
| `CLIENT_ID` | OAuth 2.0 Web Application client credential from Google Cloud Console. |
| `CLIENT_SECRET` | OAuth 2.0 client secret credentials. |
| `REFRESH_TOKEN` | OAuth 2.0 refresh token to maintain secure, persistent login streams without human prompts. |

### Step 3: Run Locally (Test Rendering)
To test the pipeline without uploading to YouTube, temporarily comment out the `upload_to_youtube(...)` call in `main.py` and run:

```bash
python main.py
```
This will output `final_short.mp4` directly in your project root.

### Step 4: Clean Your GitHub Branch on Mobile/Web
To remove pre-existing media assets and apply the optimized ignoring filters:
1. Copy the content of **`gitignore.txt`** from your Studio panel and paste it into your `.gitignore` file.
2. Individually locate and delete `scene_0.jpg` through `scene_4.jpg` and `vo.mp3` directly from your GitHub browser interface (tap the trash icon on each file and commit changes).
3. Commit the updated `.gitignore` file. All subsequent automatic builds will run without pushing clutter back into your repository!

---

## 📋 The Automated Workflow (`upload.yml`)

The production schedule runs entirely on an automated schedule inside **GitHub Actions**. Here is the clean YAML workflow configuration. Place it inside `.github/workflows/upload.yml`:

```yaml
name: build-and-upload

on:
  schedule:
    - cron: '0 12 * * *'  # Runs automatically at 12:00 PM UTC daily
  workflow_dispatch:      # Allows manual trigger button in actions tab

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: write

    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Set up Python 3.10
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Install System Dependencies
        run: |
          sudo apt-get update
          sudo apt-get install -y ffmpeg

      - name: Install Python Dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Run Video Pipeline
        env:
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
          CLIENT_ID: ${{ secrets.CLIENT_ID }}
          CLIENT_SECRET: ${{ secrets.CLIENT_SECRET }}
          REFRESH_TOKEN: ${{ secrets.REFRESH_TOKEN }}
        run: |
          python main.py

      - name: Commit and Push Updated State
        run: |
          git config --global user.name "github-actions[bot]"
          git config --global user.email "github-actions[bot]@users.noreply.github.com"
          git add -A
          git commit -m "chore: update game state and story memory [skip ci]" || echo "No changes to commit"
          git push
```

---

## 🛠️ Self-Healing & Fallback Configurations

To insulate your daily execution from sudden server interruptions or incomplete repository updates, we've implemented standard **self-healing structural boundaries**:
*   **Narrative Memories fallback**: If a specific episodic memory like `story_memory_brookhaven.txt` is missing, the state machine automatically reads your global, untracked `story_memory.txt` to find historical hooks before safely initializing a new game story.
*   **Bibles fallback**: Missing `character_bible_murder_mystery_2.json` files are automatically bypassed by pulling traits from your root `character_bible.json` file, protecting script continuity.
*   **LLM Model deprecation**: Instead of hardcoding a model ID, the Groq script wrapper queries active API endpoints on runtime, filtering for high-performance instructions (such as active LLaMA, Mixtral, and Qwen variants) to keep your calls safe from model sunsetting crashes.

---

## ⚖️ License & Compliance
This project is licensed under the MIT License. In compliance with **Roblox Campaign Brand Safety Standards** and local children's safety regulations (such as **COPPA** and **GDPR-K**), all generated stories, scripts, and descriptions are designed using strictly safe, family-friendly, non-violent visual assets and creative themes.
