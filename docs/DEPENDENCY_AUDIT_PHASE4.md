# Phase 4 Dependency Audit

**Date:** 2026-09-09
**Phase:** 4 — Scene Detection, Keyframe Extraction, Vision Scoring
**Verified by:** Static inspection of official documentation and source code

---

## Mandatory Runtime Dependencies

| Package | Version | Classification | Import style | Declared |
|---|---|---|---|---|
| `jsonschema` | 4.26.0 | MANDATORY_RUNTIME | Lazy (production `exporters.py`) | `pyproject.toml [dependencies]` |

`jsonschema` is imported lazily in `src/auto_video_editor/analysis/exporters.py` via `from jsonschema import Draft202012Validator`. Because it is used in production code (not just tests), it is classified as MANDATORY_RUNTIME and declared in `[project.dependencies]`.

## Optional Runtime Dependencies

| Package | Version | Classification | Import style | Declared |
|---|---|---|---|---|
| `openai` | 3.8.0 | OPTIONAL_RUNTIME | Lazy (only in `openai_backend.py`) | `pyproject.toml [vision-openai]` |

Install with: `pip install "auto-video-editor[vision-openai]"`. Only required when using `--provider openai`.

## Test-Only Dependencies

| Package | Version | Classification | Declared |
|---|---|---|---|
| `jsonschema` | 4.26.0 | TEST_ONLY (previously; now MANDATORY_RUNTIME) | Moved from `[test]` to `[dependencies]` |
| `pytest` | latest | TEST_ONLY | `pyproject.toml [dev]` |

## System Tool Dependencies (not Python packages)

| Tool | Required version | Usage |
|---|---|---|
| `ffmpeg` | ≥5.0 (8.1.1 tested) | Scene detection (`scdet` filter), keyframe extraction |
| `ffprobe` | ≥5.0 (8.1.1 tested) | Media metadata inspection |

Both tools must be on `PATH`. No `shell=True`. No GPU/CUDA.

---

## OpenAI Vision API Contract Verification

### Verification Status

| Item | Status |
|---|---|
| Official documentation reviewed | YES (platform.openai.com, 2026-09-04) |
| Documentation contract | **STATICALLY_VERIFIED** |
| Mock adapter tests | **MOCK_VERIFIED** |
| Live authentication | **NOT_RUN** / UNVERIFIED |
| Live image submission | **NOT_RUN** / UNVERIFIED |
| Live Structured Outputs response | **NOT_RUN** / UNVERIFIED |
| Live refusal behavior | **NOT_RUN** / UNVERIFIED |
| Live retry behavior | **NOT_RUN** / UNVERIFIED |
| API calls made during testing | **0** |
| Keyframes sent to API | **0** |
| Credentials accessed | **No** |

### Statically Verified Contract

- **Endpoint:** `POST /v1/chat/completions`
- **Image input:** `image_url.url = "data:image/jpeg;base64,{b64}"` (ephemeral, NOT Files API, NOT public URLs)
- **Structured output:** `response_format={"type":"json_schema","json_schema":{"name":..,"strict":True,"schema":{..}}}`
- **Refusal:** `choice.message.refusal` non-None = refusal (do not process content)
- **Retry:** 429/5xx → honor `Retry-After` → max 3 attempts, 60s total
- **No retry:** 400/401/403 or schema failures
- **Official sources:** https://platform.openai.com/docs/guides/vision, https://platform.openai.com/docs/guides/structured-outputs

### Remaining Unverified

The following are UNVERIFIED because live API calls are not authorized:
- Actual authentication success/failure behavior
- Actual image encoding acceptance by the API
- Actual Structured Output JSON response shape
- Actual refusal triggering conditions
- Actual Retry-After header format in rate-limit responses

---

## pip check

`pip check` in `.venv` reports: **No broken requirements found.**

## Editable Install

Package installed as editable (`pip install -e .`) in `.venv`.

## Phase 5 and Website

Phase 5 (edit planning, clip rendering, CapCut) is **NOT IMPLEMENTED**.
Website, Web UI, and Cloudflare are **NOT IMPLEMENTED**.
