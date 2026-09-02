"""Business-rule validation for merged ContentProfile objects.

All validation is performed on the already-merged typed model.
Uses ONLY Python standard library.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from auto_video_editor.exceptions import ProfileValidationError
from auto_video_editor.profiles.models import ContentProfile

SUPPORTED_SCHEMA_VERSION = "1.0.0"
PROFILE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
COLOR_HEX_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")

# Known valid enum values
VALID_PLATFORMS = {"tiktok", "youtube_shorts", "instagram_reels"}
VALID_ASPECT_RATIOS = {"9:16", "16:9", "1:1", "4:5"}
VALID_CODECS_VIDEO = {"libx264", "libx265", "h264_nvenc"}
VALID_CODECS_AUDIO = {"aac", "libopus", "libmp3lame"}
VALID_PIXEL_FORMATS = {"yuv420p", "yuv422p", "yuv444p"}
VALID_FRAMERATES = {24, 25, 30, 60}
VALID_SUBTITLE_FORMATS = {"ass", "srt"}
VALID_PREPROCESSING_MODES = {"strict", "normal", "loose"}
WEIGHT_EXACT_SUM = 100


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ProfileValidationError(message)


def validate_profile(profile: ContentProfile) -> None:
    """Validate a fully-merged ContentProfile against all business rules.

    Raises ProfileValidationError on the first failure found.
    """
    pid = profile.profile_id

    # --- Schema version ---
    _check(
        profile.schema_version == SUPPORTED_SCHEMA_VERSION,
        f"[{pid}] Unsupported schema_version {profile.schema_version!r}. "
        f"Expected {SUPPORTED_SCHEMA_VERSION!r}.",
    )

    # --- Profile ID ---
    _check(
        bool(PROFILE_ID_PATTERN.match(pid)),
        f"[{pid}] profile_id does not match required pattern {PROFILE_ID_PATTERN.pattern!r}.",
    )

    # --- Duration ---
    _check(
        profile.reference_duration_seconds > 0,
        f"[{pid}] reference_duration_seconds must be > 0, got {profile.reference_duration_seconds}.",
    )
    # --- Optional min/max bounds ---
    if profile.min_duration_seconds is not None:
        _check(
            profile.min_duration_seconds > 0,
            f"[{pid}] min_duration_seconds must be > 0, got {profile.min_duration_seconds}.",
        )
        _check(
            profile.min_duration_seconds <= profile.reference_duration_seconds,
            f"[{pid}] min_duration_seconds ({profile.min_duration_seconds}) must be <= "
            f"reference_duration_seconds ({profile.reference_duration_seconds}).",
        )
    if profile.max_duration_seconds is not None:
        _check(
            profile.max_duration_seconds >= profile.reference_duration_seconds,
            f"[{pid}] max_duration_seconds ({profile.max_duration_seconds}) must be >= "
            f"reference_duration_seconds ({profile.reference_duration_seconds}).",
        )
    if profile.min_duration_seconds is not None and profile.max_duration_seconds is not None:
        _check(
            profile.min_duration_seconds <= profile.max_duration_seconds,
            f"[{pid}] min_duration_seconds ({profile.min_duration_seconds}) must be <= "
            f"max_duration_seconds ({profile.max_duration_seconds}).",
        )

    # --- Platform / aspect ratio ---
    _check(
        profile.platform in VALID_PLATFORMS,
        f"[{pid}] Unknown platform {profile.platform!r}. Valid: {sorted(VALID_PLATFORMS)}.",
    )
    _check(
        profile.aspect_ratio in VALID_ASPECT_RATIOS,
        f"[{pid}] Unknown aspect_ratio {profile.aspect_ratio!r}. Valid: {sorted(VALID_ASPECT_RATIOS)}.",
    )

    # --- Resolution ---
    _check(
        profile.resolution.width > 0 and profile.resolution.height > 0,
        f"[{pid}] Resolution width and height must be > 0.",
    )

    # --- Framerate ---
    _check(
        profile.framerate in VALID_FRAMERATES,
        f"[{pid}] framerate {profile.framerate} not in valid set {sorted(VALID_FRAMERATES)}.",
    )

    # --- Subtitle ---
    _check(
        profile.subtitle.format in VALID_SUBTITLE_FORMATS,
        f"[{pid}] subtitle.format {profile.subtitle.format!r} not in {sorted(VALID_SUBTITLE_FORMATS)}.",
    )
    _check(
        bool(COLOR_HEX_PATTERN.match(profile.subtitle.font.color_hex)),
        f"[{pid}] subtitle.font.color_hex {profile.subtitle.font.color_hex!r} is not a valid hex color.",
    )
    _check(
        bool(COLOR_HEX_PATTERN.match(profile.subtitle.font.outline_color_hex)),
        f"[{pid}] subtitle.font.outline_color_hex {profile.subtitle.font.outline_color_hex!r} is not valid.",
    )

    # --- Audio ---
    _check(
        0.0 <= profile.audio.bgm_volume_percent <= 100.0,
        f"[{pid}] audio.bgm_volume_percent must be in [0, 100], got {profile.audio.bgm_volume_percent}.",
    )

    # --- Preprocessing mode ---
    _check(
        profile.preprocessing.mode in VALID_PREPROCESSING_MODES,
        f"[{pid}] preprocessing.mode {profile.preprocessing.mode!r} not in "
        f"{sorted(VALID_PREPROCESSING_MODES)}.",
    )
    _check(
        profile.preprocessing.hallucination_volume_threshold_db <= 0,
        f"[{pid}] hallucination_volume_threshold_db must be <= 0.",
    )

    # --- Scoring weights: must sum to EXACTLY 100 (child profiles only) ---
    if profile.extends == "base" and profile.scoring.weights:
        total = profile.scoring.total
        _check(
            total == WEIGHT_EXACT_SUM,
            f"[{pid}] scoring.weights sum to {total}, must be exactly {WEIGHT_EXACT_SUM}. "
            f"Weights: {dict(profile.scoring.weights)}",
        )
        for wname, wval in profile.scoring.items():
            _check(
                isinstance(wval, int) and 0 <= wval <= 100,
                f"[{pid}] scoring.weights[{wname!r}] = {wval!r} must be an integer in [0, 100].",
            )

    # --- Narrative stages ---
    stages = profile.narrative_stages
    if stages:
        duration = profile.reference_duration_seconds
        prev_end: float | None = None

        for i, stage in enumerate(stages):
            _check(
                stage.start_seconds >= 0,
                f"[{pid}] Stage {stage.name!r}: start_seconds must be >= 0.",
            )
            _check(
                stage.end_seconds > stage.start_seconds,
                f"[{pid}] Stage {stage.name!r}: end_seconds ({stage.end_seconds}) must be "
                f"> start_seconds ({stage.start_seconds}).",
            )
            _check(
                stage.end_seconds <= duration,
                f"[{pid}] Stage {stage.name!r}: end_seconds ({stage.end_seconds}) exceeds "
                f"reference_duration_seconds ({duration}).",
            )
            if prev_end is not None:
                _check(
                    stage.start_seconds >= prev_end,
                    f"[{pid}] Stage {stage.name!r}: start_seconds ({stage.start_seconds}) overlaps "
                    f"with previous stage end ({prev_end}).",
                )
            prev_end = stage.end_seconds


def validate_raw_dict(data: dict[str, Any], profile_id: str) -> None:
    """Validate a raw merged dict for unknown top-level keys.

    This is a pre-model-construction check to catch keys that JSON schema
    would reject but that may sneak in via deep merge.
    """
    known_keys = {
        "$schema_version", "profile_id", "extends", "display_name", "description",
        "account", "platform", "aspect_ratio", "resolution", "framerate",
        "codec", "reference_duration_seconds", "min_duration_seconds", "max_duration_seconds",
        "subtitle", "audio", "narrative", "scoring", "preprocessing",
    }
    unknown = set(data.keys()) - known_keys
    if unknown:
        raise ProfileValidationError(
            f"[{profile_id}] Unknown top-level keys after merge: {sorted(unknown)}"
        )


def validate_no_null_values(data: Any, path: str = "") -> None:
    """Recursively reject null (None) values anywhere in the merged dict."""
    if data is None:
        raise ProfileValidationError(
            f"null value is not permitted at path {path!r}"
        )
    if isinstance(data, dict):
        for key, value in data.items():
            validate_no_null_values(value, path=f"{path}.{key}" if path else key)
    elif isinstance(data, list):
        for i, item in enumerate(data):
            validate_no_null_values(item, path=f"{path}[{i}]")


def validate_profile_from_dict(data: dict[str, Any], profile_id: str) -> None:
    """Run all raw-dict validations before model construction."""
    validate_no_null_values(data, path=profile_id)
    validate_raw_dict(data, profile_id)
