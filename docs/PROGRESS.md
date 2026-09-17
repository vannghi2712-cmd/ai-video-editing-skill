# Progress Log

> Tracks completed phases and implementation status for the automated short-form video editing pipeline.

---

## Phase 1 — Workspace Audit and Fork

**Status:** ✅ COMPLETE
**Commit:** `ca1b6aedf16979af25bdb38a42934d95c5d9a0f9`
**Date:** 2026-09-02

### Completed
- Environment preflight (OS, Git 2.54, Python 3.11.9, FFmpeg 8.1.1, gh CLI 2.98.0)
- GitHub fork created: `vannghi2712-cmd/ai-video-editing-skill`
- Repository cloned to `D:\auto_edit\ai-video-editing-skill`
- Remotes: `origin` → fork, `upstream` → `znyupup/ai-video-editing-skill`
- Feature branch `feat/automated-short-form-editor` created from `upstream/main`
- Repository audit: 10 tracked files, MIT license, no upstream tests
- Baseline checks: `py_compile` pass on both scripts
- `docs/PHASE_1_PREFLIGHT.md` — environment evidence
- `docs/ARCHITECTURE.md` — 10-section architecture audit

### Known Gaps Carried Forward
- GPU/CUDA STATUS: UNVERIFIED (no CUDA GPU detected — CPU-only STT)
- No upstream automated test suite

---

## Phase 2 — Content Profile System

**Status:** ✅ COMPLETE
**Commit:** _(see GIT section in Phase 2 final report)_
**Date:** 2026-09-02

### Completed
- JSON Schema `schemas/content_profile.schema.json` (v1.0.0, `additionalProperties: false`)
- Base profile `configs/profiles/base.json` — generic defaults, no account-specific data
- Child profiles (all validated, all weight sums = 100):
  - `food_review` — 45s, 5 stages, 7 scoring criteria
  - `lifestyle_vlog` — 90s, 5 stages, 6 scoring criteria, ambient audio
  - `affiliate_fast` — 30s, 5 stages, 6 scoring criteria, Vietnamese punch-in keywords
- Python package `src/auto_video_editor/` (stdlib-only):
  - `profiles/loader.py` — path-safe loading, deep merge, typed model construction
  - `profiles/models.py` — immutable frozen dataclasses
  - `profiles/validation.py` — business-rule validation (weights, stages, nulls, unknown keys)
  - `cli.py` — argparse CLI: `profiles list/show/validate`
  - `exceptions.py` — domain exception hierarchy with exit codes
- Test suite `tests/` (94 tests, 0 failures):
  - `test_profile_loader.py` — merge, load, real profiles, unicode, path safety
  - `test_profile_validation.py` — business rules, no-hardcoding static check
  - `test_profile_cli.py` — list/show/validate via subprocess
- Documentation: `docs/PROFILE_GUIDE.md`, `docs/PROGRESS.md`, updated `docs/ARCHITECTURE.md`

### Key Design Decisions
- **Arrays replace (not concatenate)** — child `narrative.stages` fully replaces base
- **Frozen dataclasses** — all `ContentProfile` instances are immutable
- **No eval/exec/dynamic imports** — verified by static test
- **No hardcoded profile IDs** in core modules — verified by `TestNoHardcodedProfileIds`
- **UTF-8 stdout** — `sys.stdout.buffer.write` used for Vietnamese character safety on Windows

---

## Phase 2 Correction

**Status:** ✅ COMPLETE
**Previous commit:** `303fd49e2268c065560614347831da643764eb4d`
**Corrective commit SHA:** recorded in the Phase 2 execution report
**Date:** 2026-09-02

### Deviations Found in Previous Phase 2 Output

