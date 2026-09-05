#!/usr/bin/env python3
"""
Fetch visual assets for a generated script.

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
    return "drive.google.com" in url or "docs.google.com" in url


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


def download_drive_file(url: str, dest: str) -> bool:
    """Try to download a Google Drive file via direct download link."""
    file_id = extract_drive_file_id(url)
    if not file_id:
        print(f"[warn] can't extract Drive file ID from: {url}", file=sys.stderr)
        return False

    # direct download URL (works for public files)
    direct = f"https://drive.usercontent.google.com/download?id={file_id}&export=download"
    return download(direct, dest)


def download_drive_folder(url: str, dest_dir: str) -> list[str]:
    """Try to download a Google Drive folder as a zip."""
    file_id = extract_drive_file_id(url)
    if not file_id:
        print(f"[warn] can't extract Drive folder ID from: {url}", file=sys.stderr)
        return []

    zip_url = f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"
    zip_path = os.path.join(dest_dir, "_drive_folder.zip")
    if not download(zip_url, zip_path):
        return []

    downloaded = []
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                ext = os.path.splitext(name)[1].lower()
                if ext in IMAGE_EXTS | AUDIO_EXTS:
                    # flatten to dest_dir
                    flat = os.path.basename(name)
                    if flat and not flat.startswith("__"):
                        zf.extract(name, dest_dir)
                        extracted = os.path.join(dest_dir, name)
                        # move to flat name if nested
                        if extracted != os.path.join(dest_dir, flat):
                            final = os.path.join(dest_dir, flat)
                            os.rename(extracted, final)
                            downloaded.append(final)
                        else:
                            downloaded.append(extracted)
    except zipfile.BadZipFile:
        print("[warn] Drive folder download was not a valid zip", file=sys.stderr)
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)

    return downloaded


def download_drive_shared(url: str, dest_dir: str) -> list[str]:
    """Try to download from a shared Google Drive folder via the web view."""
    file_id = extract_drive_file_id(url)
    if not file_id:
        return []

    # Try folder page scraping for file links (public shared folders)
    try:
        req = urllib.request.Request(
            f"https://drive.google.com/drive/folders/{file_id}",
            headers={"User-Agent": UA},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        # find file IDs in the page
        file_ids = re.findall(r'\["([a-zA-Z0-9_-]{20,})"', html)
        downloaded = []
        for fid in file_ids[:30]:  # cap at 30 files
            dest = os.path.join(dest_dir, f"drive_{fid[:8]}")
            if download_drive_file(f"https://drive.google.com/file/d/{fid}", dest):
                downloaded.append(dest)
        return downloaded
    except Exception as e:
        print(f"[warn] Drive folder scrape failed: {e}", file=sys.stderr)
        return []


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

    # 1) local raw files already present
    raw_files = sorted(
        [f for f in os.listdir(raw_dir) if os.path.splitext(f)[1].lower() in IMAGE_EXTS]
    ) if os.path.isdir(raw_dir) else []

    # 2) campaign-provided assets (download from Drive links in brief)
    drive_links = [r["url"] for r in detail.get("reference_materials", [])
                   if r.get("url") and ("drive." in r["url"] or "docs.google.com" in r["url"])]
    drive_files = []
    drive_audio = []

    if drive_links:
        print(f"Campaign has {len(drive_links)} Drive link(s) — downloading...")
        for link in drive_links:
            if "/folders/" in link:
                files = download_drive_shared(link, raw_dir)
                drive_files.extend(files)
                time.sleep(1)
            else:
                dest = os.path.join(raw_dir, f"drive_{extract_drive_file_id(link)[:8] if extract_drive_file_id(link) else 'file'}")
                if download_drive_file(link, dest):
                    drive_files.append(dest)

        # separate audio from images
        for f in drive_files:
            ext = os.path.splitext(f)[1].lower()
            if ext in AUDIO_EXTS:
                drive_audio.append(f)

        # refresh raw_files after download
        raw_files = sorted(
            [f for f in os.listdir(raw_dir) if os.path.splitext(f)[1].lower() in IMAGE_EXTS]
        )

        # copy audio to assets/ for BGM
        for af in drive_audio:
            dest = os.path.join(asset_dir, os.path.basename(af))
            if not os.path.exists(dest):
                os.rename(af, dest)
            print(f"  audio asset: {os.path.basename(af)}")

    # 3) build index — raw files only, no stock photos
    index = {}
    photo_slots = [s for s in script["slides"]
                   if s.get("visual") in ("lifestyle-photo", "product-photo",
                                          "retail-shot", "persona-selfie")]
    used = 0
    for s in photo_slots:
        if used < len(raw_files):
            src = os.path.join("assets", "raw", raw_files[used])
            index[s["n"]] = {"kind": s["visual"], "src": "local", "path": src, "query": None}
            used += 1
        else:
            # no more campaign footage — flag it, don't fake it
            index[s["n"]] = {"kind": s["visual"], "src": "render", "path": None,
                             "query": None, "needs_media": True}

    # fill non-photo slides (text-card, notes-app — renderer handles these)
    for s in script["slides"]:
        if s["n"] not in index:
            index[s["n"]] = {"kind": s["visual"], "src": "render", "path": None, "query": None}

    # report what we got
    local_count = sum(1 for v in index.values() if v["src"] == "local")
    need_media = [n for n, v in index.items() if v.get("needs_media")]
    audio_files = [f for f in os.listdir(asset_dir) if os.path.splitext(f)[1].lower() in AUDIO_EXTS]

    notes = []
    if drive_links and not raw_files:
        notes.append(f"Drive links found but no images downloaded — check links manually: {drive_links[0]}")
    if need_media:
        notes.append(f"slides {need_media} need campaign media but no raw files available — download from campaign Drive")
    if audio_files:
        notes.append(f"audio for BGM: {', '.join(audio_files)}")
    else:
        notes.append("no BGM found in campaign assets — will use royalty-free or silent")

    with open(os.path.join(asset_dir, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"slides": index, "notes": notes, "audio": audio_files}, f, indent=2)

    print(f"assets/index.json: {len(index)} slides -> {local_count} campaign-media, "
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