#!/usr/bin/env python3
"""
Anime Catalog Manager for Bhaloo Ji Anime Explanation Channel.
Enumerates Google Drive anime repository (Folder ID: 1e5_IF3GRHNr315hP5zK_qlyfsKXm3Ox4),
identifies series, seasons, and episodes, and manages the queue/history.
"""

import json
import os
import re
import sys
from pathlib import Path

DEFAULT_GDRIVE_FOLDER_ID = "1e5_IF3GRHNr315hP5zK_qlyfsKXm3Ox4"
WORKSPACE_DIR = Path(__file__).resolve().parent.parent
TRACKER_DIR = WORKSPACE_DIR / "tracker"
CATALOG_PATH = TRACKER_DIR / "anime_catalog.json"
HISTORY_PATH = TRACKER_DIR / "anime_history.json"


def log(msg: str) -> None:
    print(f"[anime_catalog] {msg}", flush=True)


def parse_anime_filename(filename: str) -> dict:
    """
    Extract series name, season number, episode number, and clean title from filename.
    Examples:
      - 'Demon_Slayer_Kimetsu_no_Yaiba_480P_S01_E24.mp4' -> Series: 'Demon Slayer: Kimetsu no Yaiba', S: 1, E: 24
      - 'Jujutsu Kaisen - S01E01 1080p 10bit.mkv' -> Series: 'Jujutsu Kaisen', S: 1, E: 1
      - 'Jujutsu_Kaisen_S03E01_1080p_HEVC.mkv' -> Series: 'Jujutsu Kaisen', S: 3, E: 1
    """
    clean_name = Path(filename).name
    
    # 1. Season & Episode regex patterns
    se_match = re.search(r'[Ss](\d{1,2})[\s._-]*[Ee](\d{1,2})', clean_name)
    if se_match:
        season = int(se_match.group(1))
        episode = int(se_match.group(2))
    else:
        # Fallback: look for E01 or Ep 01
        ep_match = re.search(r'(?:[Ee]pisode|[Ee][Pp]|[Ee])[\s._-]*(\d{1,3})', clean_name)
        episode = int(ep_match.group(1)) if ep_match else 1
        s_match = re.search(r'[Ss]eason[\s._-]*(\d{1,2})', clean_name)
        season = int(s_match.group(1)) if s_match else 1

    # 2. Series identification
    lower = clean_name.lower()
    if "demon_slayer" in lower or "kimetsu" in lower:
        series = "Demon Slayer: Kimetsu no Yaiba"
        series_id = "demon-slayer"
    elif "jujutsu" in lower or "jjk" in lower:
        series = "Jujutsu Kaisen"
        series_id = "jujutsu-kaisen"
    elif "avengers" in lower:
        series = "The Avengers"
        series_id = "the-avengers"
    else:
        # Generic fallback from filename
        prefix = clean_name.split("-")[0].replace("_", " ").strip()
        series = prefix.title()
        series_id = re.sub(r'[^a-z0-9]+', '-', prefix.lower()).strip('-')

    return {
        "series": series,
        "series_id": series_id,
        "season": season,
        "episode": episode,
        "filename": clean_name,
        "display_name": f"{series} S{season:02d}E{episode:02d}",
        "episode_key": f"{series_id}-s{season:02d}e{episode:02d}",
    }


def enumerate_drive_folder(folder_id: str) -> list[dict]:
    """Discover video files from Google Drive folder."""
    try:
        import gdown
    except ImportError:
        log("gdown is not installed. Install with 'pip install gdown'")
        return []

    import tempfile
    log(f"Querying Google Drive folder: {folder_id}...")
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            entries = gdown.download_folder(
                id=folder_id,
                output=tmpdir,
                quiet=True,
                skip_download=True,
                use_cookies=False,
            )
        except Exception as err:
            log(f"Error enumerating drive folder {folder_id}: {err}")
            return []

    valid_exts = {".mp4", ".mkv", ".mov", ".webm", ".avi"}
    items = []
    for entry in entries or []:
        raw_path = getattr(entry, "path", "") or ""
        file_id = getattr(entry, "id", "") or ""
        if not raw_path or not file_id:
            continue
        # Skip subfolders like AMV_Outputs or non-video
        if "AMV_Outputs" in raw_path or not any(raw_path.endswith(ext) for ext in valid_exts):
            continue

        info = parse_anime_filename(raw_path)
        info["gdrive_file_id"] = file_id
        info["path"] = raw_path
        items.append(info)

    # Sort deterministically by series, season, episode
    items.sort(key=lambda x: (x["series_id"], x["season"], x["episode"]))
    return items


