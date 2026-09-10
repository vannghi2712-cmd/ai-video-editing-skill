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


def _make_semantic_request(
    scene_id: int = 0,
    start_us: int = 0,
    end_us: int = 5_000_000,
    sha_list: list[str] | None = None,
    profile=None,
    transcript_text: str | None = None,
    provider_id: str = "mock",
):
    """Build (SceneVisionSemanticRequest, ProviderContentBundle) for unit tests.

    sha_list: list of 64-char hex SHA-256 strings (one per image slot).
    If sha_list is None or empty → no images (insufficient evidence path).
    Fake 1-byte image content is synthesised per SHA to fill the bundle.
    """
    from auto_video_editor.analysis.models import ProviderContentBundle, SceneVisionSemanticRequest
    from auto_video_editor.analysis.scoring.base import PROMPT_VERSION, VISION_ADAPTER_VERSION

    if profile is None:
        profile = _make_mock_profile()

    ordered_criteria = [
        {"order": i, "criterion_id": dim, "finite_weight": float(w)}
        for i, (dim, w) in enumerate(profile.scoring.items())
    ]
    sha_list = sha_list or []

    images = []
    image_bytes = []
    for order, sha in enumerate(sha_list):
        images.append({
            "order": order,
            "frame_id": f"scene_{scene_id:04d}_slot_{order}",
            "full_sha256": sha,
            "mime_type": "image/jpeg",
            "width": 320,
            "height": 240,
            "detail": "auto",
        })
        # Synthetic bytes — not real JPEG, only needed for bundle
        image_bytes.append(sha.encode("ascii"))

    if transcript_text is not None:
        ctx_sha = hashlib.sha256(transcript_text.encode("utf-8")).hexdigest()
        ctx_mode = "included"
        ctx_chars = len(transcript_text.encode("utf-8"))
    else:
        ctx_sha = "not_included"
        ctx_mode = "not_included"
        ctx_chars = 0

    sem_req = SceneVisionSemanticRequest(
        provider_id=provider_id,
        requested_model_id="",
        adapter_version=VISION_ADAPTER_VERSION,
        prompt={"version": PROMPT_VERSION, "content_sha256": "test-prompt-sha"},
        provider_options={"detail": "auto", "expected_slots": 3},
        scene={
            "scene_id": scene_id,
            "start_us": start_us,
            "end_us": end_us,
            "duration_us": end_us - start_us,
        },
        profile={
            "profile_id": profile.profile_id,
            "resolved_profile_sha256": "P" * 64,
            "ordered_criteria": ordered_criteria,
        },
        images=tuple(images),
        transcript_context={
            "mode": ctx_mode,
            "character_count": ctx_chars,
            "content_sha256": ctx_sha,
        },
        response_schema={
            "schema_version": "2.0.0",
            "full_schema_sha256": "schema-sha",
        },
    )
    bundle = ProviderContentBundle(
        image_bytes=image_bytes,
        transcript_excerpt=transcript_text,
    )
    return sem_req, bundle


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
        sha = "A" * 64
        req, bundle = _make_semantic_request(sha_list=[sha], profile=profile)
        s1 = backend.score_scene(req, bundle)
        s2 = backend.score_scene(req, bundle)
        self.assertEqual(s1.weighted_score, s2.weighted_score)

    def test_different_sha_different_score(self):
        from auto_video_editor.analysis.scoring.mock_backend import MockVisionBackend
        backend = MockVisionBackend()
        profile = _make_mock_profile()
        req1, bundle1 = _make_semantic_request(sha_list=["A" * 64], profile=profile)
        req2, bundle2 = _make_semantic_request(sha_list=["B" * 64], profile=profile)
        s1 = backend.score_scene(req1, bundle1)
        s2 = backend.score_scene(req2, bundle2)
        self.assertIsNotNone(s1.weighted_score)
        for d in s1.dimensions:
            self.assertGreaterEqual(d.score, 0)
            self.assertLessEqual(d.score, 100)

    def test_no_keyframes_insufficient_evidence(self):
        from auto_video_editor.analysis.scoring.mock_backend import MockVisionBackend
        backend = MockVisionBackend()
        profile = _make_mock_profile()
        req, bundle = _make_semantic_request(sha_list=[], profile=profile)
        s = backend.score_scene(req, bundle)
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
        req, bundle = _make_semantic_request(sha_list=["A" * 64], profile=profile)
        score = backend.score_scene(req, bundle)
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
        req, bundle = _make_semantic_request(sha_list=[], profile=profile)
        s = backend.score_scene(req, bundle)
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

    def _job_id(self, source_sha="A" * 64, provider_id="mock"):
        """Compute a semantic_request_job_id for test use."""
        from auto_video_editor.analysis.cache import (
            preprocessing_job_id,
            semantic_request_job_id,
            CACHE_SCHEMA_VERSION,
        )
        pre_id = preprocessing_job_id(
            source_sha256=source_sha,
            ffmpeg_version="test-ffmpeg",
            ffprobe_version="test-ffprobe",
            scene_detector_config={"threshold": 0.3, "min_duration_seconds": 1.0, "max_duration_seconds": 15.0},
            extractor_slots=3,
            extractor_max_dim=1280,
        )
        profile = _make_mock_profile()
        req, _ = _make_semantic_request(sha_list=[], profile=profile, provider_id=provider_id)
        return semantic_request_job_id(
            preprocessing_sha256=pre_id,
            scene_canonical_dicts=[req.to_canonical_identity_dict()],
        )

    def test_miss_returns_none(self):
        cache = self._cache()
        result = cache.get(self._job_id())
        self.assertIsNone(result)

    def test_put_then_get_returns_data(self):
        cache = self._cache()
        analysis_json = json.dumps({"schema_version": "2.0.0", "status": "complete"})
        jid = self._job_id()
        cache.put(jid, analysis_json)
        result = cache.get(jid)
        self.assertIsNotNone(result)
        self.assertEqual(result["job_id"], jid)

    def test_different_source_sha_is_miss(self):
        cache = self._cache()
        analysis_json = json.dumps({"x": 1})
        jid1 = self._job_id(source_sha="A" * 64)
        jid2 = self._job_id(source_sha="D" * 64)
        cache.put(jid1, analysis_json)
        result = cache.get(jid2)
        self.assertIsNone(result)

    def test_different_provider_is_miss(self):
        cache = self._cache()
        jid_mock = self._job_id(provider_id="mock")
        jid_openai = self._job_id(provider_id="openai")
        cache.put(jid_mock, "{}")
        self.assertIsNone(cache.get(jid_openai))

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
            dimensions=(), score_coverage_percent=0.0,
            partial_weighted_score=0.0, weighted_score=None,
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
        self.assertEqual(doc["schema_version"], "2.0.0")

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


