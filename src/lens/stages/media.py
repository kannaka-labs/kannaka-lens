"""probe, normalise, audio — the three stages everything else stands on.

All three are ffmpeg. No torch, no model, no network. `probe` is the only
essential stage in v1: you cannot say anything true about a video you could
not open.
"""
from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from typing import Any

from ..contract import Context, Need, NotApplicable, Stage

FFPROBE = Need("exe", "ffprobe")
FFMPEG = Need("exe", "ffmpeg")


def _run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-4:]
        raise RuntimeError(f"{cmd[0]} exited {proc.returncode}: {' / '.join(tail)}")
    return proc.stdout


def _rate(value: str | None) -> float | None:
    """avg_frame_rate arrives as '30000/1001', and as '0/0' for audio."""
    if not value or "/" not in value:
        return None
    try:
        f = Fraction(value)
    except (ZeroDivisionError, ValueError):
        return None
    return float(f) if f > 0 else None


def probe(ctx: Context) -> dict[str, Any]:
    raw = _run([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(ctx.source),
    ])
    info = json.loads(raw)
    ctx.out("probe.json").write_text(json.dumps(info, indent=2), "utf-8")

    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
    fmt = info.get("format", {})

    avg = _rate(video.get("avg_frame_rate")) if video else None
    r = _rate(video.get("r_frame_rate")) if video else None
    # r_frame_rate is the highest rate that can represent every timestamp;
    # when it disagrees with the average the file is variable-rate and every
    # later timestamp we compute is a lie until normalise fixes it.
    variable = bool(avg and r and abs(avg - r) > 0.01)

    return {
        "duration": float(fmt["duration"]) if fmt.get("duration") else None,
        "container": fmt.get("format_name"),
        "size_bytes": int(fmt["size"]) if fmt.get("size") else None,
        "has_video": video is not None,
        "has_audio": audio is not None,
        "video": None if not video else {
            "codec": video.get("codec_name"),
            "width": video.get("width"),
            "height": video.get("height"),
            "avg_frame_rate": avg,
            "r_frame_rate": r,
            "variable_frame_rate": variable,
            "pix_fmt": video.get("pix_fmt"),
        },
        "audio": None if not audio else {
            "codec": audio.get("codec_name"),
            "sample_rate": int(audio["sample_rate"]) if audio.get("sample_rate") else None,
            "channels": audio.get("channels"),
        },
    }


def normalise(ctx: Context) -> dict[str, Any]:
    """Constant frame rate, so a frame index and a timestamp mean each other."""
    info = ctx.result("probe")
    if not info.get("has_video"):
        raise NotApplicable("this file has no video stream")
    rate = (info.get("video") or {}).get("avg_frame_rate") or 30.0
    rate = min(rate, 30.0)  # nothing downstream samples faster than 30fps
    dest = ctx.out("normalised.mp4")
    _run([
        "ffmpeg", "-y", "-nostdin", "-v", "error",
        "-i", str(ctx.source),
        "-map", "0:v:0", "-an",
        "-vsync", "cfr", "-r", f"{rate:.6f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        str(dest),
    ])
    if not dest.exists() or dest.stat().st_size == 0:
        raise RuntimeError("ffmpeg reported success but wrote nothing")
    return {"path": str(dest), "fps": round(rate, 6), "size_bytes": dest.stat().st_size}


def audio(ctx: Context) -> dict[str, Any]:
    """16 kHz mono PCM — what both whisper and our own ear features want."""
    info = ctx.result("probe")
    if not info.get("has_audio"):
        raise NotApplicable("this clip is silent -- no audio stream")
    dest = ctx.out("audio.wav")
    _run([
        "ffmpeg", "-y", "-nostdin", "-v", "error",
        "-i", str(ctx.source),
        "-map", "0:a:0", "-vn",
        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        str(dest),
    ])
    if not dest.exists() or dest.stat().st_size == 0:
        raise RuntimeError("ffmpeg reported success but wrote nothing")
    return {"path": str(dest), "sample_rate": 16000, "channels": 1,
            "size_bytes": dest.stat().st_size}


STAGES = [
    Stage("probe", probe, needs=(FFPROBE,), essential=True),
    Stage("normalise", normalise, needs=(FFMPEG,), after=("probe",)),
    Stage("audio", audio, needs=(FFMPEG,), after=("probe",)),
]