| Item | Previous (wrong) | Corrected |
|---|---|---|
| `lifestyle_vlog` duration | 90s, no min/max | 45s default, min:30, max:60 |
| `lifestyle_vlog` stage names | cold_open→arrival→exploration→highlight→reflection | cold_open→arrival_or_context→exploration→highlight→reflection_or_closing |
| `lifestyle_vlog` stage endpoints | 0-5-20-55-75-90 | 0-2-8-27-38-45 |
| `lifestyle_vlog` weight keys | story, emotion, visual_quality, variety, motion | story_relevance, emotion_and_human_moment, visual_quality, visual_variety, motion_and_transition_potential |
| `affiliate_fast` duration | 30s, no min/max | 40s default, min:25, max:50 |
| `affiliate_fast` stage names | hook→problem→demo→proof→cta | result_or_pain_hook→product_context→demonstration→experience_or_evidence→recommendation_and_cta |
| `affiliate_fast` stage endpoints | 0-3-8-20-26-30 | 0-2-7-22-34-40 |
| `affiliate_fast` weight keys | hook_strength, demo_value, credibility | hook_and_result_strength, demonstration_value, evidence_and_credibility |
| CLI `profiles list` | ID only (1 column) | 4 columns: ID, Display Name, Handle, Duration |
| CLI `profiles validate` no-arg | usage error (required group) | validates ALL child profiles |
| CLI `profiles validate --all` + `<id>` | not explicitly rejected | exits 2 with mutual-exclusion error |
| packaging | none | `pyproject.toml`, editable install, `.venv` |

### Corrections Applied
- `lifestyle_vlog.json` — rewritten to spec
- `affiliate_fast.json` — rewritten to spec
- `schemas/content_profile.schema.json` — added `min_duration_seconds`, `max_duration_seconds`, `required` field on stages
- `src/auto_video_editor/profiles/models.py` — added `min/max_duration_seconds` to `ContentProfile`, `required` to `NarrativeStage`
- `src/auto_video_editor/profiles/loader.py` — parses new fields
- `src/auto_video_editor/profiles/validation.py` — validates `min <= default <= max`; updated known keys
- `src/auto_video_editor/cli.py` — 4-column list; validate no-arg = all; mutual exclusion enforced
- `pyproject.toml` — added (zero runtime deps, Python >=3.11, src layout)
- `tests/test_regression_phase2c.py` — regression tests locking all corrected values

### Baseline Before Correction
```
Command: python -m unittest discover -s tests -p "test_*.py" (PYTHONPATH=src)
Tests: 94 discovered, 94 passed, 0 failed, exit 0
```

---

## Locked Phases

| Phase | Name | Status |
|---|---|---|
| 3 | Inspect & Normalize | 🔒 LOCKED |
| 4 | Scene Detection | 🔒 LOCKED |
| 5 | Transcription | 🔒 LOCKED |
| 6 | Keyframes & Scene Analysis | 🔒 LOCKED |
| 7 | Edit Plan Generation | 🔒 LOCKED |
| 8 | Human Review & Render | 🔒 LOCKED |

Each phase requires explicit user authorization before starting.

---

## Phase 2 Final Correction

**Status:** ✅ COMPLETE
**Previous corrective commit:** `7e5651fc1f7a9b63c89e2aab93da9063bfa67144`
**Final corrective commit SHA:** recorded in the execution report
**Date:** 2026-09-02

### Corrections Applied

| Item | Change |
|---|---|
| `food_review.min_duration_seconds` | Added: 30 (previously absent) |
| `food_review.max_duration_seconds` | Added: 60 (previously absent) |
| `docs/DEPLOYMENT_TARGET.md` | Removed fixed "30-second CPU time budget" claim; replaced with plan-dependent advisory |
| `docs/PROFILE_GUIDE.md` | Updated food_review table to show min:30, max:60 |
| `docs/ARCHITECTURE.md` | Updated invariants table food_review row |
| `README.md` | Updated food_review profile table |
| `tests/test_regression_phase2c.py` | Updated food_review bounds tests from None → 30/60 |

### Test Count After Final Correction
```
Command: .\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
Tests: 178+ discovered, all passed, exit 0
```

---

## Phase 3 — CPU-first Vietnamese Transcription Pipeline

**Status:** ✅ COMPLETE
**Date:** 2026-09-03

### What Was Implemented

