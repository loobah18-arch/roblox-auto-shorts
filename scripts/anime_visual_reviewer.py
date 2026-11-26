#!/usr/bin/env python3
"""
Automated Visual Alignment Reviewer for Anime Explanation Engine.
Runs in GitHub Actions CI to thoroughly review rendered video clips against
the spoken narration text, ensuring visual-to-narrative synchronization without
needing to download heavy video files to a mobile device.
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


def log(msg: str):
    print(f"[visual_reviewer] {msg}", flush=True)


def extract_frame(video_path: Path, timestamp: float, output_img: Path) -> bool:
    """Extract a single frame from video at timestamp using ffmpeg."""
    output_img.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{timestamp:.2f}",
        "-i", str(video_path),
        "-vframes", "1",
        "-q:v", "3",
        str(output_img)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.returncode == 0 and output_img.exists() and output_img.stat().st_size > 1000


def evaluate_frame_alignment(
    image_path: Path,
    narration: str,
    hook: str,
    part_num: int,
) -> dict:
    """
    Ask a vision model (shared anime_llm chain: Gemini flash models, Groq Llama 4 vision, OpenRouter /
    NVIDIA vision models, picked from the live model lists) whether the frame shows what the narration
    says. When no model answers, the result is {"skipped": True} - never a made-up PASS.
    """
    from anime_llm import complete, extract_json
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    prompt = (
        "You check anime recap videos: the footage on screen must show the scene the narrator is describing.\n\n"
        f"Chapter {part_num} ({hook}). Narration spoken over this frame:\n{narration}\n\n"
        "Look at the attached frame. Return JSON only: {\"visual_description\": <one sentence: who/what is visible>, "
        "\"matches_narration\": true|false, \"alignment_score\": <integer 1-10>, \"feedback\": <one sentence>}"
    )

    def validator(text: str) -> None:
        d = extract_json(text)
        if not isinstance(d, dict) or "alignment_score" not in d:
            raise ValueError("no alignment_score in answer")
        int(d["alignment_score"])

    res = complete(prompt, json_mode=True, temperature=0.2, max_tokens=1200, image_b64=img_b64, vision=True,
                   validator=validator, timeout=90, max_429_wait=30, label=f"vision review ch{part_num}")
    if not res:
        return {"skipped": True, "visual_description": "", "matches_narration": None, "alignment_score": None,
                "feedback": "no vision model answered; frame not reviewed"}
    d = extract_json(res[0])
    d["alignment_score"] = int(d["alignment_score"])
    d["model"] = res[1]
    d["skipped"] = False
    return d


def review_rendered_episode(ep_dir: Path) -> dict:
    """Inspects all parts in ep_dir, extracts frames, and checks alignment."""
    summary_f = ep_dir / "pipeline_summary.json"
    if not summary_f.exists():
        log(f"No pipeline_summary.json found in {ep_dir}")
        return {"status": "error", "message": "pipeline_summary.json missing"}

    with open(summary_f, "r", encoding="utf-8") as f:
        summary = json.load(f)

    script_pkg_f = ep_dir / "script_package.json"
    cinema_script_f = ep_dir / "cinema_script.json"
    arc_script_files = sorted(list(ep_dir.glob("arc_script*.json")))

    if script_pkg_f.exists():
        with open(script_pkg_f, "r", encoding="utf-8") as f:
            script_package = json.load(f)
    elif cinema_script_f.exists():
        with open(cinema_script_f, "r", encoding="utf-8") as f:
            cinema_script = json.load(f)
        script_package = {
            "episode_title": cinema_script.get("title", ep_dir.name),
            "parts": [
                {
                    "part": 1,
                    "short_title": cinema_script.get("title", ep_dir.name),
                    "narration": cinema_script.get("narration", ""),
                    "hook": cinema_script.get("hook", ""),
                    "beats": cinema_script.get("beats", []),
                    "estimated_duration": float(cinema_script.get("estimated_duration", 150.0)),
                }
            ],
        }
    elif (ep_dir / "episode_script.json").exists():
        ep_script = json.loads((ep_dir / "episode_script.json").read_text(encoding="utf-8"))
        tl_f = ep_dir / "beat_timeline.json"
        timeline = json.loads(tl_f.read_text(encoding="utf-8")) if tl_f.exists() else []
        acts = ep_script.get("acts", [])
        script_package = {
            "episode_title": ep_script.get("title", ep_dir.name),
            "parts": [
                {
                    "part": idx + 1,
                    "short_title": act.get("title", f"Act {idx + 1}"),
                    "narration": " ".join(b["text"] for b in timeline if b.get("chapter_index") == idx),
                    "hook": act.get("title", ""),
                    "beats": [],
                    "estimated_duration": 60.0,
                    "timed_beats": [b for b in timeline if b.get("chapter_index") == idx],
                }
                for idx, act in enumerate(acts)
            ],
        }
    elif arc_script_files:
        with open(arc_script_files[0], "r", encoding="utf-8") as f:
            arc_script = json.load(f)
        chapters = arc_script.get("chapters", [])
        tl_files = sorted(ep_dir.glob("beat_timeline*.json"))
        timeline = json.loads(tl_files[0].read_text(encoding="utf-8")) if tl_files else []
        script_package = {
            "episode_title": arc_script.get("full_video", {}).get("title", arc_script.get("arc_name", ep_dir.name)),
            "parts": [
                {
                    "part": ch.get("chapter", idx + 1),
                    "short_title": ch.get("chapter_title", ch.get("title", f"Chapter {idx+1}")),
                    "narration": ch.get("narration", ""),
                    "hook": ch.get("chapter_title", ""),
                    "beats": ch.get("beats", []),
                    "time_range": ch.get("time_range", [120, 500]),
                    "estimated_duration": float(ch.get("estimated_duration", 180.0)),
                    "timed_beats": [b for b in timeline if b.get("chapter_index") == idx],
                }
                for idx, ch in enumerate(chapters)
            ],
        }
    elif summary.get("parts"):
        script_package = {
            "episode_title": summary.get("display_name", ep_dir.name),
            "parts": summary["parts"],
        }
    else:
        script_package = summary.get("script_package", {})

    parts = script_package.get("parts", [])
    if not parts:
        log("No parts found in script package.")
        return {"status": "error", "message": "no parts"}

    review_results = []
    frames_dir = ep_dir / "review_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    master_vid = None
    vid_candidates = [
        Path(summary.get("video_to_upload", {}).get("video_path", "")),
        Path(summary.get("full_video", {}).get("video_path", "")),
        ep_dir / f"full_{ep_dir.name}.mp4",
    ] + list(ep_dir.glob("full_*.mp4"))
    for cand in vid_candidates:
        if cand and cand.exists() and cand.is_file() and cand.stat().st_size > 1024 * 50:
            master_vid = cand
            break
    use_master = master_vid is not None and master_vid.exists()

    log(f"🎬 Starting Visual Review for {ep_dir.name} ({len(parts)} parts, master_mode={use_master})...")

    master_dur = 0.0
    if use_master:
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(master_vid)
        ]
        try:
            dur_res = subprocess.run(probe_cmd, capture_output=True, text=True)
            master_dur = float(dur_res.stdout.strip())
        except Exception:
            master_dur = 240.0

    accum_time = 0.0
    for part_info in parts:
        p_num = part_info.get("part", 1)
        p_dir = ep_dir / f"part_{p_num:02d}"

        # Prioritize master video if available, else check landscape/short parts
        vid_f = master_vid if use_master else None
        if not vid_f or not vid_f.exists():
            candidates = [
                p_dir / f"landscape_{ep_dir.name}_part{p_num}.mp4",
                p_dir / f"short_{ep_dir.name}_part{p_num}.mp4",
                ep_dir / f"cinema_{ep_dir.name}.mp4",
                ep_dir / f"short_{ep_dir.name}.mp4",
            ]
            vid_f = next((c for c in candidates if c.exists()), None)

        if not vid_f or not vid_f.exists():
            log(f"Part {p_num} video not found in {p_dir}")
            continue

        # Determine chapter duration & beat sample times
        est_dur = float(part_info.get("estimated_duration", 60.0))
        beats = part_info.get("beats", [])

        timed = part_info.get("timed_beats") or []
        beat_texts = None
        if use_master and timed:
            # exact beat slots from the TTS timeline: sample the middle of two beats per chapter
            picks = [timed[len(timed) // 3], timed[(2 * len(timed)) // 3]] if len(timed) > 1 else timed
            sample_times = [(b["start"] + b["end"]) / 2.0 for b in picks]
            beat_texts = [b["text"] for b in picks]
        elif use_master and beats:
            sample_times = []
            beat_accum = accum_time
            for b in beats:
                b_dur = est_dur * float(b.get("weight", 1.0 / len(beats)))
                sample_times.append(beat_accum + (b_dur * 0.5))
                beat_accum += b_dur
            accum_time += est_dur
        elif use_master:
            dur = est_dur
            sample_times = [accum_time + dur * 0.25, accum_time + dur * 0.50, accum_time + dur * 0.75]
            accum_time += dur
        elif beats:
            sample_times = []
            b_accum = 0.0
            for b in beats:
                b_dur = est_dur * float(b.get("weight", 1.0 / len(beats)))
                sample_times.append(b_accum + (b_dur * 0.5))
                b_accum += b_dur
        else:
            sample_times = [est_dur * 0.25, est_dur * 0.50, est_dur * 0.75]

        # For long multi-chapter arc videos, cap samples to 2 per chapter to stay fast & within API limits
        if len(parts) > 5:
            sample_times = sample_times[:2]
        else:
            sample_times = sample_times[:3]

        part_evals = []
        log(f"🔍 Part {p_num} ({vid_f.name}): Evaluating {len(sample_times)} beat frames...")

        for idx, t in enumerate(sample_times, start=1):
            frame_img = frames_dir / f"part_{p_num:02d}_frame_{idx}.jpg"
            if extract_frame(vid_f, t, frame_img):
                eval_data = evaluate_frame_alignment(
                    image_path=frame_img,
                    narration=(beat_texts[idx - 1] if beat_texts and idx - 1 < len(beat_texts) else part_info.get("narration", "")),
                    hook=part_info.get("hook", ""),
                    part_num=p_num,
                )
                eval_data["frame_path"] = str(frame_img.relative_to(ep_dir))
                eval_data["timestamp_in_clip"] = round(t, 2)
                part_evals.append(eval_data)
                log(f"  Beat Frame {idx} ({t:.1f}s): Score {eval_data.get('alignment_score') if not eval_data.get('skipped') else 'skipped'}/10 | {(eval_data.get('visual_description') or '')[:70]}")

        # Calculate average score for this part
        scores = [e["alignment_score"] for e in part_evals if not e.get("skipped") and e.get("alignment_score") is not None]
        if scores:
            avg_score = round(sum(scores) / len(scores), 1)
            part_verdict = "PASS" if avg_score >= 6.5 else "WARN"
        else:
            avg_score = None
            part_verdict = "skipped"

        review_results.append({
            "part": p_num,
            "title": part_info.get("short_title", f"Part {p_num}"),
            "time_range": part_info.get("time_range", []),
            "avg_score": avg_score,
            "verdict": part_verdict,
            "evaluations": part_evals,
        })

    # Overall summary
    scored = [r for r in review_results if r["avg_score"] is not None]
    total_avg = round(sum(r["avg_score"] for r in scored) / len(scored), 1) if scored else None
    if not scored:
        overall_status = "skipped"
    elif all(r["verdict"] in ("PASS", "skipped") for r in review_results):
        overall_status = "PASS" if len(scored) == len(review_results) else "PARTIAL"
    else:
        overall_status = "WARN"

    report = {
        "episode_key": ep_dir.name,
        "overall_status": overall_status,
        "overall_score": total_avg,
        "parts": review_results,
    }

    # Write review_summary.json
    with open(ep_dir / "review_summary.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    # Generate Markdown Report
    md_lines = [
        f"# 🎬 Visual Alignment Quality Report: {ep_dir.name}",
        f"\n**Overall Status**: `{overall_status}` | **Alignment Score**: `{total_avg}/10`\n",
        "| Part | Scene Range (Raw Episode) | Score | Verdict | Visual Summary |",
        "|---|---|---|---|---|",
    ]
    for r in review_results:
        summary_desc = r["evaluations"][0].get("visual_description", "") if r["evaluations"] else "N/A"
        md_lines.append(f"| Part {r['part']} | {r['time_range']} | {r['avg_score']}/10 | `{r['verdict']}` | {summary_desc} |")

    md_lines.append("\n## Detailed Scene Evaluations\n")
    for r in review_results:
        md_lines.append(f"### Part {r['part']}: {r['title']}")
        md_lines.append(f"- **Scene Window**: `{r['time_range']}`")
        md_lines.append(f"- **Average Alignment Score**: `{r['avg_score']}/10` ({r['verdict']})\n")
        for idx, ev in enumerate(r["evaluations"], start=1):
            md_lines.append(f"**Sample Frame {idx}** (T={ev['timestamp_in_clip']}s):")
            md_lines.append(f"- **Visible in Footage**: {ev.get('visual_description')}")
            md_lines.append(f"- **Score**: {ev.get('alignment_score')}/10 | **Match**: {ev.get('matches_narration')}")
            md_lines.append(f"- **Feedback**: {ev.get('feedback')}\n")

    report_md_path = ep_dir / "visual_review_report.md"
    report_md_path.write_text("\n".join(md_lines), encoding="utf-8")
    log(f"📝 Visual Review Report generated at: {report_md_path}")
    return report


def main():
    parser = argparse.ArgumentParser(description="Visual Alignment Reviewer for Anime Engine")
    parser.add_argument("--dir", required=True, help="Episode output directory (e.g. output/demon-slayer-s01e05)")
    args = parser.parse_args()

    ep_dir = Path(args.dir)
    if not ep_dir.exists():
        log(f"Directory {ep_dir} does not exist.")
        sys.exit(1)

    res = review_rendered_episode(ep_dir)
    print("\n" + "=" * 50)
    print(f"🎬 REVIEW COMPLETE: {res.get('overall_status')} ({res.get('overall_score')}/10)")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    main()
