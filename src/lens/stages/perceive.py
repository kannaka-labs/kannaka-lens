"""perceive and storyboard — where a clip stops being a file and becomes features.

`perceive` shells out to the `kannaka` binary's `watch` verb, which is the Rust
eye from ADR-0008: frames, shot boundaries, block-matching optical flow, colour.
No torch, no OpenCV, no model. If the binary is absent the stage degrades and
the run continues, which is the whole contract.

**It writes to the Holographic Resonance Medium**, deliberately. ADR-0001 §5 is
that a clip becomes memory rather than a row in a side database, and that is the
reason to build this here instead of adopting a tool. Captures land ShortTerm
and are triage-eligible, matching how audio perception already behaves.

One measured caveat, recorded in ADR-0001 and filed as kannaka-memory#948: the
clip-level **temporal** vector is not discriminative — it scores 0.967 between a
panning colour chart and a mandelbrot zoom. Nothing here ranks on it. The
spatial band and the per-shot sequence are what the storyboard uses.
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Any

from ..contract import Context, Need, NotApplicable, Stage

KANNAKA = Need("exe", "kannaka")
FFMPEG = Need("exe", "ffmpeg")

#: Analysis rate. The eye defaults to 2; more frames cost linearly and the shot
#: detector gains little above 4 on ordinary footage.
DEFAULT_FPS = 2.0


def perceive(ctx: Context) -> dict[str, Any]:
    source = ctx.result("normalise")["path"]  # constant-rate, so frame N is at N/fps
    fps = float(os.environ.get("LENS_ANALYSIS_FPS", DEFAULT_FPS))
    proc = subprocess.run(
        ["kannaka", "watch", str(source), "--fps", f"{fps:g}", "--json"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        # The binary says this in words when ffmpeg is missing; pass it through
        # rather than reducing it to an exit code.
        raise RuntimeError("kannaka watch failed: " + " / ".join(tail))
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"kannaka watch returned unparseable output: {exc}") from exc

    ctx.out("perception.json").write_text(json.dumps(data, indent=2), "utf-8")
    return {
        "memory_id": data.get("id"),
        "tier": data.get("tier"),
        "duration_secs": data.get("duration_secs"),
        "frame_count": data.get("frame_count"),
        "analysis_fps": data.get("analysis_fps"),
        "shot_count": data.get("shot_count"),
        "shot_boundaries": data.get("shot_boundaries", []),
        "motion": data.get("motion", {}),
        "mean_brightness": data.get("mean_brightness"),
        "mean_contrast": data.get("mean_contrast"),
        "visual_tempo_bpm": data.get("visual_tempo_bpm"),
        "dominant_colors": data.get("dominant_colors", []),
        "tags": data.get("tags", []),
        "spatial_dim": data.get("spatial_dim"),
        # Recorded so the record is complete, and explicitly not ranked on.
        "temporal_dim": data.get("temporal_dim"),
    }


def _shot_times(per: dict[str, Any]) -> list[float]:
    """Shot start times in seconds.

    `shot_boundaries` are frame indices at `analysis_fps`, not at the video's
    own rate. Dividing by the wrong one silently shifts every keyframe, which is
    the sort of error that looks like a bad shot detector.
    """
    fps = per.get("analysis_fps") or DEFAULT_FPS
    duration = per.get("duration_secs") or 0.0
    times = [0.0]
    for b in per.get("shot_boundaries") or []:
        t = float(b) / float(fps)
        if 0.0 < t < duration:
            times.append(t)
    return times


def storyboard(ctx: Context) -> dict[str, Any]:
    """One keyframe per shot, taken at a real boundary rather than a fixed interval."""
    per = ctx.result("perceive")
    source = ctx.result("normalise")["path"]
    times = _shot_times(per)
    if not times:
        raise NotApplicable("no shots were detected to storyboard")

    frames = []
    for n, t in enumerate(times):
        # Seek a little past the cut: the boundary frame itself is often the
        # blended or black frame of the transition.
        at = t + 0.1 if n else 0.0
        dest = ctx.out("storyboard", f"shot-{n:03d}.jpg")
        proc = subprocess.run(
            ["ffmpeg", "-y", "-nostdin", "-v", "error",
             "-ss", f"{at:.3f}", "-i", str(source),
             "-frames:v", "1", "-q:v", "3", str(dest)],
            capture_output=True, text=True,
        )
        if proc.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
            frames.append({"shot": n, "at_secs": round(at, 3), "path": str(dest)})

    if not frames:
        raise RuntimeError("ffmpeg produced no keyframes for any shot")
    return {"shots": len(times), "keyframes": frames}


STAGES = [
    Stage("perceive", perceive, needs=(KANNAKA,), after=("normalise",)),
    Stage("storyboard", storyboard, needs=(FFMPEG,), after=("perceive", "normalise")),
]
