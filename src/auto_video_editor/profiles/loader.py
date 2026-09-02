"""Profile loader: resolves, reads, merges base+child JSON into typed models.

Security: Profile IDs are validated against a strict regex before any
filesystem access. Path traversal, absolute paths, and symlinks escaping
the profiles root are all rejected.
"""

from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path
from typing import Any

from auto_video_editor.exceptions import (
    ProfileNotFoundError,
    ProfileParseError,
    ProfilePathUnsafeError,
    ProfileSchemaVersionError,
)
from auto_video_editor.profiles.models import (
    AudioConfig,
    CaptionGrouping,
    CodecConfig,
    ContentProfile,
    FontConfig,
    NarrativeStage,
    PreprocessingConfig,
    PunchInConfig,
    Resolution,
    SafeZone,
    ScoringWeights,
    SubtitleConfig,
)

# --- Constants ---

SUPPORTED_SCHEMA_VERSION = "1.0.0"
PROFILE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_BASE_PROFILE_ID = "base"


def _default_profiles_dir() -> Path:
    """Resolve the default profiles directory relative to the repository root."""
    # Walk up from this file to find the repo root (contains .git)
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        if (parent / ".git").is_dir():
            return parent / "configs" / "profiles"
    # Fallback: relative to CWD
    return Path.cwd() / "configs" / "profiles"


def _validate_profile_id(profile_id: str) -> None:
    """Validate a profile ID is safe for filesystem use."""
    if not isinstance(profile_id, str):
        raise ProfilePathUnsafeError(f"Profile ID must be a string, got {type(profile_id).__name__}")

    # Reject path separators and traversal
    if "/" in profile_id or "\\" in profile_id:
        raise ProfilePathUnsafeError(
            f"Profile ID contains path separator: {profile_id!r}"
        )
    if ".." in profile_id or profile_id.startswith("."):
        raise ProfilePathUnsafeError(
            f"Profile ID contains path traversal: {profile_id!r}"
        )

    if not PROFILE_ID_PATTERN.match(profile_id):
        raise ProfilePathUnsafeError(
            f"Profile ID {profile_id!r} does not match required pattern: "
            f"{PROFILE_ID_PATTERN.pattern}"
        )


def _resolve_profile_path(profile_id: str, profiles_dir: Path) -> Path:
    """Resolve a profile ID to a safe filesystem path."""
    _validate_profile_id(profile_id)

    profiles_dir = profiles_dir.resolve()
    candidate = (profiles_dir / f"{profile_id}.json").resolve()

    # Ensure the resolved path is beneath the profiles directory
    try:
        candidate.relative_to(profiles_dir)
    except ValueError:
        raise ProfilePathUnsafeError(
            f"Resolved profile path escapes profiles directory: {candidate}"
        )

    # Reject symlinks that escape the root
    if candidate.is_symlink():
        target = candidate.resolve()
        try:
            target.relative_to(profiles_dir)
        except ValueError:
            raise ProfilePathUnsafeError(
                f"Profile symlink escapes profiles directory: {candidate} -> {target}"
            )

    return candidate


def _read_json(path: Path) -> dict[str, Any]:
    """Read and parse a JSON file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise ProfileNotFoundError(f"Profile file not found: {path}")
    except json.JSONDecodeError as e:
        raise ProfileParseError(f"Invalid JSON in {path}: {e}")

    if not isinstance(data, dict):
        raise ProfileParseError(f"Profile must be a JSON object, got {type(data).__name__}: {path}")

    return data


def _deep_merge(base: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge child into a copy of base.

    Rules:
    - JSON objects merge recursively.
    - Child scalar values replace base scalar values.
    - Child arrays REPLACE base arrays completely (never concatenate).
    - null values in child are rejected (handled by validation).
    """
    result = copy.deepcopy(base)
    for key, child_value in child.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(child_value, dict)
        ):
            result[key] = _deep_merge(result[key], child_value)
        else:
            result[key] = copy.deepcopy(child_value)
    return result


