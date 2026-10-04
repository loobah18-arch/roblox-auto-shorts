# ⚔️ Bhaloo Ji — Anime Explanation & Recap Engine

An automated, cloud-powered **Anime Explanation & Dual-Funnel Recap Engine** built exclusively for the **Bhaloo Ji** YouTube channel. 

Inspired by high-retention channels like **Woo's Clips**, upgraded with a **modern cinematic aesthetic**, **multi-part Shorts**, and **stitched Full Episode long-form videos**.

---

## 🌟 Core Concept & Dual-Funnel Strategy

1. **Source Material**: Powered exclusively by the private Google Drive Anime Library (`https://drive.google.com/drive/folders/1e5_IF3GRHNr315hP5zK_qlyfsKXm3Ox4`) containing 120+ episodes of *Demon Slayer*, *Jujutsu Kaisen*, and more.
2. **Shorts Funnel (Vertical 9:16)**:
   - 1 Episode is divided into **3 to 5 AI-adaptive parts** (~45–55 seconds each).
   - Every Short features an irresistible **0–3s hook**, fast-paced dramatic narration, and an intense **cliffhanger** driving viewers to the next part.
3. **Normal / Long-Form Video Funnel**:
   - Once all parts of an episode are generated, the engine seamlessly **stitches all parts together** into one uninterrupted Full Episode Video with smooth chapter transitions.
   - Includes full episode chapters, timestamps, and deep narrative analysis for maximum watch time and monetization.

---

## 🛡️ Anti-Copyright & High-Aesthetic Formula

To guarantee **100% YouTube Content ID safety** while looking significantly more pleasing and attractive than raw clip channels:

| Technique | Implementation Details |
| :--- | :--- |
| **Rapid Scene Slicing** | Raw anime footage is sliced into rapid, dynamic cuts strictly **under 4.2 seconds** per scene. No continuous copyrighted frame runs long enough to trigger visual match algorithms. |
| **Aesthetic 9:16 Canvas** | Duplicate video scaled and heavily blurred (`boxblur=25:5`, darkened by 12%) as an ambient motion backdrop, with the crisp anime video card centered in the sweet spot with subtle border styling. |
| **Top Info Header** | Sleek cyan/gold top badge: `• DEMON SLAYER • S01E01 • PART 1/3 •` giving each video an official, branded identity. |
| **Dynamic Karaoke Subtitles** | High-retention word-by-word animated **ASS Karaoke Subtitles** in bold sans-serif with vibrant yellow-gold glow pop-in (`{\c&H0000FFFF&}`) on the active spoken word. |
| **Cinematic Film LUT** | Visual hash modification via subtle contrast elevation (`contrast=1.06`), slight saturation boost (`saturation=1.12`), and micro-zoom / Ken Burns drift. |
| **Audio Overhaul** | Crystal-clear neural voiceover (`en-US-ChristopherNeural` via Edge-TTS) peak-normalized to -16 LUFS, layered over copyright-clean epic BGM. Original anime audio is ducked to -28dB (ambient texture only). |
| **Transformative Fair Use** | Formatted as transformative critical commentary under Section 107 of the Copyright Act 1976, accompanied by standardized Fair Use disclaimers and studio credits. |

---

## 📁 Repository Architecture

```
bhaloo-shorts/
├── .github/workflows/
│   └── bhaloo_anime_engine.yml   ← Cloud CI/CD runner (Zero phone load)
├── scripts/
│   ├── anime_catalog.py          ← GDrive folder sync, episode metadata parsing
│   ├── anime_script_engine.py    ← AI-adaptive multi-part breakdown & full video scripts
│   ├── anime_voice_subtitles.py  ← Edge-TTS voiceover & dynamic ASS karaoke subtitles
│   ├── anime_video_engine.py     ← Anti-copyright FFmpeg slicing, canvas & stitcher
│   ├── anime_pipeline.py         ← End-to-end episodic orchestrator
│   └── anime_youtube_uploader.py ← Shorts & Full Video YouTube API publisher
├── tracker/
│   ├── anime_catalog.json        ← Indexed list of all 120 GDrive episodes
│   └── anime_history.json        ← Log of produced/uploaded episodes
├── tests/
│   └── test_anime_engine.py      ← Lightweight mocked unit tests (runs in <5ms)
└── output/                       ← Rendered videos, audio, subtitles, and manifests
```

---

## 🚀 Cloud Execution (GitHub Actions)

Because rendering 1080p anime video on a mobile device would exhaust RAM and battery, the entire heavy processing pipeline runs **100% in the cloud on GitHub Actions**:

### How to Trigger:
1. Go to **Actions** → **⚔️ Bhaloo Ji — Anime Explanation Engine**.
2. Click **Run workflow**:
   - **Episode**: Specify an episode (e.g. `demon-slayer-s01e01`, `jujutsu-kaisen-s01e01`) or leave blank for automatic sequential rotation.
   - **Series**: Filter by `all`, `demon-slayer`, or `jujutsu-kaisen`.
   - **Upload to YouTube**: Toggle `true` to publish live to the Bhaloo Ji channel, or `false` to inspect artifacts first.
   - **Privacy**: `public`, `unlisted`, or `private`.
3. The runner downloads the episode directly from Google Drive, slices and renders all Shorts parts, stitches the full video, packages metadata, and uploads artifacts.

---

## 💻 Local CLI Usage (Lightweight)

You can manage the catalog and preview scripts locally without heavy rendering:

```bash
# Sync latest anime files from Google Drive
python3 scripts/anime_catalog.py --sync

# Check which episode is next in queue
python3 scripts/anime_catalog.py --next

# Generate script & audio preview in dry-run mode (safe on phone)
python3 scripts/anime_pipeline.py --dry-run

# Run local unit tests
python3 tests/test_anime_engine.py
```

---

## 🏷️ Standardized Fair Use & SEO Format

Every video uploaded includes optimized metadata:

```markdown
Title:
His Entire Family Was Slaughtered... 🩸 | Demon Slayer S1 Ep 1 Part 1 #shorts

Description:
Imagine coming home to find your entire family murdered, and the only survivor has turned into a flesh-eating demon.
Part 1 of 3 covering Demon Slayer: Kimetsu no Yaiba Season 1 Episode 1.

---
Copyright Disclaimer Under Section 107 of the Copyright Act 1976:
Allowance is made for "fair use" for purposes such as criticism, comment, news reporting, teaching, scholarship, and research. Fair use is a use permitted by copyright statute that might otherwise be infringing. Non-profit, educational or personal use tips the balance in favor of fair use.
All anime video clips and audio belong to their respective copyright holders (e.g. Ufotable, MAPPA, Shueisha, Aniplex). This video is an analytical, transformative recap and commentary.
Channel: Bhaloo Ji
---
#anime #demonslayerkimetsunoyaiba #animerecap #shorts #bhalooji #otaku
```
