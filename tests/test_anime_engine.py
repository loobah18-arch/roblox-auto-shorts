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

    def test_landscape_cues_to_ass(self):
        mock_cues = [
            {"word": "Tanjiro", "start": 0.1, "end": 0.5},
            {"word": "draws", "start": 0.5, "end": 1.0},
            {"word": "sword", "start": 1.0, "end": 1.5},
        ]
        ass_str = cues_to_ass(mock_cues, is_landscape=True)
        self.assertIn("PlayResX: 1920", ass_str)
        self.assertIn("PlayResY: 1080", ass_str)
        self.assertIn("90,1", ass_str)  # MarginV: 90 for bottom third
        self.assertNotIn("•", ass_str)  # No top badge bullet in clean landscape movie recap


class TestAnimeVideoFiltergraph(unittest.TestCase):
    def test_filtergraph_construction(self):
        fg = build_ffmpeg_filtergraph(has_subtitles=True, ass_path="/tmp/test.ass")
        self.assertIn("boxblur=28:6", fg)
        self.assertIn("scale=1080:1920", fg)
        self.assertIn("scale=1020:574", fg)
        self.assertIn("pad=1020:574", fg)
        self.assertIn("setsar=1", fg)
        self.assertIn("ass='/tmp/test.ass'", fg)
        self.assertIn("eq=contrast=1.15", fg)
        self.assertIn("vignette", fg)
        self.assertIn("unsharp", fg)
        self.assertIn("hflip", fg)

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

    def test_landscape_filtergraph_construction(self):
        from anime_video_engine import build_landscape_ffmpeg_filtergraph
        fg = build_landscape_ffmpeg_filtergraph(has_subtitles=True, ass_path="/tmp/test.ass")
        self.assertIn("scale=1920:1080", fg)
        self.assertIn("pad=1920:1080", fg)
        self.assertIn("ass='/tmp/test.ass'", fg)
        self.assertIn("eq=contrast=1.12", fg)
        self.assertIn("vignette", fg)
        self.assertIn("hflip", fg)
        self.assertNotIn("boxblur", fg)  # Pure fullscreen landscape without side blur bars!

    def test_assemble_short_part_dry_run(self):
        from anime_video_engine import assemble_short_part
        res = assemble_short_part(
            raw_video_path="/tmp/fake.mp4",
            voice_audio_path="/tmp/fake.mp3",
            ass_subtitle_path="/tmp/fake.ass",
            output_video_path="/tmp/fake_out.mp4",
            time_window=(0, 450),
            total_duration=45.0,
            is_landscape=True,
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
        self.assertEqual(DEFAULT_BGM_PATH.name, "aerohead_fragments_recap.mp3")


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

        mock_script = {
            "total_parts": 3,
            "parts": [
                {"part": 1, "hook": "H1", "narration": "N1", "short_title": "T1 #shorts", "hashtags": ["anime"], "badge": "PART 1/3"},
            ],
            "full_video": {"title": "Demon Slayer Season 1 Episode 2 Full Recap & Explanation | Trainer Urokodaki", "chapters": [], "description": "desc", "hashtags": ["anime"]}
        }

        with patch("anime_pipeline.load_history", return_value=mock_history), \
             patch("anime_pipeline.save_history") as mock_save, \
             patch("anime_pipeline.generate_episode_script", return_value=mock_script), \
             patch("anime_pipeline.produce_master_audio_subtitles", return_value={"duration": 45.0, "word_count": 150, "chapter_segments": []}), \
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


class TestAnimeSubtitleSync(unittest.TestCase):
    def test_curated_act_timelines(self):
        from anime_subtitle_sync import get_episode_scene_acts, CURATED_ACT_TIMELINES
        
        ep_info = {"episode_key": "demon-slayer-s01e06", "display_name": "Demon Slayer S01E06"}
        acts = get_episode_scene_acts(ep_info)
        self.assertEqual(len(acts), 4)
        self.assertEqual(acts[0]["time_range"], [132, 420])
        self.assertEqual(acts[3]["time_range"], [940, 1260])
        # Ensure chronological progression
        for i in range(len(acts) - 1):
            self.assertLessEqual(acts[i]["time_range"][1], acts[i+1]["time_range"][0] + 5)

    def test_uncurated_dynamic_acts(self):
        from anime_subtitle_sync import get_episode_scene_acts
        
        ep_info = {"episode_key": "naruto-s01e15", "display_name": "Naruto S01E15"}
        acts = get_episode_scene_acts(ep_info, num_parts=3)
        self.assertEqual(len(acts), 3)
        # Verify OP theme is skipped (starts >= 120)
        self.assertGreaterEqual(acts[0]["time_range"][0], 120)
        # Verify ED theme is skipped (ends <= 1260)
        self.assertLessEqual(acts[-1]["time_range"][1], 1260)

    def test_script_engine_scene_sync_enforcement(self):
        sample_ep = {
            "series": "Demon Slayer: Kimetsu no Yaiba",
            "series_id": "demon-slayer",
            "season": 1,
            "episode": 6,
            "filename": "Demon_Slayer_Kimetsu_no_Yaiba_480P_S01_E06.mp4",
            "episode_key": "demon-slayer-s01e06"
        }
        script = generate_episode_script(sample_ep)
        self.assertEqual(script["total_parts"], 4)
        self.assertEqual(len(script["parts"]), 4)
        # Part 1 must cover the Mt. Sagiri departure uniform scene
        self.assertEqual(script["parts"][0]["time_range"], [132, 420])
        # Part 4 must cover the swamp split combat
        self.assertEqual(script["parts"][3]["time_range"], [940, 1260])


class TestMasterVideoArchitecture(unittest.TestCase):
    def test_normal_video_is_continuous_master(self):
        sample_ep = {
            "series": "Demon Slayer: Kimetsu no Yaiba",
            "series_id": "demon-slayer",
            "season": 1,
            "episode": 6,
            "filename": "Demon_Slayer_Kimetsu_no_Yaiba_480P_S01_E06.mp4",
            "episode_key": "demon-slayer-s01e06"
        }
        script = generate_episode_script(sample_ep)
        full_text = script["full_video"]["script"].lower()
        
        # Word count is unconstrained and rich (> 600 words)
        words = len(full_text.split())
        self.assertGreaterEqual(words, 500, f"Master video narrative too brief: {words} words")
        
        # Master video narration must NOT contain mid-video cliffhangers
        for p in script["parts"]:
            narr = p["narration"].lower()
            self.assertNotIn("watch part 2", narr)
            self.assertNotIn("see what happens in part 2", narr)
            self.assertNotIn("find out in part 3", narr)

    def test_shorts_are_excerpts_of_normal_video(self):
        sample_ep = {
            "series": "Demon Slayer: Kimetsu no Yaiba",
            "series_id": "demon-slayer",
            "season": 1,
            "episode": 6,
            "filename": "Demon_Slayer_Kimetsu_no_Yaiba_480P_S01_E06.mp4",
            "episode_key": "demon-slayer-s01e06"
        }
        script = generate_episode_script(sample_ep)
        for p in script["parts"]:
            self.assertIn("excerpt from our full", p["description"].lower())
            self.assertTrue(len(p["time_range"]) == 2)


class TestContinuousMasterEngine(unittest.TestCase):
    def test_assemble_master_full_video_dry_run(self):
        from anime_video_engine import assemble_master_full_video
        
        chapter_segs = [
            {"part": 1, "start_time": 0.0, "end_time": 65.0, "duration": 65.0, "time_range": [132, 420]},
            {"part": 2, "start_time": 65.0, "end_time": 130.0, "duration": 65.0, "time_range": [420, 660]},
        ]
        ok = assemble_master_full_video(
            raw_video_path="fake_raw.mp4",
            voice_audio_path="fake_voice.mp3",
            ass_subtitle_path="fake_sub.ass",
            output_video_path="fake_master.mp4",
            chapter_segments=chapter_segs,
            total_duration=130.0,
            dry_run=True,
        )
        self.assertTrue(ok)

    def test_assemble_master_full_video_with_beats_dry_run(self):
        from anime_video_engine import assemble_master_full_video
        
        chapter_segs = [
            {
                "part": 1,
                "start_time": 0.0,
                "end_time": 75.0,
                "duration": 75.0,
                "time_range": [132, 420],
                "beats": [
                    {"start": 132.0, "weight": 0.24, "desc": "Tanjiro in uniform"},
                    {"start": 215.0, "weight": 0.27, "desc": "Nichirin blade lore"},
                    {"start": 285.0, "weight": 0.26, "desc": "Kirin box gift"},
                    {"start": 370.0, "weight": 0.23, "desc": "Descending Mt. Sagiri"},
                ]
            },
            {
                "part": 2,
                "start_time": 75.0,
                "end_time": 139.0,
                "duration": 64.0,
                "time_range": [420, 660],
                "beats": [
                    {"start": 425.0, "weight": 0.28, "desc": "Town arrival"},
                    {"start": 495.0, "weight": 0.37, "desc": "Kazumi despair"},
                    {"start": 575.0, "weight": 0.35, "desc": "Sniffing cobblestones"},
                ]
            },
        ]
        ok = assemble_master_full_video(
            raw_video_path="fake_raw.mp4",
            voice_audio_path="fake_voice.mp3",
            ass_subtitle_path="fake_sub.ass",
            output_video_path="fake_master.mp4",
            chapter_segments=chapter_segs,
            total_duration=139.0,
            dry_run=True,
        )
        self.assertTrue(ok)

    def test_derive_short_from_master_dry_run(self):
        from anime_video_engine import derive_short_from_master
        
        ok = derive_short_from_master(
            master_video_path="fake_master.mp4",
            output_short_path="fake_short.mp4",
            start_time=0.0,
            end_time=65.0,
            badge_text="DEMON SLAYER • PART 1/4",
            dry_run=True,
        )
        self.assertTrue(ok)

    def test_episode_script_beats_structure(self):
        from anime_script_engine import generate_episode_script
        sample_ep = {
            "series": "Demon Slayer: Kimetsu no Yaiba",
            "series_id": "demon-slayer",
            "season": 1,
            "episode": 6,
            "filename": "Demon_Slayer_Kimetsu_no_Yaiba_480P_S01_E06.mp4",
            "episode_key": "demon-slayer-s01e06"
        }
        script = generate_episode_script(sample_ep)
        for p in script["parts"]:
            self.assertIn("beats", p)
            self.assertGreaterEqual(len(p["beats"]), 2)
            total_weight = sum(b["weight"] for b in p["beats"])
            self.assertAlmostEqual(total_weight, 1.0, delta=0.05)
            for b in p["beats"]:
                self.assertIn("start", b)
                self.assertIn("weight", b)
                self.assertIn("desc", b)

    def test_get_episode_scene_acts_always_includes_beats(self):
        from anime_subtitle_sync import get_episode_scene_acts
        # Curated episode
        curated_ep = {"episode_key": "demon-slayer-s01e06"}
        acts = get_episode_scene_acts(curated_ep)
        for act in acts:
            self.assertIn("beats", act)
            self.assertGreaterEqual(len(act["beats"]), 2)

        # Uncurated episode
        uncurated_ep = {"episode_key": "bleach-s01e01"}
        acts = get_episode_scene_acts(uncurated_ep, num_parts=4)
        for act in acts:
            self.assertIn("beats", act)
            self.assertEqual(len(act["beats"]), 3)
            self.assertAlmostEqual(sum(b["weight"] for b in act["beats"]), 1.0, delta=0.01)

    def test_universal_dialogue_clustering_and_sentence_locked_sync(self):
        """Verify universal dialogue clustering and dynamic sentence duration weights."""
        from anime_subtitle_sync import cluster_dialogue_into_acts

        mock_dialogue = [
            {"start": 100.0, "end": 104.0, "text": "Ichigo Kurosaki can see ghosts."},
            {"start": 150.0, "end": 155.0, "text": "A terrifying hollow appears in Karakura Town."},
            {"start": 300.0, "end": 305.0, "text": "Rukia Kuchiki arrives with her Zanpakuto."},
            {"start": 450.0, "end": 455.0, "text": "Ichigo absorbs Rukia's soul reaper powers!"},
            {"start": 600.0, "end": 605.0, "text": "The massive blade slices the hollow in two."},
            {"start": 800.0, "end": 805.0, "text": "A new Substitute Soul Reaper is born."},
        ]

        acts = cluster_dialogue_into_acts(mock_dialogue, num_parts=3, episode_duration=1000.0)
        self.assertEqual(len(acts), 3)
        for act in acts:
            self.assertIn("time_range", act)
            self.assertIn("beats", act)
            self.assertGreaterEqual(len(act["beats"]), 1)
            self.assertAlmostEqual(sum(b["weight"] for b in act["beats"]), 1.0, delta=0.02)

    def test_demon_slayer_s01e05_curated_beats(self):
        """Verify demon-slayer-s01e05 is fully curated with 5 acts and sentence-locked beats."""
        from anime_subtitle_sync import CURATED_ACT_TIMELINES
        self.assertIn("demon-slayer-s01e05", CURATED_ACT_TIMELINES)
        acts = CURATED_ACT_TIMELINES["demon-slayer-s01e05"]["acts"]
        self.assertEqual(len(acts), 5)
        for act in acts:
            self.assertIn("time_range", act)
            self.assertIn("beats", act)
            self.assertEqual(len(act["beats"]), 4)
            for b in act["beats"]:
                self.assertGreaterEqual(b["start"], act["time_range"][0])
                self.assertLessEqual(b["start"], act["time_range"][1])

    def test_assemble_short_part_with_beats_dry_run(self):
        """Verify assemble_short_part accepts beats and narration with dynamic sentence-locking."""
        from anime_video_engine import assemble_short_part
        mock_beats = [
            {"start": 505.0, "weight": 0.25, "desc": "Beat 1"},
            {"start": 540.0, "weight": 0.25, "desc": "Beat 2"},
            {"start": 580.0, "weight": 0.25, "desc": "Beat 3"},
            {"start": 620.0, "weight": 0.25, "desc": "Beat 4"},
        ]
        mock_narration = "First sentence here. Second sentence here. Third sentence here. Fourth sentence here."
        res = assemble_short_part(
            raw_video_path="/tmp/fake.mp4",
            voice_audio_path="/tmp/fake.mp3",
            ass_subtitle_path="/tmp/fake.ass",
            output_video_path="/tmp/fake_short.mp4",
            time_window=(505, 645),
            total_duration=55.0,
            is_landscape=False,
            dry_run=True,
            beats=mock_beats,
            narration=mock_narration,
        )
        self.assertTrue(res)

    def test_all_episode_knowledge_titles_contain_explanation(self):
        """Verify every single short_title in EPISODE_KNOWLEDGE explicitly includes 'Explanation'."""
        from anime_script_engine import EPISODE_KNOWLEDGE
        for ep_key, ep_data in EPISODE_KNOWLEDGE.items():
            for p in ep_data.get("parts", []):
                title = p.get("short_title", "")
                self.assertIn(
                    "Explanation",
                    title,
                    f"EPISODE_KNOWLEDGE {ep_key} Part {p.get('part')} title lacks 'Explanation': {title}"
                )

    def test_format_script_package_enforces_explanation(self):
        """Verify _format_script_package automatically injects 'Explanation' into any raw title."""
        from anime_script_engine import _format_script_package
        ep_info = {"series": "Demon Slayer", "season": 1, "episode": 5}
        raw_parts = [
            {"part": 1, "narration": "Narration 1", "short_title": "Cool Scene | Demon Slayer S1 Ep 5 Part 1 #shorts"},
            {"part": 2, "narration": "Narration 2", "short_title": "Epic Clash #shorts"},
            {"part": 3, "narration": "Narration 3"},  # missing short_title
        ]
        pkg = _format_script_package(ep_info, "Title", "Summary", raw_parts)
        for p in pkg["parts"]:
            self.assertIn("Explanation", p["short_title"], f"Part {p['part']} title lacks 'Explanation': {p['short_title']}")

    def test_synthesize_word_cues(self):
        """Verify proportional word cue generation for fallback TTS."""
        from anime_voice_subtitles import synthesize_word_cues
        text = "Tanjiro uses water breathing tenth form"
        cues = synthesize_word_cues(text, total_duration=6.0)
        self.assertEqual(len(cues), 6)
        self.assertEqual(cues[0]["word"], "Tanjiro")
        self.assertEqual(cues[0]["start"], 0.0)
        self.assertAlmostEqual(cues[-1]["end"], 6.0, delta=0.1)

    def test_cinema_style_fullbleed_filtergraph(self):
        """Verify full-bleed cinema filtergraph (narration cinema style)."""
        from anime_video_engine import build_fullbleed_ffmpeg_filtergraph, build_ffmpeg_filtergraph
        fg_direct = build_fullbleed_ffmpeg_filtergraph(has_subtitles=True, ass_path="/tmp/cinema.ass")
        self.assertIn("scale=1080:1920:force_original_aspect_ratio=increase", fg_direct)
        self.assertIn("crop=1080:1920", fg_direct)
        self.assertIn("vignette", fg_direct)
        self.assertIn("ass='/tmp/cinema.ass'", fg_direct)
        # Verify no card or blurred backdrop in full-bleed mode
        self.assertNotIn("boxblur", fg_direct)
        self.assertNotIn("drawbox", fg_direct)

        # Verify build_ffmpeg_filtergraph with full_bleed=True returns the same
        fg_param = build_ffmpeg_filtergraph(has_subtitles=True, ass_path="/tmp/cinema.ass", full_bleed=True)
        self.assertIn("crop=1080:1920", fg_param)
        self.assertNotIn("boxblur", fg_param)

    def test_cinema_style_subtitles_and_cta(self):
        """Verify cinema-style lower-third subtitle placement and comment-trap description CTA."""
        from anime_voice_subtitles import cues_to_ass, CINEMA_VOICE
        from anime_script_engine import _format_script_package

        self.assertEqual(CINEMA_VOICE, "en-US-GuyNeural")

        mock_cues = [
            {"word": "Tanjiro", "start": 0.1, "end": 0.5},
            {"word": "strikes", "start": 0.5, "end": 1.0},
        ]
        ass_str = cues_to_ass(mock_cues, badge_text="DEMON SLAYER", full_bleed=True)
        # MarginV 240 for cinema safe area
        self.assertIn("240,1", ass_str)
        # No header badge line in full_bleed cinema mode
        self.assertNotIn("CardHeader", ass_str.split("[Events]")[1])

        # Verify description contains viral comment trap CTA
        ep_info = {"series": "Demon Slayer", "season": 1, "episode": 1}
        raw_parts = [{"part": 1, "narration": "Narration", "hook": "Hook sentence."}]
        pkg = _format_script_package(ep_info, "Title", "Summary", raw_parts)
        desc = pkg["parts"][0]["description"]
        self.assertIn("Watch until the end to find out what happens next!", desc)
        self.assertIn("comment YES if you want the next episode!", desc)

    def test_cinema_script_generation(self):
        """Verify generate_cinema_script produces 3-minute standalone script without Part fragmentation."""
        from anime_script_engine import generate_cinema_script
        sample_ep = {
            "series": "Demon Slayer: Kimetsu no Yaiba",
            "series_id": "demon-slayer",
            "season": 1,
            "episode": 9,
            "filename": "Demon_Slayer_Kimetsu_no_Yaiba_480P_S01_E09.mp4",
            "episode_key": "demon-slayer-s01e09",
            "display_name": "Demon Slayer: Kimetsu no Yaiba S01E09",
        }
        res = generate_cinema_script(sample_ep)
        self.assertIn("Until", res["title"])
        self.assertIn("Story Recap", res["title"])
        self.assertIn("Explanation", res["title"])
        self.assertIn("#shorts", res["title"])
        self.assertNotIn("Part 1", res["title"])
        self.assertNotIn("Part 2", res["title"])
        self.assertTrue(res["narration"].endswith("To watch the next episode, comment yes."))
        self.assertGreaterEqual(res["word_count"], 400)
        self.assertIn("Watch until the end to find out what happens next!", res["description"])
        self.assertIn("comment YES if you want the next episode!", res["description"])

    def test_run_cinema_pipeline_dry_run(self):
        """Verify run_cinema_pipeline executes standalone 3-minute Short in dry-run mode."""
        from anime_pipeline import run_cinema_pipeline
        res = run_cinema_pipeline(episode_key="demon-slayer-s01e09", dry_run=True)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["mode"], "cinema")
        self.assertEqual(res["action"], "short")
        self.assertTrue(res["video_to_upload"]["is_cinema_short"])
        self.assertNotIn("Part 1", res["video_to_upload"]["title"])
        self.assertNotIn("Part 2", res["video_to_upload"]["title"])
        self.assertIn("Story Recap Explanation #shorts", res["video_to_upload"]["title"])


if __name__ == "__main__":
    unittest.main()



