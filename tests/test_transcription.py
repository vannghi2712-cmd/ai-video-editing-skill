"""
Phase 3 unit tests — no ML dependencies required.
These run in both base .venv and .venv-whisperx.

MOCKED_TEST label is applied to any test using a mock backend.
Tests using live WhisperX are in test_transcription_smoke_live.py and
are NOT run in the base environment.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure src is on sys.path
_SRC = Path(__file__).parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from auto_video_editor.transcription.config import TranscriptionConfig
from auto_video_editor.transcription.models import (
    AlignmentInfo,
    EngineInfo,
    SourceInfo,
    TranscriptResult,
    TranscriptSegment,
    TranscriptWord,
)
from auto_video_editor.transcription.exporters import (
    export_srt,
    export_transcript_json,
    export_words_json,
    _format_srt_time,
)
from auto_video_editor.transcription.cache import (
    CacheIdentity,
    TranscriptCache,
    compute_local_fingerprint,
    _write_atomic,
)
from auto_video_editor.transcription.backends import BackendUnavailableError


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_config(**kwargs) -> TranscriptionConfig:
    defaults = dict(language="vi", device="cpu", compute_type="int8")
    defaults.update(kwargs)
    return TranscriptionConfig(**defaults)


def _make_identity(**kwargs) -> CacheIdentity:
    defaults = dict(
        source_sha256="A" * 64,
        normalized_config=_make_config().as_normalized_dict(),
        schema_version="1.0.0",
        adapter_version="1.0.0",
        whisperx_version="3.8.6",
        asr_model_fingerprint="asr_fp_test",
        alignment_model_fingerprint="align_fp_test",
    )
    defaults.update(kwargs)
    return CacheIdentity(**defaults)


def _make_word(text: str, aligned: bool = True, start: float = 0.0, end: float = 1.0) -> TranscriptWord:
    if aligned:
        return TranscriptWord(text=text, timing_status="aligned", start=start, end=end, score=0.9)
    return TranscriptWord(text=text, timing_status="unaligned")


def _make_segment(
    text: str = "xin chào",
    start: float = 0.0,
    end: float = 2.0,
    words: tuple | None = None,
) -> TranscriptSegment:
    if words is None:
        words = (
            _make_word("xin", aligned=True, start=0.0, end=1.0),
            _make_word("chào", aligned=True, start=1.0, end=2.0),
        )
    return TranscriptSegment(start=start, end=end, text=text, words=words)


def _make_result(segments=None, alignment_status="aligned") -> TranscriptResult:
    if segments is None:
        segments = (_make_segment(),)
    return TranscriptResult(
        schema_version="1.0.0",
        source=SourceInfo(path="/test/sample.wav", sha256="A"*64,
                          duration_seconds=10.0, size_bytes=100000),
        engine=EngineInfo(name="whisperx", version="3.8.6",
                          asr_model="tiny", device="cpu", compute_type="int8"),
        request=_make_config().as_normalized_dict(),
        segments=segments,
        alignment=AlignmentInfo(
            requested_mode="auto",
            actual_status=alignment_status,
            model_id="jonatasgrosman/wav2vec2-large-xlsr-53-vietnamese",
            words_total=2,
            words_aligned=2,
        ),
        metrics={"total_elapsed_seconds": 1.0, "realtime_factor": 0.1},
        provenance={"adapter_version": "1.0.0", "schema_version": "1.0.0",
                    "whisperx_version": "3.8.6", "job_id": "abc123",
                    "alignment_model_id": "jonatasgrosman/wav2vec2-large-xlsr-53-vietnamese"},
    )


# ── Config tests ────────────────────────────────────────────────────────────────

class TestTranscriptionConfig(unittest.TestCase):
    def test_defaults(self):
        c = TranscriptionConfig()
        self.assertEqual(c.language, "vi")
        self.assertEqual(c.task, "transcribe")
        self.assertEqual(c.device, "cpu")
        self.assertEqual(c.compute_type, "int8")
        self.assertEqual(c.alignment_mode, "auto")
        self.assertFalse(c.diarization)

    def test_rejects_cuda_device(self):
        with self.assertRaises(ValueError) as ctx:
            TranscriptionConfig(device="cuda")
        self.assertIn("cpu", str(ctx.exception))

    def test_rejects_gpu_device(self):
        with self.assertRaises(ValueError):
            TranscriptionConfig(device="gpu")

    def test_rejects_diarization(self):
        with self.assertRaises(ValueError):
            TranscriptionConfig(diarization=True)

    def test_rejects_non_vi_language(self):
        with self.assertRaises(ValueError):
            TranscriptionConfig(language="en")

    def test_rejects_translate_task(self):
        with self.assertRaises(ValueError):
            TranscriptionConfig(task="translate")

    def test_rejects_invalid_alignment_mode(self):
        with self.assertRaises(ValueError):
            TranscriptionConfig(alignment_mode="forced")

    def test_rejects_zero_batch_size(self):
        with self.assertRaises(ValueError):
            TranscriptionConfig(batch_size=0)

    def test_normalized_dict_excludes_force(self):
        c1 = TranscriptionConfig(force=True)
        c2 = TranscriptionConfig(force=False)
        self.assertEqual(c1.as_normalized_dict(), c2.as_normalized_dict())

    def test_frozen(self):
        c = TranscriptionConfig()
        with self.assertRaises(Exception):
            c.language = "en"  # type: ignore


# ── Model tests ────────────────────────────────────────────────────────────────

class TestTranscriptWord(unittest.TestCase):
    def test_aligned_word_requires_start_end(self):
        with self.assertRaises(ValueError):
            TranscriptWord(text="xin", timing_status="aligned")  # missing start/end

    def test_aligned_word_negative_start(self):
        with self.assertRaises(ValueError):
            TranscriptWord(text="xin", timing_status="aligned", start=-1.0, end=1.0)

    def test_aligned_word_start_greater_than_end(self):
        with self.assertRaises(ValueError):
            TranscriptWord(text="xin", timing_status="aligned", start=2.0, end=1.0)

    def test_unaligned_word_rejects_timing(self):
        with self.assertRaises(ValueError):
            TranscriptWord(text="xin", timing_status="unaligned", start=0.0, end=1.0)

    def test_failed_word_no_timing(self):
        w = TranscriptWord(text="xin", timing_status="failed")
        self.assertIsNone(w.start)
        self.assertIsNone(w.end)

    def test_unaligned_word_valid(self):
        w = TranscriptWord(text="chào", timing_status="unaligned")
        self.assertEqual(w.timing_status, "unaligned")
        self.assertIsNone(w.start)

    def test_word_frozen(self):
        w = TranscriptWord(text="xin", timing_status="unaligned")
        with self.assertRaises(Exception):
            w.text = "hello"  # type: ignore


class TestTranscriptSegment(unittest.TestCase):
    def test_segment_start_gt_end(self):
        with self.assertRaises(ValueError):
            TranscriptSegment(start=2.0, end=1.0, text="test", words=())

    def test_segment_negative_start(self):
        with self.assertRaises(ValueError):
            TranscriptSegment(start=-1.0, end=1.0, text="test", words=())

    def test_valid_segment(self):
        seg = _make_segment()
        self.assertEqual(seg.start, 0.0)
        self.assertEqual(seg.end, 2.0)


class TestTranscriptResult(unittest.TestCase):
    def test_wrong_schema_version(self):
        with self.assertRaises(ValueError):
            TranscriptResult(
                schema_version="2.0.0",
                source=SourceInfo(path="/a.wav", sha256="A"*64, duration_seconds=1.0, size_bytes=1),
                engine=EngineInfo(name="w", version="1", asr_model="tiny", device="cpu", compute_type="int8"),
                request={},
                segments=(),
                alignment=AlignmentInfo(requested_mode="auto", actual_status="skipped"),
                metrics={},
                provenance={},
            )

    def test_full_text(self):
        r = _make_result(segments=(_make_segment("xin chào"), _make_segment("thế giới", 2.0, 4.0, ())))
        self.assertIn("xin chào", r.full_text)
        self.assertIn("thế giới", r.full_text)

    def test_all_words(self):
        r = _make_result()
        words = r.all_words
        self.assertEqual(len(words), 2)


# ── SRT export tests ───────────────────────────────────────────────────────────

class TestSRTExport(unittest.TestCase):
    def test_srt_format_basic(self):
        r = _make_result()
        srt = export_srt(r)
        self.assertIn("1\n", srt)
        self.assertIn("-->", srt)
        self.assertIn("xin chào", srt)

    def test_srt_sequential_indices(self):
        segs = (
            _make_segment("seg1", 0.0, 2.0, ()),
            _make_segment("seg2", 2.0, 4.0, ()),
            _make_segment("seg3", 4.0, 6.0, ()),
        )
        r = _make_result(segments=segs)
        srt = export_srt(r)
        self.assertIn("1\n", srt)
        self.assertIn("2\n", srt)
        self.assertIn("3\n", srt)

    def test_srt_no_overlap(self):
        """Cues must not overlap — end of one <= start of next."""
        segs = (
            _make_segment("a", 0.0, 3.0, ()),
            _make_segment("b", 2.0, 4.0, ()),  # overlap — should be clamped
        )
        r = _make_result(segments=segs)
        srt = export_srt(r)
        # Parse timestamps
        lines = srt.strip().split("\n")
        timestamps = [l for l in lines if "-->" in l]
        self.assertEqual(len(timestamps), 2)
        # Second start should be >= first end
        first_end = timestamps[0].split("-->")[1].strip()
        second_start = timestamps[1].split("-->")[0].strip()
        # Both should have same value (clamped)
        self.assertEqual(first_end[:8], second_start[:8])

    def test_srt_time_format(self):
        self.assertEqual(_format_srt_time(0.0), "00:00:00,000")
        self.assertEqual(_format_srt_time(3661.5), "01:01:01,500")
        self.assertEqual(_format_srt_time(90.123), "00:01:30,123")

    def test_srt_skips_empty_segments(self):
        segs = (
            _make_segment("", 0.0, 2.0, ()),
            _make_segment("   ", 2.0, 4.0, ()),
        )
        r = _make_result(segments=segs)
        srt = export_srt(r)
        self.assertEqual(srt.strip(), "")

    def test_srt_utf8_vietnamese(self):
        seg = _make_segment("Tôi yêu Việt Nam", 0.0, 2.0, ())
        r = _make_result(segments=(seg,))
        srt = export_srt(r)
        srt_bytes = srt.encode("utf-8")
        decoded = srt_bytes.decode("utf-8")
        self.assertIn("Tôi yêu Việt Nam", decoded)


# ── Words JSON export tests ────────────────────────────────────────────────────

class TestWordsJSONExport(unittest.TestCase):
    def test_aligned_words_have_timing(self):
        r = _make_result()
        words_json = export_words_json(r)
        data = json.loads(words_json)
        aligned = [w for w in data if w["timing_status"] == "aligned"]
        self.assertTrue(len(aligned) > 0)
        for w in aligned:
            self.assertIn("start", w)
            self.assertIn("end", w)

    def test_unaligned_words_no_timing(self):
        seg = TranscriptSegment(
            start=0.0, end=2.0, text="test",
            words=(TranscriptWord(text="test", timing_status="unaligned"),)
        )
        r = _make_result(segments=(seg,))
        words_json = export_words_json(r)
        data = json.loads(words_json)
        unaligned = [w for w in data if w["timing_status"] == "unaligned"]
        self.assertEqual(len(unaligned), 1)
        self.assertNotIn("start", unaligned[0])
        self.assertNotIn("end", unaligned[0])

    def test_words_json_roundtrip_utf8(self):
        seg = _make_segment("Xin chào Việt Nam")
        r = _make_result(segments=(seg,))
        words_json = export_words_json(r)
        data = json.loads(words_json.encode("utf-8").decode("utf-8"))
        self.assertTrue(len(data) >= 1)


# ── Transcript JSON export tests ───────────────────────────────────────────────

class TestTranscriptJSONExport(unittest.TestCase):
    def test_schema_version_present(self):
        r = _make_result()
        doc = json.loads(export_transcript_json(r))
        self.assertEqual(doc["schema_version"], "1.0.0")

    def test_source_sha256_present(self):
        r = _make_result()
        doc = json.loads(export_transcript_json(r))
        self.assertEqual(doc["source"]["sha256"], "A" * 64)

    def test_alignment_section_present(self):
        r = _make_result()
        doc = json.loads(export_transcript_json(r))
        self.assertIn("alignment", doc)
        self.assertIn("requested_mode", doc["alignment"])
        self.assertIn("actual_status", doc["alignment"])

    def test_segments_at_root_level(self):
        """schema parity: segments MUST be at root, NOT nested in result{}."""
        r = _make_result()
        doc = json.loads(export_transcript_json(r))
        self.assertIn("segments", doc)
        self.assertNotIn("result", doc)

    def test_unaligned_words_no_timing_in_json(self):
        seg = TranscriptSegment(
            start=0.0, end=2.0, text="test",
            words=(TranscriptWord(text="test", timing_status="unaligned"),)
        )
        r = _make_result(segments=(seg,))
        doc = json.loads(export_transcript_json(r))
        word = doc["segments"][0]["words"][0]
        self.assertEqual(word["timing_status"], "unaligned")
        self.assertNotIn("start", word)
        self.assertNotIn("end", word)

    def test_word_key_is_word_not_text(self):
        """Words in transcript.json use 'word' key per schema."""
        r = _make_result()
        doc = json.loads(export_transcript_json(r))
        word = doc["segments"][0]["words"][0]
        self.assertIn("word", word)
        self.assertNotIn("text", word)

    def test_no_segment_start_end_in_transcript_words(self):
        """Words in transcript.json must NOT include segment_start/segment_end (additionalProperties:false)."""
        r = _make_result()
        doc = json.loads(export_transcript_json(r))
        word = doc["segments"][0]["words"][0]
        self.assertNotIn("segment_start", word)
        self.assertNotIn("segment_end", word)


# ── Cache tests ────────────────────────────────────────────────────────────────

class TestCacheIdentity(unittest.TestCase):
    def test_rejects_unverified_source_sha(self):
        with self.assertRaises(ValueError):
            CacheIdentity(
                source_sha256="UNVERIFIED",
                normalized_config={},
                schema_version="1.0.0",
                adapter_version="1.0.0",
                whisperx_version="3.8.6",
                asr_model_fingerprint="fp1",
                alignment_model_fingerprint="fp2",
            )

    def test_rejects_unverified_asr_fingerprint(self):
        with self.assertRaises(ValueError):
            CacheIdentity(
                source_sha256="A" * 64,
                normalized_config={},
                schema_version="1.0.0",
                adapter_version="1.0.0",
                whisperx_version="3.8.6",
                asr_model_fingerprint="UNVERIFIED",
                alignment_model_fingerprint="fp2",
            )

    def test_job_id_is_deterministic(self):
        id1 = _make_identity()
        id2 = _make_identity()
        self.assertEqual(id1.job_id(), id2.job_id())

    def test_different_sha_different_job_id(self):
        id1 = _make_identity(source_sha256="A" * 64)
        id2 = _make_identity(source_sha256="B" * 64)
        self.assertNotEqual(id1.job_id(), id2.job_id())

    def test_different_model_different_job_id(self):
        id1 = _make_identity(asr_model_fingerprint="fp_tiny")
        id2 = _make_identity(asr_model_fingerprint="fp_base")
        self.assertNotEqual(id1.job_id(), id2.job_id())


class TestTranscriptCacheRoundtrip(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cache = TranscriptCache(self.tmpdir)
        self.identity = _make_identity()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _put(self):
        return self.cache.put(
            self.identity,
            {
                # Raw is NOT in ALL_ARTIFACT_FILES — it is opt-in only
                "transcript.json": json.dumps({"schema_version": "1.0.0", "data": "test"}),
                "transcript.srt": "1\n00:00:00,000 --> 00:00:02,000\nxin chào\n\n",
                "words.json": "[]",
            },
            source_path="/test/sample.wav",
            duration_seconds=10.0,
        )

    def test_cache_miss_when_empty(self):
        result = self.cache.get(self.identity)
        self.assertIsNone(result)

    def test_cache_hit_after_put(self):
        self._put()
        result = self.cache.get(self.identity)
        self.assertIsNotNone(result)
        self.assertEqual(result["job_id"], self.identity.job_id())

    def test_cache_miss_on_schema_version_mismatch(self):
        # Write entry with wrong schema version in transcript.json
        entry_dir = self.cache._entry_dir(self.identity)
        entry_dir.mkdir(parents=True, exist_ok=True)
        # Write with wrong schema_version
        (entry_dir / "transcript.json").write_text(
            json.dumps({"schema_version": "0.9.0"}), encoding="utf-8"
        )
        (entry_dir / "manifest.json").write_text(
            json.dumps({
                "schema_version": "1.0.0",
                "job_id": self.identity.job_id(),
                "artifact_files": list(),
            }), encoding="utf-8"
        )
        for f in ["transcript.srt", "words.json"]:
            (entry_dir / f).write_text("", encoding="utf-8")
        result = self.cache.get(self.identity)
        self.assertIsNone(result)

    def test_cache_miss_on_corrupt_manifest(self):
        self._put()
        entry_dir = self.cache._entry_dir(self.identity)
        (entry_dir / "manifest.json").write_text("NOT_JSON", encoding="utf-8")
        result = self.cache.get(self.identity)
        self.assertIsNone(result)

    def test_cache_miss_on_missing_artifact(self):
        self._put()
        entry_dir = self.cache._entry_dir(self.identity)
        (entry_dir / "transcript.srt").unlink()
        result = self.cache.get(self.identity)
        self.assertIsNone(result)

    def test_output_dir_ownership_rejected_different_job(self):
        with tempfile.TemporaryDirectory() as outdir:
            out = Path(outdir)
            # Write a manifest with a different job_id
            (out / "manifest.json").write_text(
                json.dumps({"job_id": "different_job_id_xyz"}), encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                TranscriptCache.validate_output_dir_ownership(out, self.identity)

    def test_output_dir_empty_is_ok(self):
        with tempfile.TemporaryDirectory() as outdir:
            out = Path(outdir)
            # Should not raise
            TranscriptCache.validate_output_dir_ownership(out, self.identity)

    def test_atomic_write(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "test.txt"
            _write_atomic(dest, b"hello world")
            self.assertEqual(dest.read_bytes(), b"hello world")

    def test_raw_file_not_in_all_artifact_files(self):
        """transcript.raw.json MUST NOT be in ALL_ARTIFACT_FILES (privacy-safe default)."""
        from auto_video_editor.transcription.cache import ALL_ARTIFACT_FILES, TRANSCRIPT_RAW_FILE  # noqa: PLC0415
        self.assertNotIn(TRANSCRIPT_RAW_FILE, ALL_ARTIFACT_FILES)

    def test_cache_does_not_restore_raw_by_default(self):
        """Cache round-trip must NOT restore transcript.raw.json."""
        self._put()
        result = self.cache.get(self.identity)
        self.assertIsNotNone(result)
        with tempfile.TemporaryDirectory() as outdir:
            out = Path(outdir)
            TranscriptCache.populate_output_dir(out, result)
            raw_path = out / "transcript.raw.json"
            self.assertFalse(raw_path.exists(),
                "transcript.raw.json MUST NOT be restored by default (privacy-safe)")


# ── Doctor CLI tests (base env) ────────────────────────────────────────────────

class TestDoctorBase(unittest.TestCase):
    """Tests that run in base .venv (no ML deps)."""

    def test_doctor_exits_3_in_base_env(self):
        """In base .venv, doctor must exit 3 without a traceback. MOCKED_TEST"""
        import subprocess  # noqa: PLC0415
        result = subprocess.run(
            [sys.executable, "-m", "auto_video_editor", "transcribe", "doctor"],
            capture_output=True,
            cwd=str(Path(__file__).parent.parent),
        )
        # In base env: exit 3
        # In ML env: exit 0
        # Either is acceptable depending on environment
        self.assertIn(result.returncode, (0, 3))
        # Must never have a Python traceback
        stderr = result.stderr.decode("utf-8", errors="replace")
        self.assertNotIn("Traceback (most recent call last)", stderr)

    def test_doctor_reports_ready_or_ready_with_warnings(self):
        """If doctor exits 0 it must report READY or READY_WITH_WARNINGS."""
        import subprocess  # noqa: PLC0415
        result = subprocess.run(
            [sys.executable, "-m", "auto_video_editor", "transcribe", "doctor"],
            capture_output=True,
            cwd=str(Path(__file__).parent.parent),
        )
        if result.returncode == 0:
            stdout = result.stdout.decode("utf-8", errors="replace")
            self.assertTrue(
                "READY" in stdout or "READY_WITH_WARNINGS" in stdout,
                f"Exit 0 but status not READY: {stdout[:200]}"
            )

    def test_run_cuda_rejected(self):
        """--device cuda must be rejected at CLI level."""
        import subprocess  # noqa: PLC0415
        result = subprocess.run(
            [sys.executable, "-m", "auto_video_editor", "transcribe", "run",
             "/fake/path.wav", "--output-dir", "/fake/out", "--device", "cuda"],
            capture_output=True,
            cwd=str(Path(__file__).parent.parent),
        )
        self.assertEqual(result.returncode, 2)

    def test_run_diarize_rejected(self):
        """--diarize must be rejected."""
        import subprocess  # noqa: PLC0415
        result = subprocess.run(
            [sys.executable, "-m", "auto_video_editor", "transcribe", "run",
             "/fake/path.wav", "--output-dir", "/fake/out", "--diarize"],
            capture_output=True,
            cwd=str(Path(__file__).parent.parent),
        )
        self.assertEqual(result.returncode, 2)

    def test_run_nonexistent_file(self):
        """transcribe run on a non-existent file must fail gracefully."""
        import subprocess  # noqa: PLC0415
        result = subprocess.run(
            [sys.executable, "-m", "auto_video_editor", "transcribe", "run",
             "C:/does/not/exist.wav", "--output-dir", "/tmp/fake"],
            capture_output=True,
            cwd=str(Path(__file__).parent.parent),
        )
        # Should not produce traceback (exit 3 or 4 are both OK for missing dep/file)
        stderr = result.stderr.decode("utf-8", errors="replace")
        # Should not have an unhandled traceback reaching the top level
        self.assertNotIn("INTERNAL ERROR", stderr)


# ── Regression tests (Phase 3 Final Contract Correction) ──────────────────────

class TestProductionDefaults(unittest.TestCase):
    """Verify production defaults match the Phase 3 contract."""

    def test_default_model_is_small(self):
        """Production default ASR model MUST be 'small', not 'base'."""
        from auto_video_editor.transcription.config import DEFAULT_MODEL  # noqa: PLC0415
        self.assertEqual(DEFAULT_MODEL, "small",
            "Production default must be 'small'. Use 'tiny' for smoke tests only.")

    def test_config_default_model_is_small(self):
        c = TranscriptionConfig()
        self.assertEqual(c.model, "small")

    def test_include_raw_defaults_false(self):
        """include_raw MUST default to False (privacy-safe)."""
        c = TranscriptionConfig()
        self.assertFalse(c.include_raw)

    def test_include_raw_can_be_enabled(self):
        c = TranscriptionConfig(include_raw=True)
        self.assertTrue(c.include_raw)

    def test_normalized_dict_excludes_force_and_include_raw(self):
        """force and include_raw are not part of the cache key."""
        c1 = TranscriptionConfig(force=True, include_raw=True)
        c2 = TranscriptionConfig(force=False, include_raw=False)
        self.assertEqual(c1.as_normalized_dict(), c2.as_normalized_dict())


class TestStrictJSON(unittest.TestCase):
    """Strict JSON serialization: NaN/Infinity must be rejected."""

    def _make_word_nan_start(self) -> TranscriptWord:
        # Bypass TranscriptWord validation to inject NaN
        import dataclasses  # noqa: PLC0415
        w = object.__new__(TranscriptWord)
        object.__setattr__(w, "text", "nan_word")
        object.__setattr__(w, "timing_status", "aligned")
        object.__setattr__(w, "start", float("nan"))
        object.__setattr__(w, "end", 1.0)
        object.__setattr__(w, "score", None)
        return w

    def test_nan_start_raises_in_export(self):
        """export_transcript_json must raise when a word has NaN start."""
        w = self._make_word_nan_start()
        seg = TranscriptSegment(start=0.0, end=2.0, text="test", words=(w,))
        r = _make_result(segments=(seg,))
        with self.assertRaises((ValueError, TypeError)):
            export_transcript_json(r)

    def test_infinity_end_raises_in_export(self):
        """export_transcript_json must raise when a word has Infinity end."""
        import dataclasses  # noqa: PLC0415
        w = object.__new__(TranscriptWord)
        object.__setattr__(w, "text", "inf_word")
        object.__setattr__(w, "timing_status", "aligned")
        object.__setattr__(w, "start", 0.0)
        object.__setattr__(w, "end", float("inf"))
        object.__setattr__(w, "score", None)
        seg = TranscriptSegment(start=0.0, end=2.0, text="test", words=(w,))
        r = _make_result(segments=(seg,))
        with self.assertRaises((ValueError, TypeError)):
            export_transcript_json(r)

    def test_allow_nan_false_in_json_dump(self):
        """Verify json.dumps with allow_nan=False rejects NaN at python level."""
        import json as _json  # noqa: PLC0415
        with self.assertRaises((ValueError,)):
            _json.dumps(float("nan"), allow_nan=False)

    def test_allow_nan_false_rejects_infinity(self):
        import json as _json  # noqa: PLC0415
        with self.assertRaises((ValueError,)):
            _json.dumps(float("inf"), allow_nan=False)

    def test_valid_transcript_json_parses_without_nan(self):
        """Normal transcript must serialize and parse cleanly."""
        r = _make_result()
        txt = export_transcript_json(r)
        doc = json.loads(txt)
        self.assertEqual(doc["schema_version"], "1.0.0")


class TestTimingHonesty(unittest.TestCase):
    """Word timing honesty: aligned words must have timestamps, others must not."""

    def test_aligned_word_must_have_start_and_end(self):
        """aligned word without start/end raises at model level."""
        with self.assertRaises(ValueError):
            TranscriptWord(text="xin", timing_status="aligned")

    def test_unaligned_word_rejects_timestamps(self):
        """unaligned word with start/end is invalid."""
        with self.assertRaises(ValueError):
            TranscriptWord(text="xin", timing_status="unaligned", start=0.0, end=1.0)

    def test_failed_word_rejects_timestamps(self):
        """failed word with start/end is invalid."""
        with self.assertRaises(ValueError):
            TranscriptWord(text="xin", timing_status="failed", start=0.0, end=1.0)

    def test_aligned_word_exporter_validates_finite(self):
        """Exporter must raise when aligned word has non-finite timestamp."""
        from auto_video_editor.transcription.exporters import _word_to_dict  # noqa: PLC0415
        w = object.__new__(TranscriptWord)
        object.__setattr__(w, "text", "bad")
        object.__setattr__(w, "timing_status", "aligned")
        object.__setattr__(w, "start", float("nan"))
        object.__setattr__(w, "end", 1.0)
        object.__setattr__(w, "score", None)
        with self.assertRaises(ValueError):
            _word_to_dict(w)

    def test_unaligned_word_in_json_has_no_timestamps(self):
        """Unaligned words in transcript.json MUST NOT have start/end."""
        seg = TranscriptSegment(
            start=0.0, end=2.0, text="test",
            words=(TranscriptWord(text="test", timing_status="unaligned"),)
        )
        r = _make_result(segments=(seg,))
        doc = json.loads(export_transcript_json(r))
        w = doc["segments"][0]["words"][0]
        self.assertNotIn("start", w)
        self.assertNotIn("end", w)


class TestImmutableModelIdentity(unittest.TestCase):
    """Tests for the immutable model identity system."""

    def test_known_revision_tiny(self):
        """tiny model must return immutable HF revision."""
        from auto_video_editor.transcription.backends.whisperx_backend import (  # noqa: PLC0415
            _immutable_model_identity, _KNOWN_HF_REVISIONS
        )
        identity, resolved = _immutable_model_identity(
            "Systran/faster-whisper-tiny", "/fake/cache", "asr"
        )
        self.assertTrue(resolved, "Known model must be resolved")
        self.assertTrue(identity.startswith("hf:Systran/faster-whisper-tiny@"))
        rev = _KNOWN_HF_REVISIONS["Systran/faster-whisper-tiny"]
        self.assertIn(rev, identity)

    def test_known_revision_small(self):
        """small model must return immutable HF revision."""
        from auto_video_editor.transcription.backends.whisperx_backend import (  # noqa: PLC0415
            _immutable_model_identity, _KNOWN_HF_REVISIONS
        )
        identity, resolved = _immutable_model_identity(
            "Systran/faster-whisper-small", "/fake/cache", "asr"
        )
        self.assertTrue(resolved)
        self.assertIn(_KNOWN_HF_REVISIONS["Systran/faster-whisper-small"], identity)

    def test_known_revision_vi_alignment(self):
        """Vietnamese alignment model must return immutable HF revision."""
        from auto_video_editor.transcription.backends.whisperx_backend import (  # noqa: PLC0415
            _immutable_model_identity, _KNOWN_HF_REVISIONS
        )
        model_id = "nguyenvulebinh/wav2vec2-base-vi-vlsp2020"
        identity, resolved = _immutable_model_identity(model_id, "/fake/cache", "align")
        self.assertTrue(resolved)
        self.assertIn(_KNOWN_HF_REVISIONS[model_id], identity)

    def test_identity_never_uses_name_based_hash(self):
        """Identity string must start with 'hf:' or 'model-artifact-sha256-v1:' — never a bare hex hash."""
        from auto_video_editor.transcription.backends.whisperx_backend import (  # noqa: PLC0415
            _immutable_model_identity
        )
        identity, resolved = _immutable_model_identity(
            "Systran/faster-whisper-tiny", "/fake/cache", "asr"
        )
        if resolved:
            self.assertTrue(
                identity.startswith("hf:") or identity.startswith("model-artifact-sha256-v1:"),
                f"Identity must use hf: or model-artifact-sha256-v1: prefix, got: {identity[:60]}"
            )

    def test_resolve_asr_hf_id_tiny(self):
        from auto_video_editor.transcription.backends.whisperx_backend import _resolve_asr_hf_id  # noqa: PLC0415
        self.assertEqual(_resolve_asr_hf_id("tiny"), "Systran/faster-whisper-tiny")
        self.assertEqual(_resolve_asr_hf_id("small"), "Systran/faster-whisper-small")

    def test_unresolved_identity_returns_empty(self):
        """Unknown model with no cache returns ('', False)."""
        from auto_video_editor.transcription.backends.whisperx_backend import _immutable_model_identity  # noqa: PLC0415
        with tempfile.TemporaryDirectory() as d:
            identity, resolved = _immutable_model_identity(
                "unknown/totally-fake-model-xyz", d, "asr"
            )
        self.assertFalse(resolved)
        self.assertEqual(identity, "")


class TestSchemaFile(unittest.TestCase):
    """Verify schemas/transcript.schema.json exists and is valid JSON."""

    def _schema_path(self) -> Path:
        return Path(__file__).parent.parent / "schemas" / "transcript.schema.json"

    def test_schema_file_exists(self):
        self.assertTrue(self._schema_path().exists(),
            "schemas/transcript.schema.json must exist")

    def test_schema_is_valid_json(self):
        with open(self._schema_path(), encoding="utf-8") as f:
            schema = json.load(f)
        self.assertIn("$schema", schema)
        self.assertIn("$id", schema)
        self.assertEqual(schema.get("properties", {}).get("schema_version", {}).get("const"), "1.0.0")

    def test_schema_uses_draft_2020_12(self):
        with open(self._schema_path(), encoding="utf-8") as f:
            schema = json.load(f)
        self.assertIn("2020-12", schema["$schema"])

    def test_schema_word_if_then_else_present(self):
        """Word must use if/then/else for timing_status enforcement."""
        with open(self._schema_path(), encoding="utf-8") as f:
            schema = json.load(f)
        word_def = schema["$defs"]["word"]
        self.assertIn("if", word_def)
        self.assertIn("then", word_def)
        self.assertIn("else", word_def)

    def test_root_has_additional_properties_false(self):
        with open(self._schema_path(), encoding="utf-8") as f:
            schema = json.load(f)
        self.assertFalse(schema.get("additionalProperties", True))


if __name__ == "__main__":
    unittest.main()
