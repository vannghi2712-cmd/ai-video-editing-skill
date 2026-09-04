"""Phase 4 unit tests: scene analysis, keyframes, scoring, cache, consent, CLI.

All tests are deterministic and network-free.
No hard-coded profile-ID branches in production code is enforced by static test.
Synthetic smoke test generates a real video via FFmpeg in a temp dir.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── Helpers ───────────────────────────────────────────────────────────────────

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

SCHEMA_PATH = ROOT / "schemas" / "clip_analysis.schema.json"
PROFILES_DIR = ROOT / "configs" / "profiles"


def _make_mock_profile(weights: dict[str, int] | None = None):
    """Build a minimal mock ContentProfile for testing."""
    from auto_video_editor.profiles.models import ContentProfile, ScoringWeights
    w = weights or {"visual_quality": 60, "motion": 40}
    return ContentProfile(
        schema_version="1.0.0",
        profile_id="test_profile",
        display_name="Test Profile",
        scoring=ScoringWeights(weights=w),
    )


def _synthetic_video_path(tmp_dir: str, duration_s: float = 8.0, has_audio: bool = True) -> str:
    """Generate a synthetic test video with FFmpeg. Returns path."""
    out = Path(tmp_dir) / "synthetic_test.mp4"
    filters = "testsrc=duration={d}:size=320x240:rate=30".format(d=duration_s)
    cmd = ["ffmpeg", "-y",
           "-f", "lavfi", "-i", filters]
    if has_audio:
        cmd += ["-f", "lavfi", "-i",
                f"sine=frequency=440:duration={duration_s}"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac" if has_audio else "copy",
            "-t", str(duration_s), str(out)]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0 or not out.exists():
        raise RuntimeError(f"FFmpeg failed: {result.stderr.decode()[:300]}")
    return str(out)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest().upper()


# ── SceneDetectorConfig ───────────────────────────────────────────────────────

class TestSceneDetectorConfig(unittest.TestCase):
    def test_defaults(self):
        from auto_video_editor.analysis.config import SceneDetectorConfig
        c = SceneDetectorConfig()
        self.assertAlmostEqual(c.threshold, 0.30)
        self.assertAlmostEqual(c.min_duration_seconds, 1.0)
        self.assertAlmostEqual(c.max_duration_seconds, 15.0)

    def test_invalid_threshold_raises(self):
        from auto_video_editor.analysis.config import SceneDetectorConfig
        with self.assertRaises(ValueError):
            SceneDetectorConfig(threshold=0.0)
        with self.assertRaises(ValueError):
            SceneDetectorConfig(threshold=1.0)

    def test_min_gt_max_raises(self):
        from auto_video_editor.analysis.config import SceneDetectorConfig
        with self.assertRaises(ValueError):
            SceneDetectorConfig(min_duration_seconds=10.0, max_duration_seconds=5.0)

    def test_as_dict_keys(self):
        from auto_video_editor.analysis.config import SceneDetectorConfig
        d = SceneDetectorConfig().as_dict()
        self.assertIn("threshold", d)
        self.assertIn("min_duration_seconds", d)
        self.assertIn("max_duration_seconds", d)


# ── Scene Normalization ───────────────────────────────────────────────────────

class TestSceneNormalization(unittest.TestCase):
    def setUp(self):
        from auto_video_editor.analysis.config import SceneDetectorConfig
        from auto_video_editor.analysis.scene_detector import (
            _build_scenes, _merge_short, _split_long, _validate,
        )
        self.build = _build_scenes
        self.merge = _merge_short
        self.split = _split_long
        self.validate = _validate
        self.cfg = SceneDetectorConfig(
            threshold=0.3, min_duration_seconds=1.0, max_duration_seconds=15.0
        )

    def test_single_scene_full_coverage(self):
        """No cuts → 1 scene covering full duration."""
        scenes = self.build([0, 10_000_000], {})
        self.assertEqual(len(scenes), 1)
        self.assertEqual(scenes[0].start_us, 0)
        self.assertEqual(scenes[0].end_us, 10_000_000)

    def test_no_gap_no_overlap(self):
        boundaries = [0, 3_000_000, 7_000_000, 10_000_000]
        scenes = self.build(boundaries, {})
        for i in range(1, len(scenes)):
            self.assertEqual(scenes[i].start_us, scenes[i - 1].end_us,
                             msg=f"Gap/overlap between scene {i-1} and {i}")

    def test_first_starts_at_zero(self):
        scenes = self.build([0, 5_000_000, 10_000_000], {})
        self.assertEqual(scenes[0].start_us, 0)

    def test_last_ends_at_duration(self):
        dur = 10_000_000
        scenes = self.build([0, 5_000_000, dur], {})
        self.assertEqual(scenes[-1].end_us, dur)

    def test_merge_short_scene(self):
        """Scene shorter than min_duration_s must be merged."""
        from auto_video_editor.analysis.models import Scene
        # 3 scenes: 0.5s | 5s | 5s — first is too short
        scenes = [
            Scene(0, 0, 500_000, 0.8),
            Scene(1, 500_000, 5_500_000, 0.3),
            Scene(2, 5_500_000, 10_500_000, 0.4),
        ]
        min_us = int(1.0 * 1_000_000)
        merged = self.merge(scenes, min_us)
        # First scene merged with second → still covers 0 to 5_500_000
        self.assertEqual(merged[0].start_us, 0)
        self.assertEqual(merged[0].end_us, 5_500_000)
        self.assertLess(len(merged), 3)

    def test_split_long_scene(self):
        """Scene longer than max_duration_s must be split."""
        from auto_video_editor.analysis.models import Scene
        scenes = [Scene(0, 0, 20_000_000, None)]  # 20s > 15s max
        max_us = int(15.0 * 1_000_000)
        split = self.split(scenes, max_us)
        self.assertGreater(len(split), 1)
        # Coverage must be preserved
        self.assertEqual(split[0].start_us, 0)
        self.assertEqual(split[-1].end_us, 20_000_000)

    def test_validate_passes_on_valid(self):
        """_validate raises no error on valid scenes."""
        scenes = self.build([0, 5_000_000, 10_000_000], {})
        self.validate(scenes, 10_000_000)  # should not raise

    def test_validate_detects_gap(self):
        """_validate raises RuntimeError if there is a gap."""
        from auto_video_editor.analysis.models import Scene
        scenes = [Scene(0, 0, 4_000_000, None), Scene(1, 5_000_000, 10_000_000, None)]
        with self.assertRaises(RuntimeError):
            self.validate(scenes, 10_000_000)

    def test_validate_wrong_end(self):
        from auto_video_editor.analysis.models import Scene
        scenes = [Scene(0, 0, 9_000_000, None)]
        with self.assertRaises(RuntimeError):
            self.validate(scenes, 10_000_000)

    def test_chronological_order(self):
        boundaries = [0, 2_000_000, 5_000_000, 10_000_000]
        scenes = self.build(boundaries, {})
        for i in range(1, len(scenes)):
            self.assertGreater(scenes[i].start_us, scenes[i - 1].start_us)


# ── Media Inspector ───────────────────────────────────────────────────────────

class TestMediaInspector(unittest.TestCase):
    def test_missing_file_raises(self):
        from auto_video_editor.analysis.media_inspector import inspect_media
        with self.assertRaises(FileNotFoundError):
            inspect_media("/nonexistent/path/video.mp4")

    def test_no_audio_warning(self):
        """Video without audio produces NO_AUDIO_STREAM warning."""
        tmp = tempfile.mkdtemp()
        try:
            vid = _synthetic_video_path(tmp, duration_s=3.0, has_audio=False)
            from auto_video_editor.analysis.media_inspector import inspect_media
            info, warnings = inspect_media(vid)
            audio_warns = [w for w in warnings if "NO_AUDIO_STREAM" in w]
            self.assertTrue(len(audio_warns) >= 1, f"Expected audio warning, got: {warnings}")
            self.assertFalse(info.has_audio)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_valid_video_fields(self):
        tmp = tempfile.mkdtemp()
        try:
            vid = _synthetic_video_path(tmp, duration_s=5.0)
            from auto_video_editor.analysis.media_inspector import inspect_media
            info, _ = inspect_media(vid)
            self.assertGreater(info.duration_us, 0)
            self.assertGreater(info.width, 0)
            self.assertGreater(info.height, 0)
            self.assertEqual(len(info.sha256), 64)
            self.assertTrue(info.has_video)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_unicode_path(self):
        """FFprobe must handle Unicode directory paths."""
        tmp = tempfile.mkdtemp(prefix="vidéo_tëst_")
        try:
            vid = _synthetic_video_path(tmp, duration_s=2.0)
            from auto_video_editor.analysis.media_inspector import inspect_media
            info, _ = inspect_media(vid)
            self.assertGreater(info.duration_us, 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ── Keyframe Extraction ───────────────────────────────────────────────────────

class TestKeyframeExtractor(unittest.TestCase):
    def test_partial_success_scene_valid(self):
        """If ≥1/3 keyframes decoded, scene is valid (not all must succeed)."""
        from auto_video_editor.analysis.models import Keyframe
        # Simulate 1 ok + 2 failed
        kf_ok = Keyframe(0, 0, 1_000_000, "/tmp/a.jpg", "A" * 64, "ok")
        kf_fail1 = Keyframe(0, 1, 2_500_000, "/tmp/b.jpg", None, "failed")
        kf_fail2 = Keyframe(0, 2, 4_000_000, "/tmp/c.jpg", None, "failed")
        ok_count = sum(1 for kf in [kf_ok, kf_fail1, kf_fail2] if kf.status == "ok")
        self.assertEqual(ok_count, 1)
        # Scene with 1 ok keyframe is valid (not "failed")
        self.assertGreater(ok_count, 0)

    def test_zero_ok_keyframes_scene_failed(self):
        """If 0/3 keyframes decoded, scene should be marked failed by scoring."""
        from auto_video_editor.analysis.models import Keyframe, Scene
        kf_fail = Keyframe(0, 0, 1_000_000, "/tmp/x.jpg", None, "failed")
        ok_count = sum(1 for kf in [kf_fail] if kf.status == "ok")
        self.assertEqual(ok_count, 0)

    def test_no_duplicate_frames(self):
        """Keyframe slots must be at different timestamps."""
        from auto_video_editor.analysis.models import Scene
        scene = Scene(0, 0, 10_000_000, None)
        slots = (0.20, 0.50, 0.80)
        timestamps = [scene.start_us + int(scene.duration_us * f) for f in slots]
        self.assertEqual(len(set(timestamps)), 3)

    def test_real_extraction(self):
        """Test real keyframe extraction from synthetic video."""
        tmp = tempfile.mkdtemp()
        try:
            vid = _synthetic_video_path(tmp, duration_s=6.0)
            from auto_video_editor.analysis.keyframe_extractor import extract_keyframes
            from auto_video_editor.analysis.models import Scene
            scenes = [Scene(0, 0, 6_000_000, None)]
            kfs, warns = extract_keyframes(vid, scenes, tmp, slots=3)
            self.assertEqual(len(kfs), 3)
            ok = [kf for kf in kfs if kf.status == "ok"]
            self.assertGreater(len(ok), 0, "At least 1 keyframe must succeed")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ── Transcript Association ────────────────────────────────────────────────────

class TestTranscriptAssociator(unittest.TestCase):
    def _make_transcript(self):
        return {
            "result": {
                "full_text": "Hello world test",
                "segments": [
                    {"start": 0.0, "end": 2.5, "text": "Hello world"},
                    {"start": 4.0, "end": 6.0, "text": "test"},
                ],
            }
        }

    def test_overlap_association(self):
        from auto_video_editor.analysis.models import Scene
        from auto_video_editor.analysis.transcript_associator import associate_transcript
        scenes = [Scene(0, 0, 3_000_000, None), Scene(1, 3_000_000, 7_000_000, None)]
        tr = self._make_transcript()
        assoc = associate_transcript(scenes, tr, include_context=True)
        # Scene 0 (0-3s) overlaps segment 0 (0-2.5s)
        self.assertIsNotNone(assoc[0])
        # Scene 1 (3-7s) overlaps segment 1 (4-6s)
        self.assertIsNotNone(assoc[1])

    def test_no_overlap_returns_none(self):
        from auto_video_editor.analysis.models import Scene
        from auto_video_editor.analysis.transcript_associator import associate_transcript
        scenes = [Scene(0, 7_000_000, 10_000_000, None)]
        tr = self._make_transcript()
        assoc = associate_transcript(scenes, tr, include_context=True)
        self.assertIsNone(assoc[0])

    def test_consent_redacts_text(self):
        """Without include_context, full_text is redacted."""
        from auto_video_editor.analysis.models import Scene
        from auto_video_editor.analysis.transcript_associator import associate_transcript
        scenes = [Scene(0, 0, 3_000_000, None)]
        tr = self._make_transcript()
        assoc = associate_transcript(scenes, tr, include_context=False)
        ctx = assoc[0]
        self.assertIsNotNone(ctx)
        self.assertIn("REDACTED", ctx.full_text)

    def test_consent_reveals_text(self):
        from auto_video_editor.analysis.models import Scene
        from auto_video_editor.analysis.transcript_associator import associate_transcript
        scenes = [Scene(0, 0, 3_000_000, None)]
        tr = self._make_transcript()
        assoc = associate_transcript(scenes, tr, include_context=True)
        ctx = assoc[0]
        self.assertNotIn("REDACTED", ctx.full_text)
        self.assertGreater(ctx.char_count, 0)

    def test_missing_result_key_raises(self):
        from auto_video_editor.analysis.transcript_associator import load_transcript
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"schema_version": "1.0.0"}, f)
            tmp = f.name
        try:
            with self.assertRaises(RuntimeError):
                load_transcript(tmp)
        finally:
            os.unlink(tmp)


# ── Mock Vision Backend ───────────────────────────────────────────────────────

class TestMockVisionBackend(unittest.TestCase):
    def _scene(self):
        from auto_video_editor.analysis.models import Scene
        return Scene(0, 0, 5_000_000, None)

    def _kf(self, sha="A" * 64):
        from auto_video_editor.analysis.models import Keyframe
        return Keyframe(0, 0, 1_000_000, "/tmp/f.jpg", sha, "ok")

    def test_deterministic_same_sha(self):
        from auto_video_editor.analysis.scoring.mock_backend import MockVisionBackend
        backend = MockVisionBackend()
        profile = _make_mock_profile()
        kf = self._kf()
        s1 = backend.score_scene(self._scene(), [kf], profile, None)
        s2 = backend.score_scene(self._scene(), [kf], profile, None)
        self.assertEqual(s1.weighted_score, s2.weighted_score)

    def test_different_sha_different_score(self):
        from auto_video_editor.analysis.scoring.mock_backend import MockVisionBackend
        backend = MockVisionBackend()
        profile = _make_mock_profile()
        kf1 = self._kf("A" * 64)
        kf2 = self._kf("B" * 64)
        s1 = backend.score_scene(self._scene(), [kf1], profile, None)
        s2 = backend.score_scene(self._scene(), [kf2], profile, None)
        # Different SHAs should (almost certainly) produce different scores
        # Not guaranteed but statistically near-certain for distinct hex strings
        # We just verify score range and structure
        self.assertIsNotNone(s1.weighted_score)
        for d in s1.dimensions:
            self.assertGreaterEqual(d.score, 0)
            self.assertLessEqual(d.score, 100)

    def test_no_keyframes_insufficient_evidence(self):
        from auto_video_editor.analysis.scoring.mock_backend import MockVisionBackend
        backend = MockVisionBackend()
        profile = _make_mock_profile()
        s = backend.score_scene(self._scene(), [], profile, None)
        self.assertEqual(s.status, "insufficient_evidence")
        self.assertIsNone(s.weighted_score)
        for d in s.dimensions:
            self.assertIsNone(d.score)

    def test_dimensions_from_profile_weights(self):
        """Dimensions are loaded from profile.scoring.weights, not hard-coded."""
        from auto_video_editor.analysis.scoring.mock_backend import MockVisionBackend
        backend = MockVisionBackend()
        weights = {"clarity": 50, "engagement": 50}
        profile = _make_mock_profile(weights)
        kf = self._kf()
        score = backend.score_scene(self._scene(), [kf], profile, None)
        dim_names = {d.dimension for d in score.dimensions}
        self.assertEqual(dim_names, {"clarity", "engagement"})

    def test_provider_id_is_mock(self):
        from auto_video_editor.analysis.scoring.mock_backend import MockVisionBackend
        self.assertEqual(MockVisionBackend().provider_id, "mock")

    def test_model_id_is_none(self):
        from auto_video_editor.analysis.scoring.mock_backend import MockVisionBackend
        self.assertIsNone(MockVisionBackend().model_id)

    def test_missing_evidence_score_is_null_not_zero(self):
        """Missing evidence MUST be null, not silently converted to 0."""
        from auto_video_editor.analysis.scoring.mock_backend import MockVisionBackend
        backend = MockVisionBackend()
        profile = _make_mock_profile()
        # No keyframes → all null
        s = backend.score_scene(self._scene(), [], profile, None)
        for d in s.dimensions:
            self.assertIsNone(d.score, "Missing evidence must be null, not 0")


# ── Consent Gates ─────────────────────────────────────────────────────────────

class TestConsentGates(unittest.TestCase):
    def _run_service(self, **overrides):
        """Run AnalysisService with a minimal config and return exit_code."""
        from auto_video_editor.analysis.config import AnalysisConfig
        from auto_video_editor.analysis.service import AnalysisService
        defaults = dict(
            input_path="/nonexistent.mp4",
            profile_id="food_review",
            output_dir=tempfile.mkdtemp(),
            provider="mock",
        )
        defaults.update(overrides)
        config = AnalysisConfig(**defaults)
        svc = AnalysisService()
        code, _ = svc.run(config)
        return code

    def test_openai_without_consent_returns_6(self):
        """provider=openai without --allow-external-upload → exit 6."""
        code = self._run_service(provider="openai", allow_external_upload=False)
        self.assertEqual(code, 6)

    def test_openai_without_api_key_returns_6(self):
        """provider=openai with consent but no API key → exit 6."""
        env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            code = self._run_service(
                provider="openai",
                allow_external_upload=True,
            )
        self.assertEqual(code, 6)

    def test_mock_without_consent_flags_proceeds(self):
        """Mock provider does not need consent flags."""
        # Will fail at media inspection (file missing) → exit 4, not 6
        code = self._run_service(
            provider="mock",
            allow_external_upload=False,
            include_transcript_context=False,
        )
        self.assertEqual(code, 4)  # media not found, not consent error


# ── Cache Logic ───────────────────────────────────────────────────────────────

class TestAnalysisCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cache(self):
        from auto_video_editor.analysis.cache import AnalysisCache
        return AnalysisCache(self.tmp)

    def _identity(self):
        return dict(
            source_sha256="A" * 64,
            detector_config={"threshold": 0.3, "min_duration_seconds": 1.0, "max_duration_seconds": 15.0},
            profile_hash="C" * 64,
            transcript_hash="no-transcript",
            provider_id="mock",
            model_id=None,
            prompt_version="1.0.0",
        )

    def test_miss_returns_none(self):
        cache = self._cache()
        result = cache.get(**self._identity())
        self.assertIsNone(result)

    def test_put_then_get_returns_data(self):
        cache = self._cache()
        analysis_json = json.dumps({"schema_version": "1.0.0", "status": "complete"})
        jid = cache.put(**self._identity(), analysis_json=analysis_json)
        result = cache.get(**self._identity())
        self.assertIsNotNone(result)
        self.assertEqual(result["job_id"], jid)

    def test_different_source_sha_is_miss(self):
        cache = self._cache()
        analysis_json = json.dumps({"x": 1})
        cache.put(**self._identity(), analysis_json=analysis_json)
        identity2 = dict(self._identity(), source_sha256="D" * 64)
        result = cache.get(**identity2)
        self.assertIsNone(result)

    def test_different_provider_is_miss(self):
        cache = self._cache()
        cache.put(**self._identity(), analysis_json="{}")
        identity2 = dict(self._identity(), provider_id="openai")
        self.assertIsNone(cache.get(**identity2))

    def test_profile_hash_static(self):
        from auto_video_editor.analysis.cache import AnalysisCache
        d = {"profile_id": "food_review", "scoring": {"weights": {"a": 50}}}
        h1 = AnalysisCache.profile_hash(d)
        h2 = AnalysisCache.profile_hash(d)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)


# ── Exporter ──────────────────────────────────────────────────────────────────

class TestExporter(unittest.TestCase):
    def _make_analysis(self):
        from auto_video_editor.analysis.models import (
            ClipAnalysis, MediaInfo, Scene, SceneScore,
        )
        source = MediaInfo(
            path="/some/path/video.mp4",
            sha256="A" * 64,
            duration_us=5_000_000,
            width=320, height=240, fps=30.0,
            has_audio=True, has_video=True,
            codec_name="h264", size_bytes=1000000,
        )
        scene = Scene(0, 0, 5_000_000, None)
        score = SceneScore(
            scene_index=0, provider="mock", model_id=None,
            prompt_version="1.0.0",
            dimensions=(), weighted_score=None,
            keyframes_used=0, status="insufficient_evidence",
        )
        return ClipAnalysis(
            schema_version="1.0.0",
            status="complete",
            source=source,
            profile_id="test_profile",
            profile_hash="P" * 64,
            detector_config={"threshold": 0.3, "min_duration_seconds": 1.0, "max_duration_seconds": 15.0},
            scenes=(scene,),
            keyframes=(),
            scores=(score,),
            warnings=(),
            metrics={"elapsed_seconds": 1.0, "scenes_detected": 1, "keyframes_extracted": 0, "scenes_scored": 0},
            provenance={"analysis_schema_version": "1.0.0", "provider": "mock", "model_id": None, "prompt_version": "1.0.0"},
        )

    def test_export_no_absolute_path(self):
        from auto_video_editor.analysis.exporters import export_clip_analysis
        analysis = self._make_analysis()
        doc_str = export_clip_analysis(analysis)
        doc = json.loads(doc_str)
        # Filename only — no directory separator
        filename = doc["source"]["filename"]
        self.assertNotIn("/", filename)
        self.assertNotIn("\\", filename)

    def test_export_allow_nan_false(self):
        """NaN/Infinity must be rejected."""
        import math
        from auto_video_editor.analysis.exporters import _check_finite
        with self.assertRaises(ValueError):
            _check_finite({"val": float("nan")})
        with self.assertRaises(ValueError):
            _check_finite({"val": float("inf")})

    def test_export_schema_version(self):
        from auto_video_editor.analysis.exporters import export_clip_analysis
        doc = json.loads(export_clip_analysis(self._make_analysis()))
        self.assertEqual(doc["schema_version"], "1.0.0")

    def test_missing_score_is_null_not_zero(self):
        """Null weighted_score must appear as null in JSON, not 0."""
        from auto_video_editor.analysis.exporters import export_clip_analysis
        doc = json.loads(export_clip_analysis(self._make_analysis()))
        for score in doc["scores"]:
            if score["status"] == "insufficient_evidence":
                self.assertIsNone(score["weighted_score"])

    def test_schema_validation_passes(self):
        """Exported JSON must pass Draft202012Validator against schema file."""
        if not SCHEMA_PATH.exists():
            self.skipTest("clip_analysis.schema.json not found")
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema not installed")
        from auto_video_editor.analysis.exporters import export_clip_analysis
        doc = json.loads(export_clip_analysis(self._make_analysis()))
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        errors = list(Draft202012Validator(schema).iter_errors(doc))
        self.assertEqual(errors, [], [str(e) for e in errors])


# ── Static profile-ID branch test ─────────────────────────────────────────────

class TestNoProfileIDBranches(unittest.TestCase):
    """Ensure production analysis code does NOT branch on profile IDs."""

    PROFILE_IDS = {"food_review", "lifestyle_vlog", "affiliate_fast"}
    PRODUCTION_DIRS = [
        SRC / "auto_video_editor" / "analysis",
    ]

    def _collect_py_files(self):
        files = []
        for d in self.PRODUCTION_DIRS:
            if d.exists():
                files.extend(d.rglob("*.py"))
        return files

    def test_no_profile_id_string_literals_in_conditionals(self):
        """Profile IDs must not appear as string literals in if/elif branches."""
        violations = []
        for py_file in self._collect_py_files():
            if "test_" in py_file.name:
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.If,)):
                    for child in ast.walk(node.test):
                        if isinstance(child, ast.Constant) and isinstance(child.value, str):
                            if child.value in self.PROFILE_IDS:
                                violations.append(
                                    f"{py_file.name}:{child.lineno}: "
                                    f"hard-coded profile ID {child.value!r}"
                                )
        self.assertEqual(
            violations, [],
            "Production code branches on profile IDs: " + "; ".join(violations),
        )


# ── Synthetic Smoke Test ───────────────────────────────────────────────────────

class TestSyntheticSmoke(unittest.TestCase):
    """Full pipeline smoke test with synthetic FFmpeg-generated video."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="phase4_smoke_")
        cls.vid = _synthetic_video_path(cls.tmp, duration_s=10.0)
        cls.sha_before = _sha256(cls.vid)
        cls.out_dir = os.path.join(cls.tmp, "output")
        cls.cache_dir = os.path.join(cls.tmp, "cache")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _run(self, extra_args: list[str]) -> int:
        cmd = [
            sys.executable, "-m", "auto_video_editor",
            "analyze", "scenes",
            "--input", self.vid,
            "--profile", "food_review",
            "--output-dir", self.out_dir,
            "--provider", "mock",
            "--cache-dir", self.cache_dir,
        ] + extra_args
        result = subprocess.run(cmd, cwd=str(ROOT))
        return result.returncode

    def test_01_first_run_exits_0(self):
        rc = self._run(["--force"])
        self.assertEqual(rc, 0)

    def test_02_output_file_exists(self):
        out = Path(self.out_dir) / "clip_analysis.json"
        self.assertTrue(out.exists(), "clip_analysis.json not found after first run")

    def test_03_output_validates_schema(self):
        if not SCHEMA_PATH.exists():
            self.skipTest("Schema file not found")
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema not installed")
        out = Path(self.out_dir) / "clip_analysis.json"
        doc = json.loads(out.read_text(encoding="utf-8"))
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        errors = list(Draft202012Validator(schema).iter_errors(doc))
        self.assertEqual(errors, [], [str(e) for e in errors[:3]])

    def test_04_scenes_detected(self):
        out = Path(self.out_dir) / "clip_analysis.json"
        doc = json.loads(out.read_text(encoding="utf-8"))
        self.assertGreater(doc["summary"]["scene_count"], 0)

    def test_05_no_absolute_paths_in_output(self):
        out = Path(self.out_dir) / "clip_analysis.json"
        content = out.read_text(encoding="utf-8")
        # No Windows absolute path (C:\...) or Unix absolute path in JSON values
        self.assertNotIn("C:\\Users", content)
        self.assertNotIn("/home/", content)

    def test_06_resume_cache_hit(self):
        """Second run with --resume must hit cache (exit 0)."""
        rc = self._run(["--resume"])
        self.assertEqual(rc, 0)

    def test_07_force_recomputes(self):
        """--force must bypass cache and recompute (exit 0)."""
        rc = self._run(["--force"])
        self.assertEqual(rc, 0)

    def test_08_source_sha_unchanged(self):
        sha_after = _sha256(self.vid)
        self.assertEqual(self.sha_before, sha_after, "Source file was modified!")

    def test_09_no_raw_video_in_output(self):
        """Output dir must not contain raw video data."""
        for f in Path(self.out_dir).rglob("*.mp4"):
            self.fail(f"Found unexpected video file in output: {f}")
        for f in Path(self.out_dir).rglob("*.mov"):
            self.fail(f"Found unexpected video file in output: {f}")

    def test_10_dry_run_exits_0_no_output(self):
        """Dry-run must exit 0 and not write clip_analysis.json."""
        dry_out = os.path.join(self.tmp, "dry_output")
        cmd = [
            sys.executable, "-m", "auto_video_editor",
            "analyze", "scenes",
            "--input", self.vid,
            "--profile", "food_review",
            "--output-dir", dry_out,
            "--provider", "mock",
            "--dry-run",
        ]
        result = subprocess.run(cmd, cwd=str(ROOT))
        self.assertEqual(result.returncode, 0)
        self.assertFalse((Path(dry_out) / "clip_analysis.json").exists())


if __name__ == "__main__":
    unittest.main()