def _dict_to_profile(data: dict[str, Any]) -> ContentProfile:
    """Convert a merged dict into a typed ContentProfile."""
    # Resolution
    res_data = data.get("resolution", {})
    resolution = Resolution(
        width=res_data.get("width", 1080),
        height=res_data.get("height", 1920),
    )

    # Codec
    codec_data = data.get("codec", {})
    codec = CodecConfig(
        video=codec_data.get("video", "libx264"),
        audio=codec_data.get("audio", "aac"),
        pixel_format=codec_data.get("pixel_format", "yuv420p"),
        crf=codec_data.get("crf", 18),
        audio_bitrate_kbps=codec_data.get("audio_bitrate_kbps", 128),
        audio_sample_rate=codec_data.get("audio_sample_rate", 44100),
        audio_channels=codec_data.get("audio_channels", 2),
    )

    # Subtitle
    sub_data = data.get("subtitle", {})
    sz_data = sub_data.get("safe_zone", {})
    font_data = sub_data.get("font", {})
    subtitle = SubtitleConfig(
        enabled=sub_data.get("enabled", True),
        format=sub_data.get("format", "ass"),
        safe_zone=SafeZone(
            top_percent=sz_data.get("top_percent", 15.0),
            bottom_percent=sz_data.get("bottom_percent", 20.0),
            left_percent=sz_data.get("left_percent", 5.0),
            right_percent=sz_data.get("right_percent", 5.0),
        ),
        font=FontConfig(
            family=font_data.get("family", "Arial"),
            size=font_data.get("size", 42),
            bold=font_data.get("bold", True),
            color_hex=font_data.get("color_hex", "#FFFFFF"),
            outline_color_hex=font_data.get("outline_color_hex", "#000000"),
            outline_width=font_data.get("outline_width", 2.0),
        ),
    )

    # Audio
    audio_data = data.get("audio", {})
    audio = AudioConfig(
        normalize_speech=audio_data.get("normalize_speech", True),
        bgm_volume_percent=audio_data.get("bgm_volume_percent", 12.0),
        duck_bgm_under_speech=audio_data.get("duck_bgm_under_speech", True),
        preserve_ambient=audio_data.get("preserve_ambient", False),
    )

    # Narrative stages
    narrative_data = data.get("narrative", {})
    stages_data = narrative_data.get("stages", [])
    stages = tuple(
        NarrativeStage(
            name=s["name"],
            label=s["label"],
            start_seconds=s["start_seconds"],
            end_seconds=s["end_seconds"],
            description=s.get("description", ""),
            required=s.get("required", False),
        )
        for s in stages_data
    )

    # Scoring
    scoring_data = data.get("scoring", {})
    weights_data = scoring_data.get("weights", {})
    scoring = ScoringWeights(weights=dict(weights_data))

    # Preprocessing
    pre_data = data.get("preprocessing", {})
    cg_data = pre_data.get("caption_grouping", {})
    pi_data = pre_data.get("punch_in", {})
    preprocessing = PreprocessingConfig(
        mode=pre_data.get("mode", "normal"),
        remove_recording_cues=pre_data.get("remove_recording_cues", True),
        remove_filler_words=pre_data.get("remove_filler_words", False),
        remove_configured_pauses=pre_data.get("remove_configured_pauses", False),
        hallucination_volume_threshold_db=pre_data.get("hallucination_volume_threshold_db", -40.0),
        caption_grouping=CaptionGrouping(
            enabled=cg_data.get("enabled", False),
            words_per_group=cg_data.get("words_per_group", 4),
            words_per_group_min=cg_data.get("words_per_group_min"),
            words_per_group_max=cg_data.get("words_per_group_max"),
        ),
        punch_in=PunchInConfig(
            enabled=pi_data.get("enabled", False),
            keywords=tuple(pi_data.get("keywords", [])),
        ),
    )

    return ContentProfile(
        schema_version=data.get("$schema_version", SUPPORTED_SCHEMA_VERSION),
        profile_id=data["profile_id"],
        display_name=data.get("display_name", data["profile_id"]),
        description=data.get("description", ""),
        account=data.get("account", ""),
        extends=data.get("extends", ""),
        platform=data.get("platform", "tiktok"),
        aspect_ratio=data.get("aspect_ratio", "9:16"),
        resolution=resolution,
        framerate=data.get("framerate", 30),
        codec=codec,
        reference_duration_seconds=data.get("reference_duration_seconds", 60.0),
        min_duration_seconds=data.get("min_duration_seconds"),
        max_duration_seconds=data.get("max_duration_seconds"),
        subtitle=subtitle,
        audio=audio,
        narrative_stages=stages,
        scoring=scoring,
        preprocessing=preprocessing,
    )


