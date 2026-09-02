# Profile Guide — auto_video_editor

> **Phase:** 2 — Content Profile System
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
├── food_review.json    ← @luenguynnn — 45s food review
├── lifestyle_vlog.json ← @_bylue — 90s lifestyle/travel vlog
└── affiliate_fast.json ← @iz_lue — 30s affiliate product review

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
| `extends` | `"base"` | **Child profiles** | Must be `"base"` (only `base` supported) |
| `display_name` | string | Recommended | Human-readable name |
| `description` | string | Recommended | Purpose description |
| `account` | string | Optional | TikTok handle (informational) |
| `reference_duration_seconds` | number > 0 | Recommended | Target output duration |
| `narrative.stages` | array | Recommended | Ordered narrative stage list |
| `scoring.weights` | object | Required in child | Integer weights summing to exactly 100 |

### Full Field Reference

```jsonc
{
  "$schema_version": "1.0.0",
  "profile_id": "my_profile",       // ^[a-z][a-z0-9_]{1,63}$
  "extends": "base",                // child profiles only
  "display_name": "My Profile",
  "description": "...",
  "account": "@handle",             // informational only
  "platform": "tiktok",            // tiktok | youtube_shorts | instagram_reels
  "aspect_ratio": "9:16",          // 9:16 | 16:9 | 1:1 | 4:5
  "resolution": { "width": 1080, "height": 1920 },
  "framerate": 30,                  // 24 | 25 | 30 | 60
  "codec": {
    "video": "libx264",
    "audio": "aac",
    "pixel_format": "yuv420p",
    "crf": 18,
    "audio_bitrate_kbps": 128,
    "audio_sample_rate": 44100,
    "audio_channels": 2
  },
  "reference_duration_seconds": 45,
  "subtitle": {
    "enabled": true,
    "format": "ass",               // ass | srt
    "safe_zone": { "top_percent": 15, "bottom_percent": 20,
                   "left_percent": 5, "right_percent": 5 },
    "font": { "family": "Arial", "size": 42, "bold": true,
              "color_hex": "#FFFFFF", "outline_color_hex": "#000000",
              "outline_width": 2 }
  },
  "audio": {
    "normalize_speech": true,
    "bgm_volume_percent": 12,
    "duck_bgm_under_speech": true,
    "preserve_ambient": false
  },
  "narrative": {
    "stages": [
      { "name": "hook", "label": "Hook",
        "start_seconds": 0, "end_seconds": 5, "description": "..." }
    ]
  },
  "scoring": {
    "weights": { "hook_strength": 25, "clarity": 75 }  // must sum to 100
  },
  "preprocessing": {
    "mode": "normal",              // strict | normal | loose
    "remove_recording_cues": true,
    "remove_filler_words": false,
    "remove_configured_pauses": false,
    "hallucination_volume_threshold_db": -40,
    "caption_grouping": { "enabled": false, "words_per_group": 4 },
    "punch_in": { "enabled": false, "keywords": [] }
  }
}
```

---

## Business Rules

### All Profiles
- `reference_duration_seconds` > 0
- `$schema_version` must be exactly `"1.0.0"`
- No `null` values anywhere in the merged document
- No unknown top-level keys after merge

### Child Profiles
- Must declare `"extends": "base"`
- `scoring.weights` values must be integers in `[0, 100]`
- `scoring.weights` must sum to **exactly 100**
- `narrative.stages` must be **ordered** without overlap:
  - Each stage: `start_seconds < end_seconds`
  - Each stage: `end_seconds <= reference_duration_seconds`
  - Consecutive stages: `next.start_seconds >= prev.end_seconds`

---

## Base+Child Merge Rules

| Data Type | Merge Behaviour |
|---|---|
| **Scalars** (string, number, bool) | Child **replaces** base |
| **Objects** (`{}`) | **Recursive merge** — child keys override, base keys preserved |
| **Arrays** (`[]`) | Child **replaces entirely** — never concatenated |

### Example

```json
// base.json (excerpt)
{ "audio": { "bgm_volume_percent": 12, "duck_bgm_under_speech": true } }

// food_review.json (child, excerpt)
{ "audio": { "bgm_volume_percent": 10 } }

// Merged result
{ "audio": { "bgm_volume_percent": 10, "duck_bgm_under_speech": true } }
```

---

## Defined Profiles

### `food_review` — TikTok @luenguynnn

