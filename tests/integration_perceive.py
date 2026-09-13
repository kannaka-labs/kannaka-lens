"""End-to-end against the real `kannaka` binary, with ground truth we built.

Deliberately NOT named `test_*.py`, so the default suite never picks it up and
never *skips* it. `run-tests.sh --integration` runs this, and it **fails** when
the binary is missing rather than skipping — a conditional test that quietly
skips is how a green run comes to prove nothing, which is the thing this repo's
runner exists to prevent.

The fixture is three visually unrelated three-second segments concatenated, so
the cuts are known to be at exactly 3.0 s and 6.0 s. That makes it a real check
on the shot detector AND on the frame-index-to-seconds conversion, which cannot
both be wrong in a way that lands on the right answer.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lens.contract import OK, run_pipeline  # noqa: E402
from lens.stages.media import STAGES as MEDIA  # noqa: E402
from lens.stages.perceive import STAGES as PERCEIVE  # noqa: E402

SEGMENTS = [
    ("a.mp4", "testsrc2=size=640x360:rate=30:duration=3"),
    ("b.mp4", "color=c=navy:size=640x360:rate=30:duration=3"),
    ("c.mp4", "smptebars=size=640x360:rate=30:duration=3"),
]
CUTS_AT = [3.0, 6.0]


def _ffmpeg(args, cwd=None):
    p = subprocess.run(["ffmpeg", "-y", "-v", "error", *args],
                       capture_output=True, text=True, cwd=cwd)
    if p.returncode != 0:
        raise AssertionError("fixture build failed: " + p.stderr[-300:])


class TestRealPerception(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A failure, not a skip. See the module docstring.
        missing = [b for b in ("ffmpeg", "ffprobe", "kannaka") if shutil.which(b) is None]
        if missing:
            raise AssertionError(
                "integration run requires " + ", ".join(missing) + " on PATH. "
                "Build kannaka with `cargo build --release --bin kannaka` and add "
                "target/release to PATH, or run the default suite instead."
            )
        cls._tmp = tempfile.TemporaryDirectory()
        d = Path(cls._tmp.name)
        for name, spec in SEGMENTS:
            _ffmpeg(["-f", "lavfi", "-i", spec, "-c:v", "libx264",
                     "-preset", "ultrafast", "-pix_fmt", "yuv420p", name], cwd=d)
        (d / "list.txt").write_text("".join(f"file '{n}'\n" for n, _ in SEGMENTS), "utf-8")
        _ffmpeg(["-f", "concat", "-safe", "0", "-i", "list.txt",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=9",
                 "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-shortest", "cuts.mp4"], cwd=d)
        cls.clip = d / "cuts.mp4"

        # Perception writes to the HRM by design (ADR-0001 §5); point it at a
        # throwaway store so a test run never lands in anyone's real memory.
        cls._store = tempfile.TemporaryDirectory()
        import os
        os.environ["KANNAKA_DATA_DIR"] = cls._store.name

        cls._proj = tempfile.TemporaryDirectory()
        cls.record = run_pipeline(list(MEDIA) + list(PERCEIVE),
                                  Path(cls._proj.name) / "p", cls.clip,
                                  log=lambda _m: None)

    @classmethod
    def tearDownClass(cls):
        for t in ("_tmp", "_store", "_proj"):
            getattr(cls, t).cleanup()

    def test_every_stage_succeeded(self):
        for name in ("probe", "normalise", "audio", "perceive", "storyboard"):
            self.assertEqual(self.record["stages"][name]["status"], OK, name)

    def test_the_eye_found_both_cuts_where_we_put_them(self):
        per = self.record["stages"]["perceive"]["data"]
        fps = per["analysis_fps"]
        seconds = [round(b / fps, 2) for b in per["shot_boundaries"]]
        self.assertEqual(per["shot_count"], 3)
        self.assertEqual(len(seconds), len(CUTS_AT))
        for got, want in zip(seconds, CUTS_AT):
            self.assertAlmostEqual(got, want, delta=0.6, msg=f"cut at {got}s, built at {want}s")

    def test_one_keyframe_per_shot_and_each_from_its_own_segment(self):
        sb = self.record["stages"]["storyboard"]["data"]
        self.assertEqual(len(sb["keyframes"]), 3)
        sizes = [Path(k["path"]).stat().st_size for k in sb["keyframes"]]
        for s in sizes:
            self.assertGreater(s, 0)
        # The flat navy segment compresses far smaller than the busy ones. If a
        # keyframe were taken from the wrong segment this ordering would break,
        # which is a cheap way to check the seek landed in the right shot.
        self.assertLess(sizes[1], sizes[0] / 2, f"shot 1 should be the flat one: {sizes}")
        self.assertLess(sizes[1], sizes[2] / 2, f"shot 1 should be the flat one: {sizes}")

    def test_the_clip_became_a_memory(self):
        per = self.record["stages"]["perceive"]["data"]
        self.assertTrue(per["memory_id"])
        self.assertEqual(per["tier"], "short-term")
        self.assertEqual(per["spatial_dim"], 192)

    def test_the_perception_json_is_kept_for_later_stages(self):
        f = Path(self.record["source"]).parent
        blobs = list((Path(self._proj.name) / "p" / "work").glob("perception.json"))
        self.assertEqual(len(blobs), 1)
        json.loads(blobs[0].read_text("utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
