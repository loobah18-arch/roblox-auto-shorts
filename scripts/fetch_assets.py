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

try:
    from media_links import all_media_links
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from media_links import all_media_links

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
    if data[:4] == b"RIFF":
        if data[8:12] == b"WEBP":
            return ".webp"
        if data[8:12] in (b"AVI ", b"AVIX"):
            return ".avi"
    if data[:4] == b"BM":
        return ".bmp"
    if data[4:8] == b"ftyp" or data[4:12].startswith(b"ftyp"):
        # mp4/mov/m4v/m4a all share the ISO-BMFF container — disambiguate by brand
        brand = data[8:12]
        if b"m4a" in brand or b"M4A " in brand:
            return ".m4a"
        if b"m4v" in brand or b"M4V " in brand:
            return ".m4v"
        if b"isom" in data[:32] or b"mp4" in data[:32] or b"avc1" in data[:32]:
            return ".mp4"
        return ".mov"
    if data[:4] == b"\x1aE\xdf\xa3":
        # Matroska container — webm if the DOCTYPE says webm, else mkv
        return ".webm" if b"webm" in data[:256].lower() else ".mkv"
    if b"ID3" in data[:4] or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return ".mp3"
    if data[:4] == b"OggS":
        return ".ogg"
    return None


def download(url: str, dest: str, retries: int = 2) -> bool:
    """Stream a direct http(s) media URL to disk (never buffer whole big videos
    in RAM — a 1.5GB clip would OOM a GitHub Actions runner). Rejects HTML error
    pages and retries transient failures with backoff."""
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as resp, open(dest, "wb") as f:
                head = resp.read(4096)
                if b"<html" in head.lower() or b"<!doctype" in head.lower():
                    raise ValueError("got HTML page, not media")
                f.write(head)
                while True:
                    chunk = resp.read(1 << 16)
                    if not chunk:
                        break
                    f.write(chunk)
            if os.path.getsize(dest) > 2000:
                return True
            os.remove(dest)
            return False
        except Exception as e:
            print(f"[warn] download failed {url}: {e}", file=sys.stderr)
            if os.path.exists(dest):
                os.remove(dest)
            if attempt < retries:
                time.sleep(1.0 + attempt)
                continue
            return False
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


_TRANSIENT_EXC = (urllib.error.URLError, TimeoutError, ConnectionError)


