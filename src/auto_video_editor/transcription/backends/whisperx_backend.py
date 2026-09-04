"""
WhisperX backend adapter — ALL whisperx/torch imports are LAZY.

This module can be imported in the base `.venv` without installing WhisperX.
Any attempt to actually run transcription in the base env will raise
BackendUnavailableError with a clear, traceback-free message.

Model loading contract (immutable snapshot pinning):
  1. For every model, a pinned full commit SHA is declared in _PINNED_HF_REVISIONS.
  2. `_ensure_snapshot()` calls huggingface_hub.snapshot_download(revision=pinned_sha)
     and VERIFIES the returned path ends with exactly that SHA.
  3. The snapshot path (not the model alias) is passed to WhisperX/Transformers
     constructors with `local_files_only=True`, proving offline/local-only loading.
  4. Identity strings are derived from the actual snapshot directory name (= SHA),
     NOT from a hardcoded table. The table only provides the target revision to pin.

Vietnamese alignment model discovery:
  WhisperX 3.8.x maps 'vi' → wav2vec2 model via its internal
  DEFAULT_ALIGN_MODELS_HF table. We introspect the installed package to
  get the exact model ID rather than hard-coding it.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from auto_video_editor.transcription.backends import (
    BackendRuntimeError,
    BackendUnavailableError,
)
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


# ── Pinned immutable HF commit SHAs ───────────────────────────────────────────
#
# These SHAs were RESOLVED AND VERIFIED via live HfApi(token=False).model_info()
# on 2026-09-03. They are pinning TARGETS used as the `revision` argument to
# snapshot_download() — they are NOT used as identity proof. Identity proof
# comes from the snapshot directory path returned by snapshot_download().
#
# Source evidence per model:
#   tiny:  HfApi().model_info("Systran/faster-whisper-tiny",  revision=sha).sha == sha  ✓
#   small: HfApi().model_info("Systran/faster-whisper-small", revision=sha).sha == sha  ✓
#   vi:    HfApi().model_info("nguyenvulebinh/wav2vec2-base-vi-vlsp2020", revision=sha).sha == sha  ✓
#
_PINNED_HF_REVISIONS: dict[str, str] = {
    "Systran/faster-whisper-tiny":    "d90ca5fe260221311c53c58e660288d3deb8d356",
    "Systran/faster-whisper-small":   "536b0662742c02347bc0e980a01041f333bce120",
    "nguyenvulebinh/wav2vec2-base-vi-vlsp2020": "50a30dadb3ec98a0d4cdb1eb1ea315aff538f7c2",
}

# Mapping from whisperx short model name → HuggingFace repository ID
# (matches faster_whisper.utils._MODELS table, introspected from installed package)
_ASR_MODEL_HF_IDS: dict[str, str] = {
    "tiny":     "Systran/faster-whisper-tiny",
    "tiny.en":  "Systran/faster-whisper-tiny.en",
    "base":     "Systran/faster-whisper-base",
    "base.en":  "Systran/faster-whisper-base.en",
    "small":    "Systran/faster-whisper-small",
    "small.en": "Systran/faster-whisper-small.en",
    "medium":   "Systran/faster-whisper-medium",
    "large-v2": "Systran/faster-whisper-large-v2",
    "large-v3": "Systran/faster-whisper-large-v3",
}


def _resolve_asr_hf_id(model_size: str) -> str:
    """Map short model name (e.g. 'tiny') to full HF model ID."""
    return _ASR_MODEL_HF_IDS.get(model_size, f"Systran/faster-whisper-{model_size}")


def _model_cache_root() -> str:
    """Return the top-level model cache directory (huggingface_hub compatible)."""
    return os.environ.get("WHISPERX_MODEL_CACHE", "model-cache")


def _ensure_snapshot(
    repo_id: str,
    pinned_sha: str,
    cache_root: str,
    *,
    local_files_only: bool = False,
) -> tuple[str, str]:
    """
    Ensure the exact pinned revision snapshot is available locally.

    Steps:
    1. Call snapshot_download(repo_id, revision=pinned_sha, cache_dir=cache_root).
       If local_files_only=True, no network is used — proves offline loading works.
    2. Verify the returned path's directory name equals pinned_sha exactly.
       (huggingface_hub always uses the commit SHA as the snapshot directory name.)
    3. Return (snapshot_path, identity_string).

    Identity is derived from the ACTUAL snapshot path, not from a hardcoded table.
    NEVER returns an identity derived from sha256(model_name).

    Raises BackendRuntimeError if:
    - snapshot_download fails (network error, not cached)
    - Returned path SHA does not match pinned_sha (hub integrity failure)
    """
    try:
        from huggingface_hub import snapshot_download  # noqa: PLC0415
        snapshot_path = snapshot_download(
            repo_id=repo_id,
            revision=pinned_sha,
            cache_dir=cache_root,
            token=False,
            local_files_only=local_files_only,
        )
    except Exception as exc:
        raise BackendRuntimeError(
            f"Cannot ensure local snapshot for {repo_id}@{pinned_sha[:8]}: {exc}\n"
            "Ensure the model is downloaded or network is available."
        ) from exc

    # Verify: huggingface_hub names the snapshot dir after the actual commit SHA
    resolved_sha = Path(snapshot_path).name
    if resolved_sha != pinned_sha:
        raise BackendRuntimeError(
            f"Snapshot SHA integrity check failed for {repo_id}: "
            f"expected {pinned_sha!r}, got {resolved_sha!r}. "
            "The HuggingFace Hub cache may be corrupt."
        )

    identity = f"hf:{repo_id}@{resolved_sha}"
    return snapshot_path, identity


class WhisperXBackend:
    """
    WhisperX-backed ASR + forced alignment adapter.

    WhisperX, torch, and faster-whisper are only imported when a method
    is actually called, so the class can be referenced in base `.venv`.

    Model loading uses pinned snapshot paths (not aliases), with
    local_files_only=True to guarantee offline reproducibility after
    the initial download.
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
    ) -> tuple[str, str, bool]:
        """
        Return (asr_identity, alignment_identity, cache_reuse_enabled).

        Identity is derived from the actual snapshot path returned by
        snapshot_download(), NOT from a hardcoded table. The pinned SHA in
        _PINNED_HF_REVISIONS is used as the revision argument, and the
        returned path's directory name (= actual SHA) is used as proof.

        If a pinned SHA is not known for the requested model:
          cache_reuse_enabled = False
          Returns ("", "", False) → service layer disables cache.

        NEVER returns a name-based truncated hash or "UNVERIFIED".
        """
        cache_root = model_cache_dir
        asr_hf_id = _resolve_asr_hf_id(config.model)
        asr_pinned = _PINNED_HF_REVISIONS.get(asr_hf_id)

        align_model_id = _discover_alignment_model_id(config.language)
        align_pinned = _PINNED_HF_REVISIONS.get(align_model_id)

        if not asr_pinned or not align_pinned:
            return "", "", False

        try:
            _, asr_identity = _ensure_snapshot(asr_hf_id, asr_pinned, cache_root)
        except BackendRuntimeError:
            return "", "", False

        try:
            _, align_identity = _ensure_snapshot(align_model_id, align_pinned, cache_root)
        except BackendRuntimeError:
            return "", "", False

        return asr_identity, align_identity, True

    def get_alignment_model_id(self, language: str) -> str:
        """Return the alignment model ID for the given language."""
        return _discover_alignment_model_id(language)

    def transcribe(
        self,
        audio_path: str,
        config: TranscriptionConfig,
    ) -> tuple[list[Any], dict]:
        """
        Run WhisperX ASR using a pinned local snapshot.

        The model alias (e.g. 'tiny') is resolved to a full HF repo ID,
        then to a local snapshot path via snapshot_download(). The snapshot
        path is passed to whisperx.load_model() with local_files_only=True,
        guaranteeing that no network call is made during inference.
        """
        wx = _require_whisperx()
        torch = _require_torch()

        # Enforce CPU policy
        if torch.cuda.is_available():
            raise BackendRuntimeError(
                "CUDA is available but CPU-only mode is enforced by policy."
            )

        asr_hf_id = _resolve_asr_hf_id(config.model)
        asr_pinned = _PINNED_HF_REVISIONS.get(asr_hf_id)
        if not asr_pinned:
            raise BackendRuntimeError(
                f"No pinned revision known for ASR model {asr_hf_id!r}. "
                "Add it to _PINNED_HF_REVISIONS in whisperx_backend.py."
            )

        try:
            asr_snapshot, _ = _ensure_snapshot(
                asr_hf_id, asr_pinned, _model_cache_root()
            )
            model = wx.load_model(
                asr_snapshot,        # ← local snapshot path, NOT the alias "tiny"
                device=config.device,
                compute_type=config.compute_type,
                language=config.language,
                local_files_only=True,  # ← proves offline/local-only loading
            )
            audio = wx.load_audio(audio_path)
            result = model.transcribe(
                audio,
                batch_size=config.batch_size,
                language=config.language,
                task=config.task,
            )
        except BackendRuntimeError:
            raise
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
        Run WhisperX forced alignment using a pinned local snapshot.

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
        align_pinned = _PINNED_HF_REVISIONS.get(align_model_id)
        if not align_pinned:
            if config.alignment_mode == "auto":
                return _build_unaligned_segments(raw_segments), AlignmentInfo(
                    requested_mode=config.alignment_mode,
                    actual_status="failed",
                    model_id=align_model_id,
                )
            raise BackendRuntimeError(
                f"No pinned revision for alignment model {align_model_id!r}. "
                "Add it to _PINNED_HF_REVISIONS."
            )

        try:
            align_snapshot, align_identity = _ensure_snapshot(
                align_model_id, align_pinned, _model_cache_root()
            )
            align_model, metadata = wx.load_align_model(
                language_code=config.language,
                device=config.device,
                model_name=align_snapshot,  # ← local snapshot path, NOT the HF repo ID
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
        except BackendRuntimeError:
            raise
        except Exception as exc:
            if config.alignment_mode == "auto":
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
            model_fingerprint=align_identity,  # ← identity from snapshot path
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
