#!/usr/bin/env python3
"""
Fetch visual + video assets for a generated script.

Slide visuals map to assets like this:
    text-card / notes-app   -> no photo needed (renderer draws them)
    lifestyle-photo         -> campaign-provided lifestyle photo
    product-photo           -> campaign-provided product shot
    retail-shot             -> campaign-provided retail/store photo
    persona-selfie          -> campaign-provided persona/candid photo

Source priority per campaign:
  1. Local raw files dropped by the human in assets/raw/
  2. Campaign-provided assets from the Drive/Doc links in the brief
     (downloaded automatically via public share links)
  3. FAIL — pipeline stops and tells the human to download the assets manually.
     We NEVER substitute stock photos. Campaign reviewers reject anything
     not from the official campaign media kit.

IMPORTANT: Google Docs (docs.google.com/document) are brief TEXT, not media.
Skip them as asset sources. Only use Drive files/folders that actually contain
images, videos, or audio.

Writes assets/index.json: { "n": {"kind": "...", "src": "local|drive|render",
                                  "path": "...", "query": "..."} }

Also downloads any audio files (mp3/wav) from the campaign assets for BGM.
"""
import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.parse
import urllib.error
import zipfile
import tempfile
import time

UA = "Mozilla/5.0 whop-producer/1.0"
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS | AUDIO_EXTS


def sniff_ext(data: bytes) -> str | None:
    """Detect a real media extension from magic bytes. Drive serves many raw files
    as application/octet-stream, so we can't trust the Content-Type for videos."""
    if not data:
        return None
    if data[:4] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:4] == b"BM":
        return ".bmp"
    if (data[4:8] in (b"ftyp", b"moov") or data[4:12].startswith(b"ftyp")):
        return ".mp4" if b"isom" in data[:32] or b"mp4" in data[:32] else ".mov"
    if data[:4] == b"\x1aE\xdf\xa3":
        return ".mkv"
    if b"ID3" in data[:4] or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return ".mp3"
    if data[:4] == b"OggS":
        return ".ogg"
    if data[:4] == b"fLaC":
        return ".flac"
    return None


