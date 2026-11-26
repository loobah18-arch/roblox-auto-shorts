#!/usr/bin/env python3
"""
Single-episode recap writer in the "cold-open storyteller" style of short-form movie recap channels
(reference: MangoCat movie, https://youtu.be/LFEr863k7mc):

  * opens cold on an underdog / contrarian hook, no intro;
  * third person, PAST tense, short punchy sentences - each one a visible action or a change in stakes;
  * a constant setup -> twist rhythm ("But...", "Just then...", "Meanwhile...", "Seeing this...",
    "It turned out that...", "Sure enough..."), with small mysteries planted and later paid off;
  * no commentary, opinions or channel talk; it ends on the payoff line.

Reuses the grounded arc machinery (anime_arc_grounding): Groq Whisper transcript with OP/ED removed,
beats {text, src_start, src_end} validated against the episode, focus_beat_range, per-beat TTS.
On top of that the LLM returns the story's acts (3-6, become YouTube chapters), a hook title, the
climax beat and 1-3 "short_candidates" - contiguous beat ranges that open on a stand-alone hook and
end on their payoff. Everything is validated; a deterministic fallback picks a Short window around
the climax when no candidate survives. Grounding failures raise GroundingError: there is no
template narration.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from anime_llm import complete, extract_json
from anime_arc_grounding import (
    GroundingError, TRANSCRIPT_DIR, TRANSCRIPT_VERSION, SERIES_NAME_HINTS, _FILLER_RE,
    validate_beats, transcript_for_prompt, transcribe_episode, detect_song_ranges, detect_dub_language,
    clip_out_of_songs, focus_beat_range,
)

# edge-tts ChristopherNeural at +20%, clip silence trimmed, 0.1 s beat gaps: measured ~213 wpm (3.55 words/s)
EPISODE_RATE = "+20%"
EPISODE_WPS = 3.55
EPISODE_BEAT_GAP = 0.10
EPISODE_ACT_GAP = 0.35
EPISODE_MIN_WORDS = 1050       # ~5 min floor: shorter means whole scenes were skipped
EPISODE_MAX_WORDS = 2300       # ~11 min ceiling: longer is padding
SHORT_MIN_S = 35.0
SHORT_MAX_S = 59.0
SHORT_TAIL_S = 0.5             # silence kept after the payoff line

STYLE_REFERENCE = (
    "Every contestant chose top of the line ingredients, but Ethan picked a beef spine that nobody wanted. "
    "His competitors immediately laughed because beef backbone was considered one of the worst cuts of beef. "
    "But Ethan didn't bother explaining himself. "
    "Just then, another contestant brought out his dish. "
    "The food tasted pretty average, yet somehow he received a surprisingly high score. "
    "One audience member noticed something strange. "
    "Before every round of scoring, one of the judges would touch his ear. "
    "It turned out that a restaurant owner had secretly bribed the judge. "
    "Seeing this, the restaurant owner immediately contacted the bribed judge. "
    "Sure enough, it was filled with concentrated broth that had been prepared in advance. "
    "The organizers disqualified the opponent, and Ethan won the championship through his own skill."
)

TWIST_RE = re.compile(
    r"\b(but|yet|just then|just as|meanwhile|seeing this|it turned out|turned out|sure enough|however|suddenly|"
    r"at that moment|before long|instead|unfortunately|fortunately|only to|the moment|even though|although|"
    r"little did|at the last second|without warning)\b", re.I)
CONTRAST_RE = re.compile(r"\b(but|yet|while|even though|although|instead|only|so|nobody|no one|still)\b", re.I)
PAYOFF_RE = re.compile(
    r"\b(finally|turned out|sure enough|realized|revealed|defeated|killed|won|saved|beheaded|sliced|severed|"
    r"cut off|cut through|destroyed|collapsed|died|truth|at last|in the end|managed|crumbled|disintegrated|"
    r"shattered|freed|escaped|survived|exposed|stopped)\b", re.I)

# Things the reference never does: viewer address, channel talk, commentary, present-tense recap framing
STYLE_BANNED = [
    (r"\bwe (?:learn|see|find out|get|watch)\b", "present-tense recap framing ('we learn/see')"),
    (r"\bthe story begins\b", "intro framing ('the story begins')"),
    (r"\bin (?:this|today'?s|the) (?:episode|video|recap)\b", "meta reference to the episode/video"),
    (r"\bviewers?\b|\bour channel\b|\blike and subscribe\b|\bcomment\b", "channel talk"),
    (r"\b(?:i think|in my opinion|honestly|personally|let'?s|let us)\b", "narrator commentary"),
    (r"\bpreviously on\b|\blast time\b|\bto be continued\b|\bnext (?:time|episode)\b", "episode framing"),
    (r"\b(?:epic|insane|crazy|legendary moment|peak fiction|goosebumps|masterpiece)\b", "opinionated hype"),
]
_BANNED = [(re.compile(p, re.I), why) for p, why in STYLE_BANNED]

IRREGULAR_PAST = set("""was were had did saw took made came went got gave told said knew thought found left ran fell
felt held kept broke caught fought threw struck began became spun swung cut hit let put set shot rose drew flew grew
wore tore bit hid led lost met paid sent spent stood understood woke won wrote heard meant brought bought taught sought
could would should might shook slid sprang sank stuck swept stole chose spoke froze forgot forgave rode rang sang sat
slept slew sought split spread stung stank strove swore swam tore thrust wept wound bled bent bound burst clung crept
dealt dug drove ate fed fled flung forbade hung laid lay lit overheard overtook rebuilt redid shed shone shut stank
strode undid upset withdrew withstood arose awoke beheld beat blew dove sprang""".split())
PRESENT_NARRATIVE = re.compile(
    r"\b(is|are|has|does|says|tells|realizes|realises|decides|tries|runs|attacks|begins|sees|asks|notices|reveals|"
    r"finds|starts|uses|gets|takes|makes|comes|goes|wants|knows|thinks|explains|remembers|manages|appears|arrives|"
    r"continues|becomes|falls|jumps|leaves|looks|turns|grabs|cuts|slashes|strikes|shouts|screams|watches|hears)\b", re.I)

DANGLING_STARTS = {"he", "she", "they", "him", "her", "it", "this", "that", "then", "but", "so", "and", "meanwhile",
                   "just", "seeing", "after", "later", "still", "there", "these", "those", "his", "their", "its",
                   "instead", "however", "finally", "sure", "again", "also", "with", "now", "soon", "even", "yet",
                   "or", "because", "though", "both", "everyone", "nobody", "the", "unfortunately", "fortunately"}
# "The" is only dangling when the sentence never names anyone; see hook_stands_alone.
_COMMON_CAPS = {"I", "The", "A", "An", "But", "Just", "Then", "Meanwhile", "Seeing", "It", "He", "She", "They",
                "When", "As", "After", "Before", "Sure", "With", "In", "On", "At", "This", "That", "His", "Her",
                "Their", "Its", "So", "And", "Even", "Yet", "Still", "Now", "Soon", "Finally", "Instead", "However",
                "Suddenly", "Every", "Nobody", "No", "One", "Only", "Unfortunately", "Fortunately", "Before",
                "Demon", "Slayer", "Corps", "Breathing", "Hashira", "Lower", "Upper", "Moon", "Form"}


def log(msg: str) -> None:
    print(f"[episode_recap] {msg}", flush=True)


def _unquoted(text: str) -> str:
    return re.sub(r"\"[^\"]*\"|“[^”]*”", " ", text)


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def _has_past(text: str) -> bool:
    for w in re.findall(r"[A-Za-z']+", _unquoted(text).lower()):
        if w in IRREGULAR_PAST or (len(w) > 3 and w.endswith("ed")) or w.endswith("n't") and w[:-3] in IRREGULAR_PAST:
            return True
    return False


def character_names(texts: list[str]) -> set[str]:
    """Proper names used in the narration: capitalised words seen mid-sentence at least twice."""
    counts: dict[str, int] = {}
    for t in texts:
        for s in _sentences(t):
            words = re.findall(r"[A-Za-z][A-Za-z'-]+", s)
            for w in words[1:]:
                w = re.sub(r"'s$", "", w)
                if w[0].isupper() and w not in _COMMON_CAPS and len(w) >= 3:
                    counts[w] = counts.get(w, 0) + 1
    return {w for w, n in counts.items() if n >= 2}


def hook_stands_alone(text: str, names: set[str] | None = None) -> bool:
    """A cold-open hook: 6-34 words, does not lean on an earlier sentence (no leading pronoun or
    connector) and names who it is about."""
    t = re.sub(r"\s+", " ", (text or "")).strip()
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", t)
    if not (6 <= len(t.split()) <= 34) or not words:
        return False
    first = words[0].lower()
    named = bool(names) and any(re.search(rf"\b{re.escape(n)}\b", t) for n in names)
    if first == "the" or first in ("every", "a", "an", "one", "when", "as", "while", "although", "even"):
        return named or not names
    if first in DANGLING_STARTS:
        return False
    if names:
        return named
    return words[0][0].isupper()


# ----------------------------------------------------------------------------------------- style
def style_problems(beats: list[dict]) -> list[str]:
    """Checks the narration against the reference style. Returns the problems found (empty = OK)."""
    problems = []
    texts = [b["text"] for b in beats]
    n = len(texts)
    for i, t in enumerate(texts):
        for rx, why in _BANNED:
            m = rx.search(_unquoted(t))
            if m:
                problems.append(f"beat {i}: {why} ('{m.group(0)}')")
                break
        if re.search(r"\byou(?:r|'re|'ll|'ve)?\b", _unquoted(t), re.I):
            problems.append(f"beat {i}: addresses the viewer ('you') - narration is third person")
        if len(t.split()) > 34:
            problems.append(f"beat {i}: {len(t.split())} words - keep each beat to one or two short sentences")
    sents = [s for t in texts for s in _sentences(t)]
    avg = sum(len(s.split()) for s in sents) / max(1, len(sents))
    if avg > 17.5:
        problems.append(f"average sentence is {avg:.1f} words (reference style is short and punchy, <= 17)")
    past = sum(1 for t in texts if _has_past(t))
    if past < 0.75 * n:
        problems.append(f"only {past}/{n} beats are in the past tense (write in third-person PAST tense)")
    present_only = sum(1 for t in texts if PRESENT_NARRATIVE.search(_unquoted(t)) and not _has_past(t))
    if present_only > 0.12 * n:
        problems.append(f"{present_only} beats are narrated in the present tense")
    twists = sum(1 for t in texts if TWIST_RE.search(t))
    if twists < max(3, n // 7):
        problems.append(f"only {twists} beats turn the story ('But', 'Just then', 'Meanwhile', 'Seeing this', "
                        f"'It turned out', 'Sure enough'); need at least {max(3, n // 7)}")
    if texts:
        if not CONTRAST_RE.search(" ".join(texts[:2])):
            problems.append("the opening is not a contrarian/underdog hook (beat 0 needs a contrast: 'but', 'yet', 'nobody', ...)")
        if len(texts[0].split()) > 34:
            problems.append("opening hook is longer than 34 words")
        if "?" in texts[-1]:
            problems.append("the last beat asks a question; end on the payoff line")
    return problems


# ----------------------------------------------------------------------------------------- acts
def validate_acts(acts, n_beats: int) -> list[dict]:
    """3-6 acts {title, start_beat}: the first starts at beat 0, starts increase, every act has 3+ beats."""
    if not isinstance(acts, list) or not (3 <= len(acts) <= 6):
        raise ValueError(f"need 3-6 acts, got {len(acts) if isinstance(acts, list) else type(acts).__name__}")
    out = []
    for i, a in enumerate(acts):
        if not isinstance(a, dict):
            raise ValueError(f"act {i} is not an object")
        title = re.sub(r"\s+", " ", str(a.get("title", ""))).strip().strip('"')
        try:
            sb = int(a.get("start_beat"))
        except Exception:
            raise ValueError(f"act {i} has no integer start_beat")
        if not title or len(title) > 60 or re.match(r"^(act|chapter|part|episode)\s*\d", title, re.I):
            raise ValueError(f"act {i} has a bad title {title!r}")
        out.append({"title": title, "start_beat": sb})
    out[0]["start_beat"] = 0 if out[0]["start_beat"] <= 2 else out[0]["start_beat"]
    if out[0]["start_beat"] != 0:
        raise ValueError("the first act must start at beat 0")
    for i in range(1, len(out)):
        if out[i]["start_beat"] - out[i - 1]["start_beat"] < 3:
            raise ValueError(f"act {i} starts at beat {out[i]['start_beat']}, too close to act {i - 1}")
    if n_beats - out[-1]["start_beat"] < 3 or out[-1]["start_beat"] >= n_beats:
        raise ValueError("the last act starts too late")
    return out


# ----------------------------------------------------------------------------------------- shorts
def estimate_beat_seconds(text: str, wps: float = EPISODE_WPS) -> float:
    return len(text.split()) / wps


def window_seconds(slots: list[float], speech: list[float], b0: int, b1: int, tail: float = SHORT_TAIL_S) -> float:
    """Length of a Short covering beats b0..b1: every slot up to b1, then b1's speech and a short tail."""
    return sum(slots[b0:b1]) + speech[b1] + tail


