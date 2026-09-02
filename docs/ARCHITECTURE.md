# Architecture Audit — ai-video-editing-skill

> **Audit Date:** 2026-09-02T13:36:44+07:00
> **Auditor:** Phase 1 Automated Agent
> **Repository:** [znyupup/ai-video-editing-skill](https://github.com/znyupup/ai-video-editing-skill)
> **Fork:** [vannghi2712-cmd/ai-video-editing-skill](https://github.com/vannghi2712-cmd/ai-video-editing-skill)
> **Branch:** `feat/automated-short-form-editor`
> **Upstream Commit:** `b6429ab550a64c595dc68d42c47cf2b489a50619` (main)
> **License:** MIT (Copyright 2025 nyx研究所)
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
| **Author** | nyx研究所 (GitHub @znyupup) |
| **Tags/Version** | v1.1.0 (from SKILL.md YAML frontmatter) |
| **Tracked Files** | 10 files (see Section 4) |
| **Tests Directory** | None — `NO_UPSTREAM_AUTOMATED_TESTS_FOUND` |
| **CI/CD** | None detected |
| **Package Manager** | None (no `requirements.txt`, `pyproject.toml`, `setup.py`, or lock files) |

---

## 2. Current Architecture

The repository is an **AI Agent Skill specification**, not a standalone application. It provides:

1. **SKILL.md** — A 953-line executable specification document that AI coding agents (Claude Code, OpenClaw, Hermes, GPT-based agents) read and follow as procedural instructions. Contains embedded Python code snippets, bash commands, JSON schemas, and 36 production pitfalls.

2. **Two utility scripts** — Standalone Python CLI tools (`gen_dashboard.py`, `gen_storyboard.py`) that generate browser-viewable HTML previews from pipeline artifacts.

3. **Example data** — JSON fixtures and a project structure guide demonstrating the expected data contracts between pipeline stages.

4. **A prompt template** — LLM prompt for generating edit plans from analyzed footage.

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
    └─ ffprobe batch scan → clip count, duration, resolution, codec
         │
Stage 2: Reference Research (Optional)
    └─ yt-dlp download → whisper transcribe → scenedetect → visual API analysis
         │
Stage 3: Three-Dimensional Material Analysis
    ├─ Audio: ffmpeg extract 16kHz mono WAV → Whisper/FunASR transcribe
    ├─ Volume: ffmpeg volumedetect → mean/max dB classification
    └─ Visual: ffmpeg frame extraction (720p) → Vision API (base64 JPEG)
         │
Stage 3.5: Advisory Preprocessing
    ├─ Recording cue detection (first/last 3s)
    ├─ Repeat speech detection (difflib, threshold ≥ 0.6)
    ├─ Camera shake / trailing silence trim detection
    └─ Mode: strict | normal | loose
         │
Stage 4: LLM Narrative Planning
    └─ Prompt template + analysis data → edit_plan.json
         │
Stage 4+: Visual Preview
    ├─ gen_dashboard.py → dashboard.html (footage overview + QC grid)
    └─ gen_storyboard.py → storyboard/index.html (timeline + keyframes)
         │
Stage 4.5: Speech Cut Validation & Auto-Fix
    └─ validate_speech() → fix_speech_cuts() → verify assertion
         │
Stage 5: FFmpeg Rendering
    ├─ Per-segment: scale/pad to 1080p, H.264 CRF 18, AAC 128k, 30fps
    ├─ Highlight montage: 6-10 fast cuts (0.5-1s each, muted)
    ├─ Title overlay: Pillow RGBA PNG → ffmpeg overlay (3s, no shortest=1)
    ├─ Concat: demuxer concat copy (not xfade chains)
    └─ BGM: amix with volume ducking (8-12% under speech)
```

---

## 4. File Responsibility Map

| File | Responsibility | Type | Evidence | Reuse Decision |
|---|---|---|---|---|
| `SKILL.md` | Master workflow specification; 7-stage pipeline instructions, embedded code, 36 pitfalls | Agent Knowledge | 953 lines, v1.1.0, YAML frontmatter | **Keep** — Primary reference document |
| `README.md` | Human-oriented project overview, 4-step workflow summary, supported agents | Documentation | 239 lines, links to SKILL.md | **Keep** — Onboarding reference |
| `scripts/gen_dashboard.py` | Standalone HTML dashboard generator (footage overview + QC frames) | Executable (Python) | 769 lines, stdlib-only, argparse CLI | **Extend** — Integrate as review-mode output |
| `scripts/gen_storyboard.py` | Standalone HTML storyboard generator (timeline + keyframes) | Executable (Python) | 302 lines, stdlib-only, argparse CLI | **Extend** — Integrate as review-mode output |
| `templates/edit_plan_prompt.md` | LLM prompt template for edit plan generation | Template | 93 lines, 7 template variables | **Refactor** — Adapt per content profile |
| `examples/clip_analysis.json` | Reference output from Stage 3+3.5 (5 clips, Harbin winter footage) | Fixture | 182 lines, JSON, Chinese transcripts | **Keep** — Schema validation fixture |
| `examples/edit_plan.json` | Reference output from Stage 4 (4 narrative sections) | Fixture | 67 lines, JSON, Chinese text | **Keep** — Schema validation fixture |
| `examples/project_structure.md` | Directory layout and storage benchmarks | Documentation | 85 lines | **Keep** — Structural reference |
| `.gitignore` | Git ignore rules for media, caches, agent configs | Configuration | 40 lines | **Extend** — Add outputs/, caches, models |
| `LICENSE` | MIT license | Legal | 22 lines, Copyright 2025 | **Keep** — Permissive for modification |

### Baseline Checks

| Command | Exit Code | Classification | Result |
|---|---|---|---|
| `python -m py_compile scripts/gen_dashboard.py` | 0 | `STATIC_EXAMPLE_VALIDATION` | Syntax valid |
| `python -m py_compile scripts/gen_storyboard.py` | 0 | `STATIC_EXAMPLE_VALIDATION` | Syntax valid |
| `git ls-files` | 0 | Inventory | 10 tracked files, 0 untracked |

`NO_UPSTREAM_AUTOMATED_TESTS_FOUND` — No `tests/` directory, no test runner configuration, no CI/CD workflows.

---

## 5. Reusable Components

| Component | Source | Decision | Rationale |
|---|---|---|---|
| `gen_dashboard.py` | `scripts/` | **Extend** | Production-ready HTML generator; stdlib-only; adaptable for review-mode HTML storyboard output. Needs profile-aware theming. |
| `gen_storyboard.py` | `scripts/` | **Extend** | Clean timeline visualization; stdlib-only. Needs profile-aware section labels. |
| `edit_plan_prompt.md` | `templates/` | **Refactor** | Travel vlog-specific prompt. Must be parameterized per content profile (food_review, lifestyle_vlog, affiliate_fast). |
| Speech validation logic | `SKILL.md` (Stage 4.5) | **Extract & Formalize** | `validate_speech()` and `fix_speech_cuts()` — proven algorithms with margin tolerance. Must be extracted into typed Python module with tests. |
| Advisory preprocessing | `SKILL.md` (Stage 3.5) | **Extract & Formalize** | Recording cue detection, repeat detection, trim point detection. Must be extracted and extended for Vietnamese language cues. |
| `clip_analysis.json` schema | `examples/` | **Formalize** | JSON schema with visual, audio, and preprocessing fields. Must become a versioned Pydantic model. |
| `edit_plan.json` schema | `examples/` | **Formalize** | JSON schema with structure, clips, BGM, notes. Must become a versioned Pydantic model with duration math validation. |
| FFmpeg encoding presets | `SKILL.md` (Stage 5) | **Keep** | H.264 CRF 18, AAC 128k, 30fps, 1080p scale/pad, faststart — production-proven settings. |
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
| **FFmpeg filters** | 8.1.1 | `ass`, `subtitles`, `overlay`, `volumedetect`, `scale`, `pad`, `concat`, `amix` — all confirmed available |
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

> **PROPOSED — NOT IMPLEMENTED**
>
> This section describes the target architecture for Phases 2-8. No code for this design exists yet.

```
auto_video_editor/                    # Python package (new)
├── __main__.py                       # CLI entry point (click/typer)
├── cli/
│   ├── doctor.py                     # Environment validation
│   ├── analyze.py                    # Pipeline: inspect → normalize → detect → transcribe → keyframes → analyze
│   ├── plan.py                       # Pipeline: analyze + generate edit plan + review mode
│   ├── render.py                     # Pipeline: FFmpeg render + QA
│   ├── run.py                        # Full pipeline orchestrator
│   └── compare.py                    # Benchmark against video-use
├── core/
│   ├── inspector.py                  # ffprobe metadata extraction + SHA-256
│   ├── normalizer.py                 # Derived working copy generation
│   ├── scene_detector.py             # Scene detection interface
│   ├── transcriber.py                # ASR adapter (WhisperX/faster-whisper)
│   ├── keyframe_extractor.py         # Adaptive frame sampling
│   ├── scene_analyzer.py             # Technical + semantic analysis
│   ├── speech_guard.py               # Speech boundary validation (from upstream)
│   ├── preprocessor.py               # Advisory preprocessing (from upstream)
│   └── planner.py                    # Edit plan generation
├── render/
│   ├── ffmpeg_renderer.py            # FFmpeg command builder + executor
│   ├── subtitle_generator.py         # ASS subtitle generation (TikTok safe zones)
│   └── qa_checker.py                 # Automated QA verification
├── profiles/
│   ├── schema.py                     # Profile Pydantic models
│   ├── food_review.yaml              # @luenguynnn profile
│   ├── lifestyle_vlog.yaml           # @_bylue profile
│   └── affiliate_fast.yaml           # @iz_lue profile
├── models/
│   ├── schemas.py                    # Versioned data models (clip analysis, edit plan, etc.)
│   └── cache.py                      # Cache contract implementation
├── integrations/
│   ├── capcut_export.py              # Optional CapCut draft export
│   └── video_use_benchmark.py        # Comparison pipeline
├── review/
│   ├── storyboard.py                 # HTML storyboard (from upstream gen_storyboard.py)
│   └── dashboard.py                  # HTML dashboard (from upstream gen_dashboard.py)
└── utils/
    ├── logging.py                    # Command log with timestamps
    ├── hashing.py                    # SHA-256 source identity
    └── unicode.py                    # Vietnamese text handling

docs/
├── ARCHITECTURE.md                   # This document
├── PHASE_1_PREFLIGHT.md              # Environment audit evidence
└── PROFILE_GUIDE.md                  # Content profile documentation (Phase 2)

profiles/                             # Profile YAML configs (Phase 2)
tests/                                # Test suite (Phase 2+)
outputs/<project_id>/                 # Generated project outputs
```

**CLI Exit Codes:**
- `0` — Success
- `2` — Invalid user input
- `3` — Missing dependency
- `4` — Review approval required (review mode)
- `5` — Processing failure
- `6` — QA failure

---

## 9. Risks

| Risk | Severity | Phase | Mitigation |
|---|---|---|---|
| **CPU-only STT** | Medium | 3 | No CUDA GPU detected. WhisperX/faster-whisper on CPU will be slow for long footage. Consider `compute_type=int8` or FunASR as fallback. |
| **Vision API costs** | Medium | 4 | Frame analysis via commercial APIs (GPT-4o, Qwen-VL) incurs per-call costs. Free tier (Zhipu GLM-4.6V-Flash) may have rate limits. |
| **Vietnamese Unicode** | Low | 3, 6 | Upstream only tests Chinese. Vietnamese diacritics (ă, ơ, ư, ệ, etc.) must be validated through ASR, subtitles, and rendering. |
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
- [x] **Explicit user authorization received** ✅ (2026-09-02)

**Phase 2 is COMPLETE. Phase 3 is LOCKED pending explicit user authorization.**

---

## Phase 2 Implemented State

> **Added:** 2026-09-02T14:35:00+07:00
> **Commit:** see Phase 2 final report

### New Files Created

| Path | Type | Purpose |
|---|---|---|
| `schemas/content_profile.schema.json` | JSON Schema | v1.0.0 schema with `additionalProperties: false` |
| `configs/profiles/base.json` | Config | Generic defaults — no account-specific data |
| `configs/profiles/food_review.json` | Config | 45s food review — @luenguynnn |
| `configs/profiles/lifestyle_vlog.json` | Config | 90s lifestyle vlog — @_bylue |
| `configs/profiles/affiliate_fast.json` | Config | 30s affiliate fast — @iz_lue |
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

### Validated Profile Invariants (Corrected — Phase 2 Correction Commit)

| Profile | Duration | Min | Max | Stages | Weight Sum | Weights Valid |
|---|---|---|---|---|---|---|
| `food_review` | 45s | 30s | 60s | 5 | 100 ✅ | All integers in [0,100] ✅ |
| `lifestyle_vlog` | 45s | 30s | 60s | 5 | 100 ✅ | All integers in [0,100] ✅ |
| `affiliate_fast` | 40s | 25s | 50s | 5 | 100 ✅ | All integers in [0,100] ✅ |

> **Note:** Previous Phase 2 commit `303fd49` had `lifestyle_vlog` at 90s (no bounds) and `affiliate_fast` at 30s (no bounds) with incorrect stage names and weight keys. These were corrected in the Phase 2 Correction commit. See `docs/PROGRESS.md` for the full deviation table.

### Merge Contract (Implemented)

- JSON **objects** merge recursively — child keys override, base keys preserved
- **Scalars** (string, number, bool) — child replaces base
- **Arrays** — child replaces entirely (no concatenation)
- No `null` values anywhere in merged document
- Unknown top-level keys rejected after merge

### Security Constraints (Implemented)

- Profile IDs validated against `^[a-z][a-z0-9_]{1,63}$` before any filesystem access
- Path separators, `..`, `.`-prefix, and absolute paths all rejected
- Symlinks escaping `configs/profiles/` root rejected
- No `eval()`, `exec()`, or dynamic imports anywhere in package
- All profiles returned as **immutable frozen dataclasses** (no shared mutable state)
- No hardcoded profile IDs or account handles in core modules (verified by static test)
- Pure Python standard library — no external runtime dependencies

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
- [ ] **Explicit user authorization received** ← REQUIRED

**Phase 3 is LOCKED pending explicit user authorization.**
