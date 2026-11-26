#!/usr/bin/env python3
"""Tests for the single-episode recap mode: style + short-candidate validation, the deterministic
Short fallback window, the episode picker and the derived-Short cadence exclusion."""

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from anime_episode_recap import (  # noqa: E402
    validate_short_candidates, fallback_short_window, hook_stands_alone, style_problems, validate_acts,
    parse_recap_answer, character_names, shorts_title, estimated_slots, window_seconds, EPISODE_WPS,
)

# A past-tense, setup -> twist story; beat 0 is a cold-open hook.
STORY = [
    "Every slayer on the mountain was losing to the spiders, but Tanjiro chose to face the strongest demon alone.",
    "Rui, a demon child who controlled razor-sharp threads, watched him from a tree.",
    "Tanjiro swung his sword at the threads with all his strength.",
    "But the blade snapped in half the moment it touched them.",
    "Seeing this, Rui laughed and wrapped the threads around Nezuko.",
    "Nezuko screamed as the threads cut into her arms.",
    "Just then, Tanjiro remembered his father dancing in the snow.",
    "It turned out that the dance was a breathing technique passed down for generations.",
    "Tanjiro drew a deep breath and his broken sword burst into flames.",
    "Meanwhile, Nezuko used her blood to set the threads on fire.",
    "Rui panicked when the burning threads crept toward his neck.",
    "Sure enough, Tanjiro's flaming blade sliced through Rui's neck.",
]


def make_story(n: int = 60) -> list[str]:
    out = []
    while len(out) < n:
        out.extend(STORY)
    return out[:n]


class TestHookAndStyle(unittest.TestCase):
    def test_hook_stands_alone(self):
        names = {"Tanjiro", "Rui", "Nezuko"}
        self.assertTrue(hook_stands_alone(STORY[0], names))
        self.assertTrue(hook_stands_alone("Tanjiro's sword snapped against a demon child, so he used his dead father's dance.", names))
        self.assertFalse(hook_stands_alone("But the blade snapped in half the moment it touched them.", names))
        self.assertFalse(hook_stands_alone("He swung his sword at the threads with all his strength.", names))
        self.assertFalse(hook_stands_alone("Seeing this, Rui laughed and wrapped the threads around Nezuko.", names))
        self.assertFalse(hook_stands_alone("Rui laughed.", names))  # too short to carry a Short

    def test_reference_style_passes_and_present_tense_recap_fails(self):
        beats = [{"text": t} for t in make_story(60)]
        self.assertEqual(style_problems(beats), [])
        bad = [{"text": t.replace("was", "is").replace("swung", "swings").replace("laughed", "laughs")
                .replace("remembered", "remembers").replace("drew", "draws").replace("panicked", "panics")
                .replace("chose", "chooses").replace("watched", "watches").replace("snapped", "snaps")
                .replace("screamed", "screams").replace("turned", "turns").replace("used", "uses")
                .replace("sliced", "slices").replace("passed", "passes").replace("wrapped", "wraps")
                .replace("controlled", "controls").replace("burst", "bursts").replace("crept", "creeps")
                .replace("dancing", "dancing")} for t in make_story(60)]
        bad[0]["text"] = "The story begins as we learn that Tanjiro is on a mountain full of spiders and things get crazy."
        probs = " | ".join(style_problems(bad))
        self.assertIn("past tense", probs)
        self.assertIn("we learn", probs)

    def test_validate_acts(self):
        acts = validate_acts([{"title": "The Broken Blade", "start_beat": 0}, {"title": "Father's Dance", "start_beat": 20},
                              {"title": "Fire Against Threads", "start_beat": 40}], 60)
        self.assertEqual([a["start_beat"] for a in acts], [0, 20, 40])
        with self.assertRaises(ValueError):
            validate_acts([{"title": "A", "start_beat": 0}, {"title": "B", "start_beat": 1}], 60)  # only 2 acts
        with self.assertRaises(ValueError):
            validate_acts([{"title": "A", "start_beat": 0}, {"title": "B", "start_beat": 30},
                           {"title": "C", "start_beat": 31}], 60)  # act with < 3 beats
        with self.assertRaises(ValueError):
            validate_acts([{"title": "Chapter 1", "start_beat": 0}, {"title": "B", "start_beat": 20},
                           {"title": "C", "start_beat": 40}], 60)

    def test_shorts_title(self):
        self.assertEqual(shorts_title("His Sword Snapped, So He Used His Father's Dance"),
                         "His Sword Snapped, So He Used His Father's Dance #shorts")
        self.assertLessEqual(len(shorts_title("x" * 150)), 100)
        self.assertTrue(shorts_title("x" * 150).endswith(" #shorts"))