def download(url: str, dest: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
            f.write(resp.read())
        return os.path.getsize(dest) > 2000
    except Exception as e:
        print(f"[warn] download failed {url}: {e}", file=sys.stderr)
        if os.path.exists(dest):
            os.remove(dest)
        return False


def is_google_drive(url: str) -> bool:
    return any(h in url for h in (
        "drive.google.com", "drive.usercontent.google.com", "docs.google.com"))


_RAW_CLIP_HOSTS = (
    "drive.google.com", "drive.usercontent.google.com",
    "docs.google.com/file",  # /file/d/<id>/view — public Drive file opened via Docs host
)
_RAW_CLIP_MARKERS = ("drive.google.com", "drive.usercontent.google.com")


def extract_drive_file_id(url: str) -> str | None:
    """Extract file ID from various Google Drive URL formats."""
    # /d/<id>/  or  ?id=<id>  or  /uc?id=<id>
    m = re.search(r'/d/([a-zA-Z0-9_-]{20,})', url)
    if m:
        return m.group(1)
    m = re.search(r'[?&]id=([a-zA-Z0-9_-]{20,})', url)
    if m:
        return m.group(1)
    return None


def extension_from_type(content_type: str) -> str | None:
    """Map a mime content type to a file extension for IMAGE/VIDEO/AUDIO."""
    ct = (content_type or "").lower().split(";")[0].strip()
    mapping = {
        "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
        "image/webp": ".webp", "image/gif": ".gif", "image/bmp": ".bmp",
        "video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm",
        "video/x-matroska": ".mkv", "video/avi": ".avi", "video/x-msvideo": ".avi",
        "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav",
        "audio/x-wav": ".wav", "audio/mp4": ".m4a", "audio/aac": ".aac",
        "audio/ogg": ".ogg", "application/octet-stream": None,
    }
    return mapping.get(ct)


def download_drive_file(url: str, dest: str) -> str:
    """Try to download a Google Drive file via direct download link.
    Returns the FINAL saved path (real extension resolved from the Content-Type
    header, else sniffed from magic bytes), or "" on failure.
    Also follows the big-file virus-scan confirmation hop."""
    file_id = extract_drive_file_id(url)
    if not file_id:
        print(f"[warn] can't extract Drive file ID from: {url}", file=sys.stderr)
        return ""

    direct = f"https://drive.google.com/uc?export=download&id={file_id}"

    def _hop(extra: str):
        req = urllib.request.Request(direct + extra, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=180) as resp:
            return resp.read(), resp.headers.get("Content-Type", "")

    confirm_re = re.compile(r'confirm=([0-9A-Za-z_-]+)')
    try:
        data, ctype = _hop("")
        if ctype.startswith("text/html"):
            # Drive's "large file" confirmation page — grab the token
            m = confirm_re.search(data.decode("utf-8", errors="ignore"))
            extra = f"&confirm={m.group(1)}" if m else "&confirm=t"
            data, ctype = _hop(extra)
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            print(f"[warn] Drive file not accessible {url}: HTTP {e.code}", file=sys.stderr)
        else:
            print(f"[warn] Drive download failed {url}: HTTP {e.code}", file=sys.stderr)
        return ""
    except Exception as e:
        print(f"[warn] Drive download failed {url}: {e}", file=sys.stderr)
        return ""

    if len(data) < 2000:
        print(f"[warn] Drive file too small / not the real asset: {url}", file=sys.stderr)
        return ""

    # Teams often zip photos; unzip in place if we got a zip
    if ctype.startswith("application/zip") or data[:2] == b"PK" and data[:4] == b"PK\x03\x04":
        try:
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                tmp.write(data)
                zpath = tmp.name
            saved = []
            with zipfile.ZipFile(zpath) as zf:
                for name in zf.namelist():
                    ext = os.path.splitext(name)[1].lower()
                    if ext in MEDIA_EXTS:
                        flat = os.path.basename(name)
                        out = os.path.join(dest and os.path.dirname(dest) or ".", flat)
                        if not out.endswith(ext):
                            continue
                        with zf.open(name) as src, open(out, "wb") as fh:
                            fh.write(src.read())
                        saved.append(out)
            os.unlink(zpath)
            return saved[0] if saved else ""
        except Exception as e:
            print(f"[warn] Drive zip unzip failed: {e}", file=sys.stderr)
            return ""

    ext = extension_from_type(ctype) or sniff_ext(data)
    final = dest if not ext else dest + ext
    try:
        with open(final, "wb") as f:
            f.write(data)
        return final
    except Exception as e:
        print(f"[warn] writing {final} failed: {e}", file=sys.stderr)
        return ""


def extract_drive_folder_id(url: str) -> str | None:
    """Folder id from drive.google.com/drive/folders/<id> (or /drive/u/0/folders/<id>)."""
    m = re.search(r'/folders/([a-zA-Z0-9_-]{20,})', url)
    if m:
        return m.group(1)
    m = re.search(r'[?&]id=([a-zA-Z0-9_-]{20,})', url)
    return m.group(1) if m else None


def _list_drive_children(folder_id: str) -> list[dict]:
    """List a PUBLIC Drive folder's children via the JS-free embedded view
    (https://drive.google.com/embeddedfolderview?id=<id>#list).

    Folder rows link to /drive/folders/<id>; file rows link to
    /file/d/<id>/view. More reliable than parsing window['_DRIVE_ivd'] and
    avoids the noisy 'bare long id' fallback (CSS vars, JS fn names, ...).
    Returns [{id, name, kind}] with kind in {'folder','file'}."""
    url = f"https://drive.google.com/embeddedfolderview?id={folder_id}#list"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            page = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"[warn] embedded folder view failed {folder_id}: {e}", file=sys.stderr)
        return []

    out, seen = [], set()
    for m in re.finditer(r'/drive/folders/([A-Za-z0-9_-]{20,})', page):
        if m.group(1) not in seen:
            seen.add(m.group(1))
            out.append({"id": m.group(1), "name": "", "kind": "folder"})
    for m in re.finditer(r'/file/d/([A-Za-z0-9_-]{20,})/view', page):
        if m.group(1) not in seen:
            seen.add(m.group(1))
            out.append({"id": m.group(1), "name": "", "kind": "file"})
    return out