def estimated_slots(texts: list[str], wps: float = EPISODE_WPS, gap: float = EPISODE_BEAT_GAP) -> tuple[list[float], list[float]]:
    speech = [estimate_beat_seconds(t, wps) for t in texts]
    return [s + gap for s in speech], speech


def validate_short_candidates(cands, texts: list[str], names: set[str] | None = None,
                              slots: list[float] | None = None, speech: list[float] | None = None,
                              lo: float = SHORT_MIN_S, hi: float = SHORT_MAX_S, margin: float = 1.5) -> tuple[list[dict], list[str]]:
    """
    Validate 1-3 short candidates {start_beat, end_beat, hook_beat, payoff_beat, title, hook_text?}.
    A valid candidate is a contiguous range that OPENS on its hook (hook_beat == start_beat, the hook
    sentence stands alone - hook_text may rewrite beat start_beat as a cold open) and ENDS on its payoff
    (payoff_beat == end_beat), and whose narration lasts lo..hi seconds (estimated from word counts
    unless real slot lengths are given; estimates keep a safety margin). Returns (valid, problems).
    """
    n = len(texts)
    names = names if names is not None else character_names(texts)
    valid, problems = [], []
    if not isinstance(cands, list):
        return [], ["short_candidates is not a list"]
    for k, c in enumerate(cands[:3]):
        if not isinstance(c, dict):
            problems.append(f"candidate {k} is not an object")
            continue
        try:
            b0, b1 = int(c.get("start_beat")), int(c.get("end_beat"))
            hb = int(c.get("hook_beat", b0))
            pb = int(c.get("payoff_beat", b1))
        except Exception:
            problems.append(f"candidate {k} has non-integer beat indices")
            continue
        if not (0 <= b0 < b1 < n):
            problems.append(f"candidate {k} range {b0}-{b1} is outside the script (0-{n - 1})")
            continue
        if hb != b0:
            problems.append(f"candidate {k} hook_beat {hb} is not its first beat {b0}")
            continue
        if pb != b1:
            problems.append(f"candidate {k} payoff_beat {pb} is not its last beat {b1}")
            continue
        hook = re.sub(r"\s+", " ", str(c.get("hook_text") or texts[b0])).strip()
        if not hook_stands_alone(hook, names):
            problems.append(f"candidate {k} hook does not stand alone: {hook[:80]!r}")
            continue
        if _FILLER_RE.search(hook) or any(rx.search(hook) for rx, _ in _BANNED):
            problems.append(f"candidate {k} hook uses filler/commentary")
            continue
        title = re.sub(r"\s+", " ", str(c.get("title", ""))).strip().strip('"')
        if not (12 <= len(title) <= 90) or "#" in title:
            problems.append(f"candidate {k} title {title!r} must be 12-90 characters without hashtags")
            continue
        est_mode = slots is None or speech is None
        if est_mode:
            s_slots, s_speech = estimated_slots([hook] + texts[b0 + 1:b1 + 1])
            dur = window_seconds(s_slots, s_speech, 0, len(s_slots) - 1)
            ok = lo + margin <= dur <= hi - margin
        else:
            hook_delta = estimate_beat_seconds(hook) - estimate_beat_seconds(texts[b0])
            dur = window_seconds(slots, speech, b0, b1) + hook_delta
            ok = lo <= dur <= hi
        if not ok:
            problems.append(f"candidate {k} beats {b0}-{b1} run {dur:.1f}s (need {lo:.0f}-{hi:.0f}s)")
            continue
        valid.append({"start_beat": b0, "end_beat": b1, "hook_beat": b0, "payoff_beat": b1, "title": title,
                      "hook_text": hook, "hook_rewritten": hook != texts[b0], "est_duration": round(dur, 2),
                      "source": "llm"})
    return valid, problems


