#!/usr/bin/env python3
"""
Unit tests for Multi-Agent Anti-Copyright Filter System.
Fast, mocked tests running in <1s locally on device.
"""

import unittest
from pathlib import Path

from scripts.anime_copyright_filter import (
    VideoCopyrightAgent,
    TitleCopyrightAgent,
    DescriptionCopyrightAgent,
    MultiAgentCopyrightShield,
    MAX_SHORT_DURATION,
    MAX_SAFE_ANIME_STORY_TIMESTAMP,
)


class TestTitleCopyrightAgent(unittest.TestCase):
    def setUp(self):
        self.agent = TitleCopyrightAgent(blocked_titles=["Blocked Old Video Title"])

    def test_rejects_missing_explanation_marker(self):
        res = self.agent.evaluate_title("Tanjiro Fights the Swamp Demon #shorts", is_short=True)
        self.assertFalse(res.passed)
        self.assertTrue(any("transformative marker" in v for v in res.violations))

    def test_rejects_raw_scraper_episode_tags(self):
        res = self.agent.evaluate_title(
            "Tanjiro Breaks Genya's Arm LIVE! 💥 | Demon Slayer S1 Ep 5 Explanation Part 2 #shorts",
            is_short=True,
        )
        self.assertFalse(res.passed)
        self.assertTrue(any("scraper pattern" in v for v in res.violations))

    def test_rejects_season_episode_long_pattern(self):
        res = self.agent.evaluate_title(
            "Tanjiro's Journey | Season 1 Episode 5 Explanation Part 1 #shorts",
            is_short=True,
        )
        self.assertFalse(res.passed)
        self.assertTrue(any("scraper pattern" in v for v in res.violations))

    def test_rejects_blocked_titles(self):
        res = self.agent.evaluate_title(
            "Blocked Old Video Title Story Recap Explanation #shorts",
            is_short=True,
        )
        self.assertFalse(res.passed)
        self.assertTrue(any("previously blocked" in v for v in res.violations))

    def test_rejects_missing_shorts_hashtag(self):
        res = self.agent.evaluate_title(
            "Tanjiro Awakens Sun Breathing | Demon Slayer Story Recap Explanation Part 2",
            is_short=True,
        )
        self.assertFalse(res.passed)
        self.assertTrue(any("#shorts" in v for v in res.violations))

    def test_passes_valid_title(self):
        res = self.agent.evaluate_title(
            "Tanjiro Breaks Genya’s Arm LIVE! 💥 | Demon Slayer Story Recap Explanation Part 2 #shorts",
            is_short=True,
        )
        self.assertTrue(res.passed)
        self.assertEqual(len(res.violations), 0)

    def test_remediate_title(self):
        raw = "Tanjiro Breaks Genya’s Arm LIVE! 💥 | Demon Slayer S1 Ep 5 Part 2"
        remediated = self.agent.remediate_title(raw, is_short=True, part_num=2)
        self.assertIn("Story Recap", remediated)
        self.assertIn("Explanation", remediated)
        self.assertIn("#shorts", remediated)
        self.assertNotIn("S1 Ep 5", remediated)
        # Verify remediated title passes
        eval_res = self.agent.evaluate_title(remediated, is_short=True)
        self.assertTrue(eval_res.passed)


class TestDescriptionCopyrightAgent(unittest.TestCase):
    def setUp(self):
        self.agent = DescriptionCopyrightAgent()

    def test_rejects_missing_fair_use_disclaimer(self):
        desc = "Here is a quick summary of Demon Slayer Episode 5. Enjoy the video!"
        res = self.agent.evaluate_description(desc)
        self.assertFalse(res.passed)
        self.assertTrue(any("Section 107" in v for v in res.violations))

    def test_passes_description_with_section_107(self):
        desc = (
            "Tanjiro survives the final selection.\n\n"
            "Copyright Disclaimer Under Section 107 of the Copyright Act 1976:\n"
            "Allowance is made for fair use for transformative commentary and analysis."
        )
        res = self.agent.evaluate_description(desc)
        self.assertTrue(res.passed)

    def test_remediate_description(self):
        raw = "Tanjiro fights hard in Final Selection."
        remediated = self.agent.remediate_description(raw)
        self.assertIn("Section 107", remediated)
        self.assertIn("Fair Use", remediated)
        eval_res = self.agent.evaluate_description(remediated)
        self.assertTrue(eval_res.passed)


class TestVideoCopyrightAgent(unittest.TestCase):
    def setUp(self):
        self.agent = VideoCopyrightAgent(max_short_duration=58.5)

    def test_rejects_ending_credits_timestamps(self):
        # A mock video path that doesn't probe ffprobe
        res = self.agent.evaluate_video(
            video_path="/non/existent/video.mp4",
            is_short=True,
            time_window=(1207.0, 1370.0),  # In ending credits!
        )
        self.assertFalse(res.passed)
        self.assertTrue(any("anime ED credits" in v for v in res.violations))

    def test_rejects_contiguous_shots_exceeding_threshold(self):
        mock_shots = [
            {"duration": 2.5},
            {"duration": 6.8},  # Too long!
        ]
        res = self.agent.evaluate_video(
            video_path="/non/existent/video.mp4",
            is_short=True,
            time_window=(500.0, 600.0),
            shots_info=mock_shots,
        )
        self.assertFalse(res.passed)
        self.assertTrue(any("contiguous micro-cut threshold" in v for v in res.violations))


class TestMultiAgentCopyrightShield(unittest.TestCase):
    def setUp(self):
        self.shield = MultiAgentCopyrightShield()

    def test_inspect_candidate_and_remediate(self):
        # Initial bad candidate metadata
        bad_title = "Tanjiro vs Demon S1 Ep 5 Part 2"
        bad_desc = "Quick clip of the anime."

        clean_title, clean_desc = self.shield.remediate_metadata(
            title=bad_title,
            description=bad_desc,
            is_short=True,
            part_num=2,
        )
        self.assertIn("Story Recap", clean_title)
        self.assertIn("Explanation", clean_title)
        self.assertIn("#shorts", clean_title)
        self.assertIn("Section 107", clean_desc)

    def test_remediate_full_video_metadata(self):
        bad_full_title = "Demon Slayer: Kimetsu no Yaiba Season 1 Episode 6 Full Recap & Explanation"
        bad_full_desc = "Full episode breakdown."

        clean_title, clean_desc = self.shield.remediate_metadata(
            title=bad_full_title,
            description=bad_full_desc,
            is_short=False,
        )
        self.assertIn("Story Recap", clean_title)
        self.assertNotIn("Season 1 Episode 6", clean_title)
        self.assertNotIn("#shorts", clean_title)
        self.assertIn("Section 107", clean_desc)
        eval_res = self.shield.title_agent.evaluate_title(clean_title, is_short=False)
        self.assertTrue(eval_res.passed)


if __name__ == "__main__":
    unittest.main()
