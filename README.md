# Roblox Auto-Shorts — Agnes 2.0 Edition (v7.1)

**100% FREE. Works on your phone. Powered by Agnes AI.**

## What is Agnes 2.0?

Agnes 2.0 is your AI co-director. She:
- 🎨 **Generates images** using Gemini Imagen 3 (free tier)
- 📝 **Writes viral stories** using Gemini 2.5 Flash (free tier)
- 🔄 **Falls back gracefully** to free alternatives if anything fails
- 💰 **Costs $0** — runs on Google's generous free API limits

## What You Need (All Free)

| Thing | Cost | How to Get |
|-------|------|------------|
| Python | FREE | Termux (Android) or Pythonista (iOS) |
| FFmpeg | FREE | `pkg install ffmpeg` in Termux |
| Agnes 2.0 | FREE | Gemini free tier (optional but recommended) |
| Images | FREE | Pollinations AI (no key) + your photos |
| Voice | FREE | Edge-TTS (no key) |
| Music | FREE | Your own MP3s |

## Quick Start (Phone/Termux)

```bash
# 1. Install Termux from F-Droid
# 2. Update and install
pkg update && pkg upgrade
pkg install python ffmpeg git

# 3. Install Python packages
pip install -r requirements.txt

# 4. Run Agnes 2.0
python main.py
```

## Two Modes

### Mode 1: Zero-Config (Template Mode)
**No API keys. No setup. Just run.**
- Agnes uses pre-written story templates
- Pollinations AI for free images
- Your local photos as fallback
- Perfect for testing

### Mode 2: Agnes 2.0 AI Mode (Recommended)
**Agnes writes stories + generates images. Still 100% free.**
1. Go to [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Click "Create API Key" (free, no credit card)
3. Set it:
```bash
export GEMINI_API_KEY="your_key_here"
```
4. Run `python main.py` — Agnes 2.0 takes over

## Agnes 2.0 Engine Cascade

```
Story:  Agnes 2.0 (Gemini free) → Template (always works)
Images: Agnes 2.0 (Gemini free) → Pollinations (free) → Your photos
Voice:  Edge-TTS (free, no key)
Music:  Your MP3s
```

## Folder Setup

```
roblox-auto-shorts/
├── main.py              ← Agnes 2.0 pipeline
├── requirements.txt     ← Dependencies
├── assets/              ← YOUR images (optional backup)
│   ├── roblox_landscape.jpg
│   └── ... (any .jpg works)
├── bgm/                 ← YOUR music (optional)
│   └── background.mp3
├── game_state.json      ← Auto-created
├── story_memory_*.txt   ← Auto-created
└── final_short_v*.mp4   ← Your videos!
```

## Games Agnes Can Write For

- Blox Fruits
- Adopt Me!
- Murder Mystery 2
- Pet Simulator X
- Doors
- Arsenal
- Anime Adventures
- Brookhaven RP

## Tips for Phone Users

1. **Storage**: Each video ~5-15MB. Clear `motion_templates/` after runs.
2. **Battery**: Rendering uses CPU. Keep phone plugged in.
3. **Heat**: Take breaks between renders.
4. **Quality**: Add 5-10 images to `assets/` for better variety.
5. **Speed**: `ultrafast` preset is already set. Quality is good for Shorts.

## YouTube Upload

Agnes generates `final_short_v1.mp4`. Upload manually:
1. Open YouTube app → Create a Short
2. Select your video
3. Copy title from `story_memory_*.txt`
4. Post!

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "No module named moviepy" | `pip install -r requirements.txt` |
| "ffmpeg not found" | `pkg install ffmpeg` |
| Agnes not generating images | Pollinations will handle it. Or add photos to `assets/` |
| Video is black | All engines failed. Add photos to `assets/` |
| Script crashes | Make sure you're in the right folder |

## Why Agnes 2.0?

- **v1 (Groq)**: Fast but needed paid API
- **v2 (Together)**: High quality but expensive
- **Agnes 2.0 (Gemini)**: Free tier, high quality, no credit card needed

**Total cost: $0.00**