def fallback_short_window(texts: list[str], slots: list[float], speech: list[float], climax_beat: int | None = None,
                          names: set[str] | None = None, lo: float = SHORT_MIN_S, hi: float = SHORT_MAX_S,
                          target: float = 50.0) -> dict | None:
    """
    Deterministic Short window around the climax when no LLM candidate is usable. Considers every
    contiguous beat window lasting lo..hi seconds and scores it: contains the climax beat (and builds
    up to it rather than starting on it), opens on a sentence that stands alone, ends on a payoff
    sentence (a reveal or resolution), length close to target. Ties go to the earliest window.
    """
    n = len(texts)
    if n == 0:
        return None
    names = names if names is not None else character_names(texts)
    climax = climax_beat if isinstance(climax_beat, int) and 0 <= climax_beat < n else int(n * 0.7)
    best, best_key = None, None
    for b0 in range(n):
        for b1 in range(b0 + 1, n):
            dur = window_seconds(slots, speech, b0, b1)
            if dur > hi:
                break
            if dur < lo:
                continue
            score = 0.0
            if b0 <= climax <= b1:
                score += 4.0
                if climax > b0:
                    score += 1.0
            else:
                score -= min(abs(climax - b0), abs(climax - b1)) / 4.0
            if hook_stands_alone(texts[b0], names):
                score += 3.0
            if CONTRAST_RE.search(texts[b0]):
                score += 0.5
            if PAYOFF_RE.search(texts[b1]):
                score += 2.0
            if b1 + 1 < n and TWIST_RE.match(texts[b1 + 1].strip()):
                score += 0.5   # the next beat turns the story: this one closes a mini arc
            score -= abs(dur - target) / 20.0
            key = (round(score, 6), -b0)
            if best_key is None or key > best_key:
                best_key = key
                best = {"start_beat": b0, "end_beat": b1, "hook_beat": b0, "payoff_beat": b1,
                        "hook_text": texts[b0], "hook_rewritten": False, "est_duration": round(dur, 2),
                        "source": "fallback", "score": round(score, 3)}
    if best:
        best["title"] = short_title_from_hook(best["hook_text"])
    return best


