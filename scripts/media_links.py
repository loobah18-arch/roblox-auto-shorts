#!/usr/bin/env python3
"""Shared helpers for discovering campaign media links.

Campaign raw footage is frequently NOT in detail.json as a plain Drive link.
The real pattern (seen repeatedly in Whop Content Rewards briefs) is:

    detail.json reference_materials -> one or more Google DOC links (the brief)
    the brief's text -> HYPERLINKS to a Google Drive folder/file with the raw
    photos/video clips

The problem: Google Docs plain-text export (export?format=txt) STRIPS all
hyperlinks, so the Drive folder is invisible to anything that only reads the
brief as text. This module fetches the doc's RICH HTML (mobilebasic), extracts
the embedded Drive folder/file + direct media URLs, and returns them so
fetch_brief.py / fetch_assets.py / shortlist_campaigns.py can treat them as
media sources.

Evergreen rule ([[feedback-no-stock-photos]]): media = campaign-provided links
only. We NEVER synthesize or substitute stock imagery here.
"""
import os
import re
import sys
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Chrome/120 Safari/605.1.15"

# Match folder links in all the forms Drive/Google-Docs emit: /drive/folders/<id>,
# /drive/u/0/folders/<id>, /drive/shared-with-me/folders/<id>, /drive/my-drive/.../folders/<id>.
# The middle group is (zero-or-more)/segment/ so the logged-in-UI path (/drive/u/N/folders/)
# with TWO segments is matched too — not just one.
DRIVE_FOLDER_RE = re.compile(r'/drive/(?:[A-Za-z0-9_-]+/)*folders/([A-Za-z0-9_-]{20,})')
# Match file links whether they carry /view, /edit, /preview, a trailing slash,
# or nothing (the /edit form is what a logged-in Drive tab copies and is the most
# common href inside a brief).
DRIVE_FILE_RE = re.compile(r'/file/d/([A-Za-z0-9_-]{20,})(?:/(?:view|edit|preview))?(?:[/?#]|$)')
DOC_ID_RE = re.compile(r'/document/d/([A-Za-z0-9_-]+)')

DIRECT_MEDIA_EXTS = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v",
                     ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp",
                     ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".zip")


def fetch(url: str, timeout: int = 60) -> str:
    """Fetch a URL as text, following redirects, with a browser UA."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def is_gdoc(url: str) -> bool:
    return url and "docs.google.com/document" in url


def drive_folder_links(html_or_text: str) -> list[str]:
    """Return distinct public Drive folder links found in a blob."""
    out = []
    for fid in DRIVE_FOLDER_RE.findall(html_or_text or ""):
        out.append(f"https://drive.google.com/drive/folders/{fid}")
    return list(dict.fromkeys(out))


def drive_file_links(html_or_text: str) -> list[str]:
    """Return distinct public Drive file links found in a blob."""
    out = []
    for fid in DRIVE_FILE_RE.findall(html_or_text or ""):
        out.append(f"https://drive.google.com/file/d/{fid}")
    return list(dict.fromkeys(out))


# Hosts Google Docs' own HTML markup uses that are NOT campaign media. We must
# never treat the doc's UI chrome (css sprites, favicons, fonts, rendered images)
# as footage. googleusercontent.com covers the doc-image hosts (docstext.*, lh3.*)
# but NOT drive.usercontent.google.com (different label) — direct media also
# excludes Drive links separately.
NOISE_HOSTS = ("gstatic.com", "googleusercontent.com", "google.com/favicon")


def unwrap_google_url(s: str) -> str:
    """Google Docs rewrites external hyperlinks to
    `https://www.google.com/url?q=<url-encoded target>&sa=D&…`. Decode the target
    and HTML-unescape `&amp;` so the extractors can see the real Drive/media URL."""
    if not s:
        return s
    s = re.sub(
        r'https?://www\.google\.com/url\?q=([^&\s]+)',
        lambda m: urllib.parse.unquote(m.group(1)),
        s)
    return s.replace("&amp;", "&")


def direct_media_links(html_or_text: str) -> list[str]:
    """Direct http(s) links that end in a media/zip extension (or raw Drive uc
    links). Useful when the brief points straight at an mp4/jpg instead of Drive.
    Strips trailing punctuation, tolerates query strings/fragments, and drops
    Google's own image-host noise."""
    out = []
    for url in re.findall(r'https?://[^\s"<>\]\)]+', html_or_text or ""):
        clean = url.rstrip(".,;:)")
        low = clean.lower()
        if "drive.google.com" in low:
            continue
        path_only = re.split(r'[?#]', low)[0]
        if not path_only.endswith(DIRECT_MEDIA_EXTS):
            continue
        if any(h in low for h in NOISE_HOSTS):
            continue
        out.append(clean)
    return list(dict.fromkeys(out))


def media_links_from_doc(doc_url: str) -> list[str]:
    """Given a Google Docs URL, fetch its RICH html (which keeps hyperlinks the
    txt export strips) and return every Drive folder/file + direct media link
    inside it. Falls back to plain-text export if the rich view is blocked."""
    if not is_gdoc(doc_url):
        return []
    m = DOC_ID_RE.search(doc_url)
    if not m:
        return []
    doc_id = m.group(1)
    tried = []
    # 1) mobilebasic keeps hyperlinks; /document/d/<id>/ (desktop) may too.
    for base in (f"https://docs.google.com/document/d/{doc_id}/mobilebasic",
                 f"https://docs.google.com/document/d/{doc_id}"):
        try:
            html = fetch(base)
            if html and len(html.strip()) > 200:
                tried.append(base)
                html = unwrap_google_url(html)
                links = (drive_folder_links(html)
                         + drive_file_links(html)
                         + direct_media_links(html))
                if links:
                    return links
        except Exception as e:
            print(f"[warn] medialink doc fetch failed {base}: {e}", file=sys.stderr)
    return []


def all_media_links(refs: list[dict]) -> dict[str, list[str]]:
    """Categorize a campaign's reference materials + a brief-links sidecar into
    media sources. refs may include plain Drive URLs OR Google Doc URLs.

    Returns {"folders": [...], "files": [...], "direct": [...]} — campaign
    footage only. Docs are expanded (opened) to find their Drive links; a doc
    with no media links contributes nothing (it's a rule brief, e.g. Goli)."""
    folders, files, direct = [], [], []
    prev = None
    for r in refs or []:
        url = (r.get("url") or "") if isinstance(r, dict) else r
        if not url:
            continue
        low = url.lower()
        if "drive.google.com" in low:
            if "/folders/" in low:
                folders.append(url)
            elif "/file/" in low or "/uc?" in low or "?id=" in low:
                files.append(url)
            continue
        if is_gdoc(url):
            if url != prev:  # avoid re-opening the same doc repeatedly
                prev = url
                links = media_links_from_doc(url)
                for l in links:
                    ll = l.lower()
                    if "/folders/" in ll:
                        folders.append(l)
                    elif "/file/" in ll:
                        files.append(l)
                    else:
                        direct.append(l)
            continue
    # dedupe preserving order
    def _dedupe(xs):
        return list(dict.fromkeys(xs))
    return {"folders": _dedupe(folders), "files": _dedupe(files),
            "direct": _dedupe(direct)}