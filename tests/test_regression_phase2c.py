"""Regression tests for Phase 2 Correction.

Tests:
- Exact preserved food_review values (REPOSITORY-DERIVED)
- Exact corrected lifestyle_vlog values
- Exact corrected affiliate_fast values
- Weight totals == 100 for all profiles
- profiles list 4-column output structure
- Mutually exclusive --all and profile_id
- min <= default <= max constraint
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from auto_video_editor.cli import build_parser, main
from auto_video_editor.exceptions import ProfileValidationError
from auto_video_editor.profiles.loader import load_profile, load_profile_raw
from auto_video_editor.profiles.validation import validate_profile

import subprocess, os


def _run(args: list[str], profiles_dir: Path | None = None) -> tuple[int, str, str]:
    cmd = [sys.executable, "-m", "auto_video_editor"]
    if profiles_dir is not None:
        cmd += ["--profiles-dir", str(profiles_dir)]
    cmd += args
    result = subprocess.run(
        cmd,
        capture_output=True,
        cwd=str(_REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(_REPO_ROOT / "src")},
    )
    return (
        result.returncode,
        result.stdout.decode("utf-8", errors="replace"),
        result.stderr.decode("utf-8", errors="replace"),
    )


REAL_DIR = _REPO_ROOT / "configs" / "profiles"


def _skip_if_no_profiles(test):
    """Decorator to skip test if real profiles dir is absent."""
    import functools
    @functools.wraps(test)
    def wrapper(self, *args, **kwargs):
        if not REAL_DIR.is_dir():
            self.skipTest("Real profiles dir not found")
        return test(self, *args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# food_review regression — REPOSITORY-DERIVED, must NOT change
# ---------------------------------------------------------------------------

class TestFoodReviewPreserved(unittest.TestCase):
    """Lock all food_review values as REPOSITORY-DERIVED."""

    def setUp(self):
        if not REAL_DIR.is_dir():
            self.skipTest("Real profiles dir not found")
        self.profile = load_profile("food_review", REAL_DIR)

    def test_reference_duration_is_45(self):
        self.assertEqual(self.profile.reference_duration_seconds, 45)

    def test_no_min_duration(self):
        self.assertIsNone(self.profile.min_duration_seconds)

    def test_no_max_duration(self):
        self.assertIsNone(self.profile.max_duration_seconds)

    def test_account_is_luenguynnn(self):
        self.assertEqual(self.profile.account, "@luenguynnn")

    def test_stage_count_is_5(self):
        self.assertEqual(len(self.profile.narrative_stages), 5)

    def test_stage_names_in_order(self):
        names = [s.name for s in self.profile.narrative_stages]
        self.assertEqual(names, [
            "visual_hook", "location_or_main_dish", "experience", "review", "cta"
        ])

    def test_stage_visual_hook_0_to_2(self):
        s = self.profile.narrative_stages[0]
        self.assertEqual(s.start_seconds, 0)
        self.assertEqual(s.end_seconds, 2)

    def test_stage_location_or_main_dish_2_to_6(self):
        s = self.profile.narrative_stages[1]
        self.assertEqual(s.start_seconds, 2)
        self.assertEqual(s.end_seconds, 6)

    def test_stage_experience_6_to_25(self):
        s = self.profile.narrative_stages[2]
        self.assertEqual(s.start_seconds, 6)
        self.assertEqual(s.end_seconds, 25)

    def test_stage_review_25_to_38(self):
        s = self.profile.narrative_stages[3]
        self.assertEqual(s.start_seconds, 25)
        self.assertEqual(s.end_seconds, 38)

    def test_stage_cta_38_to_45(self):
        s = self.profile.narrative_stages[4]
        self.assertEqual(s.start_seconds, 38)
        self.assertEqual(s.end_seconds, 45)

    def test_weight_food_appeal_25(self):
        self.assertEqual(self.profile.scoring.weights["food_appeal"], 25)

    def test_weight_visibility_20(self):
        self.assertEqual(self.profile.scoring.weights["visibility"], 20)

    def test_weight_motion_15(self):
        self.assertEqual(self.profile.scoring.weights["motion"], 15)

    def test_weight_technical_quality_15(self):
        self.assertEqual(self.profile.scoring.weights["technical_quality"], 15)

    def test_weight_composition_10(self):
        self.assertEqual(self.profile.scoring.weights["composition"], 10)

    def test_weight_narrative_10(self):
        self.assertEqual(self.profile.scoring.weights["narrative"], 10)

    def test_weight_emotion_5(self):
        self.assertEqual(self.profile.scoring.weights["emotion"], 5)

    def test_weight_total_100(self):
        self.assertEqual(self.profile.scoring.total, 100)

    def test_validates_successfully(self):
        validate_profile(self.profile)  # must not raise


# ---------------------------------------------------------------------------
# lifestyle_vlog corrections
# ---------------------------------------------------------------------------

class TestLifestyleVlogCorrections(unittest.TestCase):

    def setUp(self):
        if not REAL_DIR.is_dir():
            self.skipTest("Real profiles dir not found")
        self.profile = load_profile("lifestyle_vlog", REAL_DIR)

    def test_reference_duration_is_45(self):
        self.assertEqual(self.profile.reference_duration_seconds, 45)

    def test_min_duration_is_30(self):
        self.assertEqual(self.profile.min_duration_seconds, 30)

    def test_max_duration_is_60(self):
        self.assertEqual(self.profile.max_duration_seconds, 60)

    def test_min_le_default_le_max(self):
        self.assertLessEqual(self.profile.min_duration_seconds, self.profile.reference_duration_seconds)
        self.assertLessEqual(self.profile.reference_duration_seconds, self.profile.max_duration_seconds)

    def test_account_is_bylue(self):
        self.assertEqual(self.profile.account, "@_bylue")

    def test_preserve_ambient_true(self):
        self.assertTrue(self.profile.audio.preserve_ambient)

    def test_stage_count_is_5(self):
        self.assertEqual(len(self.profile.narrative_stages), 5)

    def test_stage_names_in_order(self):
        names = [s.name for s in self.profile.narrative_stages]
        self.assertEqual(names, [
            "cold_open", "arrival_or_context", "exploration",
            "highlight", "reflection_or_closing"
        ])

    def test_cold_open_0_to_2_required(self):
        s = self.profile.narrative_stages[0]
        self.assertEqual(s.start_seconds, 0)
        self.assertEqual(s.end_seconds, 2)
        self.assertTrue(s.required)

    def test_arrival_or_context_2_to_8(self):
        s = self.profile.narrative_stages[1]
        self.assertEqual(s.start_seconds, 2)
        self.assertEqual(s.end_seconds, 8)
        self.assertFalse(s.required)

    def test_exploration_8_to_27_required(self):
        s = self.profile.narrative_stages[2]
        self.assertEqual(s.start_seconds, 8)
        self.assertEqual(s.end_seconds, 27)
        self.assertTrue(s.required)

    def test_highlight_27_to_38_required(self):
        s = self.profile.narrative_stages[3]
        self.assertEqual(s.start_seconds, 27)
        self.assertEqual(s.end_seconds, 38)
        self.assertTrue(s.required)

    def test_reflection_or_closing_38_to_45(self):
        s = self.profile.narrative_stages[4]
        self.assertEqual(s.start_seconds, 38)
        self.assertEqual(s.end_seconds, 45)
        self.assertFalse(s.required)

    def test_weight_story_relevance_25(self):
        self.assertEqual(self.profile.scoring.weights["story_relevance"], 25)

    def test_weight_emotion_and_human_moment_20(self):
        self.assertEqual(self.profile.scoring.weights["emotion_and_human_moment"], 20)

    def test_weight_visual_quality_20(self):
        self.assertEqual(self.profile.scoring.weights["visual_quality"], 20)

    def test_weight_technical_quality_15(self):
        self.assertEqual(self.profile.scoring.weights["technical_quality"], 15)

    def test_weight_visual_variety_10(self):
        self.assertEqual(self.profile.scoring.weights["visual_variety"], 10)

    def test_weight_motion_and_transition_potential_10(self):
        self.assertEqual(self.profile.scoring.weights["motion_and_transition_potential"], 10)

    def test_weight_total_100(self):
        self.assertEqual(self.profile.scoring.total, 100)

    def test_validates_successfully(self):
        validate_profile(self.profile)


# ---------------------------------------------------------------------------
# affiliate_fast corrections
# ---------------------------------------------------------------------------

class TestAffiliateFastCorrections(unittest.TestCase):

    def setUp(self):
        if not REAL_DIR.is_dir():
            self.skipTest("Real profiles dir not found")
        self.profile = load_profile("affiliate_fast", REAL_DIR)

    def test_reference_duration_is_40(self):
        self.assertEqual(self.profile.reference_duration_seconds, 40)

    def test_min_duration_is_25(self):
        self.assertEqual(self.profile.min_duration_seconds, 25)

    def test_max_duration_is_50(self):
        self.assertEqual(self.profile.max_duration_seconds, 50)

    def test_min_le_default_le_max(self):
        self.assertLessEqual(self.profile.min_duration_seconds, self.profile.reference_duration_seconds)
        self.assertLessEqual(self.profile.reference_duration_seconds, self.profile.max_duration_seconds)

    def test_account_is_iz_lue(self):
        self.assertEqual(self.profile.account, "@iz_lue")

    def test_stage_count_is_5(self):
        self.assertEqual(len(self.profile.narrative_stages), 5)

    def test_stage_names_in_order(self):
        names = [s.name for s in self.profile.narrative_stages]
        self.assertEqual(names, [
            "result_or_pain_hook", "product_context", "demonstration",
            "experience_or_evidence", "recommendation_and_cta"
        ])

    def test_result_or_pain_hook_0_to_2_required(self):
        s = self.profile.narrative_stages[0]
        self.assertEqual(s.start_seconds, 0)
        self.assertEqual(s.end_seconds, 2)
        self.assertTrue(s.required)

    def test_product_context_2_to_7_required(self):
        s = self.profile.narrative_stages[1]
        self.assertEqual(s.start_seconds, 2)
        self.assertEqual(s.end_seconds, 7)
        self.assertTrue(s.required)

    def test_demonstration_7_to_22_required(self):
        s = self.profile.narrative_stages[2]
        self.assertEqual(s.start_seconds, 7)
        self.assertEqual(s.end_seconds, 22)
        self.assertTrue(s.required)

    def test_experience_or_evidence_22_to_34(self):
        s = self.profile.narrative_stages[3]
        self.assertEqual(s.start_seconds, 22)
        self.assertEqual(s.end_seconds, 34)
        self.assertFalse(s.required)

    def test_recommendation_and_cta_34_to_40(self):
        s = self.profile.narrative_stages[4]
        self.assertEqual(s.start_seconds, 34)
        self.assertEqual(s.end_seconds, 40)
        self.assertFalse(s.required)

    def test_weight_hook_and_result_strength_25(self):
        self.assertEqual(self.profile.scoring.weights["hook_and_result_strength"], 25)

    def test_weight_speech_clarity_20(self):
        self.assertEqual(self.profile.scoring.weights["speech_clarity"], 20)

    def test_weight_product_visibility_20(self):
        self.assertEqual(self.profile.scoring.weights["product_visibility"], 20)

    def test_weight_demonstration_value_15(self):
        self.assertEqual(self.profile.scoring.weights["demonstration_value"], 15)

    def test_weight_evidence_and_credibility_10(self):
        self.assertEqual(self.profile.scoring.weights["evidence_and_credibility"], 10)

    def test_weight_technical_quality_10(self):
        self.assertEqual(self.profile.scoring.weights["technical_quality"], 10)

    def test_weight_total_100(self):
        self.assertEqual(self.profile.scoring.total, 100)

    def test_caption_grouping_enabled(self):
        self.assertTrue(self.profile.preprocessing.caption_grouping.enabled)

    def test_caption_grouping_min_2(self):
        self.assertEqual(self.profile.preprocessing.caption_grouping.words_per_group_min, 2)

    def test_caption_grouping_max_5(self):
        self.assertEqual(self.profile.preprocessing.caption_grouping.words_per_group_max, 5)

    def test_punch_in_enabled(self):
        self.assertTrue(self.profile.preprocessing.punch_in.enabled)

    def test_vietnamese_keywords_present(self):
        kws = list(self.profile.preprocessing.punch_in.keywords)
        combined = " ".join(kws)
        self.assertIn("sản phẩm", combined)

    def test_validates_successfully(self):
        validate_profile(self.profile)


# ---------------------------------------------------------------------------
# Duration bounds validation
# ---------------------------------------------------------------------------

class TestDurationBoundsValidation(unittest.TestCase):

    def _make_profile_with_bounds(self, ref, mn, mx):
        from auto_video_editor.profiles.models import (
            AudioConfig, CaptionGrouping, CodecConfig, ContentProfile,
            FontConfig, PreprocessingConfig, PunchInConfig, Resolution,
            SafeZone, ScoringWeights, SubtitleConfig,
        )
        return ContentProfile(
            schema_version="1.0.0",
            profile_id="test_bounds",
            display_name="Test",
            extends="base",
            reference_duration_seconds=ref,
            min_duration_seconds=mn,
            max_duration_seconds=mx,
            scoring=ScoringWeights({"a": 100}),
            resolution=Resolution(),
            codec=CodecConfig(),
            subtitle=SubtitleConfig(safe_zone=SafeZone(), font=FontConfig()),
            audio=AudioConfig(),
            preprocessing=PreprocessingConfig(
                caption_grouping=CaptionGrouping(), punch_in=PunchInConfig()
            ),
        )

    def test_valid_bounds_pass(self):
        p = self._make_profile_with_bounds(45, 30, 60)
        validate_profile(p)

    def test_min_gt_default_fails(self):
        p = self._make_profile_with_bounds(45, 50, 60)
        with self.assertRaises(ProfileValidationError):
            validate_profile(p)

    def test_max_lt_default_fails(self):
        p = self._make_profile_with_bounds(45, 30, 40)
        with self.assertRaises(ProfileValidationError):
            validate_profile(p)

    def test_min_equals_default_passes(self):
        p = self._make_profile_with_bounds(45, 45, 60)
        validate_profile(p)

    def test_max_equals_default_passes(self):
        p = self._make_profile_with_bounds(45, 30, 45)
        validate_profile(p)

    def test_no_bounds_passes(self):
        p = self._make_profile_with_bounds(45, None, None)
        validate_profile(p)


# ---------------------------------------------------------------------------
# CLI: 4-column profiles list
# ---------------------------------------------------------------------------

class TestCliProfilesListFourColumns(unittest.TestCase):

    @_skip_if_no_profiles
    def test_list_has_header_row(self):
        code, out, _ = _run(["profiles", "list"], REAL_DIR)
        self.assertEqual(code, 0)
        lines = out.strip().splitlines()
        self.assertGreater(len(lines), 0)
        header = lines[0]
        self.assertIn("ID", header)
        self.assertIn("Display Name", header)

    @_skip_if_no_profiles
    def test_list_data_rows_contain_duration(self):
        code, out, _ = _run(["profiles", "list"], REAL_DIR)
        self.assertEqual(code, 0)
        data_lines = out.strip().splitlines()[1:]  # skip header
        for line in data_lines:
            # Each row should end with a duration like "40s", "45s"
            self.assertRegex(line.strip(), r'\d+s\s*$')

    @_skip_if_no_profiles
    def test_list_food_review_row_contains_correct_handle(self):
        code, out, _ = _run(["profiles", "list"], REAL_DIR)
        self.assertEqual(code, 0)
        food_line = next(l for l in out.splitlines() if "food_review" in l)
        self.assertIn("@luenguynnn", food_line)
        self.assertIn("45s", food_line)

    @_skip_if_no_profiles
    def test_list_lifestyle_vlog_row_shows_45s(self):
        code, out, _ = _run(["profiles", "list"], REAL_DIR)
        self.assertEqual(code, 0)
        lv_line = next(l for l in out.splitlines() if "lifestyle_vlog" in l)
        self.assertIn("45s", lv_line)
        self.assertIn("@_bylue", lv_line)

    @_skip_if_no_profiles
    def test_list_affiliate_fast_row_shows_40s(self):
        code, out, _ = _run(["profiles", "list"], REAL_DIR)
        self.assertEqual(code, 0)
        af_line = next(l for l in out.splitlines() if "affiliate_fast" in l)
        self.assertIn("40s", af_line)
        self.assertIn("@iz_lue", af_line)

    @_skip_if_no_profiles
    def test_list_row_count_equals_profile_count_plus_header(self):
        code, out, _ = _run(["profiles", "list"], REAL_DIR)
        self.assertEqual(code, 0)
        lines = [l for l in out.strip().splitlines() if l.strip()]
        # 1 header + 3 profiles
        self.assertEqual(len(lines), 4)


# ---------------------------------------------------------------------------
# CLI: validate mutual exclusion and no-arg behavior
# ---------------------------------------------------------------------------

class TestCliValidateBehavior(unittest.TestCase):

    @_skip_if_no_profiles
    def test_no_arg_validates_all_exits_0(self):
        code, out, _ = _run(["profiles", "validate"], REAL_DIR)
        self.assertEqual(code, 0)
        self.assertIn("OK", out)

    @_skip_if_no_profiles
    def test_all_flag_validates_all_exits_0(self):
        code, out, _ = _run(["profiles", "validate", "--all"], REAL_DIR)
        self.assertEqual(code, 0)

    @_skip_if_no_profiles
    def test_specific_id_validates_only_that_profile(self):
        code, out, _ = _run(["profiles", "validate", "food_review"], REAL_DIR)
        self.assertEqual(code, 0)
        self.assertIn("food_review", out)

    @_skip_if_no_profiles
    def test_id_plus_all_exits_2(self):
        code, _, err = _run(["profiles", "validate", "food_review", "--all"], REAL_DIR)
        self.assertEqual(code, 2)
        self.assertIn("mutually exclusive", err)

    def test_main_no_arg_returns_0(self):
        from auto_video_editor.cli import main as cli_main
        real_dir = _REPO_ROOT / "configs" / "profiles"
        if not real_dir.is_dir():
            self.skipTest("Real profiles dir not found")
        code = cli_main(["--profiles-dir", str(real_dir), "profiles", "validate"])
        self.assertEqual(code, 0)

    def test_main_id_plus_all_returns_2(self):
        from auto_video_editor.cli import main as cli_main
        real_dir = _REPO_ROOT / "configs" / "profiles"
        if not real_dir.is_dir():
            self.skipTest("Real profiles dir not found")
        code = cli_main([
            "--profiles-dir", str(real_dir),
            "profiles", "validate", "food_review", "--all"
        ])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