def download_drive_folder(url: str, dest_dir: str, _depth: int = 0) -> list[str]:
    """Recursively download every media file in a PUBLIC Google Drive folder.
    Uses the JS-free embedded folder view to list children (files + subfolders)
    and walks into subfolders. Returns saved file paths, capped at 40 files."""
    file_id = extract_drive_folder_id(url)
    if not file_id:
        print(f"[warn] can't extract Drive folder ID from: {url}", file=sys.stderr)
        return []
    if _depth > 4:
        return []

    downloaded: list[str] = []
    for child in _list_drive_children(file_id):
        if len(downloaded) >= 40:
            break
        eid = child["id"]
        if child["kind"] == "folder":
            nested = download_drive_folder(
                f"https://drive.google.com/drive/folders/{eid}", dest_dir, _depth + 1)
            downloaded.extend(nested)
            continue
        dest = os.path.join(dest_dir, f"drive_{eid[-8:]}")
        real = download_drive_file(f"https://drive.google.com/file/d/{eid}", dest)
        if real:
            downloaded.append(real)
    return downloaded


def classify_media_link(url: str) -> str:
    """Return 'folder' | 'file' | 'doc' | '' for a reference-material URL.
    Doc links (docs.google.com/document|spreadsheet|presentation) are brief TEXT,
    never media — skip them. Only actual Drive files/folders hold raw clips."""
    if not url:
        return ""
    if any(h in url for h in _RAW_CLIP_MARKERS):
        if "/folders/" in url:
            return "folder"
        return "file"
    if "docs.google.com" in url and any(k in url for k in ("/document/", "/spreadsheets/", "/presentation/")):
        return "doc"
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", required=True, help="campaign dir (has script.json, detail.json)")
    ap.add_argument("--product", default="", help="override product phrase")
    args = ap.parse_args()

    script_path = os.path.join(args.dir, "script.json")
    detail_path = os.path.join(args.dir, "detail.json")

    if not os.path.exists(script_path):
        print(f"ERROR: {script_path} not found", file=sys.stderr)
        return 1
    if not os.path.exists(detail_path):
        print(f"ERROR: {detail_path} not found", file=sys.stderr)
        return 1

    script = json.load(open(script_path, encoding="utf-8"))
    detail = json.load(open(detail_path, encoding="utf-8"))

    asset_dir = os.path.join(args.dir, "assets")
    raw_dir = os.path.join(asset_dir, "raw")
    os.makedirs(asset_dir, exist_ok=True)
    os.makedirs(raw_dir, exist_ok=True)

    # 1) local raw files already present (images AND videos)
    raw_files = sorted(
        [f for f in os.listdir(raw_dir) if os.path.splitext(f)[1].lower() in (IMAGE_EXTS | VIDEO_EXTS)]
    ) if os.path.isdir(raw_dir) else []

    # 2) campaign-provided assets (download from Drive links in the detail page).
    #    Google DOCS are brief text, not media — skip them. Only Drive
    #    folders/files actually hold images/videos/audio.
    refs = detail.get("reference_materials") or []
    # Only actual Drive FILES/FOLDERS hold raw footage — never Google Docs (brief text).
    drive_links = [r["url"] for r in refs
                   if classify_media_link(r.get("url", "")) in ("file", "folder")]
    drive_files = []
    drive_audio = []
    if drive_links:
        print(f"  media sources: {[l.split('//')[1][:48] for l in drive_links]}")
    else:
        print("  no Drive media links in reference_materials — using local raw files only")

    if drive_links:
        print(f"Campaign has {len(drive_links)} Drive media link(s) — downloading raw footage...")
        for link in drive_links:
            role = "folder" if classify_media_link(link) == "folder" else "file"
            if role == "folder":
                files = download_drive_folder(link, raw_dir)
                drive_files.extend(files)
                time.sleep(1)
            else:
                dest = os.path.join(raw_dir, f"drive_{extract_drive_file_id(link)[:8] if extract_drive_file_id(link) else 'file'}")
                real = download_drive_file(link, dest)
                if real:
                    drive_files.append(real)

        # separate audio from image/video
        for f in drive_files:
            ext = os.path.splitext(f)[1].lower()
            if ext in AUDIO_EXTS:
                drive_audio.append(f)

        # refresh raw_files after download (images AND videos)
        raw_files = sorted(
            [f for f in os.listdir(raw_dir) if os.path.splitext(f)[1].lower() in (IMAGE_EXTS | VIDEO_EXTS)]
        )

        # copy audio to assets/ for BGM
        for af in drive_audio:
            dest = os.path.join(asset_dir, os.path.basename(af))
            if not os.path.exists(dest):
                os.rename(af, dest)
            print(f"  audio asset: {os.path.basename(af)}")

    # 3) build index — campaign media only, no stock photos
    index = {}
    photo_slots = [s for s in script["slides"]
                   if s.get("visual") in ("lifestyle-photo", "product-photo",
                                          "retail-shot", "persona-selfie")]
    used = 0
    for s in photo_slots:
        if used < len(raw_files):
            src = os.path.join("assets", "raw", raw_files[used])
            ext = os.path.splitext(raw_files[used])[1].lower()
            kind = "video" if ext in VIDEO_EXTS else "image"
            index[s["n"]] = {"kind": s["visual"], "media": kind, "src": "local",
                             "path": src, "query": None}
            used += 1
        else:
            # no more campaign footage — flag it, don't fake it
            index[s["n"]] = {"kind": s["visual"], "media": "image", "src": "render",
                             "path": None, "query": None, "needs_media": True}

    # fill non-photo slides (text-card, notes-app — renderer handles these)
    for s in script["slides"]:
        if s["n"] not in index:
            index[s["n"]] = {"kind": s["visual"], "media": "image", "src": "render",
                             "path": None, "query": None}

    # report what we got
    local_count = sum(1 for v in index.values() if v["src"] == "local")
    video_count = sum(1 for v in index.values() if v.get("media") == "video")
    need_media = [n for n, v in index.items() if v.get("needs_media")]
    audio_files = [f for f in os.listdir(asset_dir) if os.path.splitext(f)[1].lower() in AUDIO_EXTS]

    notes = []
    if drive_links and not raw_files:
        notes.append(f"Drive links found but no images/videos downloaded — check links manually: {drive_links[0]}")
    if need_media:
        notes.append(f"slides {need_media} need campaign media but no raw files available — download from campaign Drive")
    if audio_files:
        notes.append(f"audio for BGM: {', '.join(audio_files)}")
    else:
        notes.append("no BGM found in campaign assets — will use royalty-free or silent")

    with open(os.path.join(asset_dir, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"slides": index, "notes": notes, "audio": audio_files}, f, indent=2)

    print(f"assets/index.json: {len(index)} slides -> {local_count} campaign-media "
          f"({video_count} video, {local_count - video_count} image), "
          f"{len(index) - local_count} text-card render)")
    for note in notes:
        print(f"note: {note}")

    if need_media:
        print(f"\n⚠️  {len(need_media)} slide(s) need campaign photos not found in assets/raw/")
        print(f"    Download from: {drive_links[0] if drive_links else '(no Drive link — check brief)'}")
        print(f"    Place files in: {raw_dir}/")
        print(f"    Then re-run: python3 scripts/fetch_assets.py --dir {args.dir}")
        # don't fail — pipeline continues with text-cards, but the human gets the message

    return 0


if __name__ == "__main__":
    sys.exit(main())