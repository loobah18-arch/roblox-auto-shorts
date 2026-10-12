#!/usr/bin/env python3
"""
Voiceover and Animated Dynamic Subtitle Engine for Bhaloo Ji Anime Explanation Channel.
Uses Edge-TTS for high-quality neural voiceover and generates viral-style
word-by-word animated ASS karaoke subtitles.
"""

import asyncio
import os
import re
import subprocess
from datetime import timedelta
from pathlib import Path
import edge_tts

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_VOICE = "en-US-ChristopherNeural"  # RecapKun signature articulate, confident anime storyteller voice
DEFAULT_RATE = "+8%"                       # Fast-paced, engaging RecapKun cadence (~185-190 wpm)


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


def build_ass_header(font_name: str = "DejaVu Sans Bold", is_landscape: bool = False) -> str:
    """Generate ASS header configured for 1080x1920 vertical canvas or 1920x1080 landscape canvas."""
    if is_landscape:
        # 16:9 Widescreen (1920x1080) for Full Episode Videos
        # Bottom-third placement (Alignment: 2, MarginV: 90, Fontsize: 52)
        return f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},52,&H00FFFFFF,&H0000FFFF,&H00000000,&HA0000000,-1,0,0,0,100,100,1,0,1,4.0,2.0,2,80,80,90,1
Style: CardHeader,{font_name},32,&H00FFFFFF,&H0000FFFF,&H00000000,&HB0000000,-1,0,0,0,100,100,2,0,1,3.0,1.0,8,80,80,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    else:
        # 9:16 Vertical (1080x1920) for YouTube Shorts
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


def cues_to_ass(word_cues: list[dict], badge_text: str = "", is_landscape: bool = False) -> str:
    """
    Convert word-level timing cues into animated karaoke subtitle events.
    word_cues: list of {'word': str, 'start': float, 'end': float}
    """
    ass_lines = [build_ass_header(is_landscape=is_landscape)]

    # If badge text is provided and NOT in landscape, show permanent stylish top header
    if badge_text and word_cues and not is_landscape:
        start_time = "0:00:00.00"
        end_time = format_ass_time(word_cues[-1]["end"] + 0.5)
        # Top pill badge
        ass_lines.append(f"Dialogue: 1,{start_time},{end_time},CardHeader,,0,0,0,,{{\\an8\\bord3\\shad1\\c&H00D7FF&}}• {badge_text.upper()} •")

    if not word_cues:
        return "\n".join(ass_lines)

    # Group words into readable chunks (7-8 words for landscape, 3-4 for vertical)
    max_chunk = 7 if is_landscape else 4
    chunks = []
    current_chunk = []
    for cue in word_cues:
        current_chunk.append(cue)
        clean_text = cue["word"].strip()
        # Break on punctuation or after max_chunk words
        if len(current_chunk) >= max_chunk or any(clean_text.endswith(p) for p in [".", "!", "?", ","]):
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
                    scale_tag = "\\fscx108\\fscy108" if is_landscape else "\\fscx112\\fscy112"
                    words_formatted.append(f"{{\\c&H0000FFFF&\\t(0,70,{scale_tag})}}{raw_word}{{\\rDefault}}")
                else:
                    words_formatted.append(f"{{\\c&H00FFFFFF&}}{raw_word}")

            line_text = " ".join(words_formatted)
            ass_lines.append(f"Dialogue: 0,{w_start},{w_end},Default,,0,0,0,,{line_text}")

    return "\n".join(ass_lines) + "\n"