class TestShortCandidates(unittest.TestCase):
    def setUp(self):
        self.texts = make_story(60)
        self.names = character_names(self.texts)

    def _cand(self, b0, b1, **kw):
        c = {"start_beat": b0, "end_beat": b1, "hook_beat": b0, "payoff_beat": b1,
             "title": "His Sword Snapped, So He Used His Father's Dance"}
        c.update(kw)
        return c

    def _dur(self, b0, b1):
        slots, speech = estimated_slots(self.texts)
        return window_seconds(slots, speech, b0, b1)

    def test_valid_candidate_opens_on_hook_and_ends_on_payoff(self):
        # beats 12..23 = one full pass of STORY: hook at 12, payoff ("sliced through Rui's neck") at 23
        self.assertTrue(36.5 <= self._dur(12, 23) <= 57.5, self._dur(12, 23))
        valid, probs = validate_short_candidates([self._cand(12, 23)], self.texts, self.names)
        self.assertEqual(len(valid), 1, probs)
        v = valid[0]
        self.assertEqual((v["hook_beat"], v["payoff_beat"]), (12, 23))
        self.assertFalse(v["hook_rewritten"])

    def test_hook_must_be_first_and_payoff_last(self):
        valid, probs = validate_short_candidates([self._cand(12, 23, hook_beat=13)], self.texts, self.names)
        self.assertEqual(valid, [])
        self.assertIn("hook_beat", probs[0])
        valid, probs = validate_short_candidates([self._cand(12, 23, payoff_beat=22)], self.texts, self.names)
        self.assertEqual(valid, [])
        self.assertIn("payoff_beat", probs[0])

    def test_dangling_start_needs_a_cold_open_rewrite(self):
        # beat 15 = "But the blade snapped..." does not stand alone ...
        valid, probs = validate_short_candidates([self._cand(15, 27)], self.texts, self.names)
        self.assertEqual(valid, [])
        self.assertIn("does not stand alone", probs[0])
        # ... unless hook_text rewrites it as a cold open
        hook = "Tanjiro's sword snapped in half against a demon child's threads, but he refused to give up."
        valid, probs = validate_short_candidates([self._cand(15, 27, hook_text=hook)], self.texts, self.names)
        self.assertEqual(len(valid), 1, probs)
        self.assertTrue(valid[0]["hook_rewritten"])
        self.assertEqual(valid[0]["hook_text"], hook)

    def test_duration_bounds(self):
        too_short, p1 = validate_short_candidates([self._cand(12, 16)], self.texts, self.names)
        too_long, p2 = validate_short_candidates([self._cand(12, 40)], self.texts, self.names)
        self.assertEqual(too_short + too_long, [])
        self.assertIn("need 35-59s", p1[0])
        self.assertIn("need 35-59s", p2[0])
        # with real (post-TTS) beat lengths the exact 35-59 s bounds apply
        slots = [4.0] * 60
        speech = [3.9] * 60
        ok, _ = validate_short_candidates([self._cand(12, 23)], self.texts, self.names, slots, speech)
        self.assertEqual(len(ok), 1)        # 11 * 4.0 + 3.9 + 0.5 = 48.4 s
        bad, p = validate_short_candidates([self._cand(12, 30)], self.texts, self.names, slots, speech)
        self.assertEqual(bad, [])           # 18 * 4.0 + 3.9 + 0.5 = 76.4 s
        self.assertIn("76.4s", p[0])

    def test_bad_structures(self):
        valid, probs = validate_short_candidates([self._cand(50, 70), "nope", self._cand(5, 3)], self.texts, self.names)
        self.assertEqual(valid, [])
        self.assertEqual(len(probs), 3)
        valid, probs = validate_short_candidates([self._cand(12, 23, title="#shorts hype")], self.texts, self.names)
        self.assertEqual(valid, [])


