"""Tests for business-rule validation of content profiles."""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from auto_video_editor.exceptions import ProfileValidationError
from auto_video_editor.profiles.loader import load_profile
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
from auto_video_editor.profiles.validation import (
    validate_no_null_values,
    validate_profile,
    validate_profile_from_dict,
    validate_raw_dict,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_temp_profiles(**profiles) -> Path:
    tmp = Path(tempfile.mkdtemp())
    for name, data in profiles.items():
        (tmp / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return tmp


MINIMAL_BASE = {
    "$schema_version": "1.0.0",
    "profile_id": "base",
    "display_name": "Base",
    "platform": "tiktok",
    "aspect_ratio": "9:16",
    "resolution": {"width": 1080, "height": 1920},
    "framerate": 30,
    "codec": {
        "video": "libx264", "audio": "aac", "pixel_format": "yuv420p",
        "crf": 18, "audio_bitrate_kbps": 128,
        "audio_sample_rate": 44100, "audio_channels": 2,
    },
    "reference_duration_seconds": 60,
    "subtitle": {
        "enabled": True, "format": "ass",
        "safe_zone": {"top_percent": 15, "bottom_percent": 20,
                      "left_percent": 5, "right_percent": 5},
        "font": {"family": "Arial", "size": 42, "bold": True,
                 "color_hex": "#FFFFFF", "outline_color_hex": "#000000", "outline_width": 2},
    },
    "audio": {"normalize_speech": True, "bgm_volume_percent": 12, "duck_bgm_under_speech": True},
    "narrative": {"stages": []},
    "scoring": {"weights": {}},
    "preprocessing": {
        "mode": "normal", "remove_recording_cues": True,
        "hallucination_volume_threshold_db": -40,
        "caption_grouping": {"enabled": False, "words_per_group": 4},
        "punch_in": {"enabled": False, "keywords": []},
    },
}


def _make_valid_profile(
    profile_id: str = "test_profile",
    weights: dict | None = None,
    stages: tuple | None = None,
    duration: float = 45.0,
    extends: str = "base",
) -> ContentProfile:
    if weights is None:
        weights = {"a": 50, "b": 30, "c": 20}
    if stages is None:
        stages = (
            NarrativeStage("hook", "Hook", 0.0, 5.0),
            NarrativeStage("body", "Body", 5.0, 40.0),
            NarrativeStage("cta", "CTA", 40.0, 45.0),
        )
    return ContentProfile(
        schema_version="1.0.0",
        profile_id=profile_id,
        display_name="Test Profile",
        extends=extends,
        reference_duration_seconds=duration,
        scoring=ScoringWeights(weights=dict(weights)),
        narrative_stages=tuple(stages),
        resolution=Resolution(),
        codec=CodecConfig(),
        subtitle=SubtitleConfig(safe_zone=SafeZone(), font=FontConfig()),
        audio=AudioConfig(),
        preprocessing=PreprocessingConfig(
            caption_grouping=CaptionGrouping(),
            punch_in=PunchInConfig(),
        ),
    )


# ---------------------------------------------------------------------------
# Positive validation tests
# ---------------------------------------------------------------------------

class TestValidationPositive(unittest.TestCase):

    def test_valid_profile_passes(self):
        profile = _make_valid_profile()
        validate_profile(profile)  # Should not raise

    def test_valid_real_food_review(self):
        real_dir = _REPO_ROOT / "configs" / "profiles"
        if not real_dir.is_dir():
            self.skipTest("Real profiles dir not found")
        profile = load_profile("food_review", real_dir)
        validate_profile(profile)

    def test_valid_real_lifestyle_vlog(self):
        real_dir = _REPO_ROOT / "configs" / "profiles"
        if not real_dir.is_dir():
            self.skipTest("Real profiles dir not found")
        profile = load_profile("lifestyle_vlog", real_dir)
        validate_profile(profile)

    def test_valid_real_affiliate_fast(self):
        real_dir = _REPO_ROOT / "configs" / "profiles"
        if not real_dir.is_dir():
            self.skipTest("Real profiles dir not found")
        profile = load_profile("affiliate_fast", real_dir)
        validate_profile(profile)

    def test_weight_sum_exactly_100(self):
        profile = _make_valid_profile(weights={"x": 60, "y": 40})
        validate_profile(profile)

    def test_stages_touching_endpoints_valid(self):
        stages = (
            NarrativeStage("a", "A", 0.0, 15.0),
            NarrativeStage("b", "B", 15.0, 30.0),
            NarrativeStage("c", "C", 30.0, 45.0),
        )
        profile = _make_valid_profile(stages=stages, duration=45.0)
        validate_profile(profile)

    def test_no_stages_is_valid(self):
        profile = _make_valid_profile(stages=(), weights={"a": 100})
        validate_profile(profile)

    def test_no_null_values_passes_on_clean_dict(self):
        data = {"a": 1, "b": {"c": "hello"}, "d": [1, 2, 3]}
        validate_no_null_values(data)  # Should not raise


# ---------------------------------------------------------------------------
# Negative validation tests
# ---------------------------------------------------------------------------

class TestValidationNegative(unittest.TestCase):

    def test_weight_sum_not_100_fails(self):
        profile = _make_valid_profile(weights={"a": 50, "b": 30})  # sum = 80
        with self.assertRaises(ProfileValidationError) as ctx:
            validate_profile(profile)
        self.assertIn("80", str(ctx.exception))
        self.assertIn("100", str(ctx.exception))

    def test_weight_sum_over_100_fails(self):
        profile = _make_valid_profile(weights={"a": 60, "b": 50})  # sum = 110
        with self.assertRaises(ProfileValidationError):
            validate_profile(profile)

    def test_stage_end_before_start_fails(self):
        stages = (NarrativeStage("bad", "Bad", 10.0, 5.0),)
        profile = _make_valid_profile(stages=stages)
        with self.assertRaises(ProfileValidationError) as ctx:
            validate_profile(profile)
        self.assertIn("end_seconds", str(ctx.exception))

    def test_overlapping_stages_fail(self):
        stages = (
            NarrativeStage("a", "A", 0.0, 20.0),
            NarrativeStage("b", "B", 15.0, 40.0),  # overlaps with a
        )
        profile = _make_valid_profile(stages=stages)
        with self.assertRaises(ProfileValidationError) as ctx:
            validate_profile(profile)
        self.assertIn("overlaps", str(ctx.exception))

    def test_stage_exceeds_duration_fails(self):
        stages = (NarrativeStage("a", "A", 0.0, 50.0),)
        profile = _make_valid_profile(stages=stages, duration=45.0)
        with self.assertRaises(ProfileValidationError) as ctx:
            validate_profile(profile)
        self.assertIn("reference_duration_seconds", str(ctx.exception))

    def test_negative_duration_fails(self):
        profile = _make_valid_profile(duration=-1.0)
        with self.assertRaises(ProfileValidationError) as ctx:
            validate_profile(profile)
        self.assertIn("reference_duration_seconds", str(ctx.exception))

    def test_zero_duration_fails(self):
        profile = _make_valid_profile(duration=0.0)
        with self.assertRaises(ProfileValidationError):
            validate_profile(profile)

    def test_wrong_schema_version_fails(self):
        profile = ContentProfile(
            schema_version="2.0.0",
            profile_id="p",
            display_name="P",
            extends="base",
            scoring=ScoringWeights({"a": 100}),
            resolution=Resolution(),
            codec=CodecConfig(),
            subtitle=SubtitleConfig(safe_zone=SafeZone(), font=FontConfig()),
            audio=AudioConfig(),
            preprocessing=PreprocessingConfig(
                caption_grouping=CaptionGrouping(), punch_in=PunchInConfig()
            ),
        )
        with self.assertRaises(ProfileValidationError):
            validate_profile(profile)

    def test_null_value_rejected(self):
        with self.assertRaises(ProfileValidationError):
            validate_no_null_values({"key": None})

    def test_null_in_nested_dict_rejected(self):
        with self.assertRaises(ProfileValidationError):
            validate_no_null_values({"a": {"b": None}})

    def test_null_in_list_rejected(self):
        with self.assertRaises(ProfileValidationError):
            validate_no_null_values({"a": [1, None, 3]})

    def test_unknown_top_level_key_rejected(self):
        with self.assertRaises(ProfileValidationError) as ctx:
            validate_raw_dict({"$schema_version": "1.0.0", "unknown_field": "bad"}, "test")
        self.assertIn("unknown_field", str(ctx.exception))


# ---------------------------------------------------------------------------
# Real-profile weight-sum tests (explicit)
# ---------------------------------------------------------------------------

class TestRealProfileWeights(unittest.TestCase):

    def _real_dir(self):
        d = _REPO_ROOT / "configs" / "profiles"
        if not d.is_dir():
            self.skipTest("Real profiles dir not found")
        return d

    def test_food_review_weights_sum_100(self):
        p = load_profile("food_review", self._real_dir())
        self.assertEqual(p.scoring.total, 100,
                         f"food_review weights sum to {p.scoring.total}: {dict(p.scoring.weights)}")

    def test_lifestyle_vlog_weights_sum_100(self):
        p = load_profile("lifestyle_vlog", self._real_dir())
        self.assertEqual(p.scoring.total, 100,
                         f"lifestyle_vlog weights sum to {p.scoring.total}: {dict(p.scoring.weights)}")

    def test_affiliate_fast_weights_sum_100(self):
        p = load_profile("affiliate_fast", self._real_dir())
        self.assertEqual(p.scoring.total, 100,
                         f"affiliate_fast weights sum to {p.scoring.total}: {dict(p.scoring.weights)}")


# ---------------------------------------------------------------------------
# No-hardcoding check — static source inspection
# ---------------------------------------------------------------------------

class TestNoHardcodedProfileIds(unittest.TestCase):

    FORBIDDEN_PATTERNS = [
        r"if\s+profile_id\s*==\s*[\"']food_review[\"']",
        r"if\s+profile_id\s*==\s*[\"']lifestyle_vlog[\"']",
        r"if\s+profile_id\s*==\s*[\"']affiliate_fast[\"']",
        r"[\"']@luenguynnn[\"']",
        r"[\"']@_bylue[\"']",
        r"[\"']@iz_lue[\"']",
    ]

    SOURCE_FILES = [
        _REPO_ROOT / "src" / "auto_video_editor" / "profiles" / "loader.py",
        _REPO_ROOT / "src" / "auto_video_editor" / "profiles" / "validation.py",
        _REPO_ROOT / "src" / "auto_video_editor" / "profiles" / "models.py",
        _REPO_ROOT / "src" / "auto_video_editor" / "cli.py",
    ]

    def test_no_hardcoded_profile_ids_in_core_modules(self):
        violations = []
        for src_file in self.SOURCE_FILES:
            if not src_file.exists():
                continue
            source = src_file.read_text(encoding="utf-8")
            for pattern in self.FORBIDDEN_PATTERNS:
                matches = re.findall(pattern, source)
                for m in matches:
                    violations.append(f"{src_file.name}: {m!r}")
        if violations:
            self.fail(
                "Hardcoded profile IDs or account handles found in core modules:\n"
                + "\n".join(violations)
            )


if __name__ == "__main__":
    unittest.main()
