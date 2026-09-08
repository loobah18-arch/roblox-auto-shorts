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
  - text-card / notes-app: Pillow render on a dark gradient bg
  - lifestyle-photo / product-photo / retail-shot / persona-selfie:
      * if asset.src == "local" and media == "image": campaign photo, fit to 1080x1920
      * if asset.src == "local" and media == "video": campaign video clip
        (scaled/cropped, slide text burned in) as a moving slide
      * if asset.src == "render": Pillow text-card fallback

How the output is made to look hand-made (not a templated slideshow):
  - Ken Burns motion: slow push-in with a vertical drift on every still slide, so
    photos and text cards breathe instead of sitting frozen.
  - Soft 0.2s fade in/out on each slide so cuts don't feel like a machine splice.
  - Shorts-style captions: bold type, a yellow "chip" highlight on the words the
    script itself CAPITALIZED for emphasis (or the first short keywords), set
    over a legible dark scrim. No debug badges, no production notes on screen.

Audio:
  - Campaign BGM (mp3/wav from assets/) if available — looped, volume reduced
  - Silent track otherwise (YouTube requires audio)
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

# Pillow
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
FPS = 30
SLIDE_SEC = 3.0
SLIDE_FRAMES = int(SLIDE_SEC * FPS)
BG_COLOR = (18, 18, 24)
TEXT_WHITE = (255, 255, 255)
ACCENT = (250, 204, 21)   # sunny yellow — the classic short caption emphasis
CHIP_INK = (30, 30, 30)
MAX_TEXT_W = int(W * 0.86)
FONT_PATH = None

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac"}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
BGM_VOLUME = "0.3"  # ffmpeg volume filter — background music should be quiet
FADE_D = 0.22       # seconds of fade in/out on each slide
KENBURNS_ZMAX = 1.16  # push-in target (16% zoom) — enough motion, never dizzy


def pick_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
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
        path = FONT_PATH
        if bold:
            cand = (FONT_PATH.replace("DejaVuSans.ttf", "DejaVuSans-Bold.ttf")
                              .replace("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf")
                              .replace("Roboto-Regular.ttf", "Roboto-Bold.ttf"))
            if os.path.exists(cand):
                path = cand
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _pick_accent_words(text: str) -> list[str]:
    """Words a human editor would pop with a color chip. Prefer the words the
    script itself CAPITALIZED for emphasis (read: the scout / LLM already marked
    them as hook words); otherwise the first short keyword."""
    words = text.split()
    caps = []
    for w in words:
        k = w.strip(".,!?;:'\"()")
        if len(k) >= 2 and k.isupper() and any(c.isalpha() for c in k):
            caps.append(k)
    if caps:
        return list(dict.fromkeys(caps))[:2]
    short = [w.strip(".,!?;:'\"()") for w in words
             if len(w.strip(".,!?;:'\"()")) <= 6 and any(c.isalpha() for c in w)]
    return list(dict.fromkeys(short))[:2]


def _wrap_words(draw: ImageDraw.ImageDraw, words: list[str],
                font: ImageFont.FreeTypeFont, max_w: int) -> list[list[str]]:
    lines, cur, curw = [], [], 0.0
    for w in words:
        ww = draw.textlength(w + " ", font=font)
        if cur and curw + ww > max_w:
            lines.append(cur)
            cur, curw = [w], draw.textlength(w + " ", font=font)
        else:
            cur.append(w)
            curw += ww
    if cur:
        lines.append(cur)
    return lines


def draw_caption_on(draw: ImageDraw.ImageDraw, text: str):
    """Shorts-style caption: bold words, yellow chips on emphasized words, set
    slightly below centre with a soft scrim band so it reads over any footage."""
    accent_lower = {w.lower() for w in _pick_accent_words(text)}
    font = pick_font(78, bold=True)
    words = text.split()
    lines = _wrap_words(draw, words, font, MAX_TEXT_W)
    line_h = font.getbbox("Ay")[3] - font.getbbox("Ay")[1]
    line_gap = 20
    total = line_h * len(lines) + line_gap * (len(lines) - 1)

    y_start = int(H * 0.40)
    band_y0 = max(0, y_start - 42)
    band_y1 = min(H, y_start + total + 44)
    for yy in range(band_y0, band_y1):
        a = 96 if (band_y0 + 90 < yy < band_y1 - 90) else 64
        draw.line([(0, yy), (W, yy)], fill=(0, 0, 0, a))

    y = y_start
    word_gap = 14
    for line in lines:
        line_w = sum(draw.textlength(w, font=font) for w in line) + word_gap * (len(line) - 1)
        x = (W - line_w) // 2
        for w in line:
            ww = draw.textlength(w, font=font)
            key = w.strip(".,!?;:'\"()").lower()
            if key in accent_lower and any(c.isalpha() for c in key):
                pad = 16
                rx, ry, rw, rh = x - pad, y - pad, int(ww) + 2 * pad, line_h + 2 * pad
                try:
                    draw.rounded_rectangle([rx, ry, rx + rw, ry + rh], radius=14, fill=ACCENT)
                except Exception:
                    draw.rectangle([rx, ry, rx + rw, ry + rh], fill=ACCENT)
                draw.text((x, y), w, font=font, fill=CHIP_INK)
            else:
                draw.text((x + 3, y + 3), w, font=font, fill=(0, 0, 0, 200))
                draw.text((x, y), w, font=font, fill=TEXT_WHITE)
            x += ww + word_gap
        y += line_h + line_gap