| Component | Description |
|---|---|
| `src/auto_video_editor/transcription/` | Python package — config, models, cache, exporters, service, media |
| `src/auto_video_editor/transcription/backends/` | Protocol + WhisperX adapter (lazy imports) |
| `src/auto_video_editor/transcription/cli_commands.py` | `transcribe doctor` and `transcribe run` |
| `src/auto_video_editor/cli.py` | Updated to route `transcribe` subcommand |
| `tests/test_transcription.py` | 50 unit tests (no ML deps required) |
| `docs/PHASE_3_DEPENDENCY_AUDIT.md` | Verified dependency compatibility matrix |
| `docs/TRANSCRIPTION_GUIDE.md` | User guide for setup and CLI usage |
| `requirements/transcription-windows-cpu.lock.txt` | Exact resolved lock for reproducibility |
| `pyproject.toml` | Added `[project.optional-dependencies] transcription` |
| `.gitignore` | Added `.venv-whisperx/`, `model-cache/`, `.transcription-cache/`, `transcription-output/` |

### Key Contracts Enforced

- Language: Vietnamese (`vi`) only — other languages rejected at config
- Device: CPU only — `cuda` rejected at config and CLI
- Diarization: disabled by policy
- Translation: disabled by policy
- Word timing: only `timing_status="aligned"` when backend provides genuine timestamps
- Source integrity: SHA-256 before and after processing must match
- Cache: content-addressed, manifest ownership tracked

### Test Count After Phase 3

```
Base .venv:
  Command: .\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
  Tests: 229 (179 Phase 2 + 50 Phase 3), all passed, exit 0

ML .venv-whisperx:
  Same discover command — all tests pass, exit 0
```

### Phase 4 Status

Phase 4 (Vision API, scene scoring, edit planning, FFmpeg rendering, CapCut, video-use,
Cloudflare deployment) is **NOT implemented**.
Explicit user authorization is required before Phase 4 begins.

---

## Phase 3 Final Contract Correction

**Commit:** `4cab61b871075def8d261c1248d3dcbf2949e7dc`

### Corrections Applied

- DEFAULT_MODEL changed to "small" (production default; smoke tests use "tiny")
- include_raw flag added (default: False) — privacy-safe raw output suppression
- schemas/transcript.schema.json created (Draft 2020-12, v1.0.0) — but with root segments (fixed in Closure Correction 2)
- Immutable model identities: hardcoded revision table (_KNOWN_HF_REVISIONS)
- allow_nan=False, math.isfinite checks, "word" key for words in exporters.py
- 31 regression tests added

### Test Count After Final Correction

`
test_profile_cli.py:           25
test_profile_loader.py:        45
test_profile_validation.py:    24
test_regression_phase2c.py:    85
test_transcription.py:         85 (54 from Phase 3 + 31 new)
Total:                        264 — all pass, exit 0
`

### Issues Fixed in Closure Correction 2

1. root-level segments FORBIDDEN — must be result.segments
2. Model alias passed to constructors (must use local snapshot path)
3. jsonschema not a test dep; no Draft202012Validator tests
4. ADAPTER_VERSION not bumped — old name-hash cache entries not rejected

---

## Phase 3 Closure Correction 2

**Starting from:** 4cab61b871075def8d261c1248d3dcbf2949e7dc

### Corrections Applied

#### Pinned Local Snapshot Loading (STEP 4)

- Added _ensure_snapshot(repo_id, pinned_sha, cache_root) using snapshot_download()
- Verifies Path(snapshot_path).name == pinned_sha (integrity)
- Identity derived from actual path, NOT from hardcoded table
- transcribe(): passes snapshot_path to whisperx.load_model() with local_files_only=True
- align(): passes snapshot_path as model_name to whisperx.load_align_model()
- ADAPTER_VERSION bumped 1.0.0 -> 1.1.0 (rejects old cache without deleting dirs)

#### Transcript Root Restored (STEP 5)

- segments moved from root into result.segments
- result.full_text added (concatenated segment text)
- status: "success" and warnings: [] added at root

#### Schema + Independent Validation (STEP 6)

- schemas/transcript.schema.json updated: result required (not root segments)
- pyproject.toml: test = ["jsonschema==4.26.0"] added (test-only dep)
- 6 Draft202012Validator tests added (positive + 4 negative parity)

