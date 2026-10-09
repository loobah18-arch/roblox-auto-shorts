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
            self.assertTrue(
                len(p["narration"].split()) >= 150,
                f"Part {p['part']} narration too short: {len(p['narration'].split())} words"
            )
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

    def test_stitch_full_episode_video_dry_run(self):
        from anime_video_engine import stitch_full_episode_video
        res = stitch_full_episode_video(
            part_video_paths=["/tmp/p1.mp4", "/tmp/p2.mp4"],
            output_full_path="/tmp/full_out.mp4",
            dry_run=True,
        )
        self.assertTrue(res)

    def test_bgm_asset_exists(self):
        from anime_video_engine import DEFAULT_BGM_PATH
        self.assertTrue(DEFAULT_BGM_PATH.exists(), f"Default BGM not found: {DEFAULT_BGM_PATH}")


class TestAnimeUploader(unittest.TestCase):
    def test_find_uploaded_part(self):
        from anime_youtube_uploader import find_uploaded_part
        sample_parts = [
            {
                "episode_key": "demon-slayer-s01e02",
                "part": 1,
                "is_full_video": False,
                "video_id": "VRmFbfvaAnM",
                "url": "https://youtube.com/shorts/VRmFbfvaAnM"
            },
            {
                "episode_key": "demon-slayer-s01e02",
                "part": None,
                "is_full_video": True,
                "video_id": "FULL_VID_123",
                "url": "https://youtu.be/FULL_VID_123"
            }
        ]
        p1 = find_uploaded_part(sample_parts, "demon-slayer-s01e02", p_num=1, is_full=False)
        self.assertIsNotNone(p1)
        self.assertEqual(p1["video_id"], "VRmFbfvaAnM")

        p2 = find_uploaded_part(sample_parts, "demon-slayer-s01e02", p_num=2, is_full=False)
        self.assertIsNone(p2)

        full = find_uploaded_part(sample_parts, "demon-slayer-s01e02", is_full=True)
        self.assertIsNotNone(full)
        self.assertEqual(full["video_id"], "FULL_VID_123")

    def test_upload_quota_exceeded_handled(self):
        from unittest.mock import MagicMock
        from anime_youtube_uploader import upload_video_file
        import tempfile

        # Create dummy file > 50KB
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"0" * (60 * 1024))
            temp_path = f.name

        try:
            mock_yt = MagicMock()
            mock_req = MagicMock()
            mock_req.next_chunk.side_effect = Exception("<HttpError 400 'The user has exceeded the number of videos they may upload.' (reason: uploadLimitExceeded)>")
            mock_yt.videos().insert.return_value = mock_req

            res = upload_video_file(
                youtube=mock_yt,
                video_path=temp_path,
                title="Test Title #shorts",
                description="Test Desc",
                tags=["test"],
            )
            self.assertEqual(res["status"], "quota_exceeded")
            self.assertEqual(res["error"], "uploadLimitExceeded")
        finally:
            import os
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_uploader_daily_funnel_preview(self):
        import tempfile
        from anime_youtube_uploader import upload_episode_package

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            summary = {
                "status": "success",
                "mode": "daily_funnel",
                "action": "normal_video",
                "episode_key": "demon-slayer-s01e05",
                "video_to_upload": {
                    "title": "Demon Slayer S01E05 Full Recap",
                    "video_path": str(td_path / "full.mp4"),
                    "description": "Full recap",
                    "hashtags": ["anime"],
                }
            }
            with open(td_path / "pipeline_summary.json", "w") as f:
                json.dump(summary, f)

            res = upload_episode_package(episode_dir=td_path, live=False)
            self.assertEqual(res["status"], "preview")
            self.assertEqual(res["mode"], "daily_funnel")
            self.assertEqual(res["action"], "normal_video")