def short_title_from_hook(hook: str, max_len: int = 70) -> str:
    """A title from a hook sentence: its first clause, trimmed at a word boundary."""
    h = re.split(r"(?<=[.!?])\s", (hook or "").strip(), maxsplit=1)[0].strip().rstrip(".!")
    if len(h) > max_len:
        h = h[:max_len].rsplit(" ", 1)[0].rstrip(",;:-")
    return h


def shorts_title(title: str) -> str:
    """The Short's YouTube title: the hook plus ' #shorts', within 100 characters."""
    t = re.sub(r"\s+", " ", title).strip().rstrip(".")
    return f"{t[:100 - len(' #shorts')].rstrip()} #shorts"


# ----------------------------------------------------------------------------------------- prompt
SYSTEM_PROMPT = (
    "You are the head writer of a fast, cold-open story recap channel. You retell one anime episode as a tight "
    "third-person PAST-tense story told in short punchy sentences, each one a visible action or a change in stakes, "
    "with a constant setup-then-twist rhythm. You never comment, never give opinions, never address the viewer and "
    "never mention the channel. You only state what the transcript supports. You answer with JSON only."
)


def build_episode_recap_prompt(ep: dict, transcript: dict, arc: dict | None = None) -> str:
    dur = transcript["duration"]
    songs = transcript.get("songs") or []
    song_txt = ", ".join(f"{s:.0f}-{e:.0f}s" for s, e in songs) or "none detected"
    where = ""
    if arc:
        try:
            pos = arc["episode_keys"].index(ep["episode_key"]) + 1
            where = f" It is episode {pos} of {len(arc['episode_keys'])} of the {arc.get('arc_name')}."
        except ValueError:
            where = f" It belongs to the {arc.get('arc_name')}."
    return f"""Series: {ep.get('series')} - season {ep.get('season')}, episode {ep.get('episode')}.{where}

Below is the timestamped English dialogue of the whole episode (seconds from the start of the episode file;
machine-translated, so names may be misspelled). Opening/ending songs ({song_txt}) were removed.
Episode length: {dur:.0f}s.

TRANSCRIPT:
{transcript_for_prompt(transcript)}

TASK: Write the narration of a standalone recap video of THIS ONE EPISODE, as beats.

STYLE (follow it exactly). Reference narration from the style we copy:
"{STYLE_REFERENCE}"
- Open COLD on an underdog/contrarian hook built from this episode's central conflict, with no intro and no
  "the story begins": e.g. "Every demon slayer on the mountain was losing to the spiders, but Tanjiro chose to fight
  the strongest demon of all with a broken sword." The hook is beat 0.
- Third person, PAST tense ("Tanjiro swung", "Rui laughed", "It turned out that..."), never present tense.
- Short punchy sentences of 5-18 words. Each sentence is one visible action or one change in the stakes.
- Constant setup -> twist rhythm with connectors such as "But", "Just then", "Meanwhile", "Seeing this",
  "It turned out that", "Sure enough", "Before long", "At that moment", "Just as". Plant small mysteries early
  (a strange detail, an odd reaction) and pay them off later with "It turned out that...".
- Introduce every character by name with a short identity tag the first time, as if the viewer knows nothing
  (e.g. "Rui, a demon child who controlled razor-sharp threads"). Use the English-release names
  (Tanjiro, Nezuko, Zenitsu, Inosuke, Giyu, Shinobu, Rui...).
- Cover the WHOLE episode in order, every scene. Length follows the episode: about 1200-2000 words in total
  (a slow episode near 1250, a packed one near 2000). One beat = one or two sentences, at most 30 words.
- No commentary, no opinions, no hype ("epic", "insane", "jaw-dropping"), no "we learn", no "you", no questions,
  no "in this episode", no channel talk, no teaser for the next episode. The final beat is the payoff line.

GROUNDING: every beat has "id" (0, 1, 2, ... in order), "text", and src_start/src_end: the episode seconds of the
exact moment that sentence describes, from the transcript timestamps (a silent action moment uses the time
between the surrounding lines). The viewer sees exactly this footage while the sentence is read, so bracket only
that moment: usually 3-15 seconds, never more than 60. Beats follow the episode's order; nothing may come from the
song ranges.

ALSO RETURN:
- "title": the YouTube title, a hook in the same spirit WITHOUT the anime's name, Title Case, 30-95 characters,
  no hashtags, no season/episode numbers, e.g. "He Broke His Sword Against a Demon Child, So He Used His Dead Father's Dance".
- "summary": 2 plain sentences on what happens in the episode (past tense).
- "acts": 3-6 story acts that become the video's chapters: [{{"title": 2-6 vivid words, "start_beat": id}}];
  the first act starts at beat 0 and every act has at least 5 beats.
- "climax_beat": id of the beat at the episode's peak moment.
- "short_candidates": 1-3 YouTube Shorts cut from this script, best first. Each is a contiguous beat range
  {{"start_beat", "end_beat", "hook_beat", "payoff_beat", "title", "hook_text"}} where hook_beat == start_beat and
  payoff_beat == end_beat. The range must OPEN on a hook sentence that stands alone for someone who never saw the
  episode (it names the character, no leading "He"/"But"/"Then") - put that sentence in "hook_text", rewriting
  beat start_beat as a cold-open hook the way the reference opens if needed - and END on its payoff beat (the
  resolution or reveal). Its narration must last 35-59 seconds: about 125-185 words in total. "title" is the
  Short's hook headline (12-70 characters, no hashtags), e.g. "His Sword Snapped, So He Used His Father's Dance".

Return JSON: {{"title": str, "summary": str, "beats": [{{"id": int, "text": str, "src_start": number, "src_end": number}}, ...],
"acts": [...], "climax_beat": int, "short_candidates": [...]}}"""