### Smoke Test Results (STEP 7)

`
Exit: 0  |  Aligned words: 2/2  |  Char count: 7
Text SHA-256: 96A58619087B85B27126E26AF14F89D44295A1DD7C93E82E69179B34485DA998
transcript.raw.json: ABSENT
ASR identity: hf:Systran/faster-whisper-tiny@d90ca5fe260221311c53c58e660288d3deb8d356
Align identity: hf:nguyenvulebinh/wav2vec2-base-vi-vlsp2020@50a30dadb3ec98a0d4cdb1eb1ea315aff538f7c2
Draft202012Validator: PASS  |  Cache hit (run 2): VERIFIED
`

### Test Count After Closure Correction 2

`
test_profile_cli.py:           25
test_profile_loader.py:        45
test_profile_validation.py:    24
test_regression_phase2c.py:    85
test_transcription.py:         97 (85 from 4cab61b − 6 removed + 18 new)
Total:                        276 — all pass in both venvs, exit 0
`

Reconciliation: 264 − 6 (TestImmutableModelIdentity) + 7 (TestPinnedModelRevisions)
+ 3 (TestSchemaFile) + 6 (TestDraft202012Validation) + 2 (TestTranscriptJSONExport) = 276.

### Phase 4 Status

Phase 4 remains NOT implemented. Explicit authorization required.

## Phase 4 Contract Correction (2026-09-09)

- Corrected scoring semantics: added `score_coverage_percent`, `partial_weighted_score`; `weighted_score` is null unless coverage == 100%
- Silent renormalization eliminated
- Cache identity bumped to v2.0.0 with full two-level identity (ordered keyframe SHAs, transcript context mode/hash, upload mode, request payload hash)
- Output ownership enforced under `--force`; source SHA mismatch always rejects
- `jsonschema` reclassified as MANDATORY_RUNTIME in pyproject.toml
- OpenAI verification classified: STATICALLY_VERIFIED (docs), MOCK_VERIFIED (tests), NOT_RUN (live)
- Scene merge now deterministic: boundary-score comparison, equal/missing -> always merge PREVIOUS
- New docs: VISION_ANALYSIS_GUIDE.md, DEPENDENCY_AUDIT_PHASE4.md
- Phase 5 remains LOCKED. Website remains NOT IMPLEMENTED.

## Phase 4 Closure Correction (2026-09-09)

### Changes
- FIX 1: Provider cache lookup moved AFTER keyframe byte verification (step 6→10 order)
- FIX 2: Canonical semantic request object drives both cache identity and provider calls; sanitized debug projection
- FIX 3: Public output schema bumped 1.0.0→2.0.0; V1 explicitly rejected by writer and validator
- FIX 4: Cache format version bumped 2.0.0→3.0.0; V1.0.0 output rejected from cache.get()
- FIX 5: UUID marker file (.scene_analysis_root) + manifest_version/output_root_id/root_binding_sha256/generated_artifacts
- FIX 6: WhisperX ML stack verified unchanged (--no-deps install); pip check clean
- FIX 7: Zero-coverage partial_weighted_score changed None→0.0 (always numeric)
- FIX 8: OpenAI docs re-accessed and STATICALLY_VERIFIED; LIVE_VISION_STATUS: NOT_RUN

### Tests
- 361 tests PASS (base env), EXIT=0
- 10 new closure regression tests added (TestClosureCorrections, TestOutputOwnershipEnforcement +2)

---

## Phase 4 Final Evidence and Contract Correction

**Status:** ✅ COMPLETE
**Commit:** `(current HEAD — pending push)`
**Date:** 2026-09-10
**Starting commit:** `fae77fb8fe341531e12b134cdf07febe3ede2386`
**Commit message:** `fix: close phase 4 analysis contracts`

