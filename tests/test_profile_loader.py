"""Tests for profile loader: loading, merging, path safety, and model construction."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure src/ is on the path when running tests directly
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from auto_video_editor.exceptions import (
    ProfileNotFoundError,
    ProfileParseError,
    ProfilePathUnsafeError,
    ProfileSchemaVersionError,
    ProfileValidationError,
)
from auto_video_editor.profiles.loader import (
    _deep_merge,
    list_profiles,
    load_profile,
    load_profile_raw,
)
from auto_video_editor.profiles.models import ContentProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_profiles_dir(profiles: dict[str, dict]) -> Path:
    """Write profiles to a temp directory and return its path."""
    tmp = tempfile.mkdtemp()
    for name, data in profiles.items():
        (Path(tmp) / f"{name}.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
    return Path(tmp)


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
        "safe_zone": {"top_percent": 15, "bottom_percent": 20, "left_percent": 5, "right_percent": 5},
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

MINIMAL_CHILD = {
    "$schema_version": "1.0.0",
    "profile_id": "test_child",
    "extends": "base",
    "display_name": "Test Child",
    "reference_duration_seconds": 45,
    "narrative": {
        "stages": [
            {"name": "hook", "label": "Hook", "start_seconds": 0, "end_seconds": 5, "description": ""},
            {"name": "body", "label": "Body", "start_seconds": 5, "end_seconds": 40, "description": ""},
            {"name": "cta", "label": "CTA", "start_seconds": 40, "end_seconds": 45, "description": ""},
        ]
    },
    "scoring": {"weights": {
        "hook_strength": 25, "speech_clarity": 20, "product_visibility": 20,
        "demo_value": 15, "credibility": 10, "technical_quality": 10,
    }},
}


# ---------------------------------------------------------------------------
# Deep-merge tests
# ---------------------------------------------------------------------------

class TestDeepMerge(unittest.TestCase):

    def test_scalar_child_replaces_base(self):
        base = {"a": 1, "b": "base_val"}
        child = {"b": "child_val"}
        result = _deep_merge(base, child)
        self.assertEqual(result["a"], 1)
        self.assertEqual(result["b"], "child_val")

    def test_object_merges_recursively(self):
        base = {"nested": {"x": 1, "y": 2}}
        child = {"nested": {"y": 99, "z": 3}}
        result = _deep_merge(base, child)
        self.assertEqual(result["nested"]["x"], 1)
        self.assertEqual(result["nested"]["y"], 99)
        self.assertEqual(result["nested"]["z"], 3)

    def test_array_child_replaces_base(self):
        base = {"items": [1, 2, 3]}
        child = {"items": [4, 5]}
        result = _deep_merge(base, child)
        self.assertEqual(result["items"], [4, 5])

    def test_child_adds_new_key(self):
        base = {"a": 1}
        child = {"b": 2}
        result = _deep_merge(base, child)
        self.assertEqual(result["a"], 1)
        self.assertEqual(result["b"], 2)

    def test_deep_merge_does_not_mutate_base(self):
        base = {"nested": {"x": 1}}
        child = {"nested": {"x": 99}}
        _ = _deep_merge(base, child)
        self.assertEqual(base["nested"]["x"], 1)  # base unchanged

    def test_deep_merge_does_not_mutate_child(self):
        base = {"a": 1}
        child = {"b": 2}
        _ = _deep_merge(base, child)
        self.assertNotIn("a", child)  # child unchanged

    def test_empty_child_returns_base_copy(self):
        base = {"a": 1}
        result = _deep_merge(base, {})
        self.assertEqual(result, base)
        self.assertIsNot(result, base)


# ---------------------------------------------------------------------------
# Loading tests — positive
# ---------------------------------------------------------------------------

class TestProfileLoaderPositive(unittest.TestCase):

    def setUp(self):
        self.profiles_dir = _make_profiles_dir({
            "base": MINIMAL_BASE,
            "test_child": MINIMAL_CHILD,
        })

    def test_load_child_profile_returns_content_profile(self):
        profile = load_profile("test_child", self.profiles_dir)
        self.assertIsInstance(profile, ContentProfile)

    def test_load_child_inherits_base_platform(self):
        profile = load_profile("test_child", self.profiles_dir)
        self.assertEqual(profile.platform, "tiktok")

    def test_load_child_overrides_duration(self):
        profile = load_profile("test_child", self.profiles_dir)
        self.assertEqual(profile.reference_duration_seconds, 45)

    def test_load_child_has_correct_stages(self):
        profile = load_profile("test_child", self.profiles_dir)
        self.assertEqual(len(profile.narrative_stages), 3)
        self.assertEqual(profile.narrative_stages[0].name, "hook")
        self.assertEqual(profile.narrative_stages[2].name, "cta")

    def test_load_child_has_correct_weights(self):
        profile = load_profile("test_child", self.profiles_dir)
        self.assertEqual(profile.scoring.weights["hook_strength"], 25)
        self.assertEqual(profile.scoring.total, 100)

    def test_load_profile_is_immutable_frozen(self):
        profile = load_profile("test_child", self.profiles_dir)
        with self.assertRaises((AttributeError, TypeError)):
            profile.profile_id = "hacked"  # type: ignore[misc]

    def test_load_two_calls_return_independent_instances(self):
        p1 = load_profile("test_child", self.profiles_dir)
        p2 = load_profile("test_child", self.profiles_dir)
        self.assertIsNot(p1, p2)

    def test_list_profiles_excludes_base(self):
        ids = list_profiles(self.profiles_dir)
        self.assertNotIn("base", ids)
        self.assertIn("test_child", ids)

    def test_list_profiles_is_sorted(self):
        # Add a second child
        (self.profiles_dir / "alpha_child.json").write_text(
            json.dumps({**MINIMAL_CHILD, "profile_id": "alpha_child"}), encoding="utf-8"
        )
        ids = list_profiles(self.profiles_dir)
        self.assertEqual(ids, sorted(ids))

    def test_load_raw_returns_merged_dict(self):
        raw = load_profile_raw("test_child", self.profiles_dir)
        self.assertIsInstance(raw, dict)
        self.assertEqual(raw["profile_id"], "test_child")
        # Should have base fields merged in
        self.assertIn("codec", raw)

    def test_stage_order_preserved(self):
        profile = load_profile("test_child", self.profiles_dir)
        names = [s.name for s in profile.narrative_stages]
        self.assertEqual(names, ["hook", "body", "cta"])

    def test_stage_duration_property(self):
        profile = load_profile("test_child", self.profiles_dir)
        hook = profile.narrative_stages[0]
        self.assertAlmostEqual(hook.duration_seconds, 5.0)


# ---------------------------------------------------------------------------
# Loading tests — real profiles
# ---------------------------------------------------------------------------

class TestRealProfiles(unittest.TestCase):

    def _get_real_dir(self) -> Path:
        repo_root = Path(__file__).resolve().parent.parent
        return repo_root / "configs" / "profiles"

    def test_real_profiles_dir_exists(self):
        d = self._get_real_dir()
        self.assertTrue(d.is_dir(), f"Profiles dir not found: {d}")

    def test_food_review_loads(self):
        profile = load_profile("food_review", self._get_real_dir())
        self.assertEqual(profile.profile_id, "food_review")
        self.assertEqual(profile.reference_duration_seconds, 45)

    def test_food_review_stage_count(self):
        profile = load_profile("food_review", self._get_real_dir())
        self.assertEqual(len(profile.narrative_stages), 5)

    def test_food_review_weight_sum(self):
        profile = load_profile("food_review", self._get_real_dir())
        self.assertEqual(profile.scoring.total, 100)

    def test_lifestyle_vlog_loads(self):
        profile = load_profile("lifestyle_vlog", self._get_real_dir())
        self.assertEqual(profile.profile_id, "lifestyle_vlog")

    def test_lifestyle_vlog_stage_order(self):
        profile = load_profile("lifestyle_vlog", self._get_real_dir())
        names = [s.name for s in profile.narrative_stages]
        self.assertEqual(names, ["cold_open", "arrival_or_context", "exploration", "highlight", "reflection_or_closing"])

    def test_lifestyle_vlog_weight_sum(self):
        profile = load_profile("lifestyle_vlog", self._get_real_dir())
        self.assertEqual(profile.scoring.total, 100)

    def test_affiliate_fast_loads(self):
        profile = load_profile("affiliate_fast", self._get_real_dir())
        self.assertEqual(profile.profile_id, "affiliate_fast")

    def test_affiliate_fast_weight_sum(self):
        profile = load_profile("affiliate_fast", self._get_real_dir())
        self.assertEqual(profile.scoring.total, 100)

    def test_affiliate_fast_punch_in_enabled(self):
        profile = load_profile("affiliate_fast", self._get_real_dir())
        self.assertTrue(profile.preprocessing.punch_in.enabled)

    def test_affiliate_fast_keywords_contain_vietnamese(self):
        profile = load_profile("affiliate_fast", self._get_real_dir())
        # Vietnamese characters must survive round-trip
        keywords = profile.preprocessing.punch_in.keywords
        self.assertTrue(len(keywords) > 0)
        combined = " ".join(keywords)
        self.assertIn("sản phẩm", combined)

    def test_all_profiles_listed(self):
        ids = list_profiles(self._get_real_dir())
        for expected in ("affiliate_fast", "food_review", "lifestyle_vlog"):
            self.assertIn(expected, ids)
        self.assertNotIn("base", ids)


# ---------------------------------------------------------------------------
# Loading tests — negative / security
# ---------------------------------------------------------------------------

class TestProfileLoaderNegative(unittest.TestCase):

    def setUp(self):
        self.profiles_dir = _make_profiles_dir({
            "base": MINIMAL_BASE,
            "test_child": MINIMAL_CHILD,
        })

    def test_unknown_profile_raises_not_found(self):
        with self.assertRaises(ProfileNotFoundError):
            load_profile("nonexistent_profile", self.profiles_dir)

    def test_path_traversal_with_slash_raises_unsafe(self):
        with self.assertRaises(ProfilePathUnsafeError):
            load_profile("../base", self.profiles_dir)

    def test_path_traversal_with_backslash_raises_unsafe(self):
        with self.assertRaises(ProfilePathUnsafeError):
            load_profile("..\\base", self.profiles_dir)

    def test_dotdot_in_id_raises_unsafe(self):
        with self.assertRaises(ProfilePathUnsafeError):
            load_profile("..", self.profiles_dir)

    def test_dot_prefix_raises_unsafe(self):
        with self.assertRaises(ProfilePathUnsafeError):
            load_profile(".hidden", self.profiles_dir)

    def test_uppercase_id_raises_unsafe(self):
        with self.assertRaises(ProfilePathUnsafeError):
            load_profile("Food_Review", self.profiles_dir)

    def test_profile_with_spaces_raises_unsafe(self):
        with self.assertRaises(ProfilePathUnsafeError):
            load_profile("food review", self.profiles_dir)

    def test_wrong_schema_version_raises(self):
        bad_dir = _make_profiles_dir({
            "base": {**MINIMAL_BASE, "$schema_version": "99.0.0"},
        })
        with self.assertRaises(ProfileSchemaVersionError):
            load_profile("base", bad_dir)

    def test_child_wrong_schema_version_raises(self):
        bad_child = {**MINIMAL_CHILD, "$schema_version": "2.0.0"}
        bad_dir = _make_profiles_dir({"base": MINIMAL_BASE, "test_child": bad_child})
        with self.assertRaises(ProfileSchemaVersionError):
            load_profile("test_child", bad_dir)

    def test_invalid_json_raises_parse_error(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "broken.json").write_text("{not valid json", encoding="utf-8")
        (tmp / "base.json").write_text(json.dumps(MINIMAL_BASE), encoding="utf-8")
        with self.assertRaises(ProfileParseError):
            load_profile("broken", tmp)

    def test_child_without_extends_raises_parse_error(self):
        no_extends = {k: v for k, v in MINIMAL_CHILD.items() if k != "extends"}
        bad_dir = _make_profiles_dir({"base": MINIMAL_BASE, "test_child": no_extends})
        with self.assertRaises(ProfileParseError):
            load_profile("test_child", bad_dir)


# ---------------------------------------------------------------------------
# Unicode round-trip tests
# ---------------------------------------------------------------------------

class TestUnicodeRoundTrip(unittest.TestCase):

    def test_vietnamese_display_name_survives_round_trip(self):
        child_with_viet = {
            **MINIMAL_CHILD,
            "display_name": "Đánh Giá Đồ Ăn — @luenguynnn",
            "description": "Nội dung đánh giá ẩm thực TikTok với các ký tự tiếng Việt: ắ ộ ề ử",
        }
        tmp_dir = _make_profiles_dir({"base": MINIMAL_BASE, "test_child": child_with_viet})
        profile = load_profile("test_child", tmp_dir)
        self.assertEqual(profile.display_name, "Đánh Giá Đồ Ăn — @luenguynnn")
        self.assertIn("ẩm thực", profile.description)

    def test_vietnamese_keywords_survive_round_trip(self):
        child_with_kw = {
            **MINIMAL_CHILD,
            "preprocessing": {
                **MINIMAL_CHILD.get("preprocessing", {}),
                "mode": "strict",
                "remove_recording_cues": True,
                "hallucination_volume_threshold_db": -40,
                "caption_grouping": {"enabled": False, "words_per_group": 4},
                "punch_in": {
                    "enabled": True,
                    "keywords": ["sản phẩm", "giảm giá", "mua ngay", "chất lượng tốt"],
                },
            },
        }
        tmp_dir = _make_profiles_dir({"base": MINIMAL_BASE, "test_child": child_with_kw})
        profile = load_profile("test_child", tmp_dir)
        kws = list(profile.preprocessing.punch_in.keywords)
        self.assertIn("sản phẩm", kws)
        self.assertIn("chất lượng tốt", kws)

    def test_json_serialization_preserves_unicode(self):
        import json
        child = {
            **MINIMAL_CHILD,
            "display_name": "Đánh Giá Thực Phẩm",
        }
        raw_dir = _make_profiles_dir({"base": MINIMAL_BASE, "test_child": child})
        raw = load_profile_raw("test_child", raw_dir)
        serialized = json.dumps(raw, ensure_ascii=False)
        self.assertIn("Đánh Giá Thực Phẩm", serialized)
        reparsed = json.loads(serialized)
        self.assertEqual(reparsed["display_name"], "Đánh Giá Thực Phẩm")


if __name__ == "__main__":
    unittest.main()
