#!/usr/bin/env python3
"""
Voiceover and Animated Dynamic Subtitle Engine for Bhaloo Ji Anime Explanation Channel.
Uses Edge-TTS for high-quality neural voiceover and generates viral-style
word-by-word animated ASS karaoke subtitles.
"""

import asyncio
import os
import re
from datetime import timedelta
from pathlib import Path
import edge_tts

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_VOICE = "en-US-ChristopherNeural"  # Engaging, cinematic narrator
DEFAULT_RATE = "+6%"                      # Brisk, high-retention anime recap pace


def format_ass_time(seconds: float) -> str:
    """Format seconds (float) to ASS timestamp: H:MM:SS.cs"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis >= 100:
        secs += 1
        centis = 0
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def build_ass_header(font_name: str = "DejaVu Sans Bold") -> str:
    """Generate ASS header configured for 1080x1920 vertical canvas."""
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},66,&H00FFFFFF,&H0000FFFF,&H00000000,&HA0000000,-1,0,0,0,100,100,1,0,1,5.0,2.0,2,60,60,560,1
Style: CardHeader,{font_name},36,&H00FFFFFF,&H0000FFFF,&H00000000,&HB0000000,-1,0,0,0,100,100,2,0,1,3.0,1.0,8,60,60,160,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def cues_to_ass(word_cues: list[dict], badge_text: str = "") -> str:
    """
    Convert word-level timing cues into animated karaoke subtitle events.
    word_cues: list of {'word': str, 'start': float, 'end': float}
    """
    ass_lines = [build_ass_header()]

    # If badge text is provided, show permanent stylish top header
    if badge_text and word_cues:
        start_time = "0:00:00.00"
        end_time = format_ass_time(word_cues[-1]["end"] + 0.5)
        # Top pill badge
        ass_lines.append(f"Dialogue: 1,{start_time},{end_time},CardHeader,,0,0,0,,{{\\an8\\bord3\\shad1\\c&H00D7FF&}}• {badge_text.upper()} •")

    if not word_cues:
        return "\n".join(ass_lines)

    # Group words into short readable chunks (3 to 5 words)
    chunks = []
    current_chunk = []
    for cue in word_cues:
        current_chunk.append(cue)
        clean_text = cue["word"].strip()
        # Break on punctuation or after 4 words
        if len(current_chunk) >= 4 or any(clean_text.endswith(p) for p in [".", "!", "?", ","]):
            chunks.append(current_chunk)
            current_chunk = []
    if current_chunk:
        chunks.append(current_chunk)

    # For each chunk, generate events for each word being highlighted
    for chunk in chunks:
        for idx, active_cue in enumerate(chunk):
            w_start = format_ass_time(active_cue["start"])
            w_end = format_ass_time(active_cue["end"])

            # Build line text with active word highlighted
            words_formatted = []
            for j, cue in enumerate(chunk):
                raw_word = cue["word"].strip().upper()
                if j == idx:
                    # Active word: Yellow-gold glow, pop-in scale
                    words_formatted.append(f"{{\\c&H0000FFFF&\\t(0,70,\\fscx112\\fscy112)}}{raw_word}{{\\rDefault}}")
                else:
                    words_formatted.append(f"{{\\c&H00FFFFFF&}}{raw_word}")

            line_text = " ".join(words_formatted)
            ass_lines.append(f"Dialogue: 0,{w_start},{w_end},Default,,0,0,0,,{line_text}")

    return "\n".join(ass_lines) + "\n"


async def generate_voice_and_subtitles(
    text: str,
    output_audio_path: str | Path,
    output_ass_path: str | Path,
    badge_text: str = "",
    voice: str = DEFAULT_VOICE,
    rate: str = DEFAULT_RATE,
) -> dict:
    """
    Generate audio and word-aligned ASS subtitles using Edge-TTS.
    """
    output_audio_path = Path(output_audio_path)
    output_ass_path = Path(output_ass_path)
    output_audio_path.parent.mkdir(parents=True, exist_ok=True)
    output_ass_path.parent.mkdir(parents=True, exist_ok=True)

    communicate = edge_tts.Communicate(text, voice=voice, rate=rate)
    
    word_cues = []
    sentence_cues = []

    with open(output_audio_path, "wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                word_cues.append({
                    "word": chunk["text"],
                    "start": chunk["offset"] / 10_000_000.0,
                    "end": (chunk["offset"] + chunk["duration"]) / 10_000_000.0,
                })
            elif chunk["type"] == "SentenceBoundary":
                sentence_cues.append({
                    "text": chunk["text"],
                    "offset": chunk["offset"],
                    "duration": chunk["duration"],
                })

    # If WordBoundary wasn't provided, interpolate from SentenceBoundary
    if not word_cues and sentence_cues:
        for sent in sentence_cues:
            words = sent["text"].strip().split()
            if not words:
                continue
            total_chars = max(1, sum(len(w) for w in words))
            cur_offset = sent["offset"]
            for w in words:
                w_dur = int(sent["duration"] * (len(w) / total_chars))
                word_cues.append({
                    "word": w,
                    "start": cur_offset / 10_000_000.0,
                    "end": (cur_offset + w_dur) / 10_000_000.0,
                })
                cur_offset += w_dur

    ass_content = cues_to_ass(word_cues, badge_text=badge_text)
    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.write(ass_content)

    duration = word_cues[-1]["end"] if word_cues else 0.0

    return {
        "audio_path": str(output_audio_path),
        "ass_path": str(output_ass_path),
        "duration": duration,
        "word_count": len(word_cues),
    }


def produce_part_audio_subtitles(
    text: str,
    output_audio_path: str | Path,
    output_ass_path: str | Path,
    badge_text: str = "",
    voice: str = DEFAULT_VOICE,
    rate: str = DEFAULT_RATE,
) -> dict:
    """Synchronous wrapper for generate_voice_and_subtitles."""
    return asyncio.run(
        generate_voice_and_subtitles(
            text=text,
            output_audio_path=output_audio_path,
            output_ass_path=output_ass_path,
            badge_text=badge_text,
            voice=voice,
            rate=rate,
        )
    )


if __name__ == "__main__":
    sample_text = (
        "Tanjiro Kamado spent the night selling charcoal in town, completely unaware of the nightmare waiting for him at home. "
        "The moment he steps onto his porch, the horrifying scent of blood hits him! "
        "His sister Nezuko has turned into a demon and attacks with supernatural strength!"
    )
    test_audio = WORKSPACE_DIR / "output" / "test_voice.mp3"
    test_ass = WORKSPACE_DIR / "output" / "test_subtitles.ass"

    print("Generating sample voiceover and subtitles...")
    res = produce_part_audio_subtitles(
        text=sample_text,
        output_audio_path=test_audio,
        output_ass_path=test_ass,
        badge_text="DEMON SLAYER • S01E01 • PART 1/3"
    )
    print(f"Generated {res['duration']:.2f}s audio with {res['word_count']} words.")
    print(f"Audio: {res['audio_path']}")
    print(f"Subtitles: {res['ass_path']}")