### Changes
- FIX 1 (Cache order): Provider cache lookup enforced AFTER all semantic requests built and keyframe bytes verified (step 10, after step 6)
- FIX 2 (SceneVisionSemanticRequest): New immutable frozen dataclass — single source of truth for cache identity and provider construction; `to_canonical_identity_dict()` + `canonical_sha256()` methods; `ProviderContentBundle` for non-serializable bytes (never serialized or cached)
- FIX 3 (Cache v4.0.0): `CACHE_SCHEMA_VERSION` bumped `3.0.0→4.0.0`; `ADAPTER_VERSION` renamed to `VISION_ADAPTER_VERSION = "1.3.0"`; `provider_job_id()` replaced by `semantic_request_job_id(preprocessing_sha256, scene_canonical_dicts)`
- FIX 4 (VisionBackend API): `score_scene(semantic_request, content_bundle)` replaces `score_scene(scene, keyframes, profile, transcript_context)` — both backends updated; fixes pre-existing missing `score_coverage_percent`/`partial_weighted_score` in OpenAI no-keyframe path
- FIX 5 (LegacyOutputSchemaError): `validate_against_schema()` now raises `LegacyOutputSchemaError(ValueError)` for v1.0.0 docs instead of returning an error list — explicit typed rejection
- FIX 6 (Atomic writes): `_atomic_write_text()` / `_atomic_write()` using `tempfile.mkstemp` + `os.replace()` for `clip_analysis.json` and `manifest.json`
- FIX 7 (JPEG dimensions): Standard-library `_jpeg_dimensions(bytes)` helper parses SOF0/SOF1/SOF2 markers for semantic request image descriptors
- FIX 8 (Tests): 7 new semantic request + version contract tests; all old call sites updated to new `score_scene` API

### Tests
- **368 tests PASS, EXIT=0** (base env)
- 7 new tests: `TestClosureCorrections` extended with semantic request + version + LegacyOutputSchemaError tests
- Network-denied synthetic smoke test PASS: VERSION_CHECK, LEGACY_REJECTION, SEMANTIC_REQUEST_SHA, MOCK_BACKEND_NEW_API, ATOMIC_WRITE

---

## Phase 4 — Targeted Contract Correction 3 (2026-09-11)

### Objective
Harden all Phase 4 Final Contract elements identified in the read-only acceptance audit as deficiencies or failures.

### Corrections Applied

**Fix 1 — Direct source_sha256 in SceneVisionSemanticRequest**
- Added `source_sha256: str` as first field of the frozen dataclass.
- `__post_init__` validates exactly 64 hexadecimal characters.
- Normalized to lowercase in `to_canonical_identity_dict()`.
- Changing source SHA now changes `canonical_sha256()` and the cache job ID.

**Fix 2 — ProviderContentBundle immutability**
- Converted to `frozen=True` dataclass with `image_bytes: tuple[bytes, ...]`.
- Added `ProviderContentIntegrityError(ValueError)` typed exception.
- Added `validate_content_bundle_against_semantic_request()` that checks:
  image count, byte SHA-256, JPEG MIME magic, JPEG dimensions (where parseable),
  frame order, transcript consent mode, transcript hash, transcript character count.
- Error messages do not disclose raw bytes or transcript plaintext.

**Fix 3 — Keyframe mismatch fail-closed**
- `_verify_keyframe_bytes()` raises `ProviderContentIntegrityError` on SHA mismatch instead of warning and continuing.
- SHA comparison is case-insensitive (extractor stores uppercase, hashlib returns lowercase).
- All downstream steps (cache lookup, provider construction, output write) are blocked.
- Exit code: `EXIT_CONTENT_INTEGRITY_ERROR = 9`.

**Fix 4 — Two-point content verification**
- Point A: `validate_content_bundle_against_semantic_request()` for every scene before `cache.get()`.
- Point B: same validation before `backend.score_scene()` (cache miss only).
- Cache hit uses Point A only; provider never constructed.

**Fix 5 — Atomic I/O module (`atomic_io.py`)**
- New shared module with `atomic_write_bytes()`, `atomic_write_text()`, `WriterLock`.
- Contract: mkstemp → write → flush → fsync (best-effort on Windows) → os.replace → re-read → verify SHA.
- `WriterLock` uses `os.O_CREAT | os.O_EXCL` for exclusive cache entry locking.
- `ArtifactIntegrityError(OSError)` and `WriterLockError(OSError)` typed exceptions.

