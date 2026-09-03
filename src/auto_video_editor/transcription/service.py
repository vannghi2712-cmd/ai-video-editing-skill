"""
TranscriptionService: orchestrates media probing, caching, backend, and export.

This module contains NO ML imports — all heavy deps come in via the backend
adapter's lazy import mechanism.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from auto_video_editor.transcription import ADAPTER_VERSION, SCHEMA_VERSION
from auto_video_editor.transcription.backends import BackendUnavailableError
from auto_video_editor.transcription.backends.whisperx_backend import WhisperXBackend
from auto_video_editor.transcription.cache import (
    ALL_ARTIFACT_FILES,
    MANIFEST_FILE,
    TRANSCRIPT_FILE,
    TRANSCRIPT_RAW_FILE,
    SRT_FILE,
    WORDS_FILE,
    CacheIdentity,
    TranscriptCache,
    _write_atomic,
)
from auto_video_editor.transcription.config import TranscriptionConfig
from auto_video_editor.transcription.exporters import (
    export_raw_json,
    export_srt,
    export_transcript_json,
    export_words_json,
)
from auto_video_editor.transcription.media import MediaProbe, probe_media, verify_source_integrity
from auto_video_editor.transcription.models import (
    AlignmentInfo,
    EngineInfo,
    SourceInfo,
    TranscriptResult,
    TranscriptSegment,
    TranscriptWord,
)

DEFAULT_CACHE_DIR = ".transcription-cache"
DEFAULT_MODEL_CACHE_DIR = "model-cache"


class TranscriptionService:
    """
    Orchestrates the full transcription pipeline.

    Steps:
    1. Probe and validate source media
    2. Check content-addressed cache (unless --force)
    3. If cache miss: run backend (ASR + alignment)
    4. Export all output artifacts atomically
    5. Write outputs to user-specified output_dir
    6. Verify source file integrity after processing
    """

    def __init__(
        self,
        cache_dir: str | Path = DEFAULT_CACHE_DIR,
        model_cache_dir: str | Path = DEFAULT_MODEL_CACHE_DIR,
    ) -> None:
        self._cache = TranscriptCache(cache_dir)
        self._model_cache_dir = str(Path(model_cache_dir).resolve())
        self._backend = WhisperXBackend()
        # Point HuggingFace Hub cache to our model-cache directory
        os.environ.setdefault("HUGGINGFACE_HUB_CACHE", self._model_cache_dir)
        os.environ.setdefault("HF_HOME", self._model_cache_dir)

    def run(
        self,
        source: str | Path,
        output_dir: str | Path,
        config: TranscriptionConfig,
    ) -> dict:
        """
        Run transcription for source, writing outputs to output_dir.

        Returns result metadata dict.
        Raises:
          MediaProbeError: if source is invalid
          BackendUnavailableError: if ML deps not installed
          BackendRuntimeError: if transcription fails
          ValueError: output dir ownership conflict
        """
        out = Path(output_dir).resolve()

        # 1. Probe source
        probe = probe_media(source)

        # 2. Compute pre-run identity (model fingerprints may be string hashes
        #    before download; will be updated to file hashes post-download)
        wx_version = _safe_backend_version(self._backend)
        asr_fp_pre, align_fp_pre = self._backend.model_fingerprints(
            config, self._model_cache_dir
        )
        identity = CacheIdentity(
            source_sha256=probe.sha256,
            normalized_config=config.as_normalized_dict(),
            schema_version=SCHEMA_VERSION,
            adapter_version=ADAPTER_VERSION,
            whisperx_version=wx_version,
            asr_model_fingerprint=asr_fp_pre,
            alignment_model_fingerprint=align_fp_pre,
        )

        # 3. Check cache (skip if --force)
        if not config.force:
            cached = self._cache.get(identity)
            if cached is not None:
                TranscriptCache.validate_output_dir_ownership(out, identity)
                TranscriptCache.populate_output_dir(out, cached)
                return {
                    "cache_hit": True,
                    "job_id": identity.job_id(),
                    "output_dir": str(out),
                }
        else:
            # Force: validate ownership even when bypassing cache read
            if out.exists() and any(out.iterdir()):
                TranscriptCache.validate_output_dir_ownership(out, identity)

        # 4. Validate output dir ownership before committing any I/O
        if not config.force:
            TranscriptCache.validate_output_dir_ownership(out, identity)

        # 5. Run ASR
        t0 = time.monotonic()
        raw_segments, raw_info = self._backend.transcribe(
            str(probe.path), config
        )
        asr_elapsed = time.monotonic() - t0

        # 6. Alignment
        t1 = time.monotonic()
        if config.alignment_mode != "off":
            typed_segments, alignment_info = self._backend.align(
                raw_segments, str(probe.path), config
            )
        else:
            # No alignment requested — build unaligned segments directly
            from auto_video_editor.transcription.backends.whisperx_backend import (
                _build_unaligned_segments,
            )
            typed_segments = _build_unaligned_segments(raw_segments)
            alignment_info = AlignmentInfo(
                requested_mode=config.alignment_mode,
                actual_status="skipped",
            )
        align_elapsed = time.monotonic() - t1
        total_elapsed = time.monotonic() - t0

        # 7. Recompute model fingerprints now that models are cached on disk
        asr_fp_post, align_fp_post = self._backend.model_fingerprints(
            config, self._model_cache_dir
        )
        # Rebuild identity with post-download fingerprints if they changed
        if asr_fp_post != asr_fp_pre or align_fp_post != align_fp_pre:
            identity = CacheIdentity(
                source_sha256=probe.sha256,
                normalized_config=config.as_normalized_dict(),
                schema_version=SCHEMA_VERSION,
                adapter_version=ADAPTER_VERSION,
                whisperx_version=wx_version,
                asr_model_fingerprint=asr_fp_post,
                alignment_model_fingerprint=align_fp_post,
            )

        # 8. Build typed result
        engine_info = EngineInfo(
            name="whisperx",
            version=wx_version,
            asr_model=config.model,
            device=config.device,
            compute_type=config.compute_type,
        )
        source_info = SourceInfo(
            path=str(probe.path),
            sha256=probe.sha256,
            duration_seconds=probe.duration_seconds,
            size_bytes=probe.size_bytes,
        )
        result = TranscriptResult(
            schema_version=SCHEMA_VERSION,
            source=source_info,
            engine=engine_info,
            request=config.as_normalized_dict(),
            segments=tuple(typed_segments),
            alignment=alignment_info,
            metrics={
                "asr_elapsed_seconds": round(asr_elapsed, 3),
                "align_elapsed_seconds": round(align_elapsed, 3),
                "total_elapsed_seconds": round(total_elapsed, 3),
                "realtime_factor": round(
                    total_elapsed / probe.duration_seconds, 3
                ) if probe.duration_seconds > 0 else None,
                "segment_count": len(typed_segments),
                "word_count": sum(len(s.words) for s in typed_segments),
            },
            provenance={
                "adapter_version": ADAPTER_VERSION,
                "schema_version": SCHEMA_VERSION,
                "whisperx_version": wx_version,
                "job_id": identity.job_id(),
                "alignment_model_id": alignment_info.model_id,
            },
        )

        # 9. Serialize all artifacts
        transcript_json = export_transcript_json(result)
        srt = export_srt(result)
        words_json = export_words_json(result)
        raw_json = export_raw_json(raw_segments)

        artifacts = {
            TRANSCRIPT_FILE: transcript_json,
            SRT_FILE: srt,
            WORDS_FILE: words_json,
            TRANSCRIPT_RAW_FILE: raw_json,
        }

        # 10. Write to cache (atomic)
        manifest = self._cache.put(
            identity,
            artifacts,
            str(probe.path),
            probe.duration_seconds,
        )

        # 11. Populate output directory from cache
        cached_entry = self._cache.get(identity)
        if cached_entry:
            TranscriptCache.populate_output_dir(out, cached_entry)

        # 12. Verify source integrity after ALL processing
        verify_source_integrity(probe)

        return {
            "cache_hit": False,
            "job_id": identity.job_id(),
            "output_dir": str(out),
            "metrics": result.metrics,
            "alignment_status": alignment_info.actual_status,
            "words_aligned": alignment_info.words_aligned,
            "words_total": alignment_info.words_total,
            "manifest": manifest,
        }


def _safe_backend_version(backend: WhisperXBackend) -> str:
    """Return backend version without raising if deps are missing."""
    try:
        return backend.version()
    except BackendUnavailableError:
        return "unavailable"
