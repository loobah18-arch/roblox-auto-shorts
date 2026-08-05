# 🤖 Automated Roblox Shorts Engine

An advanced, zero-maintenance video rendering and publishing pipeline designed to generate, style, and upload episodic 9:16 vertical shorts for popular Roblox titles autonomously. Powered by **Groq LLaMA models**, **Multi-Provider AI Image Generators**, **Edge-TTS**, and **FFmpeg**, this engine runs daily on GitHub Actions without any local hardware dependencies.

---

## 🚀 Architecture & Core Features

```text
[GitHub Actions Run]
       │
       ├──► State Manager (Rotate Game, Load Memory, & Active Image Generator)
       │
       ├──► Groq API (High-Energy Script & Scene Prompt Generation)
       │
       ├──► Auto-Healing Image Loop (Fallback chain: New/Legacy Pollinations ➔ HF FLUX)
       │
       ├──► Edge-TTS (Raw Deep Voiceover Generation via ChristopherNeural)
       │
       ├──► FFmpeg Audio Filter (Trim Silence & Pacing Speed Optimization)
       │
       ├──► Subtitle Engine (Generate Word-Level Karaoke ASS Style)
       │
       ├──► FFmpeg Video Filter (Native Subtitle Burn & Background BGM Mix)
       │
       └──► YouTube Data API v3 (OAuth Refresh Token Handshake & Upload)
```

### 1. Game-Specific Storytelling & Episodic Memory
The engine rotates daily through five top Roblox games, injecting custom gameplay tropes and lore bibles into the scripting prompts:
*   **Blox Fruits:** High-stakes devil fruit grinding, bounties, and awakening.
*   **Brookhaven:** Neighborhood suspense, bank robberies, and hidden bunkers.
*   **Adopt Me!:** Neon pet trading drama, home design, and trust-trade security.
*   **Murder Mystery 2:** Intense survival psychological thriller (Sheriff vs. Murderer).
*   **Tower of Hell:** Gravity-shifting, laser obby, and hilarious checkpoint-less rage.

To maintain narrative continuity across daily uploads, the engine writes back an episodic **story memory** text file for each game, ensuring that tomorrow’s generation starts exactly where today's cliffhanger ended.

### 2. Auto-Healing Multi-Provider Image Generation (v16)
To prevent temporary cloud downtime or rate limits from breaking your daily publishing schedule, the engine operates an active multi-endpoint fallback loop:
*   **Primary Generator (`pollinations_new`):** Leverages speed-optimized FLUX-Schnell generation under a randomized seed modifier to completely bypass server cache states.
*   **API Outage Fallback (`huggingface_flux`):** If the primary endpoint encounters rate limits (HTTP 429) or server errors (HTTP 500), the engine programmatically switches mid-run to Hugging Face's free Inference API, checking for your `HF_TOKEN` secret.
*   **Sticky Active State:** Upon a successful render, the engine writes the working provider's name to `active_image_provider.txt` to prioritize it first on subsequent daily runs.

### 3. Styled Word-by-Word Karaoke Subtitles (ASS Format)
Unlike standard SubRip (`.srt`) formats, this engine generates **Advanced Substation Alpha (`.ass`)** subtitles. The custom style includes:
*   **Roblox Cartoon Aesthetic:** Features bold, heavy-weight lettering, standard bottom-center lower-third positioning, and a thick black outline (`Outline=6`) to ensure high contrast in mobile safe zones.
*   **Karaoke Highlighting:** A custom Python parser breaks chunks down line-by-line and generates accurate progressive highlight sweeps (`\kf` tags), transforming raw white subtitles into bright yellow exactly as each syllable is voiced.

### 4. Zero-Hassle ImageMagick Bypass
Standard video libraries like MoviePy rely on local installations of ImageMagick (`TextClip` engines) to burn text overlays, which is notorious for causing permission errors and slow render times on headless Linux servers. This engine **bypasses ImageMagick completely**:
1. MoviePy compiles the background images and mixes the audio tracks into a temporary raw video file.
2. The engine uses a local **FFmpeg subprocess** to burn the generated `.ass` subtitle script directly onto the frame buffers.
3. This shifts the rendering overhead from heavy CPU-bound image manipulation to native C-compiled video codecs, resulting in near-instant rendering on standard GitHub Actions runners!

---

## 🛠️ GitHub Repository Directory Layout

Make sure your repository has the following layout to avoid missing path errors:

```text
├── .github/
│   └── workflows/
│       └── upload.yml          # The unjittered schedule runner configuration
├── bgm/
│   └── track1.mp3              # Place your background .mp3 tracks here
├── .gitignore                  # Media-safe exclusions file
├── character_bible.json        # Global fallback character settings
├── character_bible_adopt_me.json
├── character_bible_blox_fruits.json
├── game_state.json             # Stores active rotation index and run count
├── main.py                     # The auto-healing master execution script
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
| `HF_TOKEN` | *Optional:* Your free Hugging Face API key to unlock the backup FLUX generator. |
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
2. Individually locate and delete `scene_0.jpg` through `scene_7.jpg` and `vo.mp3` directly from your GitHub browser interface (tap the trash icon on each file and commit changes).
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
          HF_TOKEN: ${{ secrets.HF_TOKEN }}
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

## ⚖️ License & Compliance
This project is licensed under the MIT License. In compliance with **Roblox Campaign Brand Safety Standards** and local children's safety regulations (such as **COPPA** and **GDPR-K**), all generated stories, scripts, and descriptions are designed using strictly safe, family-friendly, non-violent visual assets and creative themes.