| Field | Value |
|---|---|
| Duration | 45 seconds |
| Preprocessing | `normal` |
| BGM volume | 10% |

**Narrative stages:**

| Stage | Start | End | Purpose |
|---|---|---|---|
| `visual_hook` | 0s | 2s | Eye-catching food/atmosphere shot |
| `location_or_main_dish` | 2s | 6s | Establish location or reveal dish |
| `experience` | 6s | 25s | Eating experience, textures, reactions |
| `review` | 25s | 38s | Honest verdict with specific praise/critique |
| `cta` | 38s | 45s | Follow prompt, location tag, or question |

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
| Duration | 90 seconds |
| Preprocessing | `loose` |
| BGM volume | 15% |
| Ambient audio | Preserved |

**Narrative stages:**

| Stage | Start | End | Purpose |
|---|---|---|---|
| `cold_open` | 0s | 5s | Cinematic opening with highlight moment |
| `arrival` | 5s | 20s | Setting, journey, first impressions |
| `exploration` | 20s | 55s | Core discovery — places, people, activities |
| `highlight` | 55s | 75s | Peak moment, best experience |
| `reflection` | 75s | 90s | Emotional wrap-up or ambient outro |

**Scoring weights:**

| Criterion | Weight |
|---|---|
| `story` | 25 |
| `emotion` | 20 |
| `visual_quality` | 20 |
| `technical_quality` | 15 |
| `variety` | 10 |
| `motion` | 10 |
| **Total** | **100** |

---

### `affiliate_fast` — TikTok @iz_lue

| Field | Value |
|---|---|
| Duration | 30 seconds |
| Preprocessing | `strict` |
| BGM volume | 8% |
| Caption grouping | 2–5 words per group |
| Punch-in | Enabled (Vietnamese keywords) |

**Narrative stages:**

| Stage | Start | End | Purpose |
|---|---|---|---|
| `hook` | 0s | 3s | Bold claim or question about the product |
| `problem` | 3s | 8s | Relatable pain point the product solves |
| `demo` | 8s | 20s | Product demonstration with close-ups |
| `proof` | 20s | 26s | Before/after, stats, or social proof |
| `cta` | 26s | 30s | Direct purchase prompt with link/code |

**Scoring weights:**

| Criterion | Weight |
|---|---|
| `hook_strength` | 25 |
| `speech_clarity` | 20 |
| `product_visibility` | 20 |
| `demo_value` | 15 |
| `credibility` | 10 |
| `technical_quality` | 10 |
| **Total** | **100** |

---

## CLI Reference

```bash
# List all available child profiles (excludes base), lexicographic order
python -m auto_video_editor profiles list

# Show full merged JSON for a profile
python -m auto_video_editor profiles show food_review

# Validate a single profile
python -m auto_video_editor profiles validate food_review

# Validate ALL child profiles
python -m auto_video_editor profiles validate --all

# Override profiles directory (for testing)
python -m auto_video_editor --profiles-dir /path/to/profiles profiles list
```

**Exit codes:**

| Code | Meaning |
|---|---|
| `0` | Success |
| `2` | Usage error (bad arguments) |
| `3` | Profile not found or unsafe path |
| `4` | Parse or validation failure |
| `5` | Internal error |

---

## Security

### Profile ID Safety
- IDs must match `^[a-z][a-z0-9_]{1,63}$` — enforced before any filesystem access
- Path separators (`/`, `\`), `.`, `..` are rejected
- Absolute paths are rejected
- Symlinks that escape the `configs/profiles/` root are rejected
- Unknown profiles raise `ProfileNotFoundError` (exit 3), never an unhandled traceback

### Code Safety
- No `eval()`, `exec()`, or dynamic imports
- No external runtime dependencies — Python standard library only
- All loaded profiles are **immutable frozen dataclasses** — no shared mutable state

---

## Adding a New Profile

1. Create `configs/profiles/<profile_id>.json` with `"$schema_version": "1.0.0"` and `"extends": "base"`.
2. Set only the fields that differ from `base.json` — the loader merges the rest.
3. Ensure `scoring.weights` values are integers summing to exactly 100.
4. Ensure `narrative.stages` are ordered, non-overlapping, and within `reference_duration_seconds`.
5. Validate: `python -m auto_video_editor profiles validate <profile_id>`.

> **Important:** `base.json` must contain ONLY generic defaults. Account-specific settings belong exclusively in child profiles.