def list_profiles(profiles_dir: Path | None = None) -> list[str]:
    """List available child profile IDs (excludes base), sorted lexicographically."""
    if profiles_dir is None:
        profiles_dir = _default_profiles_dir()
    profiles_dir = profiles_dir.resolve()

    if not profiles_dir.is_dir():
        return []

    result = []
    for entry in sorted(profiles_dir.iterdir()):
        if entry.suffix == ".json" and entry.stem != _BASE_PROFILE_ID:
            if PROFILE_ID_PATTERN.match(entry.stem):
                result.append(entry.stem)
    return result


def load_profile(
    profile_id: str,
    profiles_dir: Path | None = None,
) -> ContentProfile:
    """Load, merge (if child), and return a typed ContentProfile.

    The returned profile is an independent immutable snapshot — modifying
    it does not affect any shared state.
    """
    if profiles_dir is None:
        profiles_dir = _default_profiles_dir()
    profiles_dir = profiles_dir.resolve()

    # Resolve and read the profile
    profile_path = _resolve_profile_path(profile_id, profiles_dir)
    profile_data = _read_json(profile_path)

    # Validate schema version
    sv = profile_data.get("$schema_version")
    if sv != SUPPORTED_SCHEMA_VERSION:
        raise ProfileSchemaVersionError(
            f"Unsupported schema version {sv!r} in {profile_id}. "
            f"Expected {SUPPORTED_SCHEMA_VERSION!r}."
        )

    # If it extends base, load and merge
    extends = profile_data.get("extends")
    if extends == _BASE_PROFILE_ID:
        base_path = _resolve_profile_path(_BASE_PROFILE_ID, profiles_dir)
        base_data = _read_json(base_path)
        merged = _deep_merge(base_data, profile_data)
    elif extends is not None:
        raise ProfileParseError(
            f"Profile {profile_id!r} declares extends={extends!r}, "
            f"but only 'base' is supported."
        )
    elif profile_id == _BASE_PROFILE_ID:
        merged = copy.deepcopy(profile_data)
    else:
        raise ProfileParseError(
            f"Non-base profile {profile_id!r} must declare 'extends': 'base'."
        )

    return _dict_to_profile(merged)


def load_profile_raw(
    profile_id: str,
    profiles_dir: Path | None = None,
) -> dict[str, Any]:
    """Load and merge a profile, returning the raw merged dict (for CLI show)."""
    if profiles_dir is None:
        profiles_dir = _default_profiles_dir()
    profiles_dir = profiles_dir.resolve()

    profile_path = _resolve_profile_path(profile_id, profiles_dir)
    profile_data = _read_json(profile_path)

    extends = profile_data.get("extends")
    if extends == _BASE_PROFILE_ID:
        base_path = _resolve_profile_path(_BASE_PROFILE_ID, profiles_dir)
        base_data = _read_json(base_path)
        return _deep_merge(base_data, profile_data)
    elif profile_id == _BASE_PROFILE_ID:
        return copy.deepcopy(profile_data)
    else:
        return copy.deepcopy(profile_data)