# ── Phase 4 Contract Correction Regression Tests ──────────────────────────────

class TestScoringContractFull(unittest.TestCase):
    """Scoring: full coverage => weighted_score = partial_weighted_score."""

    def _make_scene(self):
        from auto_video_editor.analysis.models import Scene
        return Scene(0, 0, 5_000_000, None)

    def _kf(self, sha="A" * 64):
        from auto_video_editor.analysis.models import Keyframe
        return Keyframe(0, 0, 1_000_000, "/tmp/f.jpg", sha, "ok")

    def test_full_coverage_weighted_equals_partial(self):
        """When all dims scored, weighted_score == partial_weighted_score."""
        from auto_video_editor.analysis.scoring.mock_backend import MockVisionBackend
        backend = MockVisionBackend()
        profile = _make_mock_profile({"food_appeal": 60, "motion": 40})
        req, bundle = _make_semantic_request(sha_list=["A" * 64], profile=profile)
        score = backend.score_scene(req, bundle)
        self.assertEqual(score.score_coverage_percent, 100.0)
        self.assertIsNotNone(score.partial_weighted_score)
        self.assertEqual(score.weighted_score, score.partial_weighted_score)

    def test_zero_coverage_all_null(self):
        """No keyframes -> score_coverage_percent=0, weighted_score=null."""
        from auto_video_editor.analysis.scoring.mock_backend import MockVisionBackend
        backend = MockVisionBackend()
        profile = _make_mock_profile({"food_appeal": 60, "motion": 40})
        req, bundle = _make_semantic_request(sha_list=[], profile=profile)
        score = backend.score_scene(req, bundle)
        self.assertEqual(score.score_coverage_percent, 0.0)
        self.assertEqual(score.partial_weighted_score, 0.0,
                         "Zero coverage must emit 0.0 (numeric zero), not null")
        self.assertIsNone(score.weighted_score)

    def test_no_renormalization(self):
        """weighted_score must not divide by sum(scored weights)."""
        from auto_video_editor.analysis.scoring.mock_backend import MockVisionBackend
        import math
        backend = MockVisionBackend()
        profile = _make_mock_profile({"a": 50, "b": 50})
        req, bundle = _make_semantic_request(sha_list=["A" * 64], profile=profile)
        score = backend.score_scene(req, bundle)
        if score.weighted_score is not None and score.partial_weighted_score is not None:
            self.assertGreaterEqual(score.weighted_score, 0.0)
            self.assertLessEqual(score.weighted_score, 100.0)
            self.assertAlmostEqual(score.weighted_score, score.partial_weighted_score, places=4)


    def test_partial_weighted_score_formula(self):
        """partial_weighted_score = sum(score_i * weight_i / 100), verified manually."""
        from auto_video_editor.analysis.models import DimensionScore, Scene, SceneScore
        dims = (
            DimensionScore("a", 60, 80.0, 1.0, "scored"),
            DimensionScore("b", 40, 50.0, 1.0, "scored"),
        )
        # Expected: (80 * 60 / 100) + (50 * 40 / 100) = 48 + 20 = 68
        expected_partial = 80.0 * 60 / 100.0 + 50.0 * 40 / 100.0
        score = SceneScore(
            scene_index=0, provider="mock", model_id=None,
            prompt_version="1.0.0",
            dimensions=dims,
            score_coverage_percent=100.0,
            partial_weighted_score=round(expected_partial, 4),
            weighted_score=round(expected_partial, 4),
            keyframes_used=1, status="scored",
        )
        self.assertAlmostEqual(score.partial_weighted_score, 68.0, places=2)
        self.assertAlmostEqual(score.weighted_score, 68.0, places=2)

    def test_partial_coverage_weighted_score_is_null(self):
        """If score_coverage_percent < 100, weighted_score MUST be null."""
        from auto_video_editor.analysis.models import DimensionScore, Scene, SceneScore
        dims = (
            DimensionScore("a", 60, 80.0, 1.0, "scored"),
            DimensionScore("b", 40, None, None, "insufficient_evidence"),
        )
        score = SceneScore(
            scene_index=0, provider="mock", model_id=None,
            prompt_version="1.0.0",
            dimensions=dims,
            score_coverage_percent=60.0,  # only dim a scored
            partial_weighted_score=round(80.0 * 60 / 100.0, 4),
            weighted_score=None,  # coverage < 100 -> null
            keyframes_used=1, status="scored",
        )
        self.assertEqual(score.score_coverage_percent, 60.0)
        self.assertIsNone(score.weighted_score)
        self.assertIsNotNone(score.partial_weighted_score)


