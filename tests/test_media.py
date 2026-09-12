"""End-to-end over real files, with ffmpeg generating its own fixtures.

Skipped where ffmpeg is absent rather than mocked. A mocked ffmpeg would prove
that our argument strings are the ones we wrote, which is not the thing in
doubt -- what is in doubt is whether real ffmpeg accepts them and whether the
three shapes of input (normal, silent, audio-only) land in the record honestly.
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

from lens.contract import NOT_APPLICABLE, OK, StageAborted, run_pipeline  # noqa: E402
from lens.stages.media import STAGES  # noqa: E402

HAVE_FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


def _gen(args: list[str]) -> None:
    proc = subprocess.run(["ffmpeg", "-y", "-v", "error", *args],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError("fixture generation failed: " + proc.stderr[-300:])


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg and ffprobe are required")
class TestRealMedia(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        d = Path(cls._tmp.name)
        cls.clip = d / "clip.mp4"
        cls.silent = d / "silent.mp4"
        cls.audio_only = d / "sound.m4a"
        cls.garbage = d / "garbage.mp4"
        _gen(["-f", "lavfi", "-i", "testsrc2=size=160x120:rate=15:duration=1",
              "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
              "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
              "-c:a", "aac", "-shortest", str(cls.clip)])
        _gen(["-f", "lavfi", "-i", "testsrc2=size=160x120:rate=15:duration=1",
              "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
              str(cls.silent)])
        _gen(["-f", "lavfi", "-i", "sine=frequency=330:duration=1",
              "-c:a", "aac", str(cls.audio_only)])
        cls.garbage.write_text("this is not a video", "utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self._proj = tempfile.TemporaryDirectory()
        self.project = Path(self._proj.name) / "p"
        self.addCleanup(self._proj.cleanup)

    def go(self, source):
        return run_pipeline(STAGES, self.project, source, log=lambda _m: None)

    def test_a_normal_clip_runs_every_stage(self):
        record = self.go(self.clip)
        for name in ("probe", "normalise", "audio"):
            self.assertEqual(record["stages"][name]["status"], OK, name)

    def test_probe_reports_what_the_file_actually_contains(self):
        data = self.go(self.clip)["stages"]["probe"]["data"]
        self.assertTrue(data["has_video"])
        self.assertTrue(data["has_audio"])
        self.assertEqual(data["video"]["width"], 160)
        self.assertEqual(data["video"]["height"], 120)
        self.assertAlmostEqual(data["video"]["avg_frame_rate"], 15.0, places=2)
        self.assertFalse(data["video"]["variable_frame_rate"])
        self.assertAlmostEqual(data["duration"], 1.0, delta=0.3)

    def test_normalise_writes_a_constant_rate_file_that_ffprobe_agrees_with(self):
        record = self.go(self.clip)
        out = Path(record["stages"]["normalise"]["data"]["path"])
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 0)
        # Ask ffprobe, not our own record -- checking our own output against our
        # own claim about it would prove nothing.
        raw = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=avg_frame_rate,r_frame_rate,codec_name", "-print_format", "json", str(out)],
            capture_output=True, text=True, check=True).stdout
        s = json.loads(raw)["streams"][0]
        self.assertEqual(s["avg_frame_rate"], s["r_frame_rate"])
        self.assertEqual(s["codec_name"], "h264")

    def test_audio_writes_16k_mono_pcm(self):
        record = self.go(self.clip)
        out = Path(record["stages"]["audio"]["data"]["path"])
        raw = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
             "stream=sample_rate,channels,codec_name", "-print_format", "json", str(out)],
            capture_output=True, text=True, check=True).stdout
        s = json.loads(raw)["streams"][0]
        self.assertEqual(int(s["sample_rate"]), 16000)
        self.assertEqual(int(s["channels"]), 1)
        self.assertEqual(s["codec_name"], "pcm_s16le")

    def test_a_silent_clip_is_not_a_failed_run(self):
        record = self.go(self.silent)
        self.assertEqual(record["stages"]["probe"]["status"], OK)
        self.assertEqual(record["stages"]["normalise"]["status"], OK)
        self.assertEqual(record["stages"]["audio"]["status"], NOT_APPLICABLE)

    def test_an_audio_only_file_still_yields_audio(self):
        record = self.go(self.audio_only)
        self.assertEqual(record["stages"]["normalise"]["status"], NOT_APPLICABLE)
        self.assertEqual(record["stages"]["audio"]["status"], OK)

    def test_a_file_that_is_not_media_aborts_because_probe_is_essential(self):
        with self.assertRaises(StageAborted):
            self.go(self.garbage)


if __name__ == "__main__":
    unittest.main(verbosity=2)
