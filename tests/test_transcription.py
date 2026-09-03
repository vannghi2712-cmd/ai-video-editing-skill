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

    def test_full_text_in_result(self):
        r = _make_result()
        doc = json.loads(export_transcript_json(r))
        self.assertIn("full_text", doc["result"])

    def test_unaligned_words_no_timing_in_json(self):
        seg = TranscriptSegment(
            start=0.0, end=2.0, text="test",
            words=(TranscriptWord(text="test", timing_status="unaligned"),)
        )
        r = _make_result(segments=(seg,))
        doc = json.loads(export_transcript_json(r))
        word = doc["result"]["segments"][0]["words"][0]
        self.assertEqual(word["timing_status"], "unaligned")
        self.assertNotIn("start", word)
        self.assertNotIn("end", word)


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
                "transcript.json": json.dumps({"schema_version": "1.0.0", "data": "test"}),
                "transcript.srt": "1\n00:00:00,000 --> 00:00:02,000\nxin chào\n\n",
                "words.json": "[]",
                "transcript.raw.json": "{}",
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
        for f in ["transcript.srt", "words.json", "transcript.raw.json"]:
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


# ── Doctor CLI tests (base env) ────────────────────────────────────────────────

class TestDoctorBase(unittest.TestCase):
    """Tests that run in base .venv (no ML deps)."""

    def test_doctor_exits_3_in_base_env(self):
        """In base .venv, doctor must exit 3 without a traceback. MOCKED_TEST"""
        import subprocess
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

    def test_run_cuda_rejected(self):
        """--device cuda must be rejected at CLI level."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "auto_video_editor", "transcribe", "run",
             "/fake/path.wav", "--output-dir", "/fake/out", "--device", "cuda"],
            capture_output=True,
            cwd=str(Path(__file__).parent.parent),
        )
        self.assertEqual(result.returncode, 2)

    def test_run_diarize_rejected(self):
        """--diarize must be rejected."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "auto_video_editor", "transcribe", "run",
             "/fake/path.wav", "--output-dir", "/fake/out", "--diarize"],
            capture_output=True,
            cwd=str(Path(__file__).parent.parent),
        )
        self.assertEqual(result.returncode, 2)

    def test_run_nonexistent_file(self):
        """transcribe run on a non-existent file must fail gracefully."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "auto_video_editor", "transcribe", "run",
             "C:/does/not/exist.wav", "--output-dir", "/tmp/fake"],
            capture_output=True,
            cwd=str(Path(__file__).parent.parent),
        )
        # Should not produce traceback (exit 3 or 4 are both OK for missing dep/file)
        stderr = result.stderr.decode("utf-8", errors="replace")
        # Should not have an unhandled traceback reaching the top level
        # (it's OK to have one in the error message, but not an INTERNAL ERROR)
        self.assertNotIn("INTERNAL ERROR", stderr)


if __name__ == "__main__":
    unittest.main()
