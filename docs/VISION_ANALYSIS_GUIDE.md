# Phase 4 Vision Analysis Guide

**Status:** Phase 4 COMPLETE (Mock pipeline). Live OpenAI Vision: NOT_RUN.

---

## Overview

Phase 4 adds deterministic scene detection, keyframe extraction, transcript association, and profile-aware vision scoring to the pipeline. It supports a local mock backend (network-free) and an optional OpenAI Vision adapter (requires explicit consent flags and API credentials).

## Commands

```bash
python -m auto_video_editor analyze scenes \
  --input  path/to/video.mp4 \
  --profile food_review \
  --output-dir path/to/output/ \
  --provider mock
```

### All Flags

| Flag | Description |
|---|---|
| `--input` | Source video file path (required) |
| `--profile` | Content profile ID (required) |
| `--output-dir` | Output directory (required) |
| `--provider mock\|openai` | Vision backend (default: mock) |
| `--vision-model` | Vision model ID (required for openai) |
| `--transcript` | Phase 3 transcript.json for scene association |
| `--dry-run` | Plan only — no network calls, no outputs written |
| `--resume` | Restore from cache if available |
| `--force` | Overwrite owned artifacts (does NOT override source ownership) |
| `--allow-external-upload` | Consent: allow keyframes to be sent to OpenAI API |
| `--include-transcript-context` | Consent: include transcript text in API calls |
| `--allow-paid-recompute` | Allow paid API recomputation even if cached |
| `--threshold` | Scene change threshold 0.0–1.0 (default: 0.30) |
| `--min-duration` | Minimum scene duration in seconds (default: 1.0) |
| `--max-duration` | Maximum scene duration in seconds (default: 15.0) |
| `--cache-dir` | Cache directory (default: .scene-analysis-cache) |

## Exit Codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 2 | Syntax error |
| 3 | Profile error |
| 4 | Media inspection error |
| 5 | Schema/Output ownership error or Legacy v1 rejection |
| 6 | Auth/Consent error |
| 7 | Partial (some scenes failed scoring) |
| 8 | Backend execution error |
| 9 | Content integrity failure (keyframe or bundle SHA mismatch) |

## Content Integrity (Correction 3, 2026-09-11)

### SceneVisionSemanticRequest
- `source_sha256` is a **required direct field** — exactly 64 hex chars, normalized lowercase.
- Changing source SHA changes `canonical_sha256()` and the cache job ID.
- Canonical serialization: `json.dumps(sort_keys=True, separators=(",",":"), allow_nan=False)`.

### ProviderContentBundle
- Frozen dataclass: `image_bytes: tuple[bytes, ...]`, `transcript_excerpt: str | None`.
- `validate_content_bundle_against_semantic_request()` verifies: image count, SHA-256, JPEG magic, JPEG dimensions, frame order, transcript consent mode, transcript hash, char count.
- Mismatch raises `ProviderContentIntegrityError(ValueError)` — no raw bytes in error message.

### Two-Point Verification
- **Point A**: before `cache.get()` — cache cannot restore mismatched content.
- **Point B**: before `backend.score_scene()` (cache miss only).
- Cache hit: Point A only; provider never constructed.
- Cache miss: Point A + Point B.

### Keyframe Mismatch
- SHA mismatch is **fail-closed** — exits with code 9.
- SHA comparison is case-insensitive (extractor may store uppercase).
- No silent continuation, no `insufficient_evidence` downgrade.

## Scoring Contract

All dimensions come from `profile.scoring.weights` (no hard-coded profile-ID branches).

- **score_coverage_percent:** Sum of weights of SCORED dimensions (0–100). Full coverage = 100.
- **partial_weighted_score:** `sum(score × weight / 100)` for scored dimensions only. Range [0, 100].
- **weighted_score:** Equals `partial_weighted_score` ONLY when `score_coverage_percent == 100`. Otherwise `null`.
- **Missing evidence:** `score = null`, `confidence = null`, `status = "insufficient_evidence"`. Never silently converted to 0.

Silent renormalization (dividing by `sum(scored weights)` instead of total weights) is STRICTLY FORBIDDEN.

## Consent Gates

The following flags are REQUIRED for OpenAI Vision:
- `--allow-external-upload` — Keyframes will be encoded and sent to OpenAI API (ephemeral, never stored).
- `--include-transcript-context` — Transcript text will be included in the API prompt.

Without these flags, the pipeline exits with code 6 (consent error) before any upload.

## Output Directory Ownership

- If the output directory is non-empty and has no `manifest.json` → rejected (exit 5).
- If the manifest has a different `source_sha256` → rejected even with `--force`.
- Symlinks and Windows reparse points → rejected before `resolve()` even with `--force`.
- Legacy v1 output (`schema_version == "1.0.0"`) → rejected even with `--force`.
- `--force` can only overwrite artifacts declared by a valid, same-source, non-symlink, non-v1 manifest.

## Cache (v4.0.0)

Two-level content-addressed cache (schema version 4.0.0):
- **Level A (Preprocessing):** source SHA + tool versions + detector/extractor config.
- **Level B (Provider):** Level A + ordered per-scene `SceneVisionSemanticRequest` canonical dicts
  (each includes `source_sha256`, keyframe SHAs, profile hash, provider, model, prompt hash, schema hash, transcript consent/hash).

Atomic write contract:
- `clip_analysis.json` written FIRST, `manifest.json` LAST.
- Manifest contains `clip_analysis_sha256`; `cache.get()` verifies before returning.
- Wrong SHA → safe miss. Old schema (v1.0.0) → rejection.
- `WriterLock` (O_CREAT|O_EXCL) prevents concurrent writers.

Old caches (v≠4.0.0) are safely ignored (version mismatch = cache miss).

## Live Vision (NOT RUN)

Live OpenAI Vision execution has not been tested. The OpenAI adapter is implemented based on the official documentation contract but is classified as:

- Documentation contract: `STATICALLY_VERIFIED`
- Mock adapter tests: `MOCK_VERIFIED`
- Live authentication: `NOT_RUN` / `UNVERIFIED`
- Live image submission: `NOT_RUN` / `UNVERIFIED`
- Live Structured Outputs: `NOT_RUN` / `UNVERIFIED`
- Live refusal/retry: `NOT_RUN` / `UNVERIFIED`

OpenAI optional dependency: `openai==3.13.0` (verified PyPI, 2026-09-11). Chat Completions API.

To use live OpenAI Vision, set `OPENAI_API_KEY` and pass `--allow-external-upload`.

## Phase 5

Phase 5 (edit planning, clip sequencing, rendering) is **LOCKED**. `edit_plan.json` was NOT created. No rendering or CapCut/Cloudflare infrastructure is implemented.
