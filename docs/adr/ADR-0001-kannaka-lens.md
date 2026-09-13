# ADR-0001 — kannaka-lens: media perception that runs on the hardware we actually have

**Status:** Accepted for v1 scope; the deferred passes remain Proposed
**Date:** 2026-09-12
**Author:** Kannaka / Nick Flach
**Supersedes in intent:** `kannaka-cannon` (a fork of ClipCannon; see §2 — not superseded in code, because none of that code may be carried here)
**Relates to:** kannaka-memory ADR-0008 (video perception, Proposed since 2026-03-01), ADR-0057 (the open-weight brain), the kannaka-radio production stack

## Context

The constellation has wanted eyes on moving pictures for six months and has not had them. The
attempt was `kannaka-cannon`, a fork of ClipCannon: a 22-stage pipeline and ~51 tools covering
scene analysis, source separation, diarization, emotion, voice cloning and lip-sync.

It never ran. Two reasons, and both are facts rather than opinions.

**It needed hardware we do not have.** Surveyed 2026-09-12, every machine in the fleet reports a
virtio/QEMU display adapter. There is no GPU anywhere, and the one Windows box with a physical card
has a broken driver. Only `debain2` can host a torch workload at all, on CPU, with 13 GB free, no
`ffmpeg` installed, and Python 3.13 where `mediapipe` publishes no wheels. The three Oracle boxes are
single-core with 5.5 GB of RAM. Roughly half the stages, and the whole `phase3` group, are
unreachable — not slow, unreachable. The fork's own `pyproject.toml` declares a three-way conflict
between its `ml`, `phase2` and `phase3` extras, so its dependency graph cannot be installed in one
environment, and no code in it handles that.

**And we cannot license it.** 88 of its 127 commits are upstream. 867 of 1,003 files are not ours.
The file named `LICENSE-Apache-2.0-prior` is not Apache-2.0 at all: it is Business Source License
1.1, licensed by Chris Royse, covering "ClipCannon 0.1.0 … (c) 2026 Chris Royse", with a Change Date
of **2030-03-31**. Its Additional Use Grant forbids using the work for a "Video Production Service",
defined to include video analysis, editing, rendering, voice cloning, lip-sync and audio generation
performed for third parties — which is precisely what the fork's README advertises, down to the
billing and quota tools. BUSL grants use, not sublicensing, so the licence we placed on top of it
never had effect over that code.

Meanwhile a great deal of media engineering **does** work here, all of it ours, and none of it was in
the fork: a live Icecast pipeline, a voice cascade with an ffmpeg DSP compiler, a loudness discipline
behind 45 shipped episodes, a drift-free slideshow renderer. It runs on one Windows laptop and one
single-core Oracle box, and nothing in the constellation renders video on Linux today.

And one asset nobody was using: `kannaka-memory/src/eye/` is 1,607 lines of our own Rust that
ffmpeg-decodes video and extracts shot boundaries, optical flow, colour and DCT features with **no
torch, no OpenCV, no mediapipe**. Its design record, ADR-0008, states as principle 4: *"No GPU
required … algorithmic features, not neural inference."* It has zero callers.

## Decision

Build `kannaka-lens` as a new project, from an empty repository, under our own licence.

### 1. CPU-first is the architecture, not a limitation

Every interactive path is algorithmic and runs on a CPU. That is not a compromise forced by poverty;
it is what ADR-0008 specified in March and what `src/eye/` already implements. A model-backed pass may
only ever be **optional, batched, resumable, and shippable off-box**. The rule that follows, and the
one this project is really built around:

> **A missing model degrades a stage. It never breaks the run.**

A pipeline that cannot complete without a GPU is how the last attempt died.

### 2. Clean room. No file, no commit, no docstring

Nothing is copied from `kannaka-cannon`. Not a file, not its history, not a paraphrased docstring.

The *shape* of a video pipeline is a fact about video, not an invention: that you probe a container,
normalise variable frame rate, demux audio, sample frames, detect shots, transcribe speech, and index
the result. Stage names of that kind are re-derived freely.

Four things in the fork are upstream's actual inventions and must be **re-solved independently or not
shipped**: the orchestrator, the highlight scoring function, the anti-hallucination transcription
pass, and the voice-cloning pipeline. Where we want that capability we design our own and say so here.

The old repository is now private. Cleaning up its provenance — the false Apache grant in
`RELICENSING.md`, and two of Royse's bylined research documents published under our org — is a
separate task and is deliberately not tangled into this one.

