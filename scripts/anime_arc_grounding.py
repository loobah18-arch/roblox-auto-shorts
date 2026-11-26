#!/usr/bin/env python3
"""
Grounded arc recap writer (Recap-kun style).

1. Finds each episode's opening / ending song by matching 1-fps thumbnails across the arc's
   episodes (the OP/ED are the long stretches every episode shares).
2. Transcribes the rest of each episode with the Groq Whisper API (whisper-large-v3;
   /audio/translations when the dub is not English). Audio is cut to mono 16 kHz 32 kbps
   MP3 and chunked well under the 25 MB free-tier limit. Transcripts are cached in
   cache/transcripts/<episode_key>.json.
3. Asks the LLM for a per-episode recap as beats {text, src_start, src_end} grounded in the
   timestamped dialogue, plus a real chapter title. Every answer is validated
   (chronological, inside the episode, no hype filler, enough words) and the run fails
   when no model produces a valid script: template filler is never produced here.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import numpy as np

from anime_llm import complete, extract_json

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = WORKSPACE_DIR / "cache"
TRANSCRIPT_DIR = CACHE_DIR / "transcripts"
UA = "bhaloo-ji-engine/2.0"

GROQ_STT = "https://api.groq.com/openai/v1/audio"
CHUNK_SECONDS = 900.0          # 900 s at 32 kbps ~= 3.6 MB, far below the 25 MB cap
MAX_UPLOAD_BYTES = 24 * 1024 * 1024
TRANSCRIPT_VERSION = 2

# Words-per-second the narrator speaks at (edge-tts ChristopherNeural at +10% ~= 190 wpm)
NARRATION_WPS = 3.15
EP_MIN_WORDS = 380             # ~2 min floor: shorter means the model skipped the plot
EP_MAX_WORDS = 900             # ~4.8 min ceiling: longer is padding

FILLER_PATTERNS = [
    r"\bsmash (?:that )?like\b", r"\bsubscribe\b", r"\bcomment below\b", r"\bhit the bell\b",
    r"\bunexpected techniques?\b", r"\benemy forces\b", r"\bstakes (?:have never been|are) higher\b",
    r"\bbuckle up\b", r"\bget ready\b", r"\bin this (?:video|episode recap)\b", r"\bwithout further ado\b",
    r"\bjaw-?dropping\b", r"\bmind-?blowing\b", r"\byou won'?t believe\b", r"\bstay tuned\b",
    r"\blet'?s dive in\b", r"\bthings are about to get\b", r"\bnothing will ever be the same\b",
]
_FILLER_RE = re.compile("|".join(FILLER_PATTERNS), re.I)


def log(msg: str) -> None:
    print(f"[arc_grounding] {msg}", flush=True)


class GroundingError(RuntimeError):
    """Raised when an episode cannot be grounded (no transcript / no valid LLM script)."""


# ----------------------------------------------------------------------------------------- media helpers
def probe_duration(path: str | Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def probe_video_size(path: str | Path) -> tuple[int, int]:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0:s=x", str(path)], capture_output=True, text=True)
    try:
        w, h = r.stdout.strip().split("\n")[0].split("x")[:2]
        return int(w), int(h)
    except Exception:
        return 0, 0


def _thumbs(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-vf", "fps=1,scale=32:18",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
    n = len(raw) // (32 * 18)
    return np.frombuffer(raw[: n * 32 * 18], np.uint8).reshape(n, 32 * 18).astype(np.float32)


def _shared_runs(a: np.ndarray, b: np.ndarray, min_len: int = 40) -> list[tuple[int, int, int, int]]:
    """Long diagonal runs of matching 1-fps thumbnails between two episodes: (a_start, a_end, b_start, b_end)."""
    def norm(x):
        x = x - x.mean(1, keepdims=True)
        return x / (np.linalg.norm(x, axis=1, keepdims=True) + 1e-3)
    S = norm(a) @ norm(b).T
    valid = (a.std(1) > 6)[:, None] & (b.std(1) > 6)[None, :]
    M = (S > 0.8) & valid
    M2 = M.copy()
    M2[:, 1:] |= M[:, :-1]
    M2[:, :-1] |= M[:, 1:]
    n, m = M2.shape
    runs = []
    for d in range(-n + 1, m):
        diag = np.diagonal(M2, offset=d)
        idx = np.flatnonzero(diag)
        if len(idx) < min_len // 2:
            continue
        br = np.flatnonzero(np.diff(idx) > 8)
        starts = np.r_[idx[0], idx[br + 1]]
        ends = np.r_[idx[br], idx[-1]]
        for s, e in zip(starts, ends):
            cnt = int(((idx >= s) & (idx <= e)).sum())
            if e - s >= min_len and cnt >= 0.5 * (e - s):
                i0 = max(0, -d)
                runs.append((int(i0 + s), int(i0 + e), int(i0 + s + d), int(i0 + e + d)))
    return runs


def _merge(ranges: list[tuple[float, float]], pad: float = 0.0) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for s, e in sorted((max(0.0, s - pad), e + pad) for s, e in ranges):
        if out and s <= out[-1][1] + 2:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(round(s, 1), round(e, 1)) for s, e in out]


def detect_song_ranges(episode_paths: dict[str, Path]) -> dict[str, list[tuple[float, float]]]:
    """OP/ED ranges per episode (seconds), found as stretches (>=40 s) shared with another episode of the arc."""
    keys = [k for k, p in episode_paths.items() if Path(p).exists() and Path(p).stat().st_size > 1_000_000]
    cache_f = TRANSCRIPT_DIR / ("songs_" + "_".join(sorted(keys))[:150] + ".json")
    if cache_f.exists():
        try:
            data = json.loads(cache_f.read_text())
            return {k: [tuple(r) for r in v] for k, v in data.items()}
        except Exception:
            pass
    t0 = time.time()
    thumbs = {k: _thumbs(Path(episode_paths[k])) for k in keys}
    found: dict[str, list[tuple[float, float]]] = {k: [] for k in keys}
    for i, ka in enumerate(keys):
        # compare with the next two episodes (wrap around) — enough to catch OP and ED in every episode
        partners = [keys[(i + j) % len(keys)] for j in (1, 2)] if len(keys) > 1 else []
        for kb in dict.fromkeys(p for p in partners if p != ka):
            for a0, a1, b0, b1 in _shared_runs(thumbs[ka], thumbs[kb]):
                found[ka].append((a0, a1))
                found[kb].append((b0, b1))
    result = {}
    for k in keys:
        dur = len(thumbs[k])
        rngs = _merge(found[k], pad=2.0)
        # drop the post-credits preview: a short tail right after an ED near the end is the next-episode trailer
        tail = [r for r in rngs if r[0] > dur * 0.8]
        if tail and dur - tail[-1][1] < 75:
            rngs = rngs[:-1] + [(tail[-1][0], float(dur))]
        result[k] = rngs
        log(f"{k}: OP/ED ranges {rngs} (episode {dur}s)")
    log(f"song detection took {time.time() - t0:.0f}s")
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    cache_f.write_text(json.dumps(result))
    return result


def keep_ranges(duration: float, songs: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out, cur = [], 0.0
    for s, e in sorted(songs):
        if s - cur >= 5:
            out.append((cur, s))
        cur = max(cur, e)
    if duration - cur >= 5:
        out.append((cur, duration))
    return out


# ----------------------------------------------------------------------------------------- Groq Whisper
def _multipart(fields: dict, file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = "----bhaloo" + uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        vals = v if isinstance(v, list) else [v]
        for vv in vals:
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{vv}\r\n".encode())
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; filename=\"{file_path.name}\"\r\n"
                 f"Content-Type: audio/mpeg\r\n\r\n".encode() + file_path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), boundary


def _groq_stt(task: str, model: str, mp3: Path, key: str, prompt: str = "") -> dict:
    fields = {"model": model, "response_format": "verbose_json", "temperature": "0"}
    if task == "transcriptions":
        fields["timestamp_granularities[]"] = "segment"
    if prompt:
        fields["prompt"] = prompt[:400]
    body, boundary = _multipart(fields, "file", mp3)
    req = urllib.request.Request(f"{GROQ_STT}/{task}", data=body, method="POST", headers={
        "Authorization": f"Bearer {key}", "Content-Type": f"multipart/form-data; boundary={boundary}", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))


def _stt_with_retry(task: str, models: list[str], mp3: Path, key: str, prompt: str, label: str) -> tuple[dict, str]:
    """Calls Groq STT, alternating models on 429 and waiting out short rate-limit windows."""
    last = None
    waited = 0.0
    for round_ in range(8):
        for model in models:
            try:
                t0 = time.time()
                res = _groq_stt(task, model, mp3, key, prompt)
                log(f"{label}: {task} {model} OK in {time.time() - t0:.1f}s ({len(res.get('segments') or [])} segments)")
                return res, model
            except urllib.error.HTTPError as e:
                body = ""
                try:
                    body = e.read().decode("utf-8", "replace")
                except Exception:
                    pass
                ra = e.headers.get("retry-after") if e.headers else None
                log(f"{label}: {task} {model} HTTP {e.code} (retry-after={ra}): {body[:400]}")
                last = (e.code, body, ra)
                if e.code not in (429, 500, 502, 503, 504):
                    raise GroundingError(f"Groq {task} {model} HTTP {e.code}: {body[:300]}")
            except Exception as e:
                log(f"{label}: {task} {model} failed: {e!r}")
                last = (0, repr(e), None)
        # every model refused this round: wait (bounded) and try again
        code, body, ra = last or (0, "", None)
        try:
            wait = float(ra) if ra else 30.0
        except Exception:
            wait = 30.0
        m = re.search(r"try again in (?:(\d+)m)?(\d+(?:\.\d+)?)s", body or "")
        if m:
            wait = max(wait, float(m.group(1) or 0) * 60 + float(m.group(2)))
        wait = min(max(wait, 10.0), 900.0)
        if waited + wait > 2400:
            break
        log(f"{label}: all STT models busy, waiting {wait:.0f}s (round {round_ + 1})")
        time.sleep(wait + 2)
        waited += wait
    raise GroundingError(f"{label}: Groq Whisper never answered: {last}")


def _cut_mp3(src: Path, start: float, dur: float, out: Path) -> None:
    cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{dur:.2f}", "-i", str(src),
           "-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "32k", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        raise GroundingError(f"audio cut failed for {src.name} @{start:.0f}s: {r.stderr[-300:]}")


def detect_dub_language(video: Path, start: float, key: str) -> str:
    """'en' when the dub is English, else the language Whisper reports (lowercase name or code)."""
    forced = os.environ.get("ARC_AUDIO_LANGUAGE", "").strip().lower()
    if forced:
        return forced
    with tempfile.TemporaryDirectory() as td:
        mp3 = Path(td) / "probe.mp3"
        _cut_mp3(video, start, 45.0, mp3)
        res, _ = _stt_with_retry("transcriptions", ["whisper-large-v3-turbo", "whisper-large-v3"], mp3, key, "", "language probe")
    lang = (res.get("language") or "").strip().lower()
    log(f"dub language probe: '{lang}' sample='{(res.get('text') or '')[:120]}'")
    return "en" if lang in ("en", "english") else (lang or "unknown")


_HALLUCINATION_RE = re.compile(
    r"^(thank you( so much)? for watching|thanks for watching|please subscribe|subtitles by|"
    r"translated by|subs by|♪+|\.+|you)\W*$", re.I)


def _clean_segments(raw_segments: list[dict], offset: float) -> list[dict]:
    out = []
    prev = ""
    for s in raw_segments or []:
        text = re.sub(r"\s+", " ", (s.get("text") or "")).strip()
        if not text or _HALLUCINATION_RE.match(text):
            continue
        if "♪" in text or "♫" in text:
            continue
        if float(s.get("no_speech_prob", 0)) > 0.7 and float(s.get("avg_logprob", 0)) < -0.8:
            continue
        if float(s.get("compression_ratio", 1)) > 2.6:
            continue
        if text == prev:
            continue
        prev = text
        out.append({"start": round(offset + float(s["start"]), 2), "end": round(offset + float(s["end"]), 2), "text": text})
    return out


def transcribe_episode(ep_key: str, video: Path, songs: list[tuple[float, float]], lang: str, key: str,
                       context_prompt: str = "") -> dict:
    """Timestamped English dialogue of one episode (OP/ED skipped). Cached in cache/transcripts/."""
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    cache_f = TRANSCRIPT_DIR / f"{ep_key}.json"
    if cache_f.exists():
        try:
            data = json.loads(cache_f.read_text())
            if data.get("version") == TRANSCRIPT_VERSION and data.get("segments"):
                log(f"{ep_key}: transcript from cache ({len(data['segments'])} segments, {data.get('task')})")
                return data
        except Exception:
            pass
    duration = probe_duration(video)
    ranges = keep_ranges(duration, songs)
    if lang == "en":
        task, models = "transcriptions", ["whisper-large-v3", "whisper-large-v3-turbo"]
    else:
        task, models = "translations", ["whisper-large-v3"]
    segments: list[dict] = []
    used_models = set()
    with tempfile.TemporaryDirectory() as td:
        for r0, r1 in ranges:
            n = max(1, math.ceil((r1 - r0) / CHUNK_SECONDS))
            step = (r1 - r0) / n
            for i in range(n):
                c0 = r0 + i * step
                c1 = min(r1, c0 + step)
                mp3 = Path(td) / f"{ep_key}_{int(c0)}.mp3"
                _cut_mp3(video, c0, c1 - c0, mp3)
                if mp3.stat().st_size > MAX_UPLOAD_BYTES:
                    raise GroundingError(f"{mp3.name} is {mp3.stat().st_size} bytes, over the Groq limit")
                label = f"{ep_key} [{c0:.0f}-{c1:.0f}s]"
                try:
                    res, mdl = _stt_with_retry(task, models, mp3, key, context_prompt, label)
                except GroundingError:
                    if task != "translations":
                        raise
                    # whisper-large-v3 translation quota exhausted: transcribe in the original language with
                    # turbo instead; the LLM reads Japanese fine and still writes English narration.
                    log(f"{label}: translation unavailable, falling back to original-language transcription (turbo)")
                    res, mdl = _stt_with_retry("transcriptions", ["whisper-large-v3-turbo"], mp3, key, "", label)
                used_models.add(mdl)
                segments.extend(_clean_segments(res.get("segments") or [], c0))
    data = {"version": TRANSCRIPT_VERSION, "episode_key": ep_key, "duration": duration, "task": task,
            "language": lang, "models": sorted(used_models), "songs": songs, "segments": segments}
    if len(segments) < 20:
        raise GroundingError(f"{ep_key}: transcript has only {len(segments)} usable segments")
    cache_f.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    log(f"{ep_key}: transcribed {len(segments)} segments ({task}, {sorted(used_models)})")
    return data


_CREDIT_RE = re.compile(r"thank(s| you) for watching|please subscribe|subtitles? by|translated by|subs by", re.I)


def transcript_for_prompt(transcript: dict) -> str:
    return "\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in transcript["segments"]
                     if not _CREDIT_RE.search(s["text"]))


# ----------------------------------------------------------------------------------------- beats
def validate_beats(beats: list, ep_duration: float, songs: list | None = None, min_words: int = EP_MIN_WORDS,
                   max_words: int = EP_MAX_WORDS, min_beat_words: int = 6, max_beat_words: int = 60,
                   min_beats: int = 8, free_first: bool = False) -> list[dict]:
    """
    Validate and normalise an episode's beats. Raises ValueError (with every problem found) on a bad
    script. Rules: 8+ beats; each has narration text of 6-60 words with no hype filler; src_start <
    src_end, both inside the episode; beats run in story order (start times never go back more than
    15 s); total words within [min_words, max_words]. free_first: beat 0 is a cold-open hook that may
    show a moment from anywhere in the episode, so it does not take part in the story-order check.
    """
    problems = []
    if not isinstance(beats, list) or len(beats) < min_beats:
        raise ValueError(f"need at least {min_beats} beats, got {len(beats) if isinstance(beats, list) else type(beats).__name__}")
    clean = []
    prev_start = -1.0
    max_beat = 0
    back_in_time = 0
    total_words = 0
    for i, b in enumerate(beats):
        if not isinstance(b, dict):
            problems.append(f"beat {i} is not an object")
            continue
        text = re.sub(r"\s+", " ", str(b.get("text", ""))).strip()
        try:
            s = float(b.get("src_start"))
            e = float(b.get("src_end"))
        except Exception:
            problems.append(f"beat {i} has non-numeric timestamps")
            continue
        words = len(text.split())
        total_words += words
        if words < min_beat_words:
            problems.append(f"beat {i} too short ({words} words)")
        if words > max_beat_words:
            problems.append(f"beat {i} too long ({words} words)")
        m = _FILLER_RE.search(text)
        if m:
            problems.append(f"beat {i} uses filler phrase '{m.group(0)}'")
        if not (0 <= s < e <= ep_duration + 1.0):
            problems.append(f"beat {i} range {s:.1f}-{e:.1f} outside episode (0-{ep_duration:.0f})")
        if e - s > 120:
            problems.append(f"beat {i} range {s:.1f}-{e:.1f} is longer than 120 s (bracket only the moment described)")
        if s < prev_start - 15.0:
            back_in_time += 1
            if back_in_time <= 3:
                problems.append(f"beat {i} goes back in time ({s:.1f} after beat {max_beat} at {prev_start:.1f}; "
                                f"check beat {max_beat}'s timestamps)")
        if songs and e > s:
            in_song = sum(max(0.0, min(e, float(b)) - max(s, float(a))) for a, b in songs)
            if in_song > 0.5 * (e - s):
                problems.append(f"beat {i} range {s:.1f}-{e:.1f} is mostly inside the opening/ending song")
        if not (free_first and i == 0) and s > prev_start:
            prev_start, max_beat = s, i
        clean.append({"text": text, "src_start": round(s, 2), "src_end": round(min(e, ep_duration), 2)})
    if total_words < min_words:
        problems.append(f"only {total_words} words (need >= {min_words})")
    if total_words > max_words:
        problems.append(f"{total_words} words (max {max_words})")
    if problems:
        raise ValueError("; ".join(problems[:12]))
    return clean


SYSTEM_PROMPT = (
    "You are the head writer of a Recap-kun style anime recap channel. You retell episodes as a dense, chronological, "
    "third-person present-tense story. Every sentence states a concrete plot event or explains something the viewer "
    "needs (who someone is, what a power does, why a character acts). You never hype, never address the viewer, never "
    "use filler. You only state what the transcript supports. You answer with JSON only."
)

STYLE_EXAMPLE = (
    "The story begins as a boy named Elma prepares for the ritual of divine blessings, and his father tells him to have "
    "faith in the sword god since he's the heir to their family of sword prodigies. "
    "We learn that a lot of players considered it a defective class because even though its defense is unrivaled, its "
    "attack power is so weak that it struggles to defeat monsters on its own. "
    "At that moment, a girl from a branch family named Melis asks if she can take the ritual."
)


def build_episode_prompt(arc: dict, ep_num: int, ep_index: int, n_eps: int, transcript: dict, story_so_far: str) -> str:
    dur = transcript["duration"]
    songs = transcript.get("songs") or []
    song_txt = ", ".join(f"{s:.0f}-{e:.0f}s" for s, e in songs) or "none detected"
    opener = ("Start the first beat with \"The story begins as\"." if ep_index == 0
              else "Continue straight from the previous episode (no re-introduction, no 'previously').")
    return f"""Series: {arc.get('series')} — {arc.get('arc_name')} (episode {ep_num}, {ep_index + 1} of {n_eps} in this arc).