class TestFallbackWindow(unittest.TestCase):
    def test_window_around_climax_is_hook_to_payoff_and_under_a_minute(self):
        texts = make_story(60)
        slots, speech = estimated_slots(texts)
        climax = 47   # "Sure enough, Tanjiro's flaming blade sliced through Rui's neck." (4th pass)
        w = fallback_short_window(texts, slots, speech, climax_beat=climax)
        self.assertIsNotNone(w)
        self.assertTrue(w["start_beat"] <= climax <= w["end_beat"], w)
        dur = window_seconds(slots, speech, w["start_beat"], w["end_beat"])
        self.assertGreaterEqual(dur, 35.0)
        self.assertLessEqual(dur, 59.0)
        self.assertTrue(hook_stands_alone(texts[w["start_beat"]], character_names(texts)), texts[w["start_beat"]])
        self.assertIn("sliced", texts[w["end_beat"]])     # ends on the payoff line
        self.assertEqual(w["source"], "fallback")
        self.assertTrue(w["title"])
        # deterministic
        self.assertEqual(w, fallback_short_window(texts, slots, speech, climax_beat=climax))

    def test_default_climax_and_too_short_episode(self):
        texts = make_story(60)
        slots, speech = estimated_slots(texts)
        w = fallback_short_window(texts, slots, speech, climax_beat=None)   # ~70% through
        self.assertTrue(w["start_beat"] <= 42 <= w["end_beat"])
        tiny = texts[:4]
        s2, p2 = estimated_slots(tiny)
        self.assertIsNone(fallback_short_window(tiny, s2, p2, climax_beat=2))


class TestParseRecapAnswer(unittest.TestCase):
    def _answer(self, **over):
        texts = make_story(132)   # ~1600 words
        beats = [{"id": i, "text": t, "src_start": 130 + i * 9.0, "src_end": 138 + i * 9.0} for i, t in enumerate(texts)]
        ans = {"title": "His Sword Broke Against a Demon Child, So He Used His Dead Father's Dance",
               "summary": "Tanjiro fought Rui. He won with his father's dance.",
               "beats": beats,
               "acts": [{"title": "The Thread Trap", "start_beat": 0}, {"title": "A Broken Blade", "start_beat": 40},
                        {"title": "Father's Dance", "start_beat": 80}, {"title": "Flames Through the Threads", "start_beat": 110}],
               "climax_beat": 119,
               "short_candidates": [{"start_beat": 108, "end_beat": 119, "hook_beat": 108, "payoff_beat": 119,
                                     "title": "His Sword Snapped, So He Used His Father's Dance"}]}
        ans.update(over)
        return json.dumps(ans)

    def test_accepts_valid_answer(self):
        res = parse_recap_answer(self._answer(), 1420.0, [(25, 119)])
        self.assertEqual(len(res["beats"]), 132)
        self.assertEqual(len(res["acts"]), 4)
        self.assertEqual(res["short_candidates"][0]["start_beat"], 108)
        self.assertEqual(res["climax_beat"], 119)

    def test_rejects_episode_numbers_in_title_and_missing_shorts(self):
        with self.assertRaisesRegex(ValueError, "episode number"):
            parse_recap_answer(self._answer(title="Demon Slayer S1 Ep 19 Tanjiro Fights The Spider Demon Rui"), 1420.0, [])
        with self.assertRaisesRegex(ValueError, "short_candidates"):
            parse_recap_answer(self._answer(short_candidates=[]), 1420.0, [])
        # once the strict attempts are used up, a script without candidates is accepted (fallback window)
        res = parse_recap_answer(self._answer(short_candidates=[]), 1420.0, [], strict_shorts=False)
        self.assertEqual(res["short_candidates"], [])


