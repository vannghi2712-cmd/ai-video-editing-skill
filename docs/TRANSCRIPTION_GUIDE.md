# Transcription Guide — Phase 3

> **STATUS: IMPLEMENTED (Phase 3)**
> This guide covers the CPU-first Vietnamese transcription subsystem.
> Phase 4 (scene scoring, edit planning, rendering) is **NOT implemented**.

---

## Overview

The `auto_video_editor transcribe` subsystem provides CPU-first Vietnamese speech-to-text
using WhisperX with forced word alignment. All transcription runs locally — no cloud API,
no authentication token, no data leaves the machine.

**Key properties:**
- Language: Vietnamese (`vi`) only
- Device: CPU only (no CUDA/GPU)
- Alignment: Forced word-level timestamps via wav2vec2
- Word honesty: Timing only set when genuinely aligned — never fabricated
- Cache: Content-addressed (SHA-256 keyed) with manifest ownership tracking

---

## Prerequisites

1. **FFprobe / FFmpeg** — must be on PATH
2. **Python 3.11+** with the base project installed
3. **`.venv-whisperx`** — the isolated ML environment (see setup below)

---

## Environment Setup

### Step 1: Create the ML virtual environment (once)

```powershell
# In D:\auto_edit\ai-video-editing-skill
python -m venv .venv-whisperx
.\.venv-whisperx\Scripts\python.exe -m pip install --upgrade pip
```

### Step 2: Install CPU-only PyTorch (first — before WhisperX)

```powershell
.\.venv-whisperx\Scripts\python.exe -m pip install `
  "torch==2.8.0+cpu" `
  "torchaudio==2.8.0+cpu" `
  "torchvision==0.23.0+cpu" `
  --index-url https://download.pytorch.org/whl/cpu
```

### Step 3: Install WhisperX and project

```powershell
.\.venv-whisperx\Scripts\python.exe -m pip install "whisperx==3.8.6" `
  --extra-index-url https://pypi.org/simple/
.\.venv-whisperx\Scripts\python.exe -m pip install --editable . --no-deps --no-build-isolation
```

### Step 4: Verify

```powershell
.\.venv-whisperx\Scripts\python.exe -m auto_video_editor transcribe doctor
# Expected: exit 0, "Status: READY"
```

---

## CLI Reference

### `transcribe doctor`

Read-only health check. Reports FFprobe, Python, PyTorch, WhisperX, and CUDA status.

```powershell
.\.venv-whisperx\Scripts\python.exe -m auto_video_editor transcribe doctor
```

**Exit codes:**
- `0` — ready for live CPU transcription
- `3` — optional ML dependency missing (expected in base `.venv`)

### `transcribe run`

Transcribe a local media file.

```powershell
.\.venv-whisperx\Scripts\python.exe -m auto_video_editor transcribe run `
  "path\to\video.mov" `
  --output-dir "path\to\output" `
  --language vi `
  --model tiny `
  --device cpu `
  --compute-type int8 `
  --alignment auto
```

**Options:**

| Option | Default | Notes |
|---|---|---|
| `--language` | `vi` | Vietnamese only — other languages rejected |
| `--model` | `small` | Whisper model size: `tiny`, `base`, `small`, `medium`, `large-v3` |
| `--device` | `cpu` | CPU only — `--device cuda` is rejected |
| `--compute-type` | `int8` | `int8` (fastest), `float32`, `float16` |
| `--alignment` | `auto` | `auto` (best-effort), `on` (strict), `off` (skip) |
| `--batch-size` | `4` | ASR batch size |
| `--force` | off | Bypass cache and recompute |
| `--output-dir` | required | Output directory for all artifacts |

**Rejected options (exit 2):**
- `--device cuda`
- `--diarize`

---

## Output Artifacts

All outputs are written to `--output-dir`. Each run produces:

| File | Description |
|---|---|
| `transcript.json` | Schema v1.0.0 — source, engine, segments, alignment, metrics |
| `transcript.srt` | SRT subtitles — sequential cues, UTF-8, non-overlapping |
| `words.json` | Flat word list with `timing_status` (aligned/unaligned/failed) |
| `transcript.raw.json` | Raw WhisperX ASR output — opt-in only via `--include-raw` (default: absent) |
| `manifest.json` | Job identity, cache key, artifact hashes |

---

## Transcript Schema v1.0.0

```json
{
  "schema_version": "1.0.0",
  "source": {
    "path": "...",
    "sha256": "<hex>",
    "duration_seconds": 12.8,
    "size_bytes": 11364878
  },
  "engine": {
    "name": "whisperx",
    "version": "3.8.6",
    "asr_model": "tiny",
    "device": "cpu",
    "compute_type": "int8"
  },
  "request": { ... },
  "result": {
    "segments": [
      {
        "start": 0.0, "end": 2.5, "text": "Xin chào",
        "words": [
          { "text": "Xin", "timing_status": "aligned", "start": 0.0, "end": 0.8, "score": 0.95 },
          { "text": "chào", "timing_status": "aligned", "start": 0.8, "end": 1.5, "score": 0.91 }
        ]
      }
    ],
    "full_text": "Xin chào"
  },
  "alignment": {
    "requested_mode": "auto",
    "actual_status": "aligned",
    "model_id": "jonatasgrosman/wav2vec2-large-xlsr-53-vietnamese",
    "words_total": 2,
    "words_aligned": 2,
    "coverage_fraction": 1.0
  },
  "metrics": { "total_elapsed_seconds": 8.5, "realtime_factor": 0.66 },
  "provenance": { "adapter_version": "1.1.0", "whisperx_version": "3.8.6" }
}
```

### Word Timing Honesty Contract

| `timing_status` | `start`/`end` present? | Meaning |
|---|---|---|
| `aligned` | YES — finite numbers | Backend produced genuine word timestamps |
| `unaligned` | NO | ASR ran, alignment unavailable or not attempted |
| `failed` | NO | Alignment was attempted but failed for this word |

**NEVER** are timestamps fabricated by splitting segment text.

---

## Cache Behavior

Transcription results are cached in `.transcription-cache/` (gitignored) using
a content-addressed key derived from:

- Source file SHA-256
- Normalized config (language, model, device, compute_type, alignment_mode)
- Schema version + adapter version
- WhisperX version
- ASR model fingerprint
- Alignment model fingerprint

A cache **hit** skips the WhisperX backend entirely. Use `--force` to bypass.

**Output directory ownership:** If `--output-dir` is non-empty and was not created
by the current job configuration, the run is rejected. Pass `--force` to overwrite.

---

## Model Cache

Models are downloaded on first use to `model-cache/` (gitignored):

| Model | HF Repository | Cache location (hub layout) | Size (approx) |
|---|---|---|---|
| Whisper tiny | `Systran/faster-whisper-tiny` | `model-cache/models--Systran--faster-whisper-tiny/` | ~75 MB |
| Whisper small | `Systran/faster-whisper-small` | `model-cache/models--Systran--faster-whisper-small/` | ~488 MB |
| Vietnamese wav2vec2 | `nguyenvulebinh/wav2vec2-base-vi-vlsp2020` | `model-cache/models--nguyenvulebinh--wav2vec2-base-vi-vlsp2020/` | ~375 MB |

Each model is pinned to an IMMUTABLE commit SHA (declared in `_PINNED_HF_REVISIONS`).
`snapshot_download(revision=pinned_sha)` ensures only the pinned version is used.
Local snapshot paths are passed directly to constructors — no alias loading.


---

## Privacy

- Source media is **never modified, copied, or uploaded**.
- Source SHA-256 is verified before and after processing.
- Transcript text is **not** stored in committed code, logs, or documentation.
- Model downloads come from public HuggingFace Hub — no authentication required.

---

## Phase 4 Status

> Phase 4 (Vision API scene scoring, edit planning, FFmpeg rendering, CapCut, video-use,
> Cloudflare deployment) is **NOT implemented**. Explicit user authorization is required
> before Phase 4 begins.