def _text_bg() -> Image.Image:
    """Dark study background with a faint downward gradient + subtle top glow so
    a text card reads as a designed frame, not a flat black rectangle."""
    base = Image.new("RGB", (W, H), BG_COLOR)
    g = Image.new("RGB", (1, H))
    for yy in range(H):
        t = yy / H
        g.putpixel((0, yy), (int(24 + 8 * t), int(24 + 8 * t), int(30 + 12 * t)))
    g = g.resize((W, H))
    out = Image.blend(base, g, 0.7)
    return out


def render_text_card(slide_text: str, visual: str = "", notes: str = "") -> Image.Image:
    img = _text_bg()
    draw = ImageDraw.Draw(img, "RGBA")
    draw_caption_on(draw, slide_text)
    return img


def fit_image_cover(src_path: str) -> Image.Image:
    try:
        im = Image.open(src_path).convert("RGB")
    except Exception:
        # Pillow may lack a HEIF codec for a stray .heic that fetch_assets could
        # not transcode — try ffmpeg to lift a JPEG frame so the slide still shows
        # the campaign photo instead of a black card.
        jpeg = _ffmpeg_frame_to_jpeg(src_path)
        if jpeg:
            try:
                im = Image.open(jpeg).convert("RGB")
            except Exception:
                return Image.new("RGB", (W, H), BG_COLOR)
        else:
            return Image.new("RGB", (W, H), BG_COLOR)

    try:
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
    except Exception:
        # truncated/corrupt pixel data only surfaces here (lazy decode), not in
        # the Image.open above — a single bad file must not abort the whole build
        return Image.new("RGB", (W, H), BG_COLOR)


def _ffmpeg_frame_to_jpeg(src_path: str) -> str | None:
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        dst = tmp.name
    try:
        subprocess.run(["ffmpeg", "-y", "-i", src_path, "-frames:v", "1",
                        "-q:v", "2", dst], capture_output=True, timeout=60)
        if os.path.getsize(dst) > 2000:
            return dst
    except Exception:
        pass
    try:
        os.unlink(dst)
    except Exception:
        pass
    return None


def render_photo_slide(text: str, visual: str = "", img_path: str = "",
                       notes: str = "") -> Image.Image:
    base = fit_image_cover(img_path)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 120))
    base = Image.alpha_composite(base.convert("RGBA"), ov).convert("RGB")
    draw = ImageDraw.Draw(base, "RGBA")
    draw_caption_on(draw, text)
    return base


def render_slide(slide: dict, asset: dict, campaign_dir: str) -> Image.Image:
    visual = slide.get("visual", "text-card")
    text = slide.get("text", "")
    src = asset.get("src", "render")
    path = asset.get("path")

    if visual in ("lifestyle-photo", "product-photo", "retail-shot", "persona-selfie"):
        if src == "local" and path:
            full = os.path.join(campaign_dir, path)
            if os.path.exists(full):
                return render_photo_slide(text, visual, full)
    return render_text_card(text, visual)


