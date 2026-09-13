"""Tests for the perception stages.

The arithmetic here is the dangerous part. `shot_boundaries` are frame indices
at the *analysis* rate, not the video's own rate, and dividing by the wrong one
shifts every keyframe by a factor of 15 on ordinary footage — which looks like a
broken shot detector rather than a unit error, so it is the kind of bug that
gets chased in the wrong place.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lens.contract import DEGRADED, Need, run_pipeline  # noqa: E402
from lens.stages.perceive import STAGES, _shot_times  # noqa: E402


class TestShotTimes(unittest.TestCase):
    def test_boundaries_are_divided_by_the_analysis_rate(self):
        per = {"analysis_fps": 2.0, "duration_secs": 30.0, "shot_boundaries": [4, 10, 21]}
        self.assertEqual(_shot_times(per), [0.0, 2.0, 5.0, 10.5])

    def test_the_videos_own_frame_rate_is_not_used(self):
        # Same boundaries, same clip length, a different analysis rate. If the
        # code reached for the source's 30 fps these would not move.
        slow = _shot_times({"analysis_fps": 2.0, "duration_secs": 30.0, "shot_boundaries": [4]})
        fast = _shot_times({"analysis_fps": 4.0, "duration_secs": 30.0, "shot_boundaries": [4]})
        self.assertEqual(slow, [0.0, 2.0])
        self.assertEqual(fast, [0.0, 1.0])

    def test_the_first_shot_always_starts_at_zero(self):
        self.assertEqual(_shot_times({"analysis_fps": 2.0, "duration_secs": 9.0,
                                      "shot_boundaries": []}), [0.0])

    def test_a_boundary_past_the_end_is_dropped(self):
        # A detector can report a boundary at the final frame; seeking there
        # yields an empty image rather than a keyframe.
        per = {"analysis_fps": 2.0, "duration_secs": 5.0, "shot_boundaries": [2, 10, 99]}
        self.assertEqual(_shot_times(per), [0.0, 1.0])

    def test_a_boundary_at_frame_zero_is_not_duplicated(self):
        per = {"analysis_fps": 2.0, "duration_secs": 5.0, "shot_boundaries": [0, 4]}
        self.assertEqual(_shot_times(per), [0.0, 2.0])

    def test_missing_fields_do_not_raise(self):
        self.assertEqual(_shot_times({}), [0.0])
        self.assertEqual(_shot_times({"shot_boundaries": None}), [0.0])


class TestDegradation(unittest.TestCase):
    """With no `kannaka` on PATH the run must still finish, and say why."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name) / "p"
        self.source = Path(self.tmp.name) / "clip.mp4"
        self.source.write_bytes(b"x")
        self.addCleanup(self.tmp.cleanup)

    def test_perceive_declares_the_binary_it_needs(self):
        perceive = next(s for s in STAGES if s.name == "perceive")
        self.assertIn(Need("exe", "kannaka"), list(perceive.needs))
        self.assertFalse(perceive.essential, "perception must never be able to fail a run")

    def test_storyboard_waits_on_perceive(self):
        story = next(s for s in STAGES if s.name == "storyboard")
        self.assertIn("perceive", story.after)
        self.assertFalse(story.essential)

    def test_a_missing_binary_degrades_both_stages_and_the_run_survives(self):
        import lens.stages.perceive as mod
        original = mod.KANNAKA
        try:
            mod.KANNAKA = Need("exe", "kannaka-that-does-not-exist-9f3a")
            stages = [
                mod.Stage("normalise", lambda ctx: {"path": str(self.source)}),
                mod.Stage("perceive", mod.perceive, needs=(mod.KANNAKA,), after=("normalise",)),
                mod.Stage("storyboard", mod.storyboard, after=("perceive", "normalise")),
            ]
            record = run_pipeline(stages, self.project, self.source, log=lambda _m: None)
        finally:
            mod.KANNAKA = original
        self.assertEqual(record["stages"]["perceive"]["status"], DEGRADED)
        self.assertIn("kannaka-that-does-not-exist-9f3a", record["stages"]["perceive"]["reason"])
        self.assertEqual(record["stages"]["storyboard"]["status"], DEGRADED)
        self.assertIn("perceive", record["stages"]["storyboard"]["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
