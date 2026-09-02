# Profile Guide — auto_video_editor

> **Phase:** 2 — Content Profile System (Corrected)
> **Schema Version:** 1.0.0
> **Last Updated:** 2026-09-02

---

## Overview

The profile system provides a **data-driven, account-specific configuration layer** for the automated short-form video editing pipeline. All behavioral divergence between accounts lives in JSON files — the Python code is fully generic and contains no hardcoded profile IDs or account handles.

---

## Architecture

```
configs/profiles/
├── base.json           ← Generic defaults (NOT directly usable for editing)
├── food_review.json    ← @luenguynnn — 45s food review (min:30, max:60)
├── lifestyle_vlog.json ← @_bylue — 45s lifestyle/travel vlog (min:30, max:60)
└── affiliate_fast.json ← @iz_lue — 40s affiliate product review (min:25, max:50)

schemas/
└── content_profile.schema.json  ← JSON Schema (informational reference)

src/auto_video_editor/
├── profiles/
│   ├── loader.py       ← Load, merge, and construct typed profiles
│   ├── models.py       ← Immutable frozen dataclass models
│   └── validation.py   ← Business-rule validation
├── cli.py              ← argparse CLI (profiles list/show/validate)
└── exceptions.py       ← Domain exception hierarchy with exit codes
```

---

## Profile Schema

Every profile (base and child) must include these top-level fields:

| Field | Type | Required | Description |
|---|---|---|---|
| `$schema_version` | `"1.0.0"` | **Always** | Must be exactly `"1.0.0"` |
| `profile_id` | string | **Always** | Pattern: `^[a-z][a-z0-9_]{1,63}$` |
| `extends` | `"base"` | **Child profiles** | Must be `"base"` |
| `display_name` | string | Recommended | Human-readable name |
| `reference_duration_seconds` | number > 0 | Recommended | Default output duration |
| `min_duration_seconds` | number | Optional | Must be > 0 and ≤ default |
| `max_duration_seconds` | number | Optional | Must be ≥ default |
| `narrative.stages` | array | Recommended | Ordered narrative stage list |
| `scoring.weights` | object | Required in child | Integer weights summing to exactly 100 |

---

## Business Rules

### All Profiles
- `reference_duration_seconds` > 0
- `$schema_version` must be exactly `"1.0.0"`
- No `null` values anywhere in the merged document
- No unknown top-level keys after merge

### When `min_duration_seconds` / `max_duration_seconds` are present
- `min_duration_seconds` > 0
- `min_duration_seconds` ≤ `reference_duration_seconds` ≤ `max_duration_seconds`

### Child Profiles
- Must declare `"extends": "base"`
- `scoring.weights` values must be integers in `[0, 100]`
- `scoring.weights` must sum to **exactly 100**
- `narrative.stages` must be **ordered** without overlap:
  - Each stage: `start_seconds < end_seconds`
  - Each stage: `end_seconds <= reference_duration_seconds`
  - Consecutive stages: `next.start_seconds >= prev.end_seconds`

---

## Base + Child Merge Rules

| Data Type | Merge Behaviour |
|---|---|
| **Scalars** (string, number, bool) | Child **replaces** base |
| **Objects** (`{}`) | **Recursive merge** — child keys override, base keys preserved |
| **Arrays** (`[]`) | Child **replaces entirely** — never concatenated |

---

## Defined Profiles

### `food_review` — TikTok @luenguynnn

| Field | Value | Classification |
|---|---|---|
| Default duration | 45s | SPECIFIED |
| Min duration | 30s | SPECIFIED |
| Max duration | 60s | SPECIFIED |
| Preprocessing | `normal` | REPOSITORY-DERIVED |
| BGM volume | 10% | REPOSITORY-DERIVED |

**Narrative stages (REPOSITORY-DERIVED — must not change without explicit user authorization):**

| Stage | Start | End | Required |
|---|---|---|---|
| `visual_hook` | 0s | 2s | — |
| `location_or_main_dish` | 2s | 6s | — |
| `experience` | 6s | 25s | — |
| `review` | 25s | 38s | — |
| `cta` | 38s | 45s | — |

**Scoring weights:**

