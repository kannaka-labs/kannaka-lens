"""Tests for the one rule.

Each test here is written so that removing the behaviour it describes makes it
fail. The interesting ones are the two that pin `essential`: if the runner
ignored that flag in either direction, exactly one of them would break.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lens.contract import (  # noqa: E402
    DEGRADED, FAILED, NOT_APPLICABLE, OK, Context, Need, NotApplicable, Stage,
    StageAborted, run_pipeline, summarise,
)

IMPOSSIBLE = Need("exe", "a-binary-that-will-never-exist-9f3a")


def _stage(name, *, needs=(), essential=False, after=(), boom=False, log=None):
    def run(ctx: Context):
        if log is not None:
            log.append(name)
        if boom:
            raise ValueError("deliberate")
        return {"name": name}
    return Stage(name, run, needs=needs, essential=essential, after=after)


class Quiet:
    def __call__(self, _msg):  # the runner logs; tests do not need to see it
        pass


class TestTheOneRule(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name) / "p"
        self.source = Path(self.tmp.name) / "clip.mp4"
        self.source.write_bytes(b"not really a video")
        self.addCleanup(self.tmp.cleanup)

    def go(self, stages, **kw):
        return run_pipeline(stages, self.project, self.source, log=Quiet(), **kw)

    def test_a_missing_tool_degrades_a_stage_and_the_run_continues(self):
        ran = []
        record = self.go([
            _stage("first", log=ran),
            _stage("needs_a_gpu", needs=(IMPOSSIBLE,)),
            _stage("last", log=ran),
        ])
        self.assertEqual(ran, ["first", "last"], "a degraded stage stopped the run")
        self.assertEqual(record["stages"]["needs_a_gpu"]["status"], DEGRADED)
        self.assertEqual(record["stages"]["last"]["status"], OK)

    def test_a_degradation_names_the_thing_that_was_missing(self):
        # Degrading silently is the failure mode that ships a gap unnoticed.
        record = self.go([_stage("needs_a_gpu", needs=(IMPOSSIBLE,))])
        reason = record["stages"]["needs_a_gpu"]["reason"]
        self.assertIn("a-binary-that-will-never-exist-9f3a", reason)
        self.assertIn("needs_a_gpu", summarise(record))

    def test_an_essential_stage_that_cannot_run_aborts_the_run(self):
        ran = []
        with self.assertRaises(StageAborted) as caught:
            self.go([
                _stage("probe", needs=(IMPOSSIBLE,), essential=True),
                _stage("after", log=ran),
            ])
        self.assertIn("essential", str(caught.exception))
        self.assertEqual(ran, [], "a stage ran after an essential one aborted")

    def test_an_essential_stage_that_raises_aborts_the_run(self):
        with self.assertRaises(StageAborted):
            self.go([_stage("probe", essential=True, boom=True)])
        record = json.loads((self.project / "project.json").read_text("utf-8"))
        self.assertEqual(record["stages"]["probe"]["status"], FAILED)
        self.assertIn("deliberate", record["stages"]["probe"]["reason"])

    def test_a_stage_with_a_bug_does_not_take_the_run_down(self):
        ran = []
        record = self.go([_stage("buggy", boom=True), _stage("last", log=ran)])
        self.assertEqual(record["stages"]["buggy"]["status"], FAILED)
        self.assertIn("traceback", record["stages"]["buggy"])
        self.assertEqual(ran, ["last"])

    def test_a_stage_degrades_rather_than_read_a_dependency_that_did_not_run(self):
        record = self.go([
            _stage("upstream", needs=(IMPOSSIBLE,)),
            _stage("downstream", after=("upstream",)),
        ])
        self.assertEqual(record["stages"]["downstream"]["status"], DEGRADED)
        self.assertIn("upstream", record["stages"]["downstream"]["reason"])

    def test_result_refuses_to_hand_over_output_a_stage_never_produced(self):
        def reader(ctx: Context):
            return ctx.result("never_ran")
        record = self.go([Stage("reader", reader)])
        self.assertEqual(record["stages"]["reader"]["status"], FAILED)
        # Assert the *refusal*, not merely that something went wrong: without
        # this the test also passed on an AttributeError from a missing guard.
        self.assertIn("did not produce output", record["stages"]["reader"]["reason"])

    def test_result_refuses_a_degraded_dependency_rather_than_return_empty(self):
        # The dangerous shape is not a crash, it is {} handed over as though a
        # stage had succeeded with no findings.
        def reader(ctx: Context):
            return {"got": ctx.result("upstream")}
        record = self.go([_stage("upstream", needs=(IMPOSSIBLE,)), Stage("reader", reader)])
        self.assertEqual(record["stages"]["reader"]["status"], FAILED)
        self.assertIn("did not produce output", record["stages"]["reader"]["reason"])


class TestNotApplicable(unittest.TestCase):
    """A silent clip is not a broken run.

    Before this distinction existed, a video with no audio track recorded
    `failed` for the audio stage, which made a perfectly good clip read the
    same as a crashed ffmpeg.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name) / "p"
        self.source = Path(self.tmp.name) / "clip.mp4"
        self.source.write_bytes(b"x")
        self.addCleanup(self.tmp.cleanup)

    def go(self, stages, **kw):
        return run_pipeline(stages, self.project, self.source, log=Quiet(), **kw)

    def test_nothing_to_do_is_not_a_failure(self):
        def silent(ctx):
            raise NotApplicable("this clip is silent")
        record = self.go([Stage("audio", silent)])
        self.assertEqual(record["stages"]["audio"]["status"], NOT_APPLICABLE)
        self.assertNotEqual(record["stages"]["audio"]["status"], FAILED)

    def test_nothing_to_do_carries_its_reason_but_is_not_listed_as_trouble(self):
        def silent(ctx):
            raise NotApplicable("this clip is silent")
        record = self.go([Stage("audio", silent), _stage("later")])
        self.assertIn("silent", record["stages"]["audio"]["reason"])
        summary = summarise(record)
        self.assertNotIn("audio --", summary)

    def test_the_run_continues_past_it(self):
        ran = []
        def silent(ctx):
            raise NotApplicable("nothing here")
        record = self.go([Stage("audio", silent), _stage("later", log=ran)])
        self.assertEqual(ran, ["later"])
        self.assertEqual(record["stages"]["later"]["status"], OK)

    def test_a_stage_that_needed_it_degrades_and_says_why(self):
        def silent(ctx):
            raise NotApplicable("nothing here")
        record = self.go([Stage("audio", silent), _stage("transcript", after=("audio",))])
        self.assertEqual(record["stages"]["transcript"]["status"], DEGRADED)
        self.assertIn("audio", record["stages"]["transcript"]["reason"])

    def test_it_is_retried_on_a_rerun_rather_than_treated_as_done(self):
        # n/a is a fact about this clip, not a completed unit of work; if the
        # clip is replaced in place the next run must look again.
        ran = []
        def silent(ctx):
            raise NotApplicable("nothing here")
        self.go([Stage("audio", silent)])
        record = self.go([_stage("audio", log=ran)])
        self.assertEqual(ran, ["audio"])
        self.assertEqual(record["stages"]["audio"]["status"], OK)