def get_audio_duration(audio_path: str | Path) -> float:
    """Extract precise audio duration in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration:stream=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path)
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        for line in res.stdout.splitlines():
            clean = line.strip()
            if clean and clean != "N/A":
                try:
                    val = float(clean)
                    if val > 0:
                        return val
                except ValueError:
                    continue
        return float(res.stdout.strip())
    except Exception:
        return 0.0


def synthesize_word_cues(text: str, total_duration: float) -> list[dict]:
    """Generate proportional word cues across total_duration when boundary data is absent."""
    words = text.strip().split()
    if not words or total_duration <= 0:
        return []
    total_chars = max(1, sum(len(w) for w in words))
    cur = 0.0
    cues = []
    for w in words:
        dur = total_duration * (len(w) / total_chars)
        cues.append({
            "word": w,
            "start": round(cur, 3),
            "end": round(cur + dur, 3),
        })
        cur += dur
    return cues


async def _synthesize_speech_and_cues(
    text: str,
    output_audio_path: Path,
    voice: str = DEFAULT_VOICE,
    rate: str = DEFAULT_RATE,
) -> list[dict]:
    """
    Synthesize audio and obtain word boundary cues with automated retries,
    sister-voice failover, and zero-dependency gTTS cloud fallback.
    """
    voices_to_try = [voice, "en-US-ChristopherNeural", "en-US-GuyNeural", "en-US-EricNeural", "en-US-AndrewNeural"]
    voices_to_try = list(dict.fromkeys(voices_to_try))

    last_error = None
    audio_data = bytearray()
    word_cues = []
    sentence_cues = []

    for v in voices_to_try:
        for attempt in range(1, 3):
            try:
                communicate = edge_tts.Communicate(text, voice=v, rate=rate)
                audio_data = bytearray()
                word_cues = []
                sentence_cues = []

                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_data.extend(chunk["data"])
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

                if len(audio_data) > 2000:
                    with open(output_audio_path, "wb") as f:
                        f.write(audio_data)
                    break
            except Exception as e:
                last_error = e
                print(f"[anime_voice] ⚠️ TTS warning for voice '{v}' (attempt {attempt}/2): {e}", flush=True)
                await asyncio.sleep(1.0 * attempt)

        if len(audio_data) > 2000:
            break

    # If Edge-TTS succeeded, ensure word_cues are populated
    if len(audio_data) > 2000:
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
        if word_cues:
            return word_cues
        total_dur = get_audio_duration(output_audio_path)
        return synthesize_word_cues(text, total_dur)

    # Edge-TTS failed or was blocked; fall back to gTTS
    print(f"[anime_voice] ⚠️ Edge-TTS unavailable or blocked ({last_error}); switching to reliable gTTS fallback...", flush=True)
    try:
        from gtts import gTTS
        tts = gTTS(text=text, lang="en")
        tts.save(str(output_audio_path))
        total_dur = get_audio_duration(output_audio_path)
        if total_dur <= 0:
            words_cnt = len(text.strip().split())
            total_dur = max(3.0, words_cnt / 2.8)
        print(f"[anime_voice] ✅ Voiceover generated via gTTS fallback ({total_dur:.1f}s).", flush=True)
        return synthesize_word_cues(text, total_dur)
    except Exception as ge:
        raise RuntimeError(f"All speech generation attempts failed. Edge-TTS: {last_error}; gTTS: {ge}")


async def generate_voice_and_subtitles(
    text: str,
    output_audio_path: str | Path,
    output_ass_path: str | Path,
    badge_text: str = "",
    voice: str = DEFAULT_VOICE,
    rate: str = DEFAULT_RATE,
    is_landscape: bool = False,
) -> dict:
    """
    Generate audio and word-aligned ASS subtitles with robust retry & gTTS fallback.
    """
    output_audio_path = Path(output_audio_path)
    output_ass_path = Path(output_ass_path)
    output_audio_path.parent.mkdir(parents=True, exist_ok=True)
    output_ass_path.parent.mkdir(parents=True, exist_ok=True)

    word_cues = await _synthesize_speech_and_cues(text, output_audio_path, voice=voice, rate=rate)

    ass_content = cues_to_ass(word_cues, badge_text=badge_text, is_landscape=is_landscape)
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
    is_landscape: bool = False,
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
            is_landscape=is_landscape,
        )
    )


async def generate_master_voice_and_subtitles(
    chapter_texts: list[str],
    output_audio_path: str | Path,
    output_ass_path: str | Path,
    voice: str = DEFAULT_VOICE,
    rate: str = DEFAULT_RATE,
    is_landscape: bool = True,
) -> dict:
    """
    Generates ONE single continuous audio and subtitle track for the full master video.
    Also calculates exact chapter start/end timestamps and durations from word boundaries.
    """
    full_text = " ".join(t.strip() for t in chapter_texts if t.strip())
    output_audio_path = Path(output_audio_path)
    output_ass_path = Path(output_ass_path)
    output_audio_path.parent.mkdir(parents=True, exist_ok=True)
    output_ass_path.parent.mkdir(parents=True, exist_ok=True)

    word_cues = await _synthesize_speech_and_cues(full_text, output_audio_path, voice=voice, rate=rate)

    ass_content = cues_to_ass(word_cues, badge_text="", is_landscape=is_landscape)
    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.write(ass_content)

    total_duration = word_cues[-1]["end"] if word_cues else 0.0

    # Calculate exact chapter start/end timestamps from word counts
    chapter_segments = []
    current_word_idx = 0
    total_words = len(word_cues)

    for idx, chap_text in enumerate(chapter_texts, 1):
        num_chap_words = len(chap_text.strip().split())
        start_idx = current_word_idx
        end_idx = min(current_word_idx + num_chap_words, total_words)

        if total_words > 0 and start_idx < total_words:
            c_start = word_cues[start_idx]["start"] if idx > 1 else 0.0
            last_word_idx = min(end_idx - 1, total_words - 1)
            c_end = word_cues[last_word_idx]["end"] if idx < len(chapter_texts) else total_duration
            c_dur = max(0.5, c_end - c_start)
        else:
            c_start = 0.0
            c_end = total_duration
            c_dur = total_duration

        chapter_segments.append({
            "part": idx,
            "start_time": round(c_start, 3),
            "end_time": round(c_end, 3),
            "duration": round(c_dur, 3),
            "word_count": num_chap_words,
        })
        current_word_idx = end_idx

    return {
        "audio_path": str(output_audio_path),
        "ass_path": str(output_ass_path),
        "duration": total_duration,
        "word_count": len(word_cues),
        "chapter_segments": chapter_segments,
    }


def produce_master_audio_subtitles(
    chapter_texts: list[str],
    output_audio_path: str | Path,
    output_ass_path: str | Path,
    voice: str = DEFAULT_VOICE,
    rate: str = DEFAULT_RATE,
    is_landscape: bool = True,
) -> dict:
    """Synchronous wrapper for generate_master_voice_and_subtitles."""
    return asyncio.run(
        generate_master_voice_and_subtitles(
            chapter_texts=chapter_texts,
            output_audio_path=output_audio_path,
            output_ass_path=output_ass_path,
            voice=voice,
            rate=rate,
            is_landscape=is_landscape,
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