def _retry_transient(fn, attempts: int = 3, base_delay: float = 1.0):
    """Retry a callable on transient network/timeout failures (GitHub Actions
    runners hit flaky egress; one blip must not permanently drop a clip)."""
    attempt = 0
    while True:
        try:
            return fn()
        except _TRANSIENT_EXC:
            attempt += 1
            if attempt >= attempts:
                raise
            time.sleep(base_delay + attempt)
        except urllib.error.HTTPError as e:
            if e.code in (500, 502, 503, 504, 429):
                attempt += 1
                if attempt >= attempts:
                    raise
                time.sleep(base_delay + attempt)
            else:
                raise


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
        data, ctype = _retry_transient(lambda: _hop(""))
        if ctype.startswith("text/html"):
            # Drive's "large file" confirmation page — grab the token
            m = confirm_re.search(data.decode("utf-8", errors="ignore"))
            extra = f"&confirm={m.group(1)}" if m else "&confirm=t"
            data, ctype = _retry_transient(lambda: _hop(extra))
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
    # If a second HTTP hop still returns HTML, the confirm token failed (or the
    # share needs auth). NEVER write an HTML page as a media file — build_video
    # would choke on it downstream.
    if b"<html" in data[:1024].lower() or b"<!doctype" in data[:1024].lower():
        print(f"[warn] Drive download returned an HTML page, not media: {url}", file=sys.stderr)
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
    def _fetch():
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=90) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    try:
        page = _retry_transient(_fetch)
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

    # 2) campaign-provided assets. Media links can be:
    #      - plain Drive folder/file links in detail.json reference_materials
    #      - Google DOC links (the brief) whose hyperlinks hide the real Drive
    #        folder — we OPEN the doc and pull the Drive folder/file URLs out
    #      - the brief_links.json sidecar written by fetch_brief.py (same links)
    #    We NEVER use stock photos.
    refs = detail.get("reference_materials") or []
    src = all_media_links(refs)

    # merge the brief_links.json sidecar (same doc, already expanded by fetch_brief)
    brief_links_path = os.path.join(args.dir, "brief_links.json")
    if os.path.exists(brief_links_path):
        try:
            bl = json.load(open(brief_links_path, encoding="utf-8"))
            if isinstance(bl, dict):
                for k in ("folders", "files", "direct"):
                    src.setdefault(k, []).extend(bl.get(k) or [])
            else:
                print(f"[warn] {brief_links_path} is not a dict — ignoring", file=sys.stderr)
        except Exception as e:
            print(f"[warn] could not read {brief_links_path}: {e}", file=sys.stderr)

    def _dedupe(xs):
        return list(dict.fromkeys(xs))
    folders = _dedupe(src.get("folders", []))
    files = _dedupe(src.get("files", []))
    direct = _dedupe(src.get("direct", []))

    drive_files = []
    drive_audio = []
    all_sources = folders + files
    if refs:
        # report which materials actually became media sources
        from urllib.parse import urlparse
        print(f"  reference materials: {len(refs)} -> {len(folders)} Drive folder(s), "
              f"{len(files)} Drive file(s), {len(direct)} direct media link(s)")
    else:
        print("  no reference materials — using local raw files only")

    def _is_folder(u):
        return "/folders/" in u.lower()

    if all_sources or direct:
        print(f"Campaign has media links — downloading raw footage...")
        for link in folders + files:
            if _is_folder(link):
                got = download_drive_folder(link, raw_dir)
                drive_files.extend(got)
                time.sleep(1)
            else:
                fid = extract_drive_file_id(link)
                dest = os.path.join(raw_dir, (f"drive_{fid[:8]}" if fid else "drive_file"))
                real = download_drive_file(link, dest)
                if real:
                    drive_files.append(real)
        # direct http(s) media URLs (mp4/jpg/... from the brief) — campaign-owned
        for u in direct:
            if not is_google_drive(u):
                dest = os.path.join(raw_dir, os.path.basename(urllib.parse.urlparse(u.rstrip('.,;:')).path) or "direct_media")
                if download(u, dest):
                    drive_files.append(dest)
        if folders + files + direct:
            print(f"  {len(folders + files + direct)} media link(s), "
                  f"{len(drive_files)} file(s) downloaded so far")

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

    # 3) build index — campaign media only, no stock photos.
    #    Drive raw footage is the campaign's own media kit (the "clip" format):
    #    use clips as moving bases for EVERY slide, with slide text burned on
    #    top by build_video. This ensures the video actually shows the campaign
    #    footage rather than just text cards.
    index = {}
    photo_types = ("lifestyle-photo", "product-photo", "retail-shot", "persona-selfie")
    # Give campaign footage to the slides that NEED a real image first (photo/
    # video slots) — a text-card slide should never consume the only clip while a
    # product-photo slide is left flagged as needs_media. Remaining clips then
    # fill the other slides rather than going unused.
    photo_slot_nums = [s["n"] for s in script["slides"] if s.get("visual") in photo_types]
    slide_order = photo_slot_nums + [s["n"] for s in script["slides"]
                                     if s["n"] not in photo_slot_nums]
    by_n = {s["n"]: s for s in script["slides"]}
    used = 0
    for n in slide_order:
        s = by_n[n]
        if used < len(raw_files):
            src = os.path.join("assets", "raw", raw_files[used])
            ext = os.path.splitext(raw_files[used])[1].lower()
            kind = "video" if ext in VIDEO_EXTS else "image"
            index[n] = {"kind": s["visual"], "media": kind, "src": "local",
                        "path": src, "query": None}
            used += 1
        else:
            # no more campaign footage — flag photo slots, text cards fall back
            # to the renderer (never stock photos)
            entry: dict = {"kind": s["visual"], "media": "image", "src": "render",
                           "path": None, "query": None}
            if n in photo_slot_nums:
                entry["needs_media"] = True
            index[n] = entry

    # report what we got
    local_count = sum(1 for v in index.values() if v["src"] == "local")
    video_count = sum(1 for v in index.values() if v.get("media") == "video")
    need_media = [n for n, v in index.items() if v.get("needs_media")]
    audio_files = [f for f in os.listdir(asset_dir) if os.path.splitext(f)[1].lower() in AUDIO_EXTS]

    media_sources = folders + files + direct
    notes = []
    if media_sources and not raw_files:
        notes.append(f"Media links found but no images/videos downloaded — check links manually: {media_sources[0]}")
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
        print(f"    Download from: {media_sources[0] if media_sources else '(no media link — check brief)'}")
        print(f"    Place files in: {raw_dir}/")
        print(f"    Then re-run: python3 scripts/fetch_assets.py --dir {args.dir}")
        # don't fail — pipeline continues with text-cards, but the human gets the message

    return 0


if __name__ == "__main__":
    sys.exit(main())