class TestEpisodePicker(unittest.TestCase):
    CATALOG = {"episodes": [
        {"episode_key": "jujutsu-kaisen-s01e01", "series_id": "jujutsu-kaisen", "season": 1, "episode": 1},
        {"episode_key": "demon-slayer-s01e02", "series_id": "demon-slayer", "season": 1, "episode": 2},
        {"episode_key": "demon-slayer-s01e01", "series_id": "demon-slayer", "season": 1, "episode": 1},
        {"episode_key": "demon-slayer-s02e01", "series_id": "demon-slayer", "season": 2, "episode": 1},
        {"episode_key": "the-avengers-s01e01", "series_id": "the-avengers", "season": 1, "episode": 1},
    ]}

    def test_picks_in_story_order_and_moves_to_next_show(self):
        from anime_catalog import get_next_recap_episode
        pick = lambda done, series=None: (get_next_recap_episode(series, {"completed_episode_recaps": done}, self.CATALOG) or {}).get("episode_key")
        self.assertEqual(pick([]), "demon-slayer-s01e01")
        self.assertEqual(pick(["demon-slayer-s01e01"]), "demon-slayer-s01e02")
        self.assertEqual(pick(["demon-slayer-s01e01", "demon-slayer-s01e02"]), "demon-slayer-s02e01")
        # show finished -> next show; shows outside the registry (a movie) are never picked
        self.assertEqual(pick(["demon-slayer-s01e01", "demon-slayer-s01e02", "demon-slayer-s02e01"]), "jujutsu-kaisen-s01e01")
        self.assertIsNone(pick(["demon-slayer-s01e01", "demon-slayer-s01e02", "demon-slayer-s02e01", "jujutsu-kaisen-s01e01"]))
        self.assertEqual(pick([], "jujutsu-kaisen"), "jujutsu-kaisen-s01e01")
        # legacy funnel progress does not count as an episode recap
        self.assertEqual(get_next_recap_episode(None, {"completed_episodes": ["demon-slayer-s01e01"]}, self.CATALOG)["episode_key"],
                         "demon-slayer-s01e01")

    def test_neighbour_episode(self):
        from anime_catalog import neighbour_episode
        self.assertEqual(neighbour_episode("demon-slayer-s01e01", self.CATALOG)["episode_key"], "demon-slayer-s01e02")
        self.assertEqual(neighbour_episode("demon-slayer-s01e02", self.CATALOG)["episode_key"], "demon-slayer-s01e01")
        self.assertIsNone(neighbour_episode("demon-slayer-s02e01", self.CATALOG))


