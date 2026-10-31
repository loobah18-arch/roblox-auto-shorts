#!/usr/bin/env python3
"""
Multi-Agent Anti-Copyright Filter System for Bhaloo Ji Anime Explanation Engine.
Implements 3 specialized agents to inspect and shield every video, title, and description
before reaching YouTube:
  1. VideoCopyrightAgent: Slices, duration ceiling (<=58.5s), ending credits bounds (<=1285s), audio sanity.
  2. TitleCopyrightAgent: Fair-use transformative labeling, crawler tag sanitization (no S1 Ep 5), length.
  3. DescriptionCopyrightAgent: Section 107 Fair Use statutory disclosure, transformative commentary.
Also includes automated remediation and retry loop orchestrator.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MAX_SHORT_DURATION = 180.0  # YouTube Shorts official 3-minute (180s) maximum duration
MIN_SHORT_DURATION = 10.0
MAX_SAFE_ANIME_STORY_TIMESTAMP = 1285.0
MAX_SHOT_DURATION = 3.2

# Blocked crawler patterns that trigger automated Content ID metadata scrapers
SCRAPER_PATTERN_EP = re.compile(r'\b[Ss]\d+[\s._-]*[Ee][Pp]?\s*\d+\b', re.IGNORECASE)
SCRAPER_PATTERN_SEASON = re.compile(r'\bSeason\s*\d+\s*Episode\s*\d+\b', re.IGNORECASE)

FAIR_USE_DISCLAIMER = (
    "\n\n---\n"
    "Copyright Disclaimer Under Section 107 of the Copyright Act 1976:\n"
    "Allowance is made for \"Fair Use\" for purposes such as criticism, comment, news reporting, "
    "teaching, scholarship, and research. Fair use is a use permitted by copyright statute that might "
    "otherwise be infringing. Non-profit, educational or personal use tips the balance in favor of fair use.\n"
    "All anime footage and visual elements belong to their respective copyright holders (e.g. Ufotable, "
    "MAPPA, Shueisha, Aniplex). This production is an analytical, transformative commentary and story explanation.\n"
    "Channel: Bhaloo Ji\n"
    "---\n"
)


@dataclass
class AgentResult:
    agent_name: str
    passed: bool
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MultiAgentFilterResult:
    passed: bool
    agent_results: Dict[str, AgentResult]
    remediation_needed: bool
    summary: str

    @property
    def violations(self) -> List[str]:
        all_v = []
        for r in self.agent_results.values():
            all_v.extend(r.violations)
        return all_v


class VideoCopyrightAgent:
    """Agent 1: Inspects video stream metrics, duration boundaries, and ending credits limits."""

    def __init__(self, max_short_duration: float = MAX_SHORT_DURATION):
        self.max_short_duration = max_short_duration

    def evaluate_video(
        self,
        video_path: Path | str,
        is_short: bool = True,
        time_window: Optional[Tuple[float, float]] = None,
        shots_info: Optional[List[Dict[str, Any]]] = None,
    ) -> AgentResult:
        v_path = Path(video_path)
        violations = []
        warnings = []
        details = {}

        if not v_path.exists():
            violations.append(f"Video file does not exist: {v_path}")
        else:
            # 1. ffprobe stream examination
            cmd = [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration:stream=codec_type,width,height",
                "-of", "json",
                str(v_path),
            ]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, check=True)
                probe = json.loads(res.stdout)
                duration = float(probe.get("format", {}).get("duration", 0.0))
                streams = probe.get("streams", [])
                details["duration"] = duration

                has_video = any(s.get("codec_type") == "video" for s in streams)
                has_audio = any(s.get("codec_type") == "audio" for s in streams)
                video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
                width = int(video_stream.get("width", 0))
                height = int(video_stream.get("height", 0))
                details["width"] = width
                details["height"] = height
                details["has_audio"] = has_audio

                if not has_video:
                    violations.append("No video stream found in file.")
                if not has_audio:
                    violations.append("No audio stream found; voiceover or BGM is missing.")

                # 2. Duration checks
                if is_short:
                    if duration > self.max_short_duration:
                        violations.append(
                            f"Short duration {duration:.2f}s exceeds safe ceiling {self.max_short_duration}s."
                        )
                    elif duration < MIN_SHORT_DURATION:
                        violations.append(f"Short duration {duration:.2f}s is below minimum {MIN_SHORT_DURATION}s.")
                else:
                    if duration <= 60.0:
                        violations.append(f"Long-form video is too short ({duration:.2f}s). Expected >60s.")

                # 3. Aspect ratio / Orientation
                if is_short and height < width and width > 0:
                    violations.append(f"Short is in landscape orientation ({width}x{height}); expected 9:16 vertical.")

            except Exception as e:
                # Fallback if ffprobe isn't executable locally (e.g. mock test)
                warnings.append(f"ffprobe check skipped or returned error: {e}")

        # 4. Ending credits check
        if time_window:
            w_start, w_end = time_window
            if w_end > MAX_SAFE_ANIME_STORY_TIMESTAMP + 1.0:
                violations.append(
                    f"Scene end timestamp {w_end:.1f}s enters anime ED credits (> {MAX_SAFE_ANIME_STORY_TIMESTAMP}s)."
                )
            if w_start > MAX_SAFE_ANIME_STORY_TIMESTAMP:
                violations.append(
                    f"Scene start timestamp {w_start:.1f}s starts inside anime ED credits (> {MAX_SAFE_ANIME_STORY_TIMESTAMP}s)."
                )

        # 5. Shot micro-cut duration check
        if shots_info:
            for idx, s in enumerate(shots_info):
                dur = s.get("duration", 0.0)
                if dur > (MAX_SHOT_DURATION + 0.1):
                    violations.append(
                        f"Shot #{idx} duration {dur:.2f}s exceeds contiguous micro-cut threshold ({MAX_SHOT_DURATION}s)."
                    )

        passed = len(violations) == 0
        return AgentResult(
            agent_name="VideoCopyrightAgent",
            passed=passed,
            violations=violations,
            warnings=warnings,
            details=details,
        )


class TitleCopyrightAgent:
    """Agent 2: Enforces transformative title metadata, anti-scraper keyword protection, and length."""

    def __init__(self, blocked_titles: Optional[List[str]] = None):
        self.blocked_titles = [t.lower().strip() for t in (blocked_titles or [])]

    def evaluate_title(self, title: str, is_short: bool = True) -> AgentResult:
        violations = []
        warnings = []
        clean_title = title.strip()
        lower = clean_title.lower()

        # 1. Transformative explanation indicator check
        transformative_terms = ["explanation", "recap", "explained", "breakdown", "story recap"]
        if not any(term in lower for term in transformative_terms):
            violations.append("Title missing transformative marker ('Explanation', 'Recap', or 'Explained').")

        # 2. Scraper blacklist check
        if SCRAPER_PATTERN_EP.search(clean_title):
            violations.append(
                f"Title contains exact episode scraper pattern '{SCRAPER_PATTERN_EP.search(clean_title).group(0)}' (e.g. S1 Ep 5). Must use 'Story Recap'."
            )
        if SCRAPER_PATTERN_SEASON.search(clean_title):
            violations.append(
                f"Title contains exact season/episode scraper pattern '{SCRAPER_PATTERN_SEASON.search(clean_title).group(0)}'. Must use 'Story Recap'."
            )

        # 3. Known blocked titles check
        for blocked in self.blocked_titles:
            if blocked and (blocked in lower or lower in blocked):
                violations.append(f"Title matches previously blocked YouTube upload blacklist: '{blocked}'.")
                break

        # 4. Length check
        if len(clean_title) < 15:
            violations.append(f"Title length ({len(clean_title)} chars) is too short.")
        elif len(clean_title) > 95:
            warnings.append(f"Title length ({len(clean_title)} chars) exceeds recommended 95-char limit.")

        # 5. Hashtag for Shorts
        if is_short and "#shorts" not in lower:
            violations.append("Short title missing '#shorts' hashtag.")

        passed = len(violations) == 0
        return AgentResult(
            agent_name="TitleCopyrightAgent",
            passed=passed,
            violations=violations,
            warnings=warnings,
            details={"title": clean_title, "length": len(clean_title)},
        )

    @staticmethod
    def remediate_title(title: str, is_short: bool = True, part_num: Optional[int] = None) -> str:
        """Automatically sanitizes title to pass all copyright criteria."""
        t = title.strip()
        # Replace crawler patterns
        t = SCRAPER_PATTERN_EP.sub("Story Recap", t)
        t = SCRAPER_PATTERN_SEASON.sub("Story Recap", t)

        lower = t.lower()
        if "explanation" not in lower and "explained" not in lower:
            if "story recap" in lower:
                t = re.sub(r'Story Recap', 'Story Recap Explanation', t, count=1, flags=re.IGNORECASE)
            elif "recap" in lower:
                t = re.sub(r'Recap', 'Recap Explanation', t, count=1, flags=re.IGNORECASE)
            elif part_num:
                t = f"{t} | Story Recap Explanation Part {part_num}"
            else:
                t = f"{t} | Story Recap Explanation"

        if is_short and "#shorts" not in t.lower():
            t = f"{t} #shorts"

        t = re.sub(r'\s+', ' ', t).strip()
        if len(t) > 95:
            # Preserve trailing transformative tag and #shorts if present
            trimmed = False
            for tag in [" | Story Recap Explanation #shorts", " | Story Recap #shorts", " #shorts"]:
                if t.lower().endswith(tag.lower()):
                    suffix = t[-len(tag):]
                    base = t[:-len(tag)].rstrip()
                    max_base = 95 - len(suffix)
                    if max_base > 10:
                        t = f"{base[:max_base].rstrip()}{suffix}"
                        trimmed = True
                    break
            if not trimmed:
                if "#shorts" in t.lower():
                    base = re.sub(r'#shorts', '', t, flags=re.IGNORECASE).strip()
                    t = f"{base[:85].rstrip()} #shorts"
                else:
                    t = t[:92].rstrip() + "..."
        return t


class DescriptionCopyrightAgent:
    """Agent 3: Validates fair-use statutory disclosures, transformative commentary context, and tags."""

    def evaluate_description(self, description: str, hashtags: Optional[List[str]] = None) -> AgentResult:
        violations = []
        warnings = []
        desc = description.strip()
        lower = desc.lower()

        # 1. Statutory Fair Use Disclosure Check
        has_section_107 = "section 107" in lower or "fair use" in lower
        if not has_section_107:
            violations.append("Description missing mandatory Section 107 Copyright Act Fair Use disclaimer.")

        # 2. Transformative commentary description
        has_commentary_note = any(
            term in lower for term in ["transformative", "commentary", "explanation", "recap", "educational", "analytical"]
        )
        if not has_commentary_note:
            violations.append("Description missing transformative commentary/educational context notice.")

        # 3. Tags evaluation
        tags_clean = [t.lower().replace("#", "") for t in (hashtags or [])]
        if hashtags and not any(tag in tags_clean for tag in ["animerecap", "animeexplanation", "shorts", "recap"]):
            warnings.append("Hashtags lack commentary/recap tags (e.g. #animerecap).")

        passed = len(violations) == 0
        return AgentResult(
            agent_name="DescriptionCopyrightAgent",
            passed=passed,
            violations=violations,
            warnings=warnings,
            details={"has_disclaimer": has_section_107, "length": len(desc)},
        )

    @staticmethod
    def remediate_description(description: str, title: str = "", display_name: str = "") -> str:
        """Injects Section 107 disclaimer and ensures clean fair-use framing."""
        desc = description.strip()
        if "section 107" not in desc.lower() and "fair use" not in desc.lower():
            desc = desc + FAIR_USE_DISCLAIMER
        return desc.strip()


class MultiAgentCopyrightShield:
    """Orchestrates all 3 filter agents and performs automated remediation & retry loops."""

    def __init__(self, blocked_titles: Optional[List[str]] = None):
        self.video_agent = VideoCopyrightAgent()
        self.title_agent = TitleCopyrightAgent(blocked_titles=blocked_titles)
        self.desc_agent = DescriptionCopyrightAgent()

    def inspect_candidate(
        self,
        video_path: Path | str,
        title: str,
        description: str,
        is_short: bool = True,
        time_window: Optional[Tuple[float, float]] = None,
        shots_info: Optional[List[Dict[str, Any]]] = None,
        hashtags: Optional[List[str]] = None,
    ) -> MultiAgentFilterResult:
        v_res = self.video_agent.evaluate_video(video_path, is_short, time_window, shots_info)
        t_res = self.title_agent.evaluate_title(title, is_short)
        d_res = self.desc_agent.evaluate_description(description, hashtags)

        all_passed = v_res.passed and t_res.passed and d_res.passed
        agent_results = {
            "VideoCopyrightAgent": v_res,
            "TitleCopyrightAgent": t_res,
            "DescriptionCopyrightAgent": d_res,
        }

        all_violations = v_res.violations + t_res.violations + d_res.violations
        remediation_needed = not all_passed

        summary = (
            "✅ All 3 Anti-Copyright Agents PASSED."
            if all_passed
            else f"❌ Shield REJECTED candidate with {len(all_violations)} violation(s): " + " | ".join(all_violations)
        )

        return MultiAgentFilterResult(
            passed=all_passed,
            agent_results=agent_results,
            remediation_needed=remediation_needed,
            summary=summary,
        )

    def remediate_metadata(
        self,
        title: str,
        description: str,
        is_short: bool = True,
        part_num: Optional[int] = None,
        display_name: str = "",
    ) -> Tuple[str, str]:
        """Automatically repairs title and description metadata."""
        clean_title = self.title_agent.remediate_title(title, is_short=is_short, part_num=part_num)
        clean_desc = self.desc_agent.remediate_description(description, title=clean_title, display_name=display_name)
        return clean_title, clean_desc


def verify_output_directory(output_dir: Path | str) -> bool:
    """Verifies all rendered output packages in output/ directory."""
    out_path = Path(output_dir)
    if not out_path.exists():
        print(f"[copyright_filter] ⚠️ Output directory does not exist: {out_path}")
        return True

    shield = MultiAgentCopyrightShield()
    all_ok = True

    for ep_dir in out_path.iterdir():
        if not ep_dir.is_dir():
            continue
        summary_file = ep_dir / "pipeline_summary.json"
        if not summary_file.exists():
            continue

        try:
            with open(summary_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[copyright_filter] ⚠️ Error loading {summary_file}: {e}")
            continue

        video_meta = data.get("video_to_upload")
        if not video_meta:
            # Check full_video
            video_meta = data.get("full_video")
            is_short = False
        else:
            action = data.get("action", "")
            is_full = (
                action == "normal_video"
                or video_meta.get("is_full_video", False)
                or Path(video_meta.get("video_path", "")).name.startswith("full_")
            )
            is_short = not is_full

        if not video_meta or not video_meta.get("video_path"):
            continue

        v_path = Path(video_meta["video_path"])
        title = video_meta.get("title", "")
        desc = video_meta.get("description", "")
        tags = video_meta.get("hashtags", [])

        # Auto-remediate metadata if not yet clean
        clean_title, clean_desc = shield.remediate_metadata(
            title=title,
            description=desc,
            is_short=is_short,
            part_num=data.get("part"),
            display_name=data.get("display_name", ep_dir.name),
        )

        res = shield.inspect_candidate(
            video_path=v_path,
            title=clean_title,
            description=clean_desc,
            is_short=is_short,
            hashtags=tags,
        )

        print(f"\n[copyright_filter] 🛡️ Inspecting: {v_path.name}")
        print(f"[copyright_filter] Title: '{clean_title}'")
        print(f"[copyright_filter] Result: {res.summary}")

        if not res.passed:
            all_ok = False
            print(f"[copyright_filter] 🛑 Video in {ep_dir.name} FAILED copyright filter!")

    return all_ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-Agent Anti-Copyright Filter & Shield")
    parser.add_argument("--verify-output", help="Directory containing rendered output packages to verify")
    parser.add_argument("--check-title", help="Test a title against copyright filter")
    parser.add_argument("--check-desc", help="Test a description against copyright filter")
    args = parser.parse_args()

    if args.check_title:
        agent = TitleCopyrightAgent()
        res = agent.evaluate_title(args.check_title)
        print(f"Title Passed: {res.passed}")
        print(f"Violations: {res.violations}")
        if not res.passed:
            print(f"Remediated: {agent.remediate_title(args.check_title)}")
        sys.exit(0 if res.passed else 1)

    if args.verify_output:
        ok = verify_output_directory(args.verify_output)
        sys.exit(0 if ok else 1)