def load_catalog() -> dict:
    if CATALOG_PATH.exists():
        try:
            with open(CATALOG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log(f"Failed to read catalog: {e}")
    return {"folder_id": DEFAULT_GDRIVE_FOLDER_ID, "episodes": []}


def save_catalog(data: dict) -> None:
    TRACKER_DIR.mkdir(parents=True, exist_ok=True)
    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    log(f"Catalog saved to {CATALOG_PATH} ({len(data.get('episodes', []))} episodes)")


def load_history() -> dict:
    if HISTORY_PATH.exists():
        try:
            with open(HISTORY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log(f"Failed to read history: {e}")
    return {"completed_episodes": [], "in_progress": None, "last_updated": None}


def save_history(history: dict) -> None:
    TRACKER_DIR.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
    log(f"History updated at {HISTORY_PATH}")


def sync_catalog(folder_id: str = DEFAULT_GDRIVE_FOLDER_ID, force: bool = False) -> dict:
    catalog = load_catalog()
    if catalog.get("episodes") and not force:
        log(f"Catalog already loaded with {len(catalog['episodes'])} episodes. Use --force to re-query Drive.")
        return catalog

    episodes = enumerate_drive_folder(folder_id)
    if not episodes:
        log("No episodes found. Retaining existing catalog if present.")
        return catalog

    catalog_data = {
        "folder_id": folder_id,
        "total_episodes": len(episodes),
        "series_breakdown": {},
        "episodes": episodes,
    }

    for ep in episodes:
        sid = ep["series_id"]
        catalog_data["series_breakdown"][sid] = catalog_data["series_breakdown"].get(sid, 0) + 1

    save_catalog(catalog_data)
    return catalog_data


def get_active_episode() -> dict | None:
    """Return in-progress active episode data from history if present."""
    history = load_history()
    active = history.get("active_episode")
    if active and active.get("episode_key"):
        return active
    return None


def get_next_episode(series_id: str | None = None) -> dict | None:
    catalog = load_catalog()
    history = load_history()
    completed = set(history.get("completed_episodes", []))

    # Also exclude currently active episode key if present
    active = history.get("active_episode")
    active_key = active.get("episode_key") if active else None

    episodes = catalog.get("episodes", [])
    if series_id:
        episodes = [e for e in episodes if e["series_id"] == series_id]

    for ep in episodes:
        if ep["episode_key"] not in completed and ep["episode_key"] != active_key:
            return ep
    return None


# Canonical Anime Story Arcs (1 Video per Story Arc, split into Part 1/2 if > 1 hour)
ANIME_STORY_ARCS = {
    # Demon Slayer Season 1
    "demon-slayer-final-selection": {
        "arc_key": "demon-slayer-final-selection",
        "series": "Demon Slayer: Kimetsu no Yaiba",
        "series_id": "demon-slayer",
        "season": 1,
        "arc_name": "Final Selection Arc",
        "display_name": "Demon Slayer - Final Selection Arc",
        "episode_keys": [f"demon-slayer-s01e{i:02d}" for i in range(1, 6)],
        "episodes": list(range(1, 6)),
    },
    "demon-slayer-first-mission": {
        "arc_key": "demon-slayer-first-mission",
        "series": "Demon Slayer: Kimetsu no Yaiba",
        "series_id": "demon-slayer",
        "season": 1,
        "arc_name": "First Mission Arc",
        "display_name": "Demon Slayer - First Mission Arc",
        "episode_keys": [f"demon-slayer-s01e{i:02d}" for i in range(6, 8)],
        "episodes": [6, 7],
    },
    "demon-slayer-asakusa": {
        "arc_key": "demon-slayer-asakusa",
        "series": "Demon Slayer: Kimetsu no Yaiba",
        "series_id": "demon-slayer",
        "season": 1,
        "arc_name": "Asakusa Arc",
        "display_name": "Demon Slayer - Asakusa Arc",
        "episode_keys": [f"demon-slayer-s01e{i:02d}" for i in range(8, 11)],
        "episodes": [8, 9, 10],
    },
    "demon-slayer-tsuzumi-mansion": {
        "arc_key": "demon-slayer-tsuzumi-mansion",
        "series": "Demon Slayer: Kimetsu no Yaiba",
        "series_id": "demon-slayer",
        "season": 1,
        "arc_name": "Tsuzumi Mansion Arc",
        "display_name": "Demon Slayer - Tsuzumi Mansion Arc",
        "episode_keys": [f"demon-slayer-s01e{i:02d}" for i in range(11, 15)],
        "episodes": [11, 12, 13, 14],
    },
    "demon-slayer-mount-natagumo": {
        "arc_key": "demon-slayer-mount-natagumo",
        "series": "Demon Slayer: Kimetsu no Yaiba",
        "series_id": "demon-slayer",
        "season": 1,
        "arc_name": "Mount Natagumo Arc",
        "display_name": "Demon Slayer - Mount Natagumo Arc",
        "episode_keys": [f"demon-slayer-s01e{i:02d}" for i in range(15, 22)],
        "episodes": list(range(15, 22)),
    },
    "demon-slayer-rehabilitation-training": {
        "arc_key": "demon-slayer-rehabilitation-training",
        "series": "Demon Slayer: Kimetsu no Yaiba",
        "series_id": "demon-slayer",
        "season": 1,
        "arc_name": "Rehabilitation Training Arc",
        "display_name": "Demon Slayer - Rehabilitation Training Arc",
        "episode_keys": [f"demon-slayer-s01e{i:02d}" for i in range(22, 27)],
        "episodes": list(range(22, 27)),
    },
    # Demon Slayer Seasons 2 - 5
    "demon-slayer-mugen-train": {
        "arc_key": "demon-slayer-mugen-train",
        "series": "Demon Slayer: Kimetsu no Yaiba",
        "series_id": "demon-slayer",
        "season": 2,
        "arc_name": "Mugen Train Arc",
        "display_name": "Demon Slayer - Mugen Train Arc",
        "episode_keys": [f"demon-slayer-s02e{i:02d}" for i in range(1, 8)],
        "episodes": list(range(1, 8)),
    },
    "demon-slayer-entertainment-district": {
        "arc_key": "demon-slayer-entertainment-district",
        "series": "Demon Slayer: Kimetsu no Yaiba",
        "series_id": "demon-slayer",
        "season": 3,
        "arc_name": "Entertainment District Arc",
        "display_name": "Demon Slayer - Entertainment District Arc",
        "episode_keys": [f"demon-slayer-s03e{i:02d}" for i in range(1, 12)],
        "episodes": list(range(1, 12)),
    },
    "demon-slayer-swordsmith-village": {
        "arc_key": "demon-slayer-swordsmith-village",
        "series": "Demon Slayer: Kimetsu no Yaiba",
        "series_id": "demon-slayer",
        "season": 4,
        "arc_name": "Swordsmith Village Arc",
        "display_name": "Demon Slayer - Swordsmith Village Arc",
        "episode_keys": [f"demon-slayer-s04e{i:02d}" for i in range(1, 12)],
        "episodes": list(range(1, 12)),
    },
    "demon-slayer-hashira-training": {
        "arc_key": "demon-slayer-hashira-training",
        "series": "Demon Slayer: Kimetsu no Yaiba",
        "series_id": "demon-slayer",
        "season": 5,
        "arc_name": "Hashira Training Arc",
        "display_name": "Demon Slayer - Hashira Training Arc",
        "episode_keys": [f"demon-slayer-s05e{i:02d}" for i in range(1, 9)],
        "episodes": list(range(1, 9)),
    },
    # Jujutsu Kaisen Seasons 1 - 2
    "jujutsu-kaisen-fearsome-womb": {
        "arc_key": "jujutsu-kaisen-fearsome-womb",
        "series": "Jujutsu Kaisen",
        "series_id": "jujutsu-kaisen",
        "season": 1,
        "arc_name": "Fearsome Womb Arc",
        "display_name": "Jujutsu Kaisen - Fearsome Womb Arc",
        "episode_keys": [f"jujutsu-kaisen-s01e{i:02d}" for i in range(1, 6)],
        "episodes": list(range(1, 6)),
    },
    "jujutsu-kaisen-vs-mahito": {
        "arc_key": "jujutsu-kaisen-vs-mahito",
        "series": "Jujutsu Kaisen",
        "series_id": "jujutsu-kaisen",
        "season": 1,
        "arc_name": "Vs. Mahito Arc",
        "display_name": "Jujutsu Kaisen - Vs. Mahito Arc",
        "episode_keys": [f"jujutsu-kaisen-s01e{i:02d}" for i in range(6, 14)],
        "episodes": list(range(6, 14)),
    },
    "jujutsu-kaisen-kyoto-goodwill": {
        "arc_key": "jujutsu-kaisen-kyoto-goodwill",
        "series": "Jujutsu Kaisen",
        "series_id": "jujutsu-kaisen",
        "season": 1,
        "arc_name": "Kyoto Goodwill Event Arc",
        "display_name": "Jujutsu Kaisen - Kyoto Goodwill Event Arc",
        "episode_keys": [f"jujutsu-kaisen-s01e{i:02d}" for i in range(14, 22)],
        "episodes": list(range(14, 22)),
    },
    "jujutsu-kaisen-death-painting": {
        "arc_key": "jujutsu-kaisen-death-painting",
        "series": "Jujutsu Kaisen",
        "series_id": "jujutsu-kaisen",
        "season": 1,
        "arc_name": "Death Painting Arc",
        "display_name": "Jujutsu Kaisen - Death Painting Arc",
        "episode_keys": [f"jujutsu-kaisen-s01e{i:02d}" for i in range(22, 25)],
        "episodes": list(range(22, 25)),
    },
    "jujutsu-kaisen-hidden-inventory": {
        "arc_key": "jujutsu-kaisen-hidden-inventory",
        "series": "Jujutsu Kaisen",
        "series_id": "jujutsu-kaisen",
        "season": 2,
        "arc_name": "Hidden Inventory Arc (Gojo's Past)",
        "display_name": "Jujutsu Kaisen - Hidden Inventory Arc",
        "episode_keys": [f"jujutsu-kaisen-s02e{i:02d}" for i in range(1, 6)],
        "episodes": list(range(1, 6)),
    },
    "jujutsu-kaisen-shibuya-incident": {
        "arc_key": "jujutsu-kaisen-shibuya-incident",
        "series": "Jujutsu Kaisen",
        "series_id": "jujutsu-kaisen",
        "season": 2,
        "arc_name": "Shibuya Incident Arc",
        "display_name": "Jujutsu Kaisen - Shibuya Incident Arc",
        "episode_keys": [f"jujutsu-kaisen-s02e{i:02d}" for i in range(6, 24)],
        "episodes": list(range(6, 24)),
    },
}


def get_story_arcs(series_id: str | None = None) -> list[dict]:
    """Return canonical anime story arcs, optionally filtered by series_id."""
    arcs = list(ANIME_STORY_ARCS.values())
    if series_id:
        arcs = [a for a in arcs if a["series_id"] == series_id]
    return arcs


def get_arc(arc_key: str) -> dict | None:
    """Lookup story arc by key or partial name."""
    if not arc_key:
        return None
    if arc_key in ANIME_STORY_ARCS:
        return ANIME_STORY_ARCS[arc_key]
    lower = arc_key.lower().replace("_", "-")
    for k, v in ANIME_STORY_ARCS.items():
        if k.lower() == lower or lower in k.lower():
            return v
    return None


def get_arc_for_episode(episode_key: str) -> dict | None:
    """Find the story arc that contains a specific episode key."""
    for arc in ANIME_STORY_ARCS.values():
        if episode_key in arc["episode_keys"]:
            return arc
    return None


def get_next_arc(series_id: str | None = None, history: dict | None = None) -> dict | None:
    """Find next pending story arc where not all constituent episodes are completed."""
    if history is None:
        history = load_history()
    completed_arcs = set(history.get("completed_arcs", []))
    completed_eps = set(history.get("completed_episodes", []))
    active_arc = history.get("active_arc")
    active_key = active_arc.get("arc_key") if active_arc else None

    # If an arc is actively in progress (e.g. part 2 of a split arc), resume it immediately
    if active_key:
        active_obj = get_arc(active_key)
        if active_obj:
            return active_obj

    arcs = get_story_arcs(series_id)
    for arc in arcs:
        k = arc["arc_key"]
        if k in completed_arcs:
            continue
        all_eps_done = all(e in completed_eps for e in arc["episode_keys"])
        if all_eps_done and k != active_key:
            continue
        return arc
    return None


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Sync and manage anime catalog")
    parser.add_argument("--sync", action="store_true", help="Sync with Google Drive")
    parser.add_argument("--force", action="store_true", help="Force refresh from Google Drive")
    parser.add_argument("--folder", default=DEFAULT_GDRIVE_FOLDER_ID, help="Google Drive folder ID")
    parser.add_argument("--next", action="store_true", help="Show next episode to process")
    parser.add_argument("--series", default=None, help="Filter by series (e.g. demon-slayer, jujutsu-kaisen)")

    args = parser.parse_args()

    if args.sync or args.force or not CATALOG_PATH.exists():
        sync_catalog(folder_id=args.folder, force=args.force)

    if args.next:
        nxt = get_next_episode(args.series)
        if nxt:
            print(f"NEXT EPISODE: {nxt['display_name']} (Key: {nxt['episode_key']})")
            print(f"File ID: {nxt['gdrive_file_id']}")
            print(f"Filename: {nxt['filename']}")
        else:
            print("All episodes have been completed!")
