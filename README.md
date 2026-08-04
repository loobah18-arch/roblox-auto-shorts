# 🤖 Automated Roblox Shorts Engine

A fully automated, zero-maintenance pipeline that generates, renders, and publishes episodic vertical video shorts for YouTube using free AI APIs and GitHub Actions.

---

## 🚀 Features

* **Daily Automation:** Runs autonomously via GitHub Actions on a cron schedule.
* **Dynamic Game Rotation:** Seamlessly cycles through popular Roblox games (*Blox Fruits, Brookhaven, Adopt Me!, Murder Mystery 2, Tower of Hell*).
* **Episodic Continuity:** Maintains rolling story memory so each day's video picks up right where the last cliffhanger left off.
* **Self-Healing LLM Fallback:** Dynamically queries Groq's active models to prevent sudden API deprecation crashes.
* **Unreal Engine 5 Visuals:** Enhances AI image generation with cinematic lighting, ray-tracing, and high-end aesthetic modifiers.
* **Deep Epic Voiceovers:** Powered by Edge-TTS for commanding, movie-trailer quality narration.
* **High-Retention Captions:** Features localized lower-middle text framing with auto-wrapping to guarantee optimal mobile display.
* **Auto-Publishing:** Securely pushes finished videos straight to your YouTube channel via OAuth refresh tokens.

---

## 🛠️ Tech Stack & Services

* **Orchestration:** GitHub Actions (`ubuntu-latest`)
* **Script & Narrative Generation:** Groq API (LLaMA models)
* **Visual Asset Generation:** Pollinations AI
* **Voiceover Generation:** Edge-TTS
* **Video Rendering & Audio Mixing:** MoviePy 1.0.3 & FFmpeg
* **Publishing:** YouTube Data API v3

---

## 📂 Project Structure

```text
├── .github/
│   └── workflows/
│       └── upload.yml       # GitHub Actions automation workflow
├── assets/                  # Local visual and narrator assets
├── bgm/                     # Background music tracks (.mp3)
├── main.py                  # Core automation and rendering script
├── requirements.txt         # Python dependencies
├── game_state.json          # Tracks game rotation and run counts
└── README.md                # Project documentation