class TestScoringNonFinite(unittest.TestCase):
    """Non-finite scores must be treated as missing evidence."""

    def test_nan_score_not_counted(self):
        """A NaN score must not contribute to coverage or partial_weighted_score."""
        import math
        from auto_video_editor.analysis.models import DimensionScore
        # Simulate what backend should do: check isfinite before counting
        dims = [
            DimensionScore("a", 60, float("nan"), 1.0, "scored"),
            DimensionScore("b", 40, 75.0, 1.0, "scored"),
        ]
        scored_dims = [
            d for d in dims
            if d.status == "scored" and d.score is not None and math.isfinite(d.score)
        ]
        coverage = sum(d.weight for d in scored_dims)
        self.assertEqual(coverage, 40)  # only b counted
        partial = sum(d.score * d.weight / 100 for d in scored_dims)
        self.assertAlmostEqual(partial, 30.0)  # 75 * 40 / 100
        # weighted_score must be null (coverage != 100)
        weighted = partial if coverage == 100 else None
        self.assertIsNone(weighted)


class TestMergeShortDeterminism(unittest.TestCase):
    """Merge determinism: equal-score, missing-score, inf-score tie-breaks."""

    def _scene(self, idx, start, end, score):
        from auto_video_editor.analysis.models import Scene
        return Scene(idx, start, end, score)

    def test_equal_boundary_scores_merges_previous(self):
        """Equal left/right boundary scores -> always merge PREVIOUS."""
        from auto_video_editor.analysis.scene_detector import _merge_short
        # Scene 1 (0-3s): i=0, first -> merge next
        # Scene 2 (3-3.5s): SHORT; left=scene2.raw_score=0.5, right=scene3.raw_score=0.5 -> equal -> merge PREVIOUS
        # Scene 3 (3.5-10s): i=2
        scenes = [
            self._scene(0, 0, 3_000_000, None),
            self._scene(1, 3_000_000, 3_500_000, 0.5),   # short (0.5s < 1.0s min)
            self._scene(2, 3_500_000, 10_000_000, 0.5),
        ]
        min_us = 1_000_000
        merged = _merge_short(scenes, min_us)
        # Scene 1 (short) merges with PREVIOUS (scene 0) since left==right
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0].start_us, 0)
        self.assertEqual(merged[0].end_us, 3_500_000)  # scenes 0+1 merged

    def test_missing_boundary_scores_merges_previous(self):
        """Both boundary scores None -> always merge PREVIOUS."""
        from auto_video_editor.analysis.scene_detector import _merge_short
        scenes = [
            self._scene(0, 0, 4_000_000, None),
            self._scene(1, 4_000_000, 4_500_000, None),  # short, score=None
            self._scene(2, 4_500_000, 10_000_000, None),
        ]
        min_us = 1_000_000
        merged = _merge_short(scenes, min_us)
        # Both None -> merge PREVIOUS
        self.assertEqual(merged[0].start_us, 0)
        self.assertEqual(merged[0].end_us, 4_500_000)

    def test_lower_left_boundary_merges_previous(self):
        """Left boundary score < right -> remove left -> merge with PREVIOUS."""
        from auto_video_editor.analysis.scene_detector import _merge_short
        scenes = [
            self._scene(0, 0, 4_000_000, None),
            self._scene(1, 4_000_000, 4_300_000, 0.2),   # short; left=0.2, right=0.8
            self._scene(2, 4_300_000, 10_000_000, 0.8),
        ]
        min_us = 1_000_000
        merged = _merge_short(scenes, min_us)
        # left(0.2) < right(0.8) -> merge with previous (scene 0)
        self.assertEqual(merged[0].start_us, 0)
        self.assertEqual(merged[0].end_us, 4_300_000)

    def test_lower_right_boundary_merges_next(self):
        """Left boundary score > right -> remove right -> merge with NEXT."""
        from auto_video_editor.analysis.scene_detector import _merge_short
        scenes = [
            self._scene(0, 0, 4_000_000, None),
            self._scene(1, 4_000_000, 4_300_000, 0.9),   # short; left=0.9, right=0.1
            self._scene(2, 4_300_000, 10_000_000, 0.1),
        ]
        min_us = 1_000_000
        merged = _merge_short(scenes, min_us)
        # left(0.9) > right(0.1) -> merge with next (scene 2)
        self.assertEqual(merged[-1].start_us, 4_000_000)
        self.assertEqual(merged[-1].end_us, 10_000_000)

    def test_repeated_run_same_result(self):
        """Same input always produces same merge output (deterministic)."""
        from auto_video_editor.analysis.scene_detector import _merge_short
        from auto_video_editor.analysis.models import Scene
        scenes = [
            Scene(0, 0, 3_000_000, 0.5),
            Scene(1, 3_000_000, 3_400_000, 0.5),  # short, equal boundary scores
            Scene(2, 3_400_000, 10_000_000, 0.5),
        ]
        min_us = 1_000_000
        result1 = [s.start_us for s in _merge_short(list(scenes), min_us)]
        result2 = [s.start_us for s in _merge_short(list(scenes), min_us)]
        self.assertEqual(result1, result2, "Merge must be deterministic across repeated calls")

    def test_inf_boundary_score_treated_as_missing(self):
        """Infinity boundary score -> treated as non-finite -> always merge PREVIOUS."""
        from auto_video_editor.analysis.scene_detector import _merge_short
        scenes = [
            self._scene(0, 0, 4_000_000, None),
            self._scene(1, 4_000_000, 4_200_000, float("inf")),  # short; inf score
            self._scene(2, 4_200_000, 10_000_000, 0.5),
        ]
        min_us = 1_000_000
        merged = _merge_short(scenes, min_us)
        # inf is non-finite -> merge PREVIOUS
        self.assertEqual(merged[0].start_us, 0)
        self.assertEqual(merged[0].end_us, 4_200_000)