**Fix 6 — Atomic cache publication**
- `AnalysisCache.put()` now acquires `WriterLock`, atomically writes `clip_analysis.json` with post-replace hash, then `manifest.json` LAST.
- Manifest contains `clip_analysis_sha256`.
- `AnalysisCache.get()` verifies artifact SHA from manifest before returning.
- Wrong manifest SHA → safe miss.

**Fix 7 — Root marker atomicity**
- `_write_root_marker()` now uses `atomic_write_text()` instead of `write_text()`.

**Fix 8 — Symlink/reparse point protection**
- `_is_symlink_or_reparse()` checks raw path via `is_symlink()` and `st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT`.
- `_check_ownership()` calls this BEFORE `resolve()`.
- `--force` does NOT bypass.

**Fix 9 — Legacy v1 output detection**
- Before writing output, reads existing `clip_analysis.json` if present.
- If `schema_version == "1.0.0"`, returns exit 5 without any mutation.
- `--force` does NOT bypass.

**Fix 10 — OpenAI dependency pin**
- `pyproject.toml` corrected from `openai==3.8.0` to `openai==3.13.0`.
- Version verified via `pip index versions openai` (2026-09-11).
- Installed and confirmed working in `.venv`.

**Fix 11 — Documentation synchronization**
- README.md, docs/VISION_ANALYSIS_GUIDE.md, docs/DEPENDENCY_AUDIT_PHASE4.md, docs/ARCHITECTURE.md, docs/PROGRESS.md all updated.

**Fix 12 — Regression tests (35 new test methods)**
- `TestSemanticRequestIdentity` (9 tests): source_sha256, invalid SHA rejection, canonical hash, job ID change.
- `TestBundleIntegrity` (7 tests): SHA mismatch, count mismatch, MIME, transcript mismatch/consent.
- `TestAtomicIO` (8 tests): atomic write, post-replace hash, WriterLock exclusivity, manifest-last, corrupt artifact safe miss.
- `TestSymlinkRejection` (4 tests): symlink rejected, --force no bypass, mocked reparse rejected.
- `TestLegacyV1Behavior` (3 tests): error type, v1 detection, byte-for-byte immutability.
- `TestDependencyContract` (3 tests): pyproject.toml pin, mock does not import openai, lazy import.

### Tests
- **403 tests PASS, EXIT=0** (base env, 368 + 35 new)
- Skipped: 2 symlink tests require admin on Windows (correctly skipped via `skipTest`)
- ML environment: to be verified in final read-only pass

### Status
- `LIVE_VISION_STATUS: NOT_RUN`
- `VISION_PROVIDER_RUNTIME_CONTRACT: UNVERIFIED`
- Phase 5: LOCKED
- Pending: final read-only SHA verification before Phase 4 is accepted

---

## Phase 4 — Targeted Contract Correction 4 (2026-09-17)

### Objective
Fix 7 defects found in Phase 4 Final Read-Only Acceptance Audit 2 (commit `a83f1f71`):
CONTENT_BINDING_AMBIGUOUS, PROVIDER_SEMANTIC_DIVERGENCE, VERSION_INVALIDATION,
OUTPUT_TRANSACTION_UNLOCKED, LOCK_LIFECYCLE_UNSAFE, PATH_ANCESTOR_OR_TOCTOU_GAP,
CACHE_HIT_SCHEMA_VALIDATION_MISSING.

### Corrections Applied

**Fix 1 — CONTENT_BINDING_AMBIGUOUS (models.py)**
- New `ProviderImageContent(order: int, frame_id: str, image_bytes: bytes)` frozen dataclass.
- New `ProviderContentBundle(images: tuple[ProviderImageContent, ...], ...)` — replaces `image_bytes: tuple[bytes, ...]`.
- `validate_content_bundle_against_semantic_request()` rewrote: builds `dict[(order, frame_id), ProviderImageContent]` lookup; rejects non-canonical order, duplicate pairs, empty frame_id, or unmatched frame_id.
- No positional zip allowed. Explicit (order, frame_id) → bytes mapping enforced.

