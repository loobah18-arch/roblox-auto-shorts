#!/usr/bin/env python3
"""
Unit and integration tests for Bhaloo Ji Anime Explanation Engine.
Runs isolated, lightweight checks without heavy computation or rendering.
"""

import json
import unittest
from pathlib import Path
import sys

# Add scripts to path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from anime_catalog import parse_anime_filename, load_catalog
from anime_script_engine import generate_episode_script
from anime_voice_subtitles import cues_to_ass, format_ass_time
from anime_video_engine import build_ffmpeg_filtergraph


class TestAnimeCatalog(unittest.TestCase):
    def test_parse_demon_slayer_filename(self):
        fn = "Demon_Slayer_Kimetsu_no_Yaiba_480P_S01_E24.mp4"
        res = parse_anime_filename(fn)
        self.assertEqual(res["series_id"], "demon-slayer")
        self.assertEqual(res["season"], 1)
        self.assertEqual(res["episode"], 24)
        self.assertEqual(res["episode_key"], "demon-slayer-s01e24")

    def test_parse_jjk_filename(self):
        fn = "Jujutsu Kaisen - S01E01 1080p 10bit [HIN-ENG] x265 ESub - PikaHD.com.mkv"
        res = parse_anime_filename(fn)
        self.assertEqual(res["series_id"], "jujutsu-kaisen")
        self.assertEqual(res["season"], 1)
        self.assertEqual(res["episode"], 1)
        self.assertEqual(res["episode_key"], "jujutsu-kaisen-s01e01")

    def test_catalog_structure(self):
        catalog = load_catalog()
        self.assertIn("episodes", catalog)
        self.assertGreaterEqual(len(catalog["episodes"]), 1)


class TestAnimeScriptEngine(unittest.TestCase):
    def test_script_generation_structure(self):
        sample_ep = {
            "series": "Demon Slayer: Kimetsu no Yaiba",
            "series_id": "demon-slayer",
            "season": 1,
            "episode": 1,
            "filename": "Demon_Slayer_Kimetsu_no_Yaiba_480P_S01_E01.mp4",
            "episode_key": "demon-slayer-s01e01"
        }
        script = generate_episode_script(sample_ep)
        self.assertEqual(script["total_parts"], 3)
        self.assertEqual(len(script["parts"]), 3)
        
        for p in script["parts"]:
            self.assertTrue(len(p["hook"]) > 10)
            self.assertTrue(len(p["narration"].split()) >= 70)
            self.assertIn("#shorts", p["short_title"].lower())
            self.assertIn("PART", p["badge"])
            self.assertIn("bhalooji", p["hashtags"])

        # Check full video metadata
        self.assertIn("full_video", script)
        self.assertTrue(len(script["full_video"]["title"]) > 15)
        self.assertGreaterEqual(len(script["full_video"]["chapters"]), 3)
        self.assertIn("Copyright Disclaimer", script["full_video"]["description"])


class TestAnimeSubtitles(unittest.TestCase):
    def test_format_ass_time(self):
        self.assertEqual(format_ass_time(0.0), "0:00:00.00")
        self.assertEqual(format_ass_time(65.45), "0:01:05.45")
        self.assertEqual(format_ass_time(3605.12), "1:00:05.12")

    def test_cues_to_ass(self):
        mock_cues = [
            {"word": "Tanjiro", "start": 0.1, "end": 0.5},
            {"word": "Kamado", "start": 0.5, "end": 1.0},
            {"word": "attacks", "start": 1.0, "end": 1.5},
        ]
        ass_str = cues_to_ass(mock_cues, badge_text="DEMON SLAYER • PART 1/3")
        self.assertIn("[Script Info]", ass_str)
        self.assertIn("[V4+ Styles]", ass_str)
        self.assertIn("DEMON SLAYER • PART 1/3", ass_str)
        self.assertIn("TANJIRO", ass_str)
        self.assertIn("\\c&H0000FFFF&", ass_str)  # Highlight color tag


class TestAnimeVideoFiltergraph(unittest.TestCase):
    def test_filtergraph_construction(self):
        fg = build_ffmpeg_filtergraph(has_subtitles=True, ass_path="/tmp/test.ass")
        self.assertIn("boxblur=25:5", fg)
        self.assertIn("scale=1080:1920", fg)
        self.assertIn("scale=1040:584", fg)
        self.assertIn("pad=1040:584", fg)
        self.assertIn("setsar=1", fg)
        self.assertIn("ass='/tmp/test.ass'", fg)
        self.assertIn("eq=contrast=1.06", fg)

    def test_filtergraph_ffmpeg_execution(self):
        import subprocess
        fg = build_ffmpeg_filtergraph(has_subtitles=False)
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=size=854x480:rate=1",
            "-t", "1",
            "-filter_complex", fg,
            "-map", "[v]",
            "-f", "null", "-"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"FFmpeg filtergraph failed: {res.stderr}")

    def test_assemble_short_part_dry_run(self):
        from anime_video_engine import assemble_short_part
        res = assemble_short_part(
            raw_video_path="/tmp/fake.mp4",
            voice_audio_path="/tmp/fake.mp3",
            ass_subtitle_path="/tmp/fake.ass",
            output_video_path="/tmp/fake_out.mp4",
            time_window=(0, 450),
            total_duration=45.0,
            dry_run=True,
        )
        self.assertTrue(res)

    def test_bgm_asset_exists(self):
        from anime_video_engine import DEFAULT_BGM_PATH
        self.assertTrue(DEFAULT_BGM_PATH.exists(), f"Default BGM not found: {DEFAULT_BGM_PATH}")


if __name__ == "__main__":
    unittest.main()
