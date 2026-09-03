"""
Immutable transcription configuration.

Validation is strict: rejected values raise ValueError at construction time
so bad config is caught before any I/O occurs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# ── Supported contract values (single-element frozensets because we only
#    allow one choice per axis today; expand as policy widens).
SUPPORTED_LANGUAGES: frozenset[str] = frozenset({"vi"})
SUPPORTED_TASKS: frozenset[str] = frozenset({"transcribe"})
SUPPORTED_DEVICES: frozenset[str] = frozenset({"cpu"})
SUPPORTED_COMPUTE_TYPES: frozenset[str] = frozenset({"int8", "float32", "float16"})
SUPPORTED_ALIGNMENT_MODES: frozenset[str] = frozenset({"auto", "on", "off"})
DEFAULT_MODEL = "base"
DEFAULT_BATCH_SIZE = 4


@dataclass(frozen=True)
class TranscriptionConfig:
    """Immutable, validated transcription request config.

    All defaults reflect the Phase 3 contract:
      language=vi, task=transcribe, device=cpu, compute_type=int8.
    """

    language: str = "vi"
    task: str = "transcribe"
    device: str = "cpu"
    compute_type: str = "int8"
    model: str = DEFAULT_MODEL
    batch_size: int = DEFAULT_BATCH_SIZE
    alignment_mode: str = "auto"
    diarization: bool = False
    force: bool = False

    # ── post-init validation ─────────────────────────────────────────────
    def __post_init__(self) -> None:  # noqa: D105
        if self.language not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Language {self.language!r} is not supported. "
                f"Supported languages: {sorted(SUPPORTED_LANGUAGES)}"
            )
        if self.task not in SUPPORTED_TASKS:
            raise ValueError(
                f"Task {self.task!r} is not supported. "
                f"Supported tasks: {sorted(SUPPORTED_TASKS)}. "
                "Translation is prohibited by policy."
            )
        if self.device not in SUPPORTED_DEVICES:
            raise ValueError(
                f"Device {self.device!r} is not supported. "
                "Only 'cpu' is permitted — CUDA/GPU is disabled by policy."
            )
        if self.compute_type not in SUPPORTED_COMPUTE_TYPES:
            raise ValueError(
                f"Compute type {self.compute_type!r} is not supported. "
                f"Supported: {sorted(SUPPORTED_COMPUTE_TYPES)}"
            )
        if self.alignment_mode not in SUPPORTED_ALIGNMENT_MODES:
            raise ValueError(
                f"Alignment mode {self.alignment_mode!r} is not supported. "
                f"Supported: {sorted(SUPPORTED_ALIGNMENT_MODES)}"
            )
        if self.diarization:
            raise ValueError(
                "Diarization is prohibited by policy. Set diarization=False."
            )
        if self.batch_size < 1:
            raise ValueError("batch_size must be >= 1.")

    # ── stable serialisation for cache keying ───────────────────────────
    def as_normalized_dict(self) -> dict:
        """Return a canonical dict safe for hashing/cache key construction."""
        return {
            "language": self.language,
            "task": self.task,
            "device": self.device,
            "compute_type": self.compute_type,
            "model": self.model,
            "batch_size": self.batch_size,
            "alignment_mode": self.alignment_mode,
            "diarization": self.diarization,
            # force is NOT part of the cache key — it only controls bypass
        }