### 3. One execution target, portable from the first commit

A `python:3.12` container. `debain2` is primary, `groundwave` is the idle overflow node. Fonts, keys
and scratch paths are injected, never hardcoded. The Rust perception work is a static binary.

If two stages need incompatible dependencies, that is **a process boundary with a file contract**,
decided here, not a dependency conflict discovered later. The fork's unbuildable three-way extras
conflict is the failure this rule exists to prevent.

### 4. v1 is what we can already do

| Stage | How |
|---|---|
| probe | `ffprobe` wrapper |
| normalise | `ffmpeg` CFR transcode |
| audio extract | `ffmpeg` demux |
| frame extract | **`src/eye/decode.rs`** — exists |
| visual features | **`src/eye/spatial.rs`** — 192-dim, exists |
| shot detection | **`src/eye/shot.rs`** — exists |
| motion | **`src/eye/motion.rs`** — block-matching optical flow, exists |
| acoustic features | **`src/ear/`** — 296-dim, already in production |
| storyboard | keyframe selection over our shot boundaries |
| transcript | `faster-whisper` small/base int8 on groundwave — CPU-viable; large-v3 is not |
| profanity | wordlist |
| chronemic | timing arithmetic over transcript turns |
| highlights | **our own** scoring over our own features (see §2) |
| finalize | project record + `sqlite-vec` index |

**Deferred, with the reason stated rather than hidden:** source separation, speaker embedding,
emotion embedding, reactions (all torch); mediapipe scene analysis (no wheels, no GPU); voice cloning
and lip-sync (upstream IP and no hardware). Each returns only as a batched off-box pass, if ever.

### 5. Perception lands in the HRM

`Modality::Visual` already exists in the medium's type system. A clip's features become memory, so
what Kannaka sees is recalled the same way as everything else she knows, rather than living in a
side database. This is the reason to build it here rather than adopt a tool.

## Consequences

- Video perception becomes real on the hardware that exists, and `src/eye/` stops being dead code —
  wiring it is the first task, and it makes ADR-0008 true six months after it was written.
- We own every line, so the licence question closes permanently.
- v1 will be less capable than the fork's README claimed and more capable than the fork ever was,
  because the fork's capability was aspirational on this hardware.
- If a GPU ever arrives, the deferred passes attach at defined seams instead of requiring a redesign.
- The proven production pieces (voice cascade, loudness discipline, slideshow renderer) get a Linux
  home, which is the third constraint and the one most likely to be skipped.

## Measured after the fact: what the eye's features are actually worth

The section below deferred the highlight score until the features were in hand. They now are —
`kannaka-memory` PR #945 wired `src/eye/` and measured it, so the answer is recorded here rather
than left open.

**Cost**, warm release build, 2 fps, 320 px wide, 10-second clips:

| stage | cost |
|---|---|
| decode | 0.5–2.1 s per 10 s clip |
| features | ~50 ms per frame |
| total | 150–190 ms per second of video |

**Discriminativeness is split, and this decides the highlight stage.**

- The **spatial 192 works.** Off-diagonal correlation averages 0.49 and separates to 0.05 between a
  navy field and Conway's life.
- The **clip-level temporal 128 does not.** It averages 0.69 and reaches **0.967 between a panning
  SMPTE chart and a mandelbrot zoom**, which look nothing alike. Roughly 76 of its 128 dimensions
  ever carry a value; the rest is fixed padding. Every entry is a clip-level aggregate, so it cannot
  distinguish *when* anything happened.

So the highlight score stands on the spatial band and the per-frame sequence, and does **not** use
the clip-level temporal vector. Filed upstream as a defect rather than designed around silently.

Three real defects surfaced the moment that code got its first caller, which is the argument for
wiring dead code rather than admiring it: 32 of the 192 spatial dimensions were a hardcoded zero in
every video ever encoded; block matching reported *maximum* motion for a static frame, because a flat
block ties at every offset and the search kept the first; and `dominant_colors` lost half of any frame
with vertical structure, because the k-means seed stride lined up with the row period.

## Not decided here

Whether `lens` eventually absorbs the radio's production scripts or calls them. Whether the
transcript pass runs on groundwave or in the qBraid rail. What the highlight score weights *within*
the spatial band and the per-frame sequence — the bands are chosen now, the weighting is not.