def _title_problems(title: str) -> list[str]:
    from anime_copyright_filter import SCRAPER_PATTERN_EP, SCRAPER_PATTERN_SEASON
    p = []
    if not (25 <= len(title) <= 95):
        p.append(f"title length {len(title)} (need 25-95): {title!r}")
    if "#" in title:
        p.append("hashtag in title")
    if SCRAPER_PATTERN_EP.search(title) or SCRAPER_PATTERN_SEASON.search(title) or re.search(r"\bepisode\s*\d", title, re.I):
        p.append("season/episode number in title")
    return p


def parse_recap_answer(text: str, ep_duration: float, songs: list | None, strict_shorts: bool = True) -> dict:
    """Parse + validate one LLM answer. Raises ValueError listing what is wrong."""
    data = extract_json(text)
    if not isinstance(data, dict):
        raise ValueError("answer is not a JSON object")
    raw_beats = data.get("beats")
    if not isinstance(raw_beats, list):
        raise ValueError("no beats list")
    # map ids -> positions (references in acts/candidates use ids)
    id_pos = {}
    for pos, b in enumerate(raw_beats):
        if isinstance(b, dict) and isinstance(b.get("id"), (int, float)):
            id_pos.setdefault(int(b["id"]), pos)
    def ref(v):
        try:
            v = int(v)
        except Exception:
            return v
        return id_pos.get(v, v)

    beats = validate_beats(raw_beats, ep_duration, songs, min_words=EPISODE_MIN_WORDS, max_words=EPISODE_MAX_WORDS,
                           min_beat_words=4, max_beat_words=34, min_beats=40)
    problems = style_problems(beats)
    title = re.sub(r"\s+", " ", str(data.get("title", ""))).strip().strip('"')
    problems += _title_problems(title)
    texts = [b["text"] for b in beats]
    try:
        acts = validate_acts([dict(a, start_beat=ref(a.get("start_beat"))) if isinstance(a, dict) else a
                              for a in (data.get("acts") or [])], len(beats))
    except ValueError as e:
        problems.append(str(e))
        acts = []
    names = character_names(texts)
    cands_in = [dict(c, **{k: ref(c.get(k)) for k in ("start_beat", "end_beat", "hook_beat", "payoff_beat") if k in c})
                if isinstance(c, dict) else c for c in (data.get("short_candidates") or [])]
    cands, cand_problems = validate_short_candidates(cands_in, texts, names)
    if not cands and strict_shorts:
        problems.append("no valid short_candidates: " + "; ".join(cand_problems[:3] or ["none given"]))
    if problems:
        raise ValueError("; ".join(problems[:10]))
    climax = ref(data.get("climax_beat"))
    climax = climax if isinstance(climax, int) and 0 <= climax < len(beats) else None
    return {"title": title, "summary": str(data.get("summary", "")).strip(), "beats": beats, "acts": acts,
            "climax_beat": climax, "short_candidates": cands, "short_candidate_problems": cand_problems}