| Criterion | Weight |
|---|---|
| `food_appeal` | 25 |
| `visibility` | 20 |
| `motion` | 15 |
| `technical_quality` | 15 |
| `composition` | 10 |
| `narrative` | 10 |
| `emotion` | 5 |
| **Total** | **100** |

---

### `lifestyle_vlog` — TikTok @_bylue

| Field | Value |
|---|---|
| Default duration | 45s |
| Min duration | 30s |
| Max duration | 60s |
| Preprocessing | `loose` |
| BGM volume | 15% |
| Ambient audio | Preserved (`preserve_ambient: true`) |

**Narrative stages:**

| Stage | Start | End | Required |
|---|---|---|---|
| `cold_open` | 0s | 2s | ✅ yes |
| `arrival_or_context` | 2s | 8s | no |
| `exploration` | 8s | 27s | ✅ yes |
| `highlight` | 27s | 38s | ✅ yes |
| `reflection_or_closing` | 38s | 45s | no |

**Scoring weights:**

| Criterion | Weight |
|---|---|
| `story_relevance` | 25 |
| `emotion_and_human_moment` | 20 |
| `visual_quality` | 20 |
| `technical_quality` | 15 |
| `visual_variety` | 10 |
| `motion_and_transition_potential` | 10 |
| **Total** | **100** |

---

### `affiliate_fast` — TikTok @iz_lue

| Field | Value |
|---|---|
| Default duration | 40s |
| Min duration | 25s |
| Max duration | 50s |
| Preprocessing | `strict` |
| BGM volume | 8% |
| Caption grouping | 2–5 words per group |
| Punch-in | Enabled (declarative Vietnamese keywords) |

**Narrative stages:**

| Stage | Start | End | Required |
|---|---|---|---|
| `result_or_pain_hook` | 0s | 2s | ✅ yes |
| `product_context` | 2s | 7s | ✅ yes |
| `demonstration` | 7s | 22s | ✅ yes |
| `experience_or_evidence` | 22s | 34s | no |
| `recommendation_and_cta` | 34s | 40s | no |

**Scoring weights:**

| Criterion | Weight |
|---|---|
| `hook_and_result_strength` | 25 |
| `speech_clarity` | 20 |
| `product_visibility` | 20 |
| `demonstration_value` | 15 |
| `evidence_and_credibility` | 10 |
| `technical_quality` | 10 |
| **Total** | **100** |

---

## CLI Reference

```bash
# List all available child profiles (4 columns: ID / Display Name / Handle / Duration)
python -m auto_video_editor profiles list

# Show full merged JSON for a profile
python -m auto_video_editor profiles show food_review

# Validate ALL child profiles (no-arg default)
python -m auto_video_editor profiles validate

# Validate ALL child profiles (explicit alias)
python -m auto_video_editor profiles validate --all

# Validate a single profile
python -m auto_video_editor profiles validate food_review

# Validate single profile AND --all → exit 2 (usage error: mutually exclusive)
python -m auto_video_editor profiles validate food_review --all

# Override profiles directory (for testing)
python -m auto_video_editor --profiles-dir /path/to/profiles profiles list
```

**Exit codes:**

| Code | Meaning |
|---|---|
| `0` | Success |
| `2` | Usage error (bad arguments or mutually exclusive args) |
| `3` | Profile not found or unsafe path |
| `4` | Parse or validation failure |
| `5` | Internal error |

---

## Security

- Profile IDs validated against `^[a-z][a-z0-9_]{1,63}$` before any filesystem access
- Path separators, `..`, `.`-prefix, absolute paths rejected
- Symlinks escaping `configs/profiles/` root rejected
- No `eval()`, `exec()`, or dynamic imports
- No external runtime dependencies — Python standard library only
- All loaded profiles are **immutable frozen dataclasses**
- No hardcoded profile IDs in core modules (verified by static test)

---

## Adding a New Profile

1. Create `configs/profiles/<profile_id>.json` with `"$schema_version": "1.0.0"` and `"extends": "base"`.
2. Set only fields that differ from `base.json`.
3. Ensure `scoring.weights` values are integers summing to exactly 100.
4. Ensure `narrative.stages` are ordered, non-overlapping, within `reference_duration_seconds`.
5. If using duration bounds: `min_duration_seconds` ≤ `reference_duration_seconds` ≤ `max_duration_seconds`.
6. Validate: `python -m auto_video_editor profiles validate <profile_id>`.