**Fix 2 — PROVIDER_SEMANTIC_DIVERGENCE (models.py, cache.py, service.py)**
- `preprocessing_identity_sha256: str` added as second field of `SceneVisionSemanticRequest`.
- Validated to exactly 64 hex chars; normalized to lowercase in `to_canonical_identity_dict()`.
- `semantic_request_job_id()` drops `preprocessing_sha256` parameter. Hashes strict JSON envelope:
  `{"cache_schema_version": "4.1.0", "request_count": N, "semantic_requests": [...]}`.
- `preprocessing_identity_sha256` is embedded in each canonical dict (NOT the envelope).

**Fix 3 — VERSION_INVALIDATION (cache.py)**
- `CACHE_SCHEMA_VERSION = "4.1.0"` (was `"4.0.0"`).
- `VISION_ADAPTER_VERSION = "1.4.0"` (was `"1.3.0"`).
- `service.py` now imports `VISION_ADAPTER_VERSION` from `cache.py` (not `scoring/base.py`).
- `scoring/base.py` unchanged (outside allowlist; its `VISION_ADAPTER_VERSION = "1.3.0"` is its internal constant).

**Fix 4 — OUTPUT_TRANSACTION_UNLOCKED (service.py)**
- `WriterLock(out_dir)` now wraps BOTH `clip_analysis.json` AND `manifest.json` writes on the normal path.
- Cache-hit path now also acquires `WriterLock(out_dir)` and writes `manifest.json` (was missing).
- Post-lock TOCTOU recheck: `_is_symlink_or_reparse(out_dir)` inside the lock context.

**Fix 5 — LOCK_LIFECYCLE_UNSAFE (atomic_io.py)**
- `WriterLock.__init__`: `self._token = str(uuid.uuid4())` — random per-instance UUID.
- `_acquire()` writes `f"{self._token}:{os.getpid()}"` to lock file.
- `_try_remove_dead_lock()`: parses `token:pid`, calls `os.kill(pid, 0)` — only removes if `ProcessLookupError` (provably dead); `PermissionError`/`OSError` → leave lock.
- `_release()`: reads file; only deletes if `content.startswith(f"{self._token}:")` — never deletes foreign-token lock.

**Fix 6 — PATH_ANCESTOR_OR_TOCTOU_GAP (atomic_io.py, service.py)**
- `PathSafetyError(OSError)` new exception.
- `check_path_ancestors(path)` checks every existing ancestor component for symlink/reparse via `lstat()`.
- `atomic_write_bytes()` rechecks destination for symlink/reparse before `os.replace()`.
- `service.py` calls `_check_path_safety(out_dir)` and `_check_path_safety(cache_root)` before pipeline start.

**Fix 7 — CACHE_HIT_SCHEMA_VALIDATION_MISSING (cache.py, models.py)**
- `CacheSchemaValidationError(ValueError)` new exception in `models.py`.
- `_validate_cached_analysis_strict(analysis: dict)`: raises `CacheSchemaValidationError` if schema file missing, jsonschema not installed, or Draft 2020-12 validation fails.
- `AnalysisCache.get()` calls `_validate_cached_analysis_strict()` at step 7 (before returning).
- `CacheSchemaValidationError` propagates to caller (NOT converted to safe miss).
- `service.py` catches `CacheSchemaValidationError` from `cache.get()` and returns `EXIT_SCHEMA_OUTPUT_ERROR`.

### Tests
- **421 tests PASS, EXIT=0** (base env, 403 + 18 new)
- Skipped: 2 (symlink tests require admin on Windows)
- New: `TestCorrection4Contracts` (18 tests covering all 7 contracts)
- Updated: `_make_semantic_request()`, `TestAnalysisCache._job_id()`, `TestBundleIntegrity`, `TestCacheVersionBump`, `TestClosureCorrections.test_vision_adapter_version`, existing semantic job ID tests

### Status
- `LIVE_VISION_STATUS: NOT_RUN`
- `VISION_PROVIDER_RUNTIME_CONTRACT: UNVERIFIED`
- Phase 5: LOCKED
- Correction 4 commit pending final SHA verification

