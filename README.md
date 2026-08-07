# 🎮 Roblox Auto Shorts

Automatically generates and uploads daily Roblox story short videos to YouTube using AI — fully hands-free via GitHub Actions.

---

## 🔄 How the Workflow Works

Every day at **12:00 UTC** (or manually triggered), GitHub Actions runs the full pipeline:

```
1. Pick a Roblox game from the rotation
        ↓
2. Load story memory + character bible for that game
        ↓
3. Generate script + image prompts via Groq AI (LLM)
        ↓
4. Generate 8 vertical scene images via Pollinations AI
        ↓
5. Generate deep voiceover via Edge-TTS
        ↓
6. Render 9:16 video with Ken Burns motion & bottom karaoke captions via FFmpeg
        ↓
7. Upload video to YouTube
        ↓
8. Save updated story memory + game state back to repo
```

The pipeline rotates through 5 games daily:
- 🗡️ Blox Fruits
- 🏡 Brookhaven
- 🐣 Adopt Me!
- 🔪 Murder Mystery 2
- 🏗️ Tower of Hell

---

## 🎬 Video & Subtitle Quality (9:16 Vertical)

The pipeline is optimized for YouTube Shorts (1080x1920 portrait format):

- **Pure FFmpeg Engine**: Replaced MoviePy with a pure FFmpeg pipeline for smooth 30fps rendering, precise audio mixing, and high quality encoding (`libx264`, CRF 18).
- **Dynamic Ken Burns Pan & Zoom**: 8 distinct camera motion styles across scenes (center zoom in/out, pan left/right/up/down, top-left/bottom-right zoom).
- **Bottom Karaoke Subtitles**: Stylized Aegisub (`.ass`) subtitles burned directly onto the video:
  - **Position**: Bottom-center alignment (`Alignment: 2`) with comfortable vertical margins (`MarginV: 120px`) for optimal readability on mobile screens.
  - **Karaoke Highlights**: Word-by-word color transition (vibrant yellow active highlight over white font with bold black outline).
  - **9:16 Safe Zone**: Designed so subtitles never overlap top headers or bottom UI elements in YouTube Shorts.

---

## 🖼️ Image Generation

Images are generated using **Pollinations AI** (`image.pollinations.ai`) with a multi-provider fallback chain. If one provider fails, the next is tried automatically.

| Provider | Model | URL |
|---|---|---|
| `pollinations_new` | FLUX | `image.pollinations.ai/prompt/...?model=flux` |
| `pollinations_legacy` | FLUX | `image.pollinations.ai/prompt/...?model=flux` |
| `pollinations_turbo` | Turbo | `image.pollinations.ai/prompt/...?model=turbo` |
| `pollinations_realism` | FLUX Realism | `image.pollinations.ai/prompt/...?model=flux-realism` |
| `huggingface_flux` | FLUX Schnell | `api-inference.huggingface.co` *(requires `HF_TOKEN` secret)* |

> **Note:** All providers use `image.pollinations.ai` — the old `gen.pollinations.ai` domain now requires paid auth and has been removed.

If all providers fail for a scene, a stylized placeholder image is automatically generated using Pillow so the video still renders. The pipeline remembers which provider last worked and tries it first on the next run ("sticky provider").

---

## ⚙️ Setup

### 1. Fork / Clone this repo

```bash
git clone https://github.com/loobah18-arch/roblox-auto-shorts.git
cd roblox-auto-shorts
```

### 2. Add GitHub Secrets

Go to **Settings → Secrets and variables → Actions → New repository secret**

| Secret | What it is | Required? |
|---|---|---|
| `GROQ_API_KEY` | API key from [console.groq.com](https://console.groq.com) | ✅ Yes |
| `CLIENT_ID` | Google OAuth client ID | ✅ Yes |
| `CLIENT_SECRET` | Google OAuth client secret | ✅ Yes |
| `REFRESH_TOKEN` | YouTube OAuth refresh token | ✅ Yes |
| `HF_TOKEN` | Hugging Face API token (from [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)) | ⚠️ Optional (enables 5th fallback provider) |

### 3. Set up YouTube OAuth

To get `CLIENT_ID`, `CLIENT_SECRET`, and `REFRESH_TOKEN`:
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → Enable **YouTube Data API v3**
3. Create OAuth 2.0 credentials (Desktop app)
4. Run the OAuth flow locally to get a refresh token
5. Add all three values as GitHub secrets

### 4. Run the workflow

- **Automatic:** Runs every day at 12:00 UTC
- **Manual:** Go to **Actions → build-and-upload → Run workflow**

---

## 📁 File Structure

```
roblox-auto-shorts/
├── .github/
│   └── workflows/
│       └── upload.yml          # GitHub Actions workflow
├── assets/                     # Static background images
├── bgm/                        # Background music tracks
├── main.py                     # 🔑 Main pipeline script (FFmpeg, Groq, Edge-TTS, ASS captions)
├── requirements.txt            # Python dependencies
├── game_state.json             # Tracks current game rotation & episode counts
├── active_llm_model.txt        # Remembers last working LLM
├── active_image_provider.txt   # Remembers last working image provider
├── character_bible_*.json      # Character lore per game
└── story_memory_*.txt          # Ongoing story continuity per game
```

---

## 🛠️ Tech Stack

| Component | Tool |
|---|---|
| Script & image prompts | [Groq](https://groq.com) (LLM — llama-3.3-70b / multi-model fallback) |
| Image generation | [Pollinations AI](https://pollinations.ai) (free FLUX / Turbo) + HuggingFace |
| Voiceover | [Edge-TTS](https://github.com/rany2/edge-tts) (Microsoft neural voices) |
| Video rendering | [FFmpeg](https://ffmpeg.org/) (Pure FFmpeg with Ken Burns effects) |
| Captions & Subtitles | Aegisub ASS (`.ass`) with karaoke highlights at bottom (9:16 layout) |
| Upload | YouTube Data API v3 |
| Automation | GitHub Actions (free tier) |

---

## 🐛 Troubleshooting

**Images all show as placeholders**
- Check the workflow logs under Actions for the specific error
- Make sure `gen.pollinations.ai` is NOT in your `main.py` (it now requires paid auth)
- The correct domain is `image.pollinations.ai`

**Video upload fails**
- Check that all 4 YouTube secrets are set correctly
- Ensure your YouTube OAuth refresh token hasn't expired

**LLM quota errors**
- Groq free tier has daily limits; the pipeline auto-falls back through multiple models
- Check [console.groq.com](https://console.groq.com) for quota status

**Workflow doesn't trigger on schedule**
- GitHub disables scheduled workflows after 60 days of repo inactivity
- Re-enable by going to Actions and clicking "Enable workflow"

---

## 📄 License

MIT — free to use, modify, and share.
