#!/usr/bin/env python3
"""
Assemble a 9:16 YouTube Short (1080x1920) from the script + assets.

Inputs (in the campaign dir):
  - script.json       : storyboard with slides (text, visual type, notes)
  - assets/index.json : asset index from fetch_assets.py
  - assets/*.mp3/wav  : campaign BGM (optional)

Output:
  - video.mp4         : 1080x1920, 30fps, ~3s/slide, BGM or silent audio

Slide rendering:
  - text-card / notes-app: Pillow render on dark gradient bg
  - lifestyle-photo / product-photo / retail-shot / persona-selfie:
      * if asset.src == "local": load campaign-provided image, fit to 1080x1920
      * if asset.src == "render": Pillow text-card fallback

Audio:
  - Campaign BGM (mp3/wav from assets/) if available — looped, volume reduced
  - Silent track otherwise (YouTube requires audio)

ffmpeg concat: generate individual slide MP4s -> concat -> mix audio -> final.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Pillow
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
FPS = 30
SLIDE_SEC = 3.0
SLIDE_FRAMES = int(SLIDE_SEC * FPS)
BG_COLOR = (18, 18, 24)
TEXT_WHITE = (255, 255, 255)
TEXT_DIM = (200, 200, 200)
MAX_TEXT_W = int(W * 0.88)
FONT_PATH = None

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac"}
BGM_VOLUME = "0.3"  # ffmpeg volume filter — background music should be quiet


def pick_font(size: int) -> ImageFont.FreeTypeFont:
    global FONT_PATH
    if FONT_PATH is None:
        for cand in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/system/fonts/Roboto-Regular.ttf",
            "/data/data/com.termux/files/usr/share/fonts/DejaVuSans.ttf",
        ]:
            if os.path.exists(cand):
                FONT_PATH = cand
                break
    if FONT_PATH:
        return ImageFont.truetype(FONT_PATH, size)
    return ImageFont.load_default()


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words = text.split()
    lines, cur = [], []
    for w in words:
        test = " ".join(cur + [w])
        if draw.textlength(test, font=font) <= max_w:
            cur.append(w)
        else:
            if cur:
                lines.append(" ".join(cur))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))
    return lines or [""]


def render_text_card(slide_text: str, visual: str, notes: str = "") -> Image.Image:
    img = Image.new("RGB", (W, H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    for y in range(H):
        alpha = int(40 * (y / H))
        draw.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))

    font = pick_font(72)
    lines = wrap_text(draw, slide_text, font, MAX_TEXT_W)
    line_h = font.getbbox("Ay")[3] - font.getbbox("Ay")[1]
    total_h = line_h * len(lines) + 16 * (len(lines) - 1)
    y_start = (H - total_h) // 2

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (W - (bbox[2] - bbox[0])) // 2
        y = y_start + i * (line_h + 16)
        draw.text((x + 3, y + 3), line, font=font, fill=(0, 0, 0, 180))
        draw.text((x, y), line, font=font, fill=TEXT_WHITE)

    badge_font = pick_font(28)
    draw.text((40, H - 60), f"[{visual}]", font=badge_font, fill=TEXT_DIM)

    if notes:
        note_font = pick_font(24)
        note_lines = wrap_text(draw, notes, note_font, MAX_TEXT_W)
        ny = H - 40 - (note_font.getbbox("Ay")[3] + 6) * len(note_lines)
        for nl in note_lines:
            bbox = draw.textbbox((0, 0), nl, font=note_font)
            draw.text((W - bbox[2] - 40, ny), nl, font=note_font, fill=TEXT_DIM)
            ny += note_font.getbbox("Ay")[3] + 6

    return img


def fit_image_cover(src_path: str) -> Image.Image:
    try:
        im = Image.open(src_path).convert("RGB")
    except Exception:
        return Image.new("RGB", (W, H), BG_COLOR)

    src_w, src_h = im.size
    target_ratio = W / H
    src_ratio = src_w / src_h
    if src_ratio > target_ratio:
        new_w = int(src_h * target_ratio)
        left = (src_w - new_w) // 2
        im = im.crop((left, 0, left + new_w, src_h))
    else:
        new_h = int(src_w / target_ratio)
        top = (src_h - new_h) // 2
        im = im.crop((0, top, src_w, top + new_h))
    return im.resize((W, H), Image.LANCZOS)


def render_photo_slide(text: str, visual: str, img_path: str, notes: str = "") -> Image.Image:
    base = fit_image_cover(img_path)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 140))
    base = base.convert("RGBA")
    base = Image.alpha_composite(base, overlay).convert("RGB")
    draw = ImageDraw.Draw(base)

    font = pick_font(72)
    lines = wrap_text(draw, text, font, MAX_TEXT_W)
    line_h = font.getbbox("Ay")[3] - font.getbbox("Ay")[1]
    total_h = line_h * len(lines) + 16 * (len(lines) - 1)
    y_start = (H - total_h) // 2

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (W - (bbox[2] - bbox[0])) // 2
        y = y_start + i * (line_h + 16)
        draw.text((x + 3, y + 3), line, font=font, fill=(0, 0, 0, 180))
        draw.text((x, y), line, font=font, fill=TEXT_WHITE)

    badge_font = pick_font(28)
    draw.text((40, H - 60), f"[{visual}]", font=badge_font, fill=TEXT_DIM)

    if notes:
        note_font = pick_font(24)
        note_lines = wrap_text(draw, notes, note_font, MAX_TEXT_W)
        ny = H - 40 - (note_font.getbbox("Ay")[3] + 6) * len(note_lines)
        for nl in note_lines:
            bbox = draw.textbbox((0, 0), nl, font=note_font)
            draw.text((W - bbox[2] - 40, ny), nl, font=note_font, fill=TEXT_DIM)
            ny += note_font.getbbox("Ay")[3] + 6

    return base


def render_slide(slide: dict, asset: dict, campaign_dir: str) -> Image.Image:
    visual = slide.get("visual", "text-card")
    text = slide.get("text", "")
    notes = slide.get("notes", "")

    src = asset.get("src", "render")
    path = asset.get("path")

    if visual in ("lifestyle-photo", "product-photo", "retail-shot", "persona-selfie"):
        if src == "local" and path:
            full = os.path.join(campaign_dir, path)
            if os.path.exists(full):
                return render_photo_slide(text, visual, full, notes)
    return render_text_card(text, visual, notes)


def slide_to_mp4(img: Image.Image, out_path: str):
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        img.save(tmp.name, "PNG")
        png_path = tmp.name
    try:
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-framerate", str(FPS),
            "-i", png_path, "-c:v", "libx264", "-t", str(SLIDE_SEC),
            "-pix_fmt", "yuv420p",
            "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2",
            out_path
        ]
        subprocess.run(cmd, check=True, capture_output=True)
    finally:
        os.unlink(png_path)


def concat_slides(slide_mp4s: list[str], out_path: str):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for p in slide_mp4s:
            f.write(f"file '{os.path.abspath(p)}'\n")
        list_path = f.name
    try:
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
            "-c", "copy", "-movflags", "+faststart", out_path
        ]
        subprocess.run(cmd, check=True, capture_output=True)
    finally:
        os.unlink(list_path)


def find_bgm(campaign_dir: str) -> str | None:
    """Find an audio file in assets/ for BGM."""
    asset_dir = os.path.join(campaign_dir, "assets")
    if not os.path.isdir(asset_dir):
        return None
    for f in sorted(os.listdir(asset_dir)):
        if os.path.splitext(f)[1].lower() in AUDIO_EXTS:
            return os.path.join(asset_dir, f)
    return None


def add_audio(video_path: str, bgm_path: str | None, out_path: str, duration: float):
    """Mix BGM into video, or add silent audio track if no BGM."""
    if bgm_path:
        # loop BGM, reduce volume, trim to video length
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-stream_loop", "-1", "-i", bgm_path,
            "-filter_complex",
            f"[1:a]volume={BGM_VOLUME},afade=t=out:st={duration - 1}:d=1[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            "-t", str(duration),
            "-movflags", "+faststart",
            out_path,
        ]
        print(f"  mixing BGM: {os.path.basename(bgm_path)} (vol={BGM_VOLUME})")
    else:
        # generate silent audio track — YouTube requires audio
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "64k",
            "-t", str(duration),
            "-movflags", "+faststart",
            out_path,
        ]
        print("  no BGM found — adding silent audio track")

    subprocess.run(cmd, check=True, capture_output=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", required=True, help="campaign dir")
    ap.add_argument("--output", default="video.mp4", help="output video file")
    args = ap.parse_args()

    script_path = os.path.join(args.dir, "script.json")
    assets_path = os.path.join(args.dir, "assets", "index.json")
    out_path = os.path.join(args.dir, args.output)

    if not os.path.exists(script_path):
        print(f"ERROR: {script_path} not found", file=sys.stderr)
        return 1
    if not os.path.exists(assets_path):
        print(f"ERROR: {assets_path} not found", file=sys.stderr)
        return 1

    script = json.load(open(script_path, encoding="utf-8"))
    assets = json.load(open(assets_path, encoding="utf-8")).get("slides", {})
    n_slides = len(script["slides"])
    total_duration = n_slides * SLIDE_SEC

    print(f"Building video: {n_slides} slides -> {out_path}")

    # find BGM
    bgm = find_bgm(args.dir)

    with tempfile.TemporaryDirectory() as tmpdir:
        slide_files = []
        for i, slide in enumerate(script["slides"]):
            n = slide.get("n", i + 1)
            asset = assets.get(str(n), {"src": "render"})
            print(f"  slide {n}: visual={slide.get('visual')} src={asset.get('src')}")
            img = render_slide(slide, asset, args.dir)
            mp4_path = os.path.join(tmpdir, f"slide_{n}.mp4")
            slide_to_mp4(img, mp4_path)
            slide_files.append(mp4_path)

        # concat slides (video only, no audio yet)
        concat_slides(slide_files, out_path)

        # mix in audio
        if bgm or True:  # always add audio (silent fallback)
            audio_out = os.path.join(tmpdir, "final_audio.mp4")
            add_audio(out_path, bgm, audio_out, total_duration)
            os.replace(audio_out, out_path)

    if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
        size_kb = os.path.getsize(out_path) // 1024
        print(f"OK: {out_path} ({size_kb}KB, {total_duration:.0f}s, {'BGM' if bgm else 'silent'})")
        return 0
    else:
        print("ERROR: video not created", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
