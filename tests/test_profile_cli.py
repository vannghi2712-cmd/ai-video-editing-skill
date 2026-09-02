"""Tests for the CLI: profiles list, show, validate commands.

Uses subprocess for output capture so sys.stdout.buffer.write works correctly.
Internal main() is also called directly for exit-code-only checks.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from auto_video_editor.cli import build_parser, main


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

MINIMAL_CHILD_ALPHA = {
    "$schema_version": "1.0.0",
    "profile_id": "alpha_profile",
    "extends": "base",
    "display_name": "Alpha",
    "reference_duration_seconds": 30,
    "narrative": {"stages": [
        {"name": "hook", "label": "Hook", "start_seconds": 0, "end_seconds": 3, "description": ""},
        {"name": "body", "label": "Body", "start_seconds": 3, "end_seconds": 27, "description": ""},
        {"name": "cta", "label": "CTA", "start_seconds": 27, "end_seconds": 30, "description": ""},
    ]},
    "scoring": {"weights": {"hook_strength": 40, "clarity": 35, "quality": 25}},
}

MINIMAL_CHILD_BETA = {
    "$schema_version": "1.0.0",
    "profile_id": "beta_profile",
    "extends": "base",
    "display_name": "Beta",
    "reference_duration_seconds": 60,
    "narrative": {"stages": [
        {"name": "intro", "label": "Intro", "start_seconds": 0, "end_seconds": 10, "description": ""},
    ]},
    "scoring": {"weights": {"story": 60, "quality": 40}},
}


def _make_profiles_dir(**profiles) -> Path:
    tmp = Path(tempfile.mkdtemp())
    for name, data in profiles.items():
        (tmp / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return tmp


def _run(args: list[str], profiles_dir: Path | None = None) -> tuple[int, str, str]:
    """Run CLI via subprocess, return (exit_code, stdout, stderr)."""
    cmd = [sys.executable, "-m", "auto_video_editor"]
    if profiles_dir is not None:
        cmd += ["--profiles-dir", str(profiles_dir)]
    cmd += args
    result = subprocess.run(
        cmd,
        capture_output=True,
        cwd=str(_REPO_ROOT),
        env={**__import__("os").environ, "PYTHONPATH": str(_REPO_ROOT / "src")},
    )
    return (
        result.returncode,
        result.stdout.decode("utf-8", errors="replace"),
        result.stderr.decode("utf-8", errors="replace"),
    )


# ---------------------------------------------------------------------------
# CLI: profiles list
# ---------------------------------------------------------------------------

class TestCliProfilesList(unittest.TestCase):

    def setUp(self):
        self.profiles_dir = _make_profiles_dir(
            base=MINIMAL_BASE,
            alpha_profile=MINIMAL_CHILD_ALPHA,
            beta_profile=MINIMAL_CHILD_BETA,
        )

    def test_list_exit_code_0(self):
        code, _, _ = _run(["profiles", "list"], self.profiles_dir)
        self.assertEqual(code, 0)

    def test_list_output_is_sorted(self):
        _, out, _ = _run(["profiles", "list"], self.profiles_dir)
        lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
        self.assertEqual(lines, sorted(lines))

    def test_list_excludes_base(self):
        _, out, _ = _run(["profiles", "list"], self.profiles_dir)
        lines = out.strip().splitlines()
        self.assertNotIn("base", lines)

    def test_list_includes_child_profiles(self):
        _, out, _ = _run(["profiles", "list"], self.profiles_dir)
        lines = out.strip().splitlines()
        self.assertIn("alpha_profile", lines)
        self.assertIn("beta_profile", lines)

    def test_list_is_deterministic(self):
        _, out1, _ = _run(["profiles", "list"], self.profiles_dir)
        _, out2, _ = _run(["profiles", "list"], self.profiles_dir)
        self.assertEqual(out1, out2)

    def test_real_list_exit_0(self):
        real_dir = _REPO_ROOT / "configs" / "profiles"
        if not real_dir.is_dir():
            self.skipTest("Real profiles dir not found")
        code, out, _ = _run(["profiles", "list"], real_dir)
        self.assertEqual(code, 0)
        ids = out.strip().splitlines()
        self.assertIn("food_review", ids)
        self.assertIn("lifestyle_vlog", ids)
        self.assertIn("affiliate_fast", ids)
        self.assertNotIn("base", ids)


# ---------------------------------------------------------------------------
# CLI: profiles show
# ---------------------------------------------------------------------------

class TestCliProfilesShow(unittest.TestCase):

    def setUp(self):
        self.profiles_dir = _make_profiles_dir(
            base=MINIMAL_BASE,
            alpha_profile=MINIMAL_CHILD_ALPHA,
        )

    def test_show_exit_code_0_for_valid_profile(self):
        code, _, _ = _run(["profiles", "show", "alpha_profile"], self.profiles_dir)
        self.assertEqual(code, 0)

    def test_show_outputs_valid_json(self):
        _, out, _ = _run(["profiles", "show", "alpha_profile"], self.profiles_dir)
        parsed = json.loads(out)
        self.assertEqual(parsed["profile_id"], "alpha_profile")

    def test_show_merged_profile_includes_base_fields(self):
        _, out, _ = _run(["profiles", "show", "alpha_profile"], self.profiles_dir)
        parsed = json.loads(out)
        self.assertIn("codec", parsed)
        self.assertIn("subtitle", parsed)

    def test_show_unknown_profile_exits_nonzero(self):
        code, _, _ = _run(["profiles", "show", "no_such_profile"], self.profiles_dir)
        self.assertNotEqual(code, 0)

    def test_show_path_traversal_exits_nonzero(self):
        code, _, _ = _run(["profiles", "show", "../base"], self.profiles_dir)
        self.assertNotEqual(code, 0)

    def test_show_real_food_review(self):
        real_dir = _REPO_ROOT / "configs" / "profiles"
        if not real_dir.is_dir():
            self.skipTest("Real profiles dir not found")
        code, out, _ = _run(["profiles", "show", "food_review"], real_dir)
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertEqual(parsed["profile_id"], "food_review")

    def test_show_real_affiliate_fast_with_vietnamese(self):
        real_dir = _REPO_ROOT / "configs" / "profiles"
        if not real_dir.is_dir():
            self.skipTest("Real profiles dir not found")
        code, out, _ = _run(["profiles", "show", "affiliate_fast"], real_dir)
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        keywords = parsed["preprocessing"]["punch_in"]["keywords"]
        combined = " ".join(keywords)
        self.assertIn("sản phẩm", combined)

    def test_show_unicode_preserved_in_output(self):
        child_viet = {
            **MINIMAL_CHILD_ALPHA,
            "profile_id": "viet_test",
            "display_name": "Đánh Giá Sản Phẩm",
        }
        d = _make_profiles_dir(base=MINIMAL_BASE, viet_test=child_viet)
        code, out, _ = _run(["profiles", "show", "viet_test"], d)
        self.assertEqual(code, 0)
        self.assertIn("Đánh Giá Sản Phẩm", out)


# ---------------------------------------------------------------------------
# CLI: profiles validate
# ---------------------------------------------------------------------------

class TestCliProfilesValidate(unittest.TestCase):

    def setUp(self):
        self.profiles_dir = _make_profiles_dir(
            base=MINIMAL_BASE,
            alpha_profile=MINIMAL_CHILD_ALPHA,
            beta_profile=MINIMAL_CHILD_BETA,
        )

    def test_validate_single_valid_exits_0(self):
        code, _, _ = _run(["profiles", "validate", "alpha_profile"], self.profiles_dir)
        self.assertEqual(code, 0)

    def test_validate_all_valid_exits_0(self):
        code, _, _ = _run(["profiles", "validate", "--all"], self.profiles_dir)
        self.assertEqual(code, 0)

    def test_validate_unknown_exits_nonzero(self):
        code, _, _ = _run(["profiles", "validate", "ghost"], self.profiles_dir)
        self.assertNotEqual(code, 0)

    def test_validate_bad_weights_exits_nonzero(self):
        bad_child = {
            **MINIMAL_CHILD_ALPHA,
            "profile_id": "bad_weights",
            "scoring": {"weights": {"a": 50, "b": 10}},  # sum = 60
        }
        d = _make_profiles_dir(base=MINIMAL_BASE, bad_weights=bad_child)
        code, _, _ = _run(["profiles", "validate", "bad_weights"], d)
        self.assertNotEqual(code, 0)

    def test_validate_overlapping_stages_exits_nonzero(self):
        bad_child = {
            **MINIMAL_CHILD_ALPHA,
            "profile_id": "bad_stages",
            "narrative": {"stages": [
                {"name": "a", "label": "A", "start_seconds": 0, "end_seconds": 20, "description": ""},
                {"name": "b", "label": "B", "start_seconds": 15, "end_seconds": 30, "description": ""},
            ]},
        }
        d = _make_profiles_dir(base=MINIMAL_BASE, bad_stages=bad_child)
        code, _, _ = _run(["profiles", "validate", "bad_stages"], d)
        self.assertNotEqual(code, 0)

    def test_validate_all_with_one_bad_exits_nonzero(self):
        bad_child = {
            **MINIMAL_CHILD_ALPHA,
            "profile_id": "broken",
            "scoring": {"weights": {"x": 1}},  # sum = 1
        }
        d = _make_profiles_dir(
            base=MINIMAL_BASE,
            alpha_profile=MINIMAL_CHILD_ALPHA,
            broken=bad_child,
        )
        code, _, _ = _run(["profiles", "validate", "--all"], d)
        self.assertNotEqual(code, 0)

    def test_validate_real_all_exits_0(self):
        real_dir = _REPO_ROOT / "configs" / "profiles"
        if not real_dir.is_dir():
            self.skipTest("Real profiles dir not found")
        code, out, _ = _run(["profiles", "validate", "--all"], real_dir)
        self.assertEqual(code, 0, f"Validation failed:\n{out}")

    def test_validate_path_traversal_exits_nonzero(self):
        code, _, _ = _run(["profiles", "validate", "../base"], self.profiles_dir)
        self.assertNotEqual(code, 0)


# ---------------------------------------------------------------------------
# CLI parser structure tests
# ---------------------------------------------------------------------------

class TestCliParser(unittest.TestCase):

    def test_parser_builds_without_error(self):
        parser = build_parser()
        self.assertIsNotNone(parser)

    def test_no_args_exits_with_usage_error(self):
        code = main([])
        self.assertEqual(code, 2)

    def test_real_list_via_main(self):
        real_dir = _REPO_ROOT / "configs" / "profiles"
        if not real_dir.is_dir():
            self.skipTest("Real profiles dir not found")
        code = main(["--profiles-dir", str(real_dir), "profiles", "list"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