class TestDerivedShortCadence(unittest.TestCase):
    def test_derived_shorts_do_not_reset_the_clock(self):
        from anime_youtube_uploader import get_latest_upload_time, is_derived_short
        now = datetime(2026, 11, 26, 5, 0, tzinfo=timezone.utc)
        long_at = (now - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")
        short_at = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        hist = {"uploaded_parts": [
            {"episode_key": "demon-slayer-s01e19-recap", "is_full_video": True, "uploaded_at": long_at},
            {"episode_key": "demon-slayer-s01e19-recap", "part": 1, "is_derived_short": True, "uploaded_at": short_at},
        ]}
        self.assertTrue(is_derived_short(hist["uploaded_parts"][1]))
        self.assertTrue(is_derived_short({"is_arc_short": True}))
        self.assertEqual(get_latest_upload_time(hist), now - timedelta(hours=25))


class TestEpisodeChapters(unittest.TestCase):
    def test_act_chapters_exact_and_merged(self):
        from anime_pipeline import _act_chapters
        timeline = [{"start": i * 4.0} for i in range(100)]
        acts = [{"title": "Thread Trap", "start_beat": 0}, {"title": "Too Close", "start_beat": 1},
                {"title": "Broken Blade", "start_beat": 30}, {"title": "Father's Dance", "start_beat": 70}]
        lines = _act_chapters(acts, timeline, 400.0)
        self.assertEqual(lines, ["00:00 Thread Trap", "02:00 Broken Blade", "04:40 Father's Dance"])


if __name__ == "__main__":
    unittest.main()


class TestTwoHalfWriter(unittest.TestCase):
    def _transcript(self):
        segs = [{"start": 130.0 + i * 10, "end": 136.0 + i * 10, "text": "line"} for i in range(60)]
        segs += [{"start": 760.0 + i * 10, "end": 766.0 + i * 10, "text": "line"} for i in range(55)]  # gap 726-760
        return {"duration": 1420.0, "songs": [(25, 119)], "segments": segs}

    def test_split_point_uses_dialogue_gap_near_middle(self):
        from anime_episode_recap import split_point
        self.assertEqual(split_point(self._transcript()), 743.0)

    def test_half_one_hook_may_come_from_later_but_rest_is_in_order(self):
        from anime_episode_recap import parse_half_answer
        texts = make_story(66)
        beats = [{"text": t, "src_start": 140 + i * 9.0, "src_end": 146 + i * 9.0} for i, t in enumerate(texts)]
        beats[0].update(src_start=1100.0, src_end=1108.0)   # cold open shows the climax
        out = parse_half_answer(json.dumps({"beats": beats}), self._transcript(), 1, 743.0)
        self.assertEqual(out[0]["src_start"], 1100.0)
        bad = [dict(b) for b in beats]
        bad[5].update(src_start=1000.0, src_end=1006.0)      # a later beat from the second half is not allowed
        with self.assertRaisesRegex(ValueError, "back in time|past the first half"):
            parse_half_answer(json.dumps({"beats": bad}), self._transcript(), 1, 743.0)

    def test_writer_runs_three_validated_calls(self):
        from unittest.mock import patch
        import anime_episode_recap as er
        tr = self._transcript()
        h1 = [{"text": t, "src_start": 140 + i * 9.0, "src_end": 146 + i * 9.0} for i, t in enumerate(make_story(66))]
        h2 = [{"text": t, "src_start": 770 + i * 9.0, "src_end": 776 + i * 9.0} for i, t in enumerate(make_story(66))]
        h2[0]["text"] = "Meanwhile, Rui wrapped his threads tighter around Nezuko as Tanjiro got back up."
        pack = {"title": "His Sword Broke Against a Demon Child, So He Used His Dead Father's Dance",
                "summary": "Tanjiro fought Rui.", "climax_beat": 101,
                "acts": [{"title": "Thread Trap", "start_beat": 0}, {"title": "Broken Blade", "start_beat": 40},
                         {"title": "Father's Dance", "start_beat": 80}],
                "short_candidates": [{"start_beat": 90, "end_beat": 101, "hook_beat": 90, "payoff_beat": 101,
                                      "title": "His Sword Snapped, So He Used His Father's Dance"}]}
        answers = iter([json.dumps({"beats": h1}), json.dumps({"beats": h2}), json.dumps(pack)])

        def fake_complete(prompt, system="", validator=None, **kw):
            text = next(answers)
            validator(text)
            return text, "fake:model"

        with patch.object(er, "complete", side_effect=fake_complete):
            res = er.write_episode_recap({"episode_key": "demon-slayer-s01e19", "series": "Demon Slayer", "season": 1,
                                          "episode": 19}, tr)
        self.assertEqual(len(res["beats"]), 132)
        self.assertEqual(res["short_candidates"][0]["end_beat"], 101)
        self.assertEqual(len(res["acts"]), 3)