class TestResumability(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name) / "p"
        self.source = Path(self.tmp.name) / "clip.mp4"
        self.source.write_bytes(b"x")
        self.addCleanup(self.tmp.cleanup)

    def go(self, stages, **kw):
        return run_pipeline(stages, self.project, self.source, log=Quiet(), **kw)

    def test_a_finished_stage_is_not_redone(self):
        ran = []
        self.go([_stage("slow", log=ran)])
        self.go([_stage("slow", log=ran)])
        self.assertEqual(ran, ["slow"], "a completed stage ran twice")

    def test_force_redoes_it(self):
        ran = []
        self.go([_stage("slow", log=ran)])
        self.go([_stage("slow", log=ran)], force=True)
        self.assertEqual(ran, ["slow", "slow"])

    def test_a_degraded_stage_is_retried_when_the_tool_arrives(self):
        # The whole point of degrading: install the thing, run again, get it.
        ran = []
        self.go([_stage("optional", needs=(IMPOSSIBLE,))])
        record = self.go([_stage("optional", log=ran)])
        self.assertEqual(ran, ["optional"])
        self.assertEqual(record["stages"]["optional"]["status"], OK)

    def test_the_record_survives_an_abort_midway(self):
        with self.assertRaises(StageAborted):
            self.go([_stage("one"), _stage("two", essential=True, boom=True)])
        record = json.loads((self.project / "project.json").read_text("utf-8"))
        self.assertEqual(record["stages"]["one"]["status"], OK)
        self.assertEqual(record["stages"]["two"]["status"], FAILED)


class TestNeeds(unittest.TestCase):
    def test_an_exe_that_exists_is_met(self):
        self.assertIsNone(Need("exe", sys.executable).missing())

    def test_an_exe_that_does_not_exist_is_unmet(self):
        why = Need("exe", "a-binary-that-will-never-exist-9f3a").missing()
        self.assertIsNotNone(why)
        self.assertIn("PATH", why)

    def test_a_module_that_exists_is_met(self):
        self.assertIsNone(Need("py", "json").missing())

    def test_a_module_that_does_not_exist_is_unmet(self):
        self.assertIsNotNone(Need("py", "no_such_module_9f3a").missing())

    def test_a_path_need_checks_the_filesystem(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(Need("path", d).missing())
            self.assertIsNotNone(Need("path", str(Path(d) / "nope")).missing())

    def test_an_unknown_need_kind_is_a_bug_not_a_silent_pass(self):
        with self.assertRaises(ValueError):
            Need("vibes", "x").missing()


if __name__ == "__main__":
    unittest.main(verbosity=2)
