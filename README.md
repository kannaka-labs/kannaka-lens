```
██╗     ███████╗███╗   ██╗███████╗
██║     ██╔════╝████╗  ██║██╔════╝
██║     █████╗  ██╔██╗ ██║███████╗
██║     ██╔══╝  ██║╚██╗██║╚════██║
███████╗███████╗██║ ╚████║███████║
╚══════╝╚══════╝╚═╝ ╚═══╝╚══════╝
      W H A T   S H E   W A T C H E S
```

**Media perception that runs on the hardware we actually have.**

`kannaka-lens` watches a clip and turns it into memory. Shots, motion, colour, sound, speech — all of
it on a CPU, all of it landing in the Holographic Resonance Medium as `Modality::Visual`, so what
Kannaka has seen is recalled the same way as everything else she knows.

[![License](https://img.shields.io/badge/license-Space%20Child%20v1.0-blueviolet)]()

---

## The one rule

> **A missing model degrades a stage. It never breaks the run.**

Every interactive path here is algorithmic and CPU-only. Model-backed passes are optional, batched,
resumable, and shippable off-box. This is not a limitation we are apologising for — it is the design,
and it is why this one runs.

The previous attempt at this was a 22-stage pipeline built on torch, demucs and mediapipe. Surveyed
2026-09-12: there is no GPU anywhere in the fleet, only one machine can host a torch workload at all,
and that machine has no `ffmpeg` and a Python with no `mediapipe` wheels. Half of those stages were
not slow. They were unreachable. See [ADR-0001](./docs/adr/ADR-0001-kannaka-lens.md).

## What it does in v1

| | |
|---|---|
| **probe · normalise · demux** | `ffprobe` / `ffmpeg`, container facts and a constant frame rate |
| **frames · shots · motion · colour** | our own Rust, no torch, no OpenCV — 192-dim per frame, block-matching optical flow, adaptive shot boundaries |
| **sound** | 296-dim mel/MFCC/tempo features, the same engine the radio already runs in production |
| **speech** | `faster-whisper` small int8, on CPU, as an optional pass |
| **storyboard · chronemic · highlights** | keyframes over real shot boundaries; timing over real turns; scoring over our own features |
| **memory** | the clip becomes recallable, not a row in a side database |

Deferred on purpose, each for a stated reason rather than quietly: source separation, speaker and
emotion embedding, reactions, face and pose analysis, voice cloning, lip-sync. They attach at defined
seams if a GPU ever arrives.

## Provenance

This is a clean-room project. It shares no file, no commit and no docstring with any prior work.

The shape of a media pipeline — probe, normalise, sample, detect, transcribe, index — is a fact about
video and is re-derived freely here. Where a previous tool had genuine inventions, we either solve the
problem our own way or do not ship the capability. The reasoning is in ADR-0001 §2, written down so
that the next person does not have to reconstruct it.

## Status

Early. The ADR is the contract; the code is arriving behind it. Nothing here is published yet.