Story so far (from the earlier episodes of this arc): {story_so_far or 'This is the first episode of the arc.'}

Below is the timestamped English dialogue of the whole episode (seconds from the start of the episode file).
Opening/ending songs ({song_txt}) were removed. Episode length: {dur:.0f}s.

TRANSCRIPT:
{transcript_for_prompt(transcript)}

TASK: Write the narration for this episode of our long-form arc recap.
- Retell everything that happens in this episode in order, as beats. One beat = one narration sentence of 12-35 words.
- Aim for {int(EP_MIN_WORDS * 1.25)}-{int(EP_MAX_WORDS * 0.85)} words in total (about 2.5-4 minutes spoken). Do not pad.
- Style: third person, present tense, dense and factual, like this example: "{STYLE_EXAMPLE}"
  Use connectors such as "Meanwhile,", "At that moment,", "We learn that", "However,", "Suddenly,". {opener}
- Use character names as they are commonly known in the English release (e.g. Tanjiro, Nezuko, Zenitsu, Inosuke).
- No hype or filler ("get ready", "jaw-dropping", "things are about to get intense"), no questions to the viewer,
  no "in this episode", no mention of subscribing.
- For every beat give src_start and src_end: the episode seconds of the exact moment that sentence describes,
  taken from the transcript timestamps (a beat about a silent action scene uses the time between the surrounding
  lines). The viewer sees exactly this footage while the sentence is read, so bracket only that moment: normally
  5-25 seconds, never more than 60, and never spanning unrelated dialogue before or after it. Beats must follow
  the episode's order, and nothing may come from the opening/ending song ranges.
