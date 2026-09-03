# Architecture Audit â€” ai-video-editing-skill

> **Audit Date:** 2026-09-02T13:36:44+07:00
> **Auditor:** Phase 1 Automated Agent
> **Repository:** [znyupup/ai-video-editing-skill](https://github.com/znyupup/ai-video-editing-skill)
> **Fork:** [vannghi2712-cmd/ai-video-editing-skill](https://github.com/vannghi2712-cmd/ai-video-editing-skill)
> **Branch:** `feat/automated-short-form-editor`
> **Upstream Commit:** `b6429ab550a64c595dc68d42c47cf2b489a50619` (main)
> **License:** MIT (Copyright 2025 nyxç ”ç©¶æ‰€)
> **Version:** v1.1.0 (stable)

---

## 1. Upstream Overview

| Field | Value |
|---|---|
| **Upstream URL** | `https://github.com/znyupup/ai-video-editing-skill` |
| **Fork URL** | `https://github.com/vannghi2712-cmd/ai-video-editing-skill` |
| **Default Branch** | `main` |
| **Audited Commit SHA** | `b6429ab550a64c595dc68d42c47cf2b489a50619` |
| **Upstream Branches** | `main`, `add-skill-vlog-auto-edit` |
| **License** | MIT |
| **Author** | nyxç ”ç©¶æ‰€ (GitHub @znyupup) |
| **Tags/Version** | v1.1.0 (from SKILL.md YAML frontmatter) |
| **Tracked Files** | 10 files (see Section 4) |
| **Tests Directory** | None â€” `NO_UPSTREAM_AUTOMATED_TESTS_FOUND` |
| **CI/CD** | None detected |
| **Package Manager** | None (no `requirements.txt`, `pyproject.toml`, `setup.py`, or lock files) |

---

## 2. Current Architecture

The repository is an **AI Agent Skill specification**, not a standalone application. It provides:

1. **SKILL.md** â€” A 953-line executable specification document that AI coding agents (Claude Code, OpenClaw, Hermes, GPT-based agents) read and follow as procedural instructions. Contains embedded Python code snippets, bash commands, JSON schemas, and 36 production pitfalls.

2. **Two utility scripts** â€” Standalone Python CLI tools (`gen_dashboard.py`, `gen_storyboard.py`) that generate browser-viewable HTML previews from pipeline artifacts.

3. **Example data** â€” JSON fixtures and a project structure guide demonstrating the expected data contracts between pipeline stages.

4. **A prompt template** â€” LLM prompt for generating edit plans from analyzed footage.

**Key Design Principles:**
- Zero NLE dependency (explicitly rejects CapCut/Jianying, MoviePy, ImageMagick)
- FFmpeg as the sole video processing engine (subprocess calls)
- Dual ASR support: OpenAI Whisper (primary) or Alibaba FunASR (alternative)
- Vision understanding via OpenAI-compatible multimodal API endpoints
- Advisory preprocessing (LLM retains final override authority)
- Speech boundary safety via programmatic post-LLM validation

---

## 3. Current Pipeline

The upstream defines a 7-stage workflow (with sub-stages):

```
Stage 1: Footage Inventory
    â””â”€ ffprobe batch scan â†’ clip count, duration, resolution, codec
         â”‚
Stage 2: Reference Research (Optional)
    â””â”€ yt-dlp download â†’ whisper transcribe â†’ scenedetect â†’ visual API analysis
         â”‚
Stage 3: Three-Dimensional Material Analysis
    â”œâ”€ Audio: ffmpeg extract 16kHz mono WAV â†’ Whisper/FunASR transcribe
    â”œâ”€ Volume: ffmpeg volumedetect â†’ mean/max dB classification
    â””â”€ Visual: ffmpeg frame extraction (720p) â†’ Vision API (base64 JPEG)
         â”‚
Stage 3.5: Advisory Preprocessing
    â”œâ”€ Recording cue detection (first/last 3s)
    â”œâ”€ Repeat speech detection (difflib, threshold â‰¥ 0.6)
    â”œâ”€ Camera shake / trailing silence trim detection
    â””â”€ Mode: strict | normal | loose
         â”‚
Stage 4: LLM Narrative Planning
    â””â”€ Prompt template + analysis data â†’ edit_plan.json
         â”‚
Stage 4+: Visual Preview
    â”œâ”€ gen_dashboard.py â†’ dashboard.html (footage overview + QC grid)
    â””â”€ gen_storyboard.py â†’ storyboard/index.html (timeline + keyframes)
         â”‚
Stage 4.5: Speech Cut Validation & Auto-Fix
    â””â”€ validate_speech() â†’ fix_speech_cuts() â†’ verify assertion
         â”‚
Stage 5: FFmpeg Rendering
    â”œâ”€ Per-segment: scale/pad to 1080p, H.264 CRF 18, AAC 128k, 30fps
    â”œâ”€ Highlight montage: 6-10 fast cuts (0.5-1s each, muted)
    â”œâ”€ Title overlay: Pillow RGBA PNG â†’ ffmpeg overlay (3s, no shortest=1)
    â”œâ”€ Concat: demuxer concat copy (not xfade chains)
    â””â”€ BGM: amix with volume ducking (8-12% under speech)
```

---

## 4. File Responsibility Map

| File | Responsibility | Type | Evidence | Reuse Decision |
|---|---|---|---|---|
| `SKILL.md` | Master workflow specification; 7-stage pipeline instructions, embedded code, 36 pitfalls | Agent Knowledge | 953 lines, v1.1.0, YAML frontmatter | **Keep** â€” Primary reference document |
| `README.md` | Human-oriented project overview, 4-step workflow summary, supported agents | Documentation | 239 lines, links to SKILL.md | **Keep** â€” Onboarding reference |
| `scripts/gen_dashboard.py` | Standalone HTML dashboard generator (footage overview + QC frames) | Executable (Python) | 769 lines, stdlib-only, argparse CLI | **Extend** â€” Integrate as review-mode output |
| `scripts/gen_storyboard.py` | Standalone HTML storyboard generator (timeline + keyframes) | Executable (Python) | 302 lines, stdlib-only, argparse CLI | **Extend** â€” Integrate as review-mode output |
| `templates/edit_plan_prompt.md` | LLM prompt template for edit plan generation | Template | 93 lines, 7 template variables | **Refactor** â€” Adapt per content profile |
| `examples/clip_analysis.json` | Reference output from Stage 3+3.5 (5 clips, Harbin winter footage) | Fixture | 182 lines, JSON, Chinese transcripts | **Keep** â€” Schema validation fixture |
| `examples/edit_plan.json` | Reference output from Stage 4 (4 narrative sections) | Fixture | 67 lines, JSON, Chinese text | **Keep** â€” Schema validation fixture |
| `examples/project_structure.md` | Directory layout and storage benchmarks | Documentation | 85 lines | **Keep** â€” Structural reference |
| `.gitignore` | Git ignore rules for media, caches, agent configs | Configuration | 40 lines | **Extend** â€” Add outputs/, caches, models |
| `LICENSE` | MIT license | Legal | 22 lines, Copyright 2025 | **Keep** â€” Permissive for modification |

### Baseline Checks

| Command | Exit Code | Classification | Result |
|---|---|---|---|
| `python -m py_compile scripts/gen_dashboard.py` | 0 | `STATIC_EXAMPLE_VALIDATION` | Syntax valid |
| `python -m py_compile scripts/gen_storyboard.py` | 0 | `STATIC_EXAMPLE_VALIDATION` | Syntax valid |
| `git ls-files` | 0 | Inventory | 10 tracked files, 0 untracked |

`NO_UPSTREAM_AUTOMATED_TESTS_FOUND` â€” No `tests/` directory, no test runner configuration, no CI/CD workflows.

---

## 5. Reusable Components

| Component | Source | Decision | Rationale |
|---|---|---|---|
| `gen_dashboard.py` | `scripts/` | **Extend** | Production-ready HTML generator; stdlib-only; adaptable for review-mode HTML storyboard output. Needs profile-aware theming. |
| `gen_storyboard.py` | `scripts/` | **Extend** | Clean timeline visualization; stdlib-only. Needs profile-aware section labels. |
| `edit_plan_prompt.md` | `templates/` | **Refactor** | Travel vlog-specific prompt. Must be parameterized per content profile (food_review, lifestyle_vlog, affiliate_fast). |
| Speech validation logic | `SKILL.md` (Stage 4.5) | **Extract & Formalize** | `validate_speech()` and `fix_speech_cuts()` â€” proven algorithms with margin tolerance. Must be extracted into typed Python module with tests. |
| Advisory preprocessing | `SKILL.md` (Stage 3.5) | **Extract & Formalize** | Recording cue detection, repeat detection, trim point detection. Must be extracted and extended for Vietnamese language cues. |
| `clip_analysis.json` schema | `examples/` | **Formalize** | JSON schema with visual, audio, and preprocessing fields. Must become a versioned Pydantic model. |
| `edit_plan.json` schema | `examples/` | **Formalize** | JSON schema with structure, clips, BGM, notes. Must become a versioned Pydantic model with duration math validation. |
| FFmpeg encoding presets | `SKILL.md` (Stage 5) | **Keep** | H.264 CRF 18, AAC 128k, 30fps, 1080p scale/pad, faststart â€” production-proven settings. |
| 36 FFmpeg pitfalls | `SKILL.md` | **Keep** | Hard-won operational knowledge. Must inform renderer implementation constraints. |
| FunASR timestamp aggregation | `SKILL.md` (Stage 3) | **Needs Verification** | Character-to-sentence aggregation by punctuation. Requires verification against actual FunASR API before use. |
| OpenAI Whisper integration | `SKILL.md` (Stage 3) | **Do Not Use Directly** | Uses `openai-whisper`, but our pipeline specifies WhisperX/faster-whisper. Different API contract. |
| CapCut integration | `SKILL.md` (Pitfall 1) | **Do Not Use** | Explicitly documented as broken (Jianying v10.4+ encryption). pyCapCut contract must be independently verified in Phase 7. |
| Vision API calls | `SKILL.md` (Stage 3c) | **Needs Verification** | Uses `urllib.request` with OpenAI-compatible endpoint. Must verify against actual provider chosen for our pipeline. |

---

## 6. Verified Contracts

These findings are backed by code inspection or command output:

| Contract | Version | Evidence |
|---|---|---|
| **`clip_analysis.json` schema** | Implicit v1 | `examples/clip_analysis.json`: 5 clips with `filename`, `duration`, `resolution`, `visual[]`, `audio{}`, `preprocessing{}` |
| **`edit_plan.json` schema** | Implicit v1 | `examples/edit_plan.json`: `title`, `structure[].section`, `structure[].clips[].{file,start,end,note,subtitle}`, `bgm_suggestion`, `editing_notes` |
| **`gen_dashboard.py` CLI** | v1 | argparse: `--analysis`, `--plan`, `--footage`, `--out`, `--video`, `--skip-thumbs`, `--skip-qc`, `--qc-interval`. Python stdlib-only. `py_compile` pass. |
| **`gen_storyboard.py` CLI** | v1 | argparse: `--plan`, `--footage`, `--out`, `--skip-frames`. Python stdlib-only. `py_compile` pass. |
| **FFmpeg filters** | 8.1.1 | `ass`, `subtitles`, `overlay`, `volumedetect`, `scale`, `pad`, `concat`, `amix` â€” all confirmed available |
| **Speech validation algorithm** | v1 | `validate_speech()` + `fix_speech_cuts()` in SKILL.md: margin=0.3s, start adjust: `speech.start - 0.1s`, end adjust: `speech.end + 0.2s` |
| **.gitignore coverage** | v1 | Media extensions (mp4, mov, wav, mp3, m4a), working directories, Python caches, model weights (.pt) |

---

## 7. Unverified Assumptions

> These external contracts are mentioned in requirements but have NOT been verified against installed packages or live APIs.

| Assumption | Status | Required By | Risk |
|---|---|---|---|
| **WhisperX** package interface | **UNVERIFIED** | Phase 3 | Package API may differ from openai-whisper. Word-level timestamps, VAD integration, alignment behavior need live verification. |
| **faster-whisper** capabilities | **UNVERIFIED** | Phase 3 | Must verify: language=vi support, word timestamps, compute types, CUDA/CPU modes. |
| **Vision API schema** (Zhipu/GPT-4o/Qwen-VL) | **UNVERIFIED** | Phase 4 | OpenAI-compatible Chat Completions format assumed. Provider-specific rate limits, error codes, and response schemas not verified. |
| **pyCapCut** official contract | **UNVERIFIED** | Phase 7 | Upstream explicitly warns CapCut v10.4+ encrypts project files. pyCapCut compatibility must be independently verified. |
| **video-use** repo/commit | **UNVERIFIED** | Phase 8 | Not referenced in upstream. Must locate exact package, version, and API before benchmarking. |
| **FunASR API stability** | **UNVERIFIED** | Phase 3 | Upstream documents FunASR v1.x API. Current API may have changed. `modelscope` download availability varies by region. |
| **ElevenLabs** credentials | **UNVERIFIED** | Phase 8 | Required for video-use benchmark. No credentials configured. |
| **Vietnamese ASR quality** | **UNVERIFIED** | Phase 3 | Upstream tests Chinese only. Vietnamese (`language=vi`) support in WhisperX/faster-whisper needs validation. |
| **ASS subtitle Vietnamese glyphs** | **UNVERIFIED** | Phase 6 | libass is compiled in FFmpeg, but font availability for Vietnamese diacritics on this Windows system not verified. |

---

## 8. Proposed Future Architecture

> **PROPOSED â€” NOT IMPLEMENTED**
>
> This section describes the target architecture for Phases 2-8. No code for this design exists yet.

```
auto_video_editor/                    # Python package (new)
â”œâ”€â”€ __main__.py                       # CLI entry point (click/typer)
â”œâ”€â”€ cli/
â”‚   â”œâ”€â”€ doctor.py                     # Environment validation
â”‚   â”œâ”€â”€ analyze.py                    # Pipeline: inspect â†’ normalize â†’ detect â†’ transcribe â†’ keyframes â†’ analyze
â”‚   â”œâ”€â”€ plan.py                       # Pipeline: analyze + generate edit plan + review mode
â”‚   â”œâ”€â”€ render.py                     # Pipeline: FFmpeg render + QA
â”‚   â”œâ”€â”€ run.py                        # Full pipeline orchestrator
â”‚   â””â”€â”€ compare.py                    # Benchmark against video-use
â”œâ”€â”€ core/
â”‚   â”œâ”€â”€ inspector.py                  # ffprobe metadata extraction + SHA-256
â”‚   â”œâ”€â”€ normalizer.py                 # Derived working copy generation
â”‚   â”œâ”€â”€ scene_detector.py             # Scene detection interface
â”‚   â”œâ”€â”€ transcriber.py                # ASR adapter (WhisperX/faster-whisper)
â”‚   â”œâ”€â”€ keyframe_extractor.py         # Adaptive frame sampling
â”‚   â”œâ”€â”€ scene_analyzer.py             # Technical + semantic analysis
â”‚   â”œâ”€â”€ speech_guard.py               # Speech boundary validation (from upstream)
â”‚   â”œâ”€â”€ preprocessor.py               # Advisory preprocessing (from upstream)
â”‚   â””â”€â”€ planner.py                    # Edit plan generation
â”œâ”€â”€ render/
â”‚   â”œâ”€â”€ ffmpeg_renderer.py            # FFmpeg command builder + executor
â”‚   â”œâ”€â”€ subtitle_generator.py         # ASS subtitle generation (TikTok safe zones)
â”‚   â””â”€â”€ qa_checker.py                 # Automated QA verification
â”œâ”€â”€ profiles/
â”‚   â”œâ”€â”€ schema.py                     # Profile Pydantic models
â”‚   â”œâ”€â”€ food_review.yaml              # @luenguynnn profile
â”‚   â”œâ”€â”€ lifestyle_vlog.yaml           # @_bylue profile
â”‚   â””â”€â”€ affiliate_fast.yaml           # @iz_lue profile
â”œâ”€â”€ models/
â”‚   â”œâ”€â”€ schemas.py                    # Versioned data models (clip analysis, edit plan, etc.)
â”‚   â””â”€â”€ cache.py                      # Cache contract implementation
â”œâ”€â”€ integrations/
â”‚   â”œâ”€â”€ capcut_export.py              # Optional CapCut draft export
â”‚   â””â”€â”€ video_use_benchmark.py        # Comparison pipeline
â”œâ”€â”€ review/
â”‚   â”œâ”€â”€ storyboard.py                 # HTML storyboard (from upstream gen_storyboard.py)
â”‚   â””â”€â”€ dashboard.py                  # HTML dashboard (from upstream gen_dashboard.py)
â””â”€â”€ utils/
    â”œâ”€â”€ logging.py                    # Command log with timestamps
    â”œâ”€â”€ hashing.py                    # SHA-256 source identity
    â””â”€â”€ unicode.py                    # Vietnamese text handling

docs/
â”œâ”€â”€ ARCHITECTURE.md                   # This document
â”œâ”€â”€ PHASE_1_PREFLIGHT.md              # Environment audit evidence
â””â”€â”€ PROFILE_GUIDE.md                  # Content profile documentation (Phase 2)

profiles/                             # Profile YAML configs (Phase 2)
tests/                                # Test suite (Phase 2+)
outputs/<project_id>/                 # Generated project outputs
```

**CLI Exit Codes:**
- `0` â€” Success
- `2` â€” Invalid user input
- `3` â€” Missing dependency
- `4` â€” Review approval required (review mode)
- `5` â€” Processing failure
- `6` â€” QA failure

---

## 9. Risks

| Risk | Severity | Phase | Mitigation |
|---|---|---|---|
| **CPU-only STT** | Medium | 3 | No CUDA GPU detected. WhisperX/faster-whisper on CPU will be slow for long footage. Consider `compute_type=int8` or FunASR as fallback. |
| **Vision API costs** | Medium | 4 | Frame analysis via commercial APIs (GPT-4o, Qwen-VL) incurs per-call costs. Free tier (Zhipu GLM-4.6V-Flash) may have rate limits. |
| **Vietnamese Unicode** | Low | 3, 6 | Upstream only tests Chinese. Vietnamese diacritics (Äƒ, Æ¡, Æ°, á»‡, etc.) must be validated through ASR, subtitles, and rendering. |
| **Raw footage protection** | Critical | All | Pipeline must never modify, rename, or delete raw footage. SHA-256 verification at every stage boundary. |
| **CapCut encryption** | High | 7 | Upstream confirms Jianying v10.4+ encrypts project files. pyCapCut integration may be impossible. Must verify independently. |
| **video-use availability** | Medium | 8 | Package not referenced in upstream. Must locate, verify contract, and confirm ElevenLabs dependency. |
| **ASR hallucination** | Medium | 3 | Whisper hallucinates on pure ambient audio. Must implement VAD threshold filtering (mean_volume < -40dB). |
| **FFmpeg audio drift** | Medium | 6 | `atempo` causes 0.4-0.8s drift per segment. Must verify `|v_dur - a_dur| < 0.05s` per segment (Pitfall 28). |
| **No upstream tests** | Medium | All | No existing test suite. All new functionality must include tests from Phase 2 onward. |
| **Font availability** | Low | 6 | ASS subtitle rendering requires fonts supporting Vietnamese. Windows typically has Arial/Segoe UI which cover Vietnamese, but must verify. |

---

## 10. Phase 2 Entry Criteria

Phase 2 (Content Profile Configuration) may begin ONLY when ALL of the following are satisfied:

- [x] Phase 1 status is **PASS**
- [x] Fork cloned with verified origin/upstream remotes
- [x] Feature branch `feat/automated-short-form-editor` active and clean
- [x] `docs/PHASE_1_PREFLIGHT.md` committed and pushed
- [x] `docs/ARCHITECTURE.md` committed and pushed
- [x] Working tree is clean (no uncommitted changes)
- [x] GitHub authentication verified
- [x] **Explicit user authorization received** âœ… (2026-09-02)

**Phase 2 is COMPLETE. Phase 3 is LOCKED pending explicit user authorization.**

---

## Phase 2 Implemented State

> **Added:** 2026-09-02T14:35:00+07:00
> **Commit:** see Phase 2 final report

### New Files Created

| Path | Type | Purpose |
|---|---|---|
| `schemas/content_profile.schema.json` | JSON Schema | v1.0.0 schema with `additionalProperties: false` |
| `configs/profiles/base.json` | Config | Generic defaults â€” no account-specific data |
| `configs/profiles/food_review.json` | Config | 45s food review â€” @luenguynnn |
| `configs/profiles/lifestyle_vlog.json` | Config | 90s lifestyle vlog â€” @_bylue |
| `configs/profiles/affiliate_fast.json` | Config | 30s affiliate fast â€” @iz_lue |
| `src/auto_video_editor/__init__.py` | Python | Package init (v0.1.0) |
| `src/auto_video_editor/__main__.py` | Python | Module entry point |
| `src/auto_video_editor/cli.py` | Python | argparse CLI (profiles list/show/validate) |
| `src/auto_video_editor/exceptions.py` | Python | Domain exception hierarchy with exit codes |
| `src/auto_video_editor/profiles/__init__.py` | Python | Sub-package init |
| `src/auto_video_editor/profiles/loader.py` | Python | Path-safe load, deep merge, model construction |
| `src/auto_video_editor/profiles/models.py` | Python | Immutable frozen dataclasses |
| `src/auto_video_editor/profiles/validation.py` | Python | Business-rule validation |
| `tests/__init__.py` | Python | Test package init |
| `tests/test_profile_loader.py` | Python | 30 loader/merge/unicode/safety tests |
| `tests/test_profile_validation.py` | Python | 35 validation + no-hardcoding tests |
| `tests/test_profile_cli.py` | Python | 29 CLI tests via subprocess |
| `docs/PROFILE_GUIDE.md` | Docs | Complete profile system guide |
| `docs/PROGRESS.md` | Docs | Phase progress log |

### Validated Profile Invariants (Corrected â€” Phase 2 Correction Commit)

| Profile | Duration | Min | Max | Stages | Weight Sum | Weights Valid |
|---|---|---|---|---|---|---|
| `food_review` | 45s | 30s | 60s | 5 | 100 âœ… | All integers in [0,100] âœ… |
| `lifestyle_vlog` | 45s | 30s | 60s | 5 | 100 âœ… | All integers in [0,100] âœ… |
| `affiliate_fast` | 40s | 25s | 50s | 5 | 100 âœ… | All integers in [0,100] âœ… |

> **Note:** Previous Phase 2 commit `303fd49` had `lifestyle_vlog` at 90s (no bounds) and `affiliate_fast` at 30s (no bounds) with incorrect stage names and weight keys. These were corrected in the Phase 2 Correction commit. See `docs/PROGRESS.md` for the full deviation table.

### Merge Contract (Implemented)

- JSON **objects** merge recursively â€” child keys override, base keys preserved
- **Scalars** (string, number, bool) â€” child replaces base
- **Arrays** â€” child replaces entirely (no concatenation)
- No `null` values anywhere in merged document
- Unknown top-level keys rejected after merge

### Security Constraints (Implemented)

- Profile IDs validated against `^[a-z][a-z0-9_]{1,63}$` before any filesystem access
- Path separators, `..`, `.`-prefix, and absolute paths all rejected
- Symlinks escaping `configs/profiles/` root rejected
- No `eval()`, `exec()`, or dynamic imports anywhere in package
- All profiles returned as **immutable frozen dataclasses** (no shared mutable state)
- No hardcoded profile IDs or account handles in core modules (verified by static test)
- Pure Python standard library â€” no external runtime dependencies

### Test Results

```
Ran 94 tests in ~7s
OK (0 failures, 0 errors, 0 skips)
```

### Phase 3 Entry Criteria

Phase 3 (Inspect & Normalize) may begin ONLY when ALL of the following are satisfied:

- [x] Phase 2 status is **PASS**
- [x] All 94 Phase 2 tests pass
- [x] `python -m auto_video_editor profiles validate --all` exits 0
- [x] Phase 2 commit pushed and remote SHA verified
- [x] Working tree is clean
- [ ] **Explicit user authorization received** â† REQUIRED

**Phase 3 is LOCKED pending explicit user authorization.**

---

## Phase 3 — CPU-first Vietnamese Transcription (IMPLEMENTED)

**Status:** COMPLETE — 2026-09-03

### Package Structure Added

```
src/auto_video_editor/transcription/
+-- __init__.py           # Public API, SCHEMA_VERSION, ADAPTER_VERSION
+-- config.py             # TranscriptionConfig (frozen, validates at construction)
+-- models.py             # TranscriptWord, TranscriptSegment, TranscriptResult
+-- media.py              # MediaProbe (ffprobe wrapper, SHA-256, safety checks)
+-- cache.py              # TranscriptCache (content-addressed, atomic writes)
+-- exporters.py          # SRT, words.json, transcript.json exporters
+-- service.py            # TranscriptionService (orchestrates all components)
+-- backends/
¦   +-- __init__.py       # BackendProtocol, BackendUnavailableError
¦   +-- whisperx_backend.py  # WhisperX adapter (LAZY IMPORT)
+-- cli_commands.py       # transcribe doctor / run (exit 3 in base venv)
```

### Runtime Architecture

```
transcribe run
  +-- TranscriptionService.run()
        +-- probe_media()          -- ffprobe + SHA-256
        +-- CacheIdentity.job_id() -- deterministic 32-char hex
        +-- TranscriptCache.get()  -- cache check
        ¦   (cache miss) ?
        +-- WhisperXBackend.transcribe()  -- lazy import whisperx
        +-- WhisperXBackend.align()       -- lazy import whisperx
        +-- TranscriptCache.put()         -- atomic write
        +-- populate_output_dir()
        +-- verify_source_integrity()     -- SHA-256 after
```

### Invariants

| Invariant | Value |
|---|---|
| Language | Vietnamese (i) only |
| Device | CPU only — CUDA rejected at config time |
| Diarization | Disabled by policy |
| Translation | Disabled by policy |
| Word timing | NEVER fabricated — timing_status in {aligned, unaligned, failed} |
| Source mutation | Source file is NEVER modified |
| Schema version | 1.0.0 |
| Cache key | source_sha256 + config + schema + adapter + wx_version + model fingerprints |

### Known Risks (Phase 3)

| Risk | Severity |
|---|---|
| Vietnamese ASR quality | Medium — tiny/base models may struggle with regional accents |
| Vietnamese alignment quality | Medium — wav2vec2 model trained on read speech |
| Model storage (~1.4 GB total) | Low — one-time download to model-cache/ |
| Windows CPU inference speed | Low — RTF ~0.5-2x depending on model size |

### Phase 4 Lock

Phase 4 (Vision API, scene scoring, edit planning, FFmpeg rendering, CapCut, video-use,
Cloudflare deployment) is **NOT implemented**.
Explicit user authorization is required before Phase 4 begins.
