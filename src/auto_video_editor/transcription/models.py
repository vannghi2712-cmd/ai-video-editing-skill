"""
Typed, immutable result models for the transcription pipeline.

Word-timing honesty contract (from STEP_6 / OUTPUT_SCHEMA_V1):
  - timing_status: "aligned" | "unaligned" | "failed"
  - start / end are ONLY set when timing_status == "aligned"
  - NEVER derive word timestamps by splitting segment text
  - NEVER invent alignment scores
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

TimingStatus = Literal["aligned", "unaligned", "failed"]
AlignmentActualStatus = Literal["aligned", "failed", "skipped", "unavailable"]


@dataclass(frozen=True)
class TranscriptWord:
    """A single recognized word with honest timing metadata."""

    text: str
    timing_status: TimingStatus
    # Finite numeric start/end ONLY when timing_status == "aligned"
    start: Optional[float] = None
    end: Optional[float] = None
    # Confidence score ONLY when timing_status == "aligned"
    score: Optional[float] = None

    def __post_init__(self) -> None:
        if self.timing_status == "aligned":
            if self.start is None or self.end is None:
                raise ValueError(
                    "aligned words MUST have finite start and end."
                )
            if not isinstance(self.start, (int, float)) or not isinstance(self.end, (int, float)):
                raise TypeError("start and end must be numeric.")
            if self.start < 0 or self.end < 0:
                raise ValueError("Word timestamps cannot be negative.")
            if self.start > self.end:
                raise ValueError(
                    f"Word start ({self.start}) > end ({self.end}) — invalid."
                )
        else:
            # Unaligned or failed: timing values must be absent
            if self.start is not None or self.end is not None:
                raise ValueError(
                    f"timing_status={self.timing_status!r} but start/end are set. "
                    "Timing values MUST be absent for non-aligned words."
                )


@dataclass(frozen=True)
class TranscriptSegment:
    """A contiguous audio segment from the ASR engine."""

    start: float
    end: float
    text: str
    words: tuple[TranscriptWord, ...]

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError(f"Segment start {self.start} < 0.")
        if self.end < 0:
            raise ValueError(f"Segment end {self.end} < 0.")
        if self.start > self.end:
            raise ValueError(
                f"Segment start ({self.start}) > end ({self.end})."
            )


@dataclass(frozen=True)
class AlignmentInfo:
    """Records alignment request, actual outcome, and coverage metrics."""

    requested_mode: str
    actual_status: AlignmentActualStatus
    model_id: Optional[str] = None
    model_fingerprint: Optional[str] = None
    words_total: int = 0
    words_aligned: int = 0

    @property
    def coverage_fraction(self) -> float:
        """Fraction of words that were successfully aligned."""
        if self.words_total == 0:
            return 0.0
        return self.words_aligned / self.words_total


@dataclass(frozen=True)
class EngineInfo:
    """Identifies the backend engine and its configuration."""

    name: str
    version: str
    asr_model: str
    device: str
    compute_type: str


@dataclass(frozen=True)
class SourceInfo:
    """Immutable record of the source media file before processing."""

    path: str
    sha256: str
    duration_seconds: float
    size_bytes: int


@dataclass(frozen=True)
class TranscriptResult:
    """
    Top-level transcription result.

    schema_version MUST be "1.0.0".
    """

    schema_version: str
    source: SourceInfo
    engine: EngineInfo
    request: dict
    segments: tuple[TranscriptSegment, ...]
    alignment: AlignmentInfo
    metrics: dict
    provenance: dict

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError(
                f"schema_version must be '1.0.0', got {self.schema_version!r}."
            )

    @property
    def all_words(self) -> list[TranscriptWord]:
        """Flat list of all words across all segments."""
        result = []
        for seg in self.segments:
            result.extend(seg.words)
        return result

    @property
    def full_text(self) -> str:
        """Concatenated segment text."""
        return " ".join(s.text.strip() for s in self.segments if s.text.strip())