- chapter_title: a vivid 3-7 word title for this episode's chapter (not "Chapter 1", no episode numbers).
- story_so_far: 2-3 sentences summarising the whole arc up to the end of this episode (for the next episode's writer).
- climax_hint: the src_start of the most intense action moment of this episode.

Return JSON: {{"chapter_title": str, "beats": [{{"text": str, "src_start": number, "src_end": number}}, ...],
"story_so_far": str, "climax_hint": number}}"""


def write_episode_beats(arc: dict, ep_num: int, ep_index: int, n_eps: int, transcript: dict, story_so_far: str) -> dict:
    prompt = build_episode_prompt(arc, ep_num, ep_index, n_eps, transcript, story_so_far)
    dur = transcript["duration"]
    holder: dict = {}

    def validator(text: str) -> None:
        data = extract_json(text)
        if not isinstance(data, dict):
            raise ValueError("answer is not a JSON object")
        title = re.sub(r"\s+", " ", str(data.get("chapter_title", ""))).strip().strip('"')
        if not title or re.match(r"^(chapter|episode|ep\.?)\s*\d", title, re.I) or len(title) > 70:
            raise ValueError(f"bad chapter_title {title!r}")
        holder["beats"] = validate_beats(data.get("beats"), dur, transcript.get("songs"))
        holder["chapter_title"] = title
        holder["story_so_far"] = str(data.get("story_so_far", "")).strip()
        try:
            holder["climax_hint"] = float(data.get("climax_hint"))
        except Exception:
            holder["climax_hint"] = None

    res = complete(prompt, system=SYSTEM_PROMPT, json_mode=True, temperature=0.5, max_tokens=16000,
                   validator=validator, label=f"episode {ep_num} beats")
    if not res:
        raise GroundingError(f"no LLM produced a valid recap script for episode {ep_num}")
    holder["model"] = res[1]
    return holder


def write_premise_title(arc: dict, summary: str, chapter_titles: list[str], part_label: str = "") -> tuple[str, str]:
    prompt = f"""We made a long-form recap of {arc.get('series')} — {arc.get('arc_name')}.
What happens: {summary}
Chapters: {', '.join(chapter_titles)}

Write the YouTube title in Recap-kun's premise style: a plain-English one-sentence premise of the story without the
anime's name, written as "<who> <does/suffers what> So/But <what follows>", e.g.
"Boy Loses His Family to Demons So He Becomes a Demon Slayer to Save His Sister" or
"Boy is Kicked Out For Getting the Weakest Shield Class But Becomes Overpowered By MAXING His Defense".
Title Case, at most {95 - len(part_label)} characters, no emojis, no hashtags, no quotes.
Return JSON: {{"title": str}}"""

    def validator(text: str) -> None:
        t = str(extract_json(text).get("title", "")).strip().strip('"')
        if not (25 <= len(t) <= 95 - len(part_label)):
            raise ValueError(f"title length {len(t)}: {t!r}")
        if "#" in t:
            raise ValueError("hashtag in title")

    res = complete(prompt, system="You write YouTube titles for an anime recap channel. JSON only.", json_mode=True,
                   temperature=0.8, max_tokens=2000, validator=validator, label="premise title")
    if not res:
        raise GroundingError("no LLM produced a valid video title")
    title = str(extract_json(res[0])["title"]).strip().strip('"')
    return (f"{title}{part_label}")[:100], res[1]


# ----------------------------------------------------------------------------------------- whole arc
# Names that Whisper tends to mangle; passed as the STT prompt so spellings come out right.
SERIES_NAME_HINTS = {
    "demon-slayer": "Tanjiro, Nezuko, Zenitsu, Inosuke, Giyu Tomioka, Shinobu Kocho, Rui, Muzan, Kanao, "
                    "Murata, Hashira, Demon Slayer Corps, Breathing, Lower Moon, Kasugai crow",
    "jujutsu-kaisen": "Yuji Itadori, Megumi Fushiguro, Nobara Kugisaki, Satoru Gojo, Sukuna, Nanami, Mahito, "
                      "cursed energy, Domain Expansion, Jujutsu High",
}


def clip_out_of_songs(s: float, e: float, songs: list) -> tuple[float, float]:
    """Trim a source range so it does not start or end inside an OP/ED range."""
    for a, b in songs or []:
        a, b = float(a), float(b)
        if a <= s < b:
            s = b
        if a < e <= b:
            e = a
    return s, e


_STOP = set("""about above after again against also among another because been before being below between both
could does doing down during each from further have having here herself himself into itself just more most
other over same should some such than that their them then there these they this those through under until very
what when where which while whom will with would your yours story begins meanwhile moment learn suddenly however
while finally later still even back away only every""".split())


def _keys(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z]+", text.lower().replace("z", "s")):
        if len(w) >= 4 and w not in _STOP:
            out.add(w[:5])
    return out


def focus_beat_range(text: str, s: float, e: float, segments: list[dict], min_window: float = 12.0) -> tuple[float, float]:
    """
    Narrow a beat's source range to the part whose dialogue shares the most words with the narration
    sentence, so the footage shown is the moment described rather than the start of a long range.
    Returns the (possibly unchanged) range; never leaves [s, e].
    """
    est = len(text.split()) / 2.85
    window = max(min_window, est * 1.6)
    if e - s <= window * 1.25:
        return s, e
    keys = _keys(text)
    segs = [g for g in segments if g["end"] > s and g["start"] < e]
    if not keys or not segs:
        return s, e
    best, best_t = 0.0, None
    for g in segs:
        t0 = max(s, min(g["start"] - 1.0, e - window))
        score = sum(len(keys & _keys(h["text"])) for h in segs if h["start"] < t0 + window and h["end"] > t0)
        if score > best:
            best, best_t = score, t0
    if best_t is None or best < 1:
        return s, e
    return round(best_t, 2), round(min(e, best_t + window), 2)


def ground_arc(arc: dict, episode_paths: dict[str, Path], episode_numbers: dict[str, int] | None = None) -> dict:
    """
    Ground every episode of an arc: OP/ED detection, Whisper transcript, LLM beats.
    Returns {"episodes": [{episode_key, episode, duration, songs, chapter_title, beats, story_so_far,
    climax_hint, model}], "language": str}. Raises GroundingError when any episode cannot be grounded:
    the caller must not fall back to template narration.
    """
    keys = list(episode_paths.keys())
    missing = [k for k in keys if not Path(episode_paths[k]).exists() or Path(episode_paths[k]).stat().st_size < 1_000_000]
    if missing:
        raise GroundingError(f"episodes missing on disk: {missing}")
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not groq_key:
        cached = all((TRANSCRIPT_DIR / f"{k}.json").exists() for k in keys)
        if not cached:
            raise GroundingError("GROQ_API_KEY is not set and transcripts are not cached")
    songs = detect_song_ranges(episode_paths)
    first = keys[0]
    probe_at = 120.0
    for a, b in songs.get(first, []):
        if a < 300:
            probe_at = max(probe_at, b + 5)
    lang = "en"
    if not all((TRANSCRIPT_DIR / f"{k}.json").exists() for k in keys):
        lang = detect_dub_language(Path(episode_paths[first]), probe_at, groq_key)
    names = SERIES_NAME_HINTS.get(arc.get("series_id", ""), "")
    out_eps = []
    story = ""
    t0 = time.time()
    for i, k in enumerate(keys):
        ep_num = (episode_numbers or {}).get(k) or i + 1
        tr = transcribe_episode(k, Path(episode_paths[k]), songs.get(k, []), lang, groq_key, names)
        tr["songs"] = songs.get(k, tr.get("songs") or [])
        res = write_episode_beats(arc, ep_num, i, len(keys), tr, story)
        for b in res["beats"]:
            s, e = clip_out_of_songs(b["src_start"], b["src_end"], tr["songs"])
            if e - s >= 2.0:
                b["src_start"], b["src_end"] = round(s, 2), round(e, 2)
            fs, fe = focus_beat_range(b["text"], b["src_start"], b["src_end"], tr["segments"])
            if (fs, fe) != (b["src_start"], b["src_end"]):
                b["llm_src"] = [b["src_start"], b["src_end"]]
                b["src_start"], b["src_end"] = fs, fe
        story = res.get("story_so_far") or story
        words = sum(len(b["text"].split()) for b in res["beats"])
        log(f"{k}: '{res['chapter_title']}' {len(res['beats'])} beats, {words} words ({res['model']})")
        out_eps.append({"episode_key": k, "episode": ep_num, "duration": tr["duration"], "songs": tr["songs"],
                        "chapter_title": res["chapter_title"], "beats": res["beats"],
                        "story_so_far": res.get("story_so_far", ""), "climax_hint": res.get("climax_hint"),
                        "model": res["model"]})
    log(f"grounded {len(out_eps)} episodes in {time.time() - t0:.0f}s")
    return {"episodes": out_eps, "language": lang}