class TestRecapKunStyle(unittest.TestCase):
    def test_recapkun_voice_and_rate(self):
        from anime_voice_subtitles import DEFAULT_VOICE, DEFAULT_RATE
        self.assertEqual(DEFAULT_VOICE, "en-US-ChristopherNeural")
        self.assertEqual(DEFAULT_RATE, "+8%")


class TestDailyFunnel(unittest.TestCase):
    def test_daily_funnel_case_a_starts_normal_video(self):
        from unittest.mock import patch
        from anime_pipeline import run_daily_funnel

        mock_history = {
            "completed_episodes": ["demon-slayer-s01e01"],
            "active_episode": None,
            "uploaded_parts": [],
        }

        with patch("anime_pipeline.load_history", return_value=mock_history), \
             patch("anime_pipeline.save_history") as mock_save, \
             patch("anime_pipeline.produce_part_audio_subtitles", return_value={"duration": 45.0, "word_count": 150}):
            res = run_daily_funnel(dry_run=True)
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["mode"], "daily_funnel")
            self.assertEqual(res["action"], "normal_video")
            self.assertIn("Full Recap & Explanation", res["video_to_upload"]["title"])
            self.assertTrue(mock_save.called)

    def test_daily_funnel_progresses_through_shorts(self):
        from unittest.mock import patch
        from anime_pipeline import run_daily_funnel

        sample_script = {
            "total_parts": 3,
            "parts": [
                {"part": 1, "hook": "Hook 1", "narration": "Narr 1", "short_title": "Title 1 #shorts", "hashtags": ["anime"], "badge": "PART 1/3"},
                {"part": 2, "hook": "Hook 2", "narration": "Narr 2", "short_title": "Title 2 #shorts", "hashtags": ["anime"], "badge": "PART 2/3"},
                {"part": 3, "hook": "Hook 3", "narration": "Narr 3", "short_title": "Title 3 #shorts", "hashtags": ["anime"], "badge": "PART 3/3"},
            ],
            "full_video": {"title": "Full Recap"}
        }

        mock_history = {
            "completed_episodes": ["demon-slayer-s01e01"],
            "active_episode": {
                "episode_key": "demon-slayer-s01e05",
                "display_name": "Demon Slayer S01E05",
                "series_id": "demon-slayer",
                "total_parts": 3,
                "normal_video_uploaded": True,
                "uploaded_shorts": [],
                "script_package": sample_script,
            },
            "uploaded_parts": [],
        }

        # Step 1: Uploads Part 1
        with patch("anime_pipeline.load_history", return_value=mock_history), \
             patch("anime_pipeline.save_history"), \
             patch("anime_pipeline.produce_part_audio_subtitles", return_value={"duration": 45.0, "word_count": 150}):
            res = run_daily_funnel(dry_run=True)
            self.assertEqual(res["mode"], "daily_funnel")
            self.assertEqual(res["action"], "short")
            self.assertEqual(res["part"], 1)

        # Step 2: Part 1 done -> Uploads Part 2
        mock_history["active_episode"]["uploaded_shorts"] = [1]
        with patch("anime_pipeline.load_history", return_value=mock_history), \
             patch("anime_pipeline.save_history"), \
             patch("anime_pipeline.produce_part_audio_subtitles", return_value={"duration": 45.0, "word_count": 150}):
            res = run_daily_funnel(dry_run=True)
            self.assertEqual(res["action"], "short")
            self.assertEqual(res["part"], 2)

        # Step 3: Part 1 & 2 done -> Uploads Part 3
        mock_history["active_episode"]["uploaded_shorts"] = [1, 2]
        with patch("anime_pipeline.load_history", return_value=mock_history), \
             patch("anime_pipeline.save_history"), \
             patch("anime_pipeline.produce_part_audio_subtitles", return_value={"duration": 45.0, "word_count": 150}):
            res = run_daily_funnel(dry_run=True)
            self.assertEqual(res["action"], "short")
            self.assertEqual(res["part"], 3)


if __name__ == "__main__":
    unittest.main()