def write_episode_recap(ep: dict, transcript: dict, arc: dict | None = None) -> dict:
    prompt = build_episode_recap_prompt(ep, transcript, arc)
    holder: dict = {}
    calls = {"n": 0}

    def validator(text: str) -> None:
        calls["n"] += 1
        # The first answers must carry a usable Short; later ones may lean on the deterministic fallback.
        holder.update(parse_recap_answer(text, transcript["duration"], transcript.get("songs"),
                                         strict_shorts=calls["n"] <= 3))

    res = complete(prompt, system=SYSTEM_PROMPT, json_mode=True, temperature=0.6, max_tokens=24000,
                   validator=validator, label=f"{ep['episode_key']} recap", feedback=True)
    if not res:
        raise GroundingError(f"no LLM produced a valid recap of {ep['episode_key']}")
    holder["model"] = res[1]
    return holder


# ----------------------------------------------------------------------------------------- grounding
def find_cached_songs(ep_key: str) -> list | None:
    """OP/ED ranges for an episode from any cached transcript or arc song-detection file."""
    tf = TRANSCRIPT_DIR / f"{ep_key}.json"
    if tf.exists():
        try:
            d = json.loads(tf.read_text())
            if d.get("version") == TRANSCRIPT_VERSION and d.get("songs") is not None:
                return [tuple(r) for r in d["songs"]]
        except Exception:
            pass
    for f in sorted(TRANSCRIPT_DIR.glob("songs_*.json")):
        try:
            d = json.loads(f.read_text())
            if ep_key in d:
                return [tuple(r) for r in d[ep_key]]
        except Exception:
            continue
    return None


