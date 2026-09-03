"""
WhisperX backend adapter — ALL whisperx/torch imports are LAZY.

This module can be imported in the base `.venv` without installing WhisperX.
Any attempt to actually run transcription in the base env will raise
BackendUnavailableError with a clear, traceback-free message.

Vietnamese alignment model discovery:
  WhisperX 3.8.x maps 'vi' → wav2vec2 model via its internal
  DEFAULT_ALIGN_MODELS_HF table. We introspect the installed package to
  get the exact model ID rather than hard-coding it.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from auto_video_editor.transcription.backends import (
    BackendRuntimeError,
    BackendUnavailableError,
)
from auto_video_editor.transcription.cache import compute_local_fingerprint
from auto_video_editor.transcription.config import TranscriptionConfig
from auto_video_editor.transcription.models import (
    AlignmentInfo,
    TranscriptSegment,
    TranscriptWord,
)


def _require_whisperx() -> Any:
    """
    Lazily import whisperx. Raises BackendUnavailableError if missing.
    Never raises ImportError with a traceback into the user's terminal.
    """
    try:
        import whisperx  # noqa: PLC0415
        return whisperx
    except ImportError as exc:
        raise BackendUnavailableError(
            "WhisperX is not installed in this environment.\n"
            "Install it with: pip install -e '.[transcription]' "
            "(in the .venv-whisperx environment)\n"
            f"Underlying import error: {exc}"
        ) from exc


def _require_torch() -> Any:
    try:
        import torch  # noqa: PLC0415
        return torch
    except ImportError as exc:
        raise BackendUnavailableError(
            "PyTorch is not installed in this environment."
        ) from exc


class WhisperXBackend:
    """
    WhisperX-backed ASR + forced alignment adapter.

    WhisperX, torch, and faster-whisper are only imported when a method
    is actually called, so the class can be referenced in base `.venv`.
    """

    def version(self) -> str:
        _require_whisperx()  # Ensure deps available
        try:
            from importlib.metadata import version as pkg_version  # noqa: PLC0415
            return pkg_version("whisperx")
        except Exception:
            import whisperx  # noqa: PLC0415
            return getattr(whisperx, "__version__", "unknown")

    def model_fingerprints(
        self,
        config: TranscriptionConfig,
        model_cache_dir: str,
    ) -> tuple[str, str]:
        """
        Return (asr_fingerprint, alignment_fingerprint).

        Computes local file fingerprints if models are cached; otherwise
        uses a hash of the model name string to produce a stable non-UNVERIFIED
        fingerprint.
        """
        # ASR model fingerprint
        asr_fingerprint = _model_fingerprint(
            config.model, model_cache_dir, "asr"
        )

        # Alignment model fingerprint — discover the model ID first
        align_model_id = _discover_alignment_model_id(config.language)
        alignment_fingerprint = _model_fingerprint(
            align_model_id, model_cache_dir, "align"
        )
        return asr_fingerprint, alignment_fingerprint

    def get_alignment_model_id(self, language: str) -> str:
        """Return the alignment model ID for the given language."""
        return _discover_alignment_model_id(language)

    def transcribe(
        self,
        audio_path: str,
        config: TranscriptionConfig,
    ) -> tuple[list[Any], dict]:
        """Run WhisperX ASR. Returns (raw_segments_list, info_dict)."""
        wx = _require_whisperx()
        torch = _require_torch()

        # Enforce CPU policy
        if torch.cuda.is_available():
            # This should not happen in this environment, but guard anyway
            raise BackendRuntimeError(
                "CUDA is available but CPU-only mode is enforced by policy."
            )

        try:
            model = wx.load_model(
                config.model,
                device=config.device,
                compute_type=config.compute_type,
                language=config.language,
                download_root=_model_cache_subdir("asr"),
            )
            audio = wx.load_audio(audio_path)
            result = model.transcribe(
                audio,
                batch_size=config.batch_size,
                language=config.language,
                task=config.task,
            )
        except Exception as exc:
            raise BackendRuntimeError(
                f"WhisperX ASR failed: {exc}"
            ) from exc

        raw_segments = result.get("segments", [])
        info = {k: v for k, v in result.items() if k != "segments"}
        return raw_segments, info

    def align(
        self,
        raw_segments: list[Any],
        audio_path: str,
        config: TranscriptionConfig,
    ) -> tuple[list[TranscriptSegment], AlignmentInfo]:
        """
        Run WhisperX forced alignment on raw ASR segments.

        Returns typed TranscriptSegment list with honest timing_status on each
        word. Never fabricates timing: only words with backend-derived start/end
        get timing_status="aligned".

        If alignment is not requested (mode=="off") or unavailable, returns
        segments with all words marked timing_status="unaligned".
        """
        wx = _require_whisperx()

        if config.alignment_mode == "off":
            return _build_unaligned_segments(raw_segments), AlignmentInfo(
                requested_mode=config.alignment_mode,
                actual_status="skipped",
            )

        align_model_id = _discover_alignment_model_id(config.language)

        try:
            align_model, metadata = wx.load_align_model(
                language_code=config.language,
                device=config.device,
                model_name=align_model_id,
                model_dir=_model_cache_subdir("align"),
            )
            audio = wx.load_audio(audio_path)
            aligned = wx.align(
                raw_segments,
                align_model,
                metadata,
                audio,
                config.device,
                return_char_alignments=False,
            )
            aligned_segments = aligned.get("segments", [])
        except Exception as exc:
            if config.alignment_mode == "auto":
                # auto = best-effort; return unaligned on failure
                return _build_unaligned_segments(raw_segments), AlignmentInfo(
                    requested_mode=config.alignment_mode,
                    actual_status="failed",
                    model_id=align_model_id,
                )
            else:
                raise BackendRuntimeError(
                    f"Forced alignment failed (mode={config.alignment_mode!r}): {exc}"
                ) from exc

        typed_segments, words_total, words_aligned = _parse_aligned_segments(
            aligned_segments
        )
        return typed_segments, AlignmentInfo(
            requested_mode=config.alignment_mode,
            actual_status="aligned",
            model_id=align_model_id,
            model_fingerprint=_model_fingerprint(
                align_model_id, _model_cache_subdir("align"), "align"
            ),
            words_total=words_total,
            words_aligned=words_aligned,
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _discover_alignment_model_id(language: str) -> str:
    """
    Introspect the installed WhisperX package to find the alignment model ID
    for the given language.

    Falls back to a deterministic default if introspection fails.
    """
    try:
        wx = _require_whisperx()
        # WhisperX 3.x exposes alignment model map in alignment module
        align_mod = getattr(wx, "alignment", None)
        if align_mod is None:
            import whisperx.alignment as align_mod  # noqa: PLC0415
        models_hf = getattr(align_mod, "DEFAULT_ALIGN_MODELS_HF", {})
        model_id = models_hf.get(language)
        if model_id:
            return model_id
    except Exception:
        pass
    # Deterministic fallback confirmed via RUNTIME_INTROSPECTION of
    # whisperx.alignment.DEFAULT_ALIGN_MODELS_HF in whisperx 3.8.6
    return "nguyenvulebinh/wav2vec2-base-vi-vlsp2020"


def _model_cache_subdir(kind: str) -> str:
    """Return the appropriate model cache subdirectory path as a string."""
    # We set HF_HOME / HUGGINGFACE_HUB_CACHE in the service layer.
    # Here we just return a relative path used as download_root.
    cache = os.environ.get("WHISPERX_MODEL_CACHE", "model-cache")
    return os.path.join(cache, kind)


def _model_fingerprint(model_id: str, cache_dir: str, kind: str) -> str:
    """
    Produce a stable, deterministic fingerprint for a model.

    Uses SHA-256 of the model_id string. This is stable across all runs
    (before and after download) for the same model identifier.

    File-based hashing is intentionally NOT used: HuggingFace Hub adds
    lock files, ref updates, and incomplete markers between runs, making
    file-based hashes non-reproducible across the pre/post-download boundary.

    The model_id + whisperx version (included in the CacheIdentity outer key)
    uniquely identifies the model weights being used.
    """
    return hashlib.sha256(model_id.encode("utf-8")).hexdigest()[:16]


def _build_unaligned_segments(raw_segments: list[Any]) -> list[TranscriptSegment]:
    """
    Convert raw ASR segments to typed segments with timing_status='unaligned'.

    Called when alignment is skipped or unavailable. Never fabricates timing.
    """
    result = []
    for seg in raw_segments:
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start))
        text = str(seg.get("text", "")).strip()
        # Build unaligned word list from segment-level word info if available
        raw_words = seg.get("words", [])
        if raw_words:
            words = tuple(
                TranscriptWord(
                    text=str(w.get("word", "")).strip(),
                    timing_status="unaligned",
                )
                for w in raw_words
            )
        else:
            # No word-level info: represent as single unaligned word
            words = (
                TranscriptWord(text=text, timing_status="unaligned"),
            ) if text else ()
        result.append(TranscriptSegment(start=start, end=end, text=text, words=words))
    return result


def _parse_aligned_segments(
    aligned_segments: list[Any],
) -> tuple[list[TranscriptSegment], int, int]:
    """
    Convert WhisperX aligned segment dicts to typed TranscriptSegment objects.

    Returns (typed_segments, words_total, words_aligned).

    Word timing honesty:
    - A word is "aligned" ONLY if it has both 'start' and 'end' from the backend.
    - Words missing start/end are marked "unaligned".
    - No inference or interpolation of timestamps is performed.
    """
    typed = []
    words_total = 0
    words_aligned = 0

    for seg in aligned_segments:
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start))
        text = str(seg.get("text", "")).strip()
        raw_words = seg.get("words", [])

        typed_words: list[TranscriptWord] = []
        for w in raw_words:
            words_total += 1
            w_text = str(w.get("word", "")).strip()
            w_start = w.get("start")
            w_end = w.get("end")
            w_score = w.get("score")

            # Only mark as aligned when BOTH start and end are genuine numbers
            if (
                w_start is not None
                and w_end is not None
                and isinstance(w_start, (int, float))
                and isinstance(w_end, (int, float))
                and w_end >= w_start >= 0
            ):
                typed_words.append(
                    TranscriptWord(
                        text=w_text,
                        timing_status="aligned",
                        start=float(w_start),
                        end=float(w_end),
                        score=float(w_score) if w_score is not None else None,
                    )
                )
                words_aligned += 1
            else:
                typed_words.append(
                    TranscriptWord(
                        text=w_text,
                        timing_status="unaligned",
                    )
                )

        typed.append(
            TranscriptSegment(
                start=start,
                end=end,
                text=text,
                words=tuple(typed_words),
            )
        )

    return typed, words_total, words_aligned
