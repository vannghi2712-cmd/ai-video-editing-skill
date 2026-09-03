"""Backend protocol (abstract interface) for transcription backends.

No ML imports here. Concrete implementations do the lazy importing.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from auto_video_editor.transcription.config import TranscriptionConfig
from auto_video_editor.transcription.models import AlignmentInfo, TranscriptSegment


@runtime_checkable
class TranscriptionBackend(Protocol):
    """
    Abstract protocol for ASR + alignment backends.

    Concrete implementations MUST:
    - Lazily import any ML dependencies (whisperx, torch, etc.)
    - Never modify source media
    - Raise BackendUnavailableError if optional deps are missing
    - Raise BackendRuntimeError if transcription fails at runtime
    - Return honest word timing: only set start/end when genuinely aligned
    """

    def transcribe(
        self,
        audio_path: str,
        config: TranscriptionConfig,
    ) -> tuple[list[Any], dict]:
        """
        Run ASR on audio_path.

        Returns:
          (raw_segments, raw_info) — backend-native format
        """
        ...

    def align(
        self,
        raw_segments: list[Any],
        audio_path: str,
        config: TranscriptionConfig,
    ) -> tuple[list[TranscriptSegment], AlignmentInfo]:
        """
        Align word timing for ASR output.

        Returns:
          (typed segments, alignment info)

        MUST set word.timing_status = "aligned" ONLY for words with genuine
        backend-derived finite start/end timestamps. NEVER fabricate timing.
        """
        ...

    def version(self) -> str:
        """Return the backend library version string."""
        ...

    def model_fingerprints(
        self,
        config: TranscriptionConfig,
        model_cache_dir: str,
    ) -> tuple[str, str]:
        """
        Return (asr_model_fingerprint, alignment_model_fingerprint).

        Fingerprints MUST be deterministic and non-'UNVERIFIED'.
        Use local file fingerprints if remote revision is unavailable.
        """
        ...


class BackendUnavailableError(ImportError):
    """
    Raised when optional ML dependencies (whisperx, torch) are not installed.

    Deliberately subclasses ImportError so callers can detect missing-dep
    vs runtime-failure cleanly.
    """


class BackendRuntimeError(RuntimeError):
    """Raised when the backend is available but transcription fails."""