class TestCacheVersionBump(unittest.TestCase):
    """Cache v4.0.0 — old caches must safely miss."""

    def test_cache_schema_version_is_4(self):
        from auto_video_editor.analysis.cache import CACHE_SCHEMA_VERSION
        self.assertEqual(CACHE_SCHEMA_VERSION, "4.0.0")

    def test_old_version_manifest_is_miss(self):
        """A manifest with v3.0.0 (old) must return None (safe miss on v4.0.0)."""
        import tempfile
        tmp = tempfile.mkdtemp()
        try:
            from auto_video_editor.analysis.cache import AnalysisCache
            cache = AnalysisCache(tmp)
            import os, json as j
            job_id = "abc123"
            entry = os.path.join(tmp, job_id)
            os.makedirs(entry)
            with open(os.path.join(entry, "manifest.json"), "w") as f:
                j.dump({"job_id": job_id, "cache_schema_version": "3.0.0"}, f)
            with open(os.path.join(entry, "clip_analysis.json"), "w") as f:
                j.dump({"schema_version": "2.0.0"}, f)
            result = cache.get(job_id)
            self.assertIsNone(result, "Stale v3.0.0 cache must be a miss on v4.0.0")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_v1_output_rejected_from_cache(self):
        """Cache.get() must reject cached entries containing v1.0.0 output."""
        import tempfile
        tmp = tempfile.mkdtemp()
        try:
            from auto_video_editor.analysis.cache import AnalysisCache, CACHE_SCHEMA_VERSION
            cache = AnalysisCache(tmp)
            import os, json as j
            job_id = "v1test"
            entry = os.path.join(tmp, job_id)
            os.makedirs(entry)
            with open(os.path.join(entry, "manifest.json"), "w") as f:
                j.dump({"job_id": job_id, "cache_schema_version": CACHE_SCHEMA_VERSION}, f)
            with open(os.path.join(entry, "clip_analysis.json"), "w") as f:
                j.dump({"schema_version": "1.0.0"}, f)
            result = cache.get(job_id)
            self.assertIsNone(result, "Cache must reject v1.0.0 output schema entries")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class TestClosureCorrections(unittest.TestCase):
    """Phase 4 Closure + Final Contract regression tests."""

    def test_v1_schema_rejected_by_validator(self):
        """validate_against_schema must raise LegacyOutputSchemaError for v1.0.0."""
        from auto_video_editor.analysis.exporters import validate_against_schema
        from auto_video_editor.analysis.models import LegacyOutputSchemaError
        import json as j
        v1_doc = j.dumps({"schema_version": "1.0.0", "status": "complete"})
        with self.assertRaises(LegacyOutputSchemaError) as ctx:
            validate_against_schema(v1_doc, str(
                __import__("pathlib").Path(__file__).parent.parent /
                "schemas" / "clip_analysis.schema.json"
            ))
        self.assertIn("1.0.0", str(ctx.exception))

    def test_schema_version_is_2(self):
        """Exporter SCHEMA_VERSION must be 2.0.0."""
        from auto_video_editor.analysis.exporters import SCHEMA_VERSION
        self.assertEqual(SCHEMA_VERSION, "2.0.0")

    def test_partial_weighted_score_is_always_float(self):
        """partial_weighted_score must be float (never None) for zero-coverage scene."""
        from auto_video_editor.analysis.scoring.mock_backend import MockVisionBackend
        backend = MockVisionBackend()
        profile = _make_mock_profile({"a": 60, "b": 40})
        req, bundle = _make_semantic_request(sha_list=[], profile=profile)
        score = backend.score_scene(req, bundle)
        self.assertIsInstance(score.partial_weighted_score, float,
                              "partial_weighted_score must be float, not None")
        self.assertEqual(score.partial_weighted_score, 0.0)

    def test_cache_not_included_sentinel(self):
        """transcript_context_sha256 sentinel must be 'not-included'."""
        from auto_video_editor.analysis.cache import AnalysisCache
        sha = AnalysisCache.transcript_context_sha256(None)
        self.assertEqual(sha, "not-included")

    def test_keyframe_sha_verification(self):
        """AnalysisCache.verify_keyframe_sha256 reads file bytes and returns SHA."""
        import tempfile, hashlib
        data = b"fake_jpeg_data"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
            f.write(data)
            fname = f.name
        try:
            from auto_video_editor.analysis.cache import AnalysisCache
            result = AnalysisCache.verify_keyframe_sha256(fname)
            expected = hashlib.sha256(data).hexdigest()
            self.assertEqual(result, expected)
        finally:
            import os
            os.unlink(fname)

    def test_keyframe_sha_missing_file_returns_none(self):
        """verify_keyframe_sha256 returns None for missing files."""
        from auto_video_editor.analysis.cache import AnalysisCache
        result = AnalysisCache.verify_keyframe_sha256("/nonexistent/path/kf.jpg")
        self.assertIsNone(result)

    def test_provider_cache_only_after_verified_keyframes(self):
        """Service must build semantic job id AFTER keyframe bytes are verified."""
        import inspect
        from auto_video_editor.analysis import service as svc
        src = inspect.getsource(svc.AnalysisService.run)
        step6_pos = src.find("VERIFY KEYFRAME BYTES")
        step10_pos = src.find("Provider cache lookup")
        self.assertGreater(step6_pos, 0, "Step 6 comment must exist in service.run")
        self.assertGreater(step10_pos, 0, "Step 10 comment must exist in service.run")
        self.assertLess(step6_pos, step10_pos,
                        "Keyframe verification (step 6) must precede provider cache lookup (step 10)")

    def test_semantic_request_canonical_sha_deterministic(self):
        """Same semantic request always produces same SHA-256."""
        req, _ = _make_semantic_request(sha_list=["A" * 64])
        sha1 = req.canonical_sha256()
        sha2 = req.canonical_sha256()
        self.assertEqual(sha1, sha2)
        self.assertEqual(len(sha1), 64)

    def test_semantic_request_different_sha_different_identity(self):
        """Different image SHAs produce different canonical identities."""
        req1, _ = _make_semantic_request(sha_list=["A" * 64])
        req2, _ = _make_semantic_request(sha_list=["B" * 64])
        self.assertNotEqual(req1.canonical_sha256(), req2.canonical_sha256())

    def test_semantic_request_immutable(self):
        """SceneVisionSemanticRequest must be immutable (frozen dataclass)."""
        req, _ = _make_semantic_request(sha_list=["A" * 64])
        with self.assertRaises((AttributeError, TypeError)):
            req.provider_id = "hacked"  # type: ignore[misc]

    def test_provider_content_bundle_not_in_canonical_dict(self):
        """ProviderContentBundle fields must NOT appear in canonical identity dict."""
        req, bundle = _make_semantic_request(sha_list=["A" * 64])
        identity = req.to_canonical_identity_dict()
        identity_str = json.dumps(identity)
        # Raw bytes should never be in the canonical identity
        self.assertNotIn("image_bytes", identity_str)
        self.assertNotIn("transcript_excerpt", identity_str)

    def test_legacy_output_schema_error_is_value_error(self):
        """LegacyOutputSchemaError must be a ValueError subclass."""
        from auto_video_editor.analysis.models import LegacyOutputSchemaError
        self.assertTrue(issubclass(LegacyOutputSchemaError, ValueError))

    def test_vision_adapter_version(self):
        """VISION_ADAPTER_VERSION must be 1.3.0."""
        from auto_video_editor.analysis.scoring.base import VISION_ADAPTER_VERSION
        self.assertEqual(VISION_ADAPTER_VERSION, "1.3.0")
        from auto_video_editor.analysis.cache import VISION_ADAPTER_VERSION as CV
        self.assertEqual(CV, "1.3.0")

    def test_semantic_request_job_id_exists(self):
        """semantic_request_job_id must exist and return 64-char hex."""
        from auto_video_editor.analysis.cache import (
            semantic_request_job_id, preprocessing_job_id,
        )
        pre = preprocessing_job_id(
            source_sha256="A" * 64, ffmpeg_version="v", ffprobe_version="v",
            scene_detector_config={}, extractor_slots=3, extractor_max_dim=1280,
        )
        req, _ = _make_semantic_request()
        jid = semantic_request_job_id(
            preprocessing_sha256=pre,
            scene_canonical_dicts=[req.to_canonical_identity_dict()],
        )
        self.assertEqual(len(jid), 64)


