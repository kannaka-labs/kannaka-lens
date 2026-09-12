"""The stage contract — where the one rule is enforced instead of hoped for.

    A missing model degrades a stage. It never breaks the run.

ADR-0001 states that rule, and a rule stated in prose is a rule nobody keeps.
So it lives here as structure: a stage declares what it needs, the runner
checks before calling it, and a stage whose needs are absent is *recorded as
degraded* and stepped over. The run continues and exits zero.

Two things this deliberately refuses to do:

  * degrade silently. A skipped stage writes why it was skipped into the
    project record and prints it. A pipeline that quietly produces less is
    worse than one that stops, because you ship the gap without knowing.
  * let every stage be optional. `essential=True` means the run cannot mean
    anything without it — you cannot analyse a video you could not probe.
    Exactly those stages abort. Everything else degrades.
"""
from __future__ import annotations

import json
import os
import shutil
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

OK = "ok"
DEGRADED = "degraded"
FAILED = "failed"
SKIPPED = "skipped"  # already done in a previous run
NOT_APPLICABLE = "n/a"

#: Statuses that mean "look at this". A silent clip is not one of them.
TROUBLE = (DEGRADED, FAILED)


class StageAborted(Exception):
    """An essential stage could not run. The only thing that stops a run."""


class NotApplicable(Exception):
    """This clip has nothing for this stage to do.

    Distinct from failure on purpose. A video with no audio track is not a
    broken run, and recording it as `failed` would make a perfectly good clip
    indistinguishable from a crashed ffmpeg the next time somebody reads the
    record.
    """


@dataclass(frozen=True)
class Need:
    """Something a stage cannot work without.

    kind "exe"  — an executable on PATH (ffmpeg, ffprobe, a Rust binary)
    kind "py"   — an importable module (faster_whisper)
    kind "path" — a file or directory that must exist (a model directory)
    """

    kind: str
    name: str

    def missing(self) -> str | None:
        """Return a human reason if unmet, else None."""
        if self.kind == "exe":
            if shutil.which(self.name) is None:
                return f"{self.name} is not on PATH"
            return None
        if self.kind == "py":
            import importlib.util

            try:
                found = importlib.util.find_spec(self.name) is not None
            except (ImportError, ValueError):
                found = False
            if not found:
                return f"python module {self.name!r} is not installed"
            return None
        if self.kind == "path":
            if not Path(os.path.expandvars(self.name)).exists():
                return f"{self.name} does not exist"
            return None
        raise ValueError(f"unknown need kind {self.kind!r}")


@dataclass
class Stage:
    name: str
    run: Callable[["Context"], dict[str, Any]]
    needs: Sequence[Need] = field(default_factory=tuple)
    essential: bool = False
    #: Stages whose `ok` output this one reads. If a dependency degraded,
    #: this stage degrades too rather than reading a half-written record.
    after: Sequence[str] = field(default_factory=tuple)


@dataclass
class Context:
    """What a stage is handed. Paths are injected, never hardcoded (ADR-0001 §3)."""

    project: Path
    source: Path
    record: dict[str, Any]
    work: Path

    def out(self, *parts: str) -> Path:
        p = self.work.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def result(self, stage: str) -> dict[str, Any]:
        """The payload of an earlier stage. Raises if it did not succeed."""
        entry = self.record["stages"].get(stage)
        if not entry or entry["status"] not in (OK, SKIPPED):
            raise StageAborted(f"{stage} did not produce output")
        return entry.get("data", {})


def _unmet(stage: Stage, record: dict[str, Any]) -> str | None:
    for need in stage.needs:
        why = need.missing()
        if why:
            return why
    for dep in stage.after:
        entry = record["stages"].get(dep)
        if entry is None:
            return f"{dep} has not run"
        if entry["status"] not in (OK, SKIPPED):
            # Covers degraded, failed and n/a alike: whatever the reason, this
            # stage has no upstream output to read, so it degrades rather than
            # guess. The status is quoted so the record says which it was.
            return f"{dep} was {entry['status']}"
    return None


def run_pipeline(
    stages: Sequence[Stage],
    project: Path,
    source: Path,
    *,
    force: bool = False,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Run every stage that can run. Return the project record.

    Raises StageAborted only when an *essential* stage cannot run.
    """
    project.mkdir(parents=True, exist_ok=True)
    work = project / "work"
    work.mkdir(exist_ok=True)
    record_path = project / "project.json"

    if record_path.exists() and not force:
        record = json.loads(record_path.read_text("utf-8"))
    else:
        record = {"source": str(source), "created": time.time(), "stages": {}}
    record.setdefault("stages", {})

    def flush() -> None:
        # Written after every stage, so a killed run resumes instead of restarting.
        tmp = record_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, indent=2, sort_keys=True), "utf-8")
        tmp.replace(record_path)

    for stage in stages:
        prior = record["stages"].get(stage.name)
        if prior and prior["status"] == OK and not force:
            log(f"  = {stage.name}: already done")
            continue

        why = _unmet(stage, record)
        if why:
            if stage.essential:
                record["stages"][stage.name] = {"status": FAILED, "reason": why}
                flush()
                raise StageAborted(f"{stage.name} is essential and cannot run: {why}")
            record["stages"][stage.name] = {"status": DEGRADED, "reason": why}
            flush()
            log(f"  ~ {stage.name}: degraded -- {why}")
            continue

        started = time.time()
        ctx = Context(project=project, source=source, record=record, work=work)
        try:
            data = stage.run(ctx) or {}
        except NotApplicable as exc:
            record["stages"][stage.name] = {"status": NOT_APPLICABLE, "reason": str(exc)}
            flush()
            log(f"  . {stage.name}: n/a -- {exc}")
            continue
        except Exception as exc:  # a stage's own bug must not take the run down
            detail = f"{type(exc).__name__}: {exc}"
            record["stages"][stage.name] = {
                "status": FAILED,
                "reason": detail,
                "traceback": traceback.format_exc(limit=6),
                "seconds": round(time.time() - started, 3),
            }
            flush()
            if stage.essential:
                raise StageAborted(f"{stage.name} is essential and failed: {detail}") from exc
            log(f"  ! {stage.name}: failed -- {detail}")
            continue

        record["stages"][stage.name] = {
            "status": OK,
            "data": data,
            "seconds": round(time.time() - started, 3),
        }
        flush()
        log(f"  + {stage.name}: {record['stages'][stage.name]['seconds']}s")

    return record


def summarise(record: dict[str, Any]) -> str:
    """One block a human can read. Degradations are named, never totalled away."""
    lines = []
    counts: dict[str, int] = {}
    for name, entry in record["stages"].items():
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    lines.append(" ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "nothing ran")
    for name, entry in sorted(record["stages"].items()):
        if entry["status"] in TROUBLE:
            lines.append(f"  {entry['status']}: {name} -- {entry.get('reason', '?')}")
    return "\n".join(lines)