def render_text_overlay(text: str, visual: str = "", notes: str = "") -> Image.Image:
    """Transparent RGBA overlay of the shorts-style caption, burned on top of a
    campaign video clip so the moving footage stays visible under the text."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw_caption_on(draw, text)
    return img


def _fade_vf() -> str:
    return (f"fade=t=in:st=0:d={FADE_D},"
            f"fade=t=out:st={SLIDE_SEC - FADE_D:.2f}:d={FADE_D}")


def video_slide_to_mp4(slide: dict, video_path: str, out_path: str):
    """Use a campaign video clip as a moving slide: scale/crop to 1080x1920,
    loop to fill SLIDE_SEC, burn the caption overlay in, soft fade at the edges."""
    text = slide.get("text", "")
    visual = slide.get("visual", "video")
    overlay = render_text_overlay(text, visual)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        overlay.save(tmp.name, "PNG")
        ov_path = tmp.name
    try:
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", video_path,
            "-i", ov_path,
            "-filter_complex",
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,format=rgba[bv];"
            f"[bv][1:v]overlay=0:0:format=auto,{_fade_vf()},format=yuv420p[vout]",
            "-map", "[vout]",
            "-t", str(SLIDE_SEC), "-r", str(FPS),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            out_path,
        ]
        subprocess.run(cmd, check=True, capture_output=True)
    finally:
        os.unlink(ov_path)


def render_kenburns_mp4(img: Image.Image, out_path: str):
    """Encode a still slide as a 3s moving clip: scale up for zoom headroom, then
    per-frame crop a window that slowly pushes in (Ken Burns) with a gentle sink,
    feeding raw RGB frames straight into ffmpeg. Adds the per-slide fades."""
    frames = SLIDE_FRAMES
    big = img.resize((int(W * KENBURNS_ZMAX), int(H * KENBURNS_ZMAX)), Image.LANCZOS)
    bw, bh = big.size

    cmd = ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-frames:v", str(frames),
           "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
           "-vf", _fade_vf(), out_path]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rgb = img.convert("RGB")
    for i in range(frames):
        f = i / (frames - 1) if frames > 1 else 1.0
        z = 1.0 + (KENBURNS_ZMAX - 1.0) * f
        cw = max(int(bw / z), 4) - (int(bw / z) % 2)
        ch = max(int(bh / z), 4) - (int(bh / z) % 2)
        cx = (bw - cw) // 2
        drift = int((bh - ch) * 0.05 * f)   # slight camera sink, subtle
        cy = max(0, min(bh - ch, (bh - ch) // 2 + drift))
        crop = big.crop((cx, cy, cx + cw, cy + ch)).resize((W, H), Image.LANCZOS)
        p.stdin.write(crop.tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("kenburns encode failed")


def slide_to_mp4_static(img: Image.Image, out_path: str):
    """Static fallback (and the safe default if Ken Burns ever fails) — still
    keeps the per-slide fade so transitions stay soft."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        img.save(tmp.name, "PNG")
        png_path = tmp.name
    try:
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-framerate", str(FPS),
            "-i", png_path, "-c:v", "libx264", "-t", str(SLIDE_SEC),
            "-pix_fmt", "yuv420p",
            "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                   f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,{_fade_vf()}",
            out_path
        ]
        subprocess.run(cmd, check=True, capture_output=True)
    finally:
        os.unlink(png_path)


def concat_slides(slide_mp4s: list[str], out_path: str):
    """Join slide MP4s with the concat FILTER (re-encode). More robust than the
    concat demuxer + `-c copy`, which can fail across different libx264 parameter
    sets (cards vs. clip slides encode with different timebases). Short video, so
    a veryfast x264 re-encode here is cheap and guarantees compatibility."""
    if not slide_mp4s:
        raise RuntimeError("no slides rendered")
    ins, chains = [], []
    for i, p in enumerate(slide_mp4s):
        ins += ["-i", p]
        chains.append(
            f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p[v{i}]")
    chains.append(
        "".join(f"[v{i}]" for i in range(len(slide_mp4s)))
        + f"concat=n={len(slide_mp4s)}:v=1:a=0,format=yuv420p[vout]")
    cmd = [
        "ffmpeg", "-y", *ins, "-filter_complex", ";".join(chains),
        "-map", "[vout]", "-c:v", "libx264", "-preset", "veryfast",
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-movflags", "+faststart",
        out_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


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
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
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
    out_path = args.output if os.path.isabs(args.output) else os.path.join(args.dir, args.output)

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

    bgm = find_bgm(args.dir)

    with tempfile.TemporaryDirectory() as tmpdir:
        slide_files = []
        for i, slide in enumerate(script["slides"]):
            n = slide.get("n", i + 1)
            asset = assets.get(str(n), {"src": "render"})
            mp4_path = os.path.join(tmpdir, f"slide_{n}.mp4")
            media = asset.get("media")
            print(f"  slide {n}: visual={slide.get('visual')} src={asset.get('src')} media={media}")
            if media == "video" and asset.get("src") == "local" and asset.get("path"):
                full = os.path.join(args.dir, asset["path"])
                if os.path.exists(full) and os.path.splitext(full)[1].lower() in VIDEO_EXTS:
                    try:
                        video_slide_to_mp4(slide, full, mp4_path)
                        slide_files.append(mp4_path)
                        continue
                    except Exception as e:
                        # one undecodable/truncated clip (real Drive files are
                        # often partial or mislabeled) must NOT abort the whole
                        # automated run — degrade to the renderer for that slide
                        print(f"[warn] slide {n}: video clip failed to encode, "
                              f"rendering as a still slide: {e}", file=sys.stderr)
            img = render_slide(slide, asset, args.dir)
            try:
                render_kenburns_mp4(img, mp4_path)
            except Exception as e:
                print(f"[warn] slide {n}: Ken Burns failed, using static frame: {e}",
                      file=sys.stderr)
                slide_to_mp4_static(img, mp4_path)
            slide_files.append(mp4_path)

        concat_slides(slide_files, out_path)

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