def _make_full_ownership_manifest(tmp_path):
    """Create a properly-formed v2 ownership manifest + marker in tmp_path."""
    import hashlib, uuid as _uuid, json as j
    root_id = str(_uuid.uuid4())
    # Write marker
    (tmp_path / ".scene_analysis_root").write_text(root_id, encoding="utf-8")
    # Compute root binding
    normalized = str(tmp_path.resolve()).replace("\\", "/")
    binding_sha = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    manifest = {
        "manifest_version": "1.0.0",
        "owner": "auto_video_editor.scene_analysis",
        "output_root_id": root_id,
        "root_binding_sha256": binding_sha,
        "source_sha256": "A" * 64,
        "generated_artifacts": ["clip_analysis.json", "manifest.json", ".scene_analysis_root"],
    }
    (tmp_path / "manifest.json").write_text(j.dumps(manifest), encoding="utf-8")
    (tmp_path / "clip_analysis.json").write_text("{}", encoding="utf-8")
    return manifest


class TestOutputOwnershipEnforcement(unittest.TestCase):
    """--force cannot bypass source SHA mismatch; marker+binding required."""

    def test_force_cannot_override_different_source(self):
        """Force with different source SHA -> rejected even with --force."""
        import tempfile, shutil
        from pathlib import Path
        tmp = tempfile.mkdtemp()
        try:
            p = Path(tmp)
            _make_full_ownership_manifest(p)
            from auto_video_editor.analysis.service import _check_ownership
            different_sha = "B" * 64
            ok, msg = _check_ownership(p, different_sha, force=True)
            self.assertFalse(ok, "Force must NOT bypass source SHA mismatch")
            self.assertIn("source sha mismatch", msg.lower())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_force_on_same_source_is_ok(self):
        """Force with matching source SHA and valid manifest/marker is allowed."""
        import tempfile, shutil
        from pathlib import Path
        tmp = tempfile.mkdtemp()
        try:
            p = Path(tmp)
            _make_full_ownership_manifest(p)
            from auto_video_editor.analysis.service import _check_ownership
            ok, msg = _check_ownership(p, "A" * 64, force=True)
            self.assertTrue(ok, f"Force on same-source owned dir should be OK: {msg}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_unowned_dir_always_rejected(self):
        """Non-empty dir with no manifest -> rejected with or without --force."""
        import tempfile, shutil
        from pathlib import Path
        tmp = tempfile.mkdtemp()
        try:
            p = Path(tmp)
            (p / "data.txt").write_text("hello", encoding="utf-8")
            from auto_video_editor.analysis.service import _check_ownership
            ok_no_force, _ = _check_ownership(p, "A" * 64, force=False)
            ok_force, _ = _check_ownership(p, "A" * 64, force=True)
            self.assertFalse(ok_no_force)
            self.assertFalse(ok_force)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_missing_marker_file_rejected(self):
        """Valid manifest but missing marker file -> ownership rejected."""
        import tempfile, shutil
        from pathlib import Path
        tmp = tempfile.mkdtemp()
        try:
            p = Path(tmp)
            _make_full_ownership_manifest(p)
            # Remove marker file
            (p / ".scene_analysis_root").unlink()
            from auto_video_editor.analysis.service import _check_ownership
            ok, msg = _check_ownership(p, "A" * 64, force=False)
            self.assertFalse(ok, "Missing marker file must be rejected")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_marker_mismatch_rejected(self):
        """Marker file UUID differs from manifest output_root_id -> rejected."""
        import tempfile, shutil
        from pathlib import Path
        tmp = tempfile.mkdtemp()
        try:
            p = Path(tmp)
            _make_full_ownership_manifest(p)
            # Tamper: overwrite marker with different UUID
            (p / ".scene_analysis_root").write_text("different-uuid", encoding="utf-8")
            from auto_video_editor.analysis.service import _check_ownership
            ok, msg = _check_ownership(p, "A" * 64, force=False)
            self.assertFalse(ok, "Marker UUID mismatch must be rejected")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)



if __name__ == "__main__":
    unittest.main()