def ground_episode(ep: dict, video: Path, neighbour_video: Path | None = None, arc: dict | None = None) -> dict:
    """
    Transcript (cached) + validated recap script for one episode, with every beat's footage range
    clipped out of the OP/ED and focused on the dialogue it describes. neighbour_video is another
    episode of the same season, used only to find the shared OP/ED when nothing is cached.
    """
    ep_key = ep["episode_key"]
    if not Path(video).exists() or Path(video).stat().st_size < 1_000_000:
        raise GroundingError(f"{ep_key}: episode file missing ({video})")
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    songs = find_cached_songs(ep_key)
    if songs is None:
        if neighbour_video and Path(neighbour_video).exists():
            songs = detect_song_ranges({ep_key: Path(video), "neighbour": Path(neighbour_video)}).get(ep_key, [])
        else:
            log(f"{ep_key}: no OP/ED reference available; transcribing the whole file")
            songs = []
    cached = (TRANSCRIPT_DIR / f"{ep_key}.json").exists()
    if not groq_key and not cached:
        raise GroundingError("GROQ_API_KEY is not set and the transcript is not cached")
    lang = "en"
    if not cached:
        probe_at = 120.0
        for a, b in songs:
            if a < 300:
                probe_at = max(probe_at, b + 5)
        lang = detect_dub_language(Path(video), probe_at, groq_key)
    names = SERIES_NAME_HINTS.get(ep.get("series_id", ""), "")
    tr = transcribe_episode(ep_key, Path(video), songs, lang, groq_key, names)
    tr["songs"] = songs if songs else (tr.get("songs") or [])
    t0 = time.time()
    res = write_episode_recap(ep, tr, arc)
    for b in res["beats"]:
        s, e = clip_out_of_songs(b["src_start"], b["src_end"], tr["songs"])
        if e - s >= 1.5:
            b["src_start"], b["src_end"] = round(s, 2), round(e, 2)
        fs, fe = focus_beat_range(b["text"], b["src_start"], b["src_end"], tr["segments"], min_window=8.0)
        if (fs, fe) != (b["src_start"], b["src_end"]):
            b["llm_src"] = [b["src_start"], b["src_end"]]
            b["src_start"], b["src_end"] = fs, fe
    words = sum(len(b["text"].split()) for b in res["beats"])
    log(f"{ep_key}: '{res['title']}' {len(res['beats'])} beats, {words} words, {len(res['acts'])} acts, "
        f"{len(res['short_candidates'])} short candidate(s) ({res['model']}, {time.time() - t0:.0f}s)")
    res.update({"episode_key": ep_key, "duration": tr["duration"], "songs": tr["songs"], "language": lang,
                "word_count": words})
    return res
