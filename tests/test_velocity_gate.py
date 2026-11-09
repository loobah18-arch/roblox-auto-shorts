#!/usr/bin/env python3
"""
Unit tests for View Velocity Gate in roblox-auto-shorts (Bhaloo Ji).
"""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from anime_youtube_uploader import evaluate_view_velocity_gate, VIEW_THRESHOLD_PER_HOUR


class TestVelocityGate(unittest.TestCase):

    def setUp(self):
        self.mock_history = {
            "uploaded_parts": [
                {"video_id": "test_active_vid_123", "title": "Demon Slayer Ep 09"}
            ]
        }

    def test_override_bypasses_check(self):
        can_upload, msg, _ = evaluate_view_velocity_gate(
            youtube=None,
            history=self.mock_history,
            allow_override=True,
        )
        self.assertTrue(can_upload)
        self.assertIn("Override active", msg)

    def test_viral_velocity_blocks_upload(self):
        mock_youtube = MagicMock()
        mock_resp = {
            "items": [
                {
                    "snippet": {
                        "title": "Demon Slayer Ep 09",
                        "publishedAt": "2026-11-07T10:00:00Z",  # ~30h ago (past 24h early window)
                    },
                    "statistics": {
                        "viewCount": "120000",  # ~4,000 views/hr over ~30 hours
                    },
                }
            ]
        }
        mock_youtube.videos().list().execute.return_value = mock_resp

        can_upload, msg, data = evaluate_view_velocity_gate(
            youtube=mock_youtube,
            history=self.mock_history,
            threshold_per_hour=2500,
            allow_override=False,
        )
        self.assertFalse(can_upload)
        self.assertIn("performing well", msg)

    def test_sub_threshold_velocity_clears_upload(self):
        mock_youtube = MagicMock()
        mock_resp = {
            "items": [
                {
                    "snippet": {
                        "title": "Demon Slayer Ep 09",
                        "publishedAt": "2026-11-07T10:00:00Z",
                    },
                    "statistics": {
                        "viewCount": "800",  # ~24h elapsed, ~33 views/hr
                    },
                }
            ]
        }
        mock_youtube.videos().list().execute.return_value = mock_resp

        can_upload, msg, data = evaluate_view_velocity_gate(
            youtube=mock_youtube,
            history=self.mock_history,
            threshold_per_hour=2500,
            allow_override=False,
        )
        self.assertTrue(can_upload)
        self.assertIn("below", msg)

    def test_early_momentum_blocks_upload(self):
        mock_youtube = MagicMock()
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        mock_resp = {
            "items": [
                {
                    "snippet": {
                        "title": "Demon Slayer Ep 09",
                        "publishedAt": now_str,  # Very fresh
                    },
                    "statistics": {
                        "viewCount": "2500",  # >= 2k in first few hours
                    },
                }
            ]
        }
        mock_youtube.videos().list().execute.return_value = mock_resp

        can_upload, msg, data = evaluate_view_velocity_gate(
            youtube=mock_youtube,
            history=self.mock_history,
            early_views_threshold=2000,
            early_hours_window=24.0,
            allow_override=False,
        )
        self.assertFalse(can_upload)
        self.assertIn("Early momentum detected", msg)


if __name__ == "__main__":
    unittest.main()
