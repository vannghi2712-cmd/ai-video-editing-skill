"""In-memory data models for Phase 4 scene analysis.

All time values are stored in MICROSECONDS (int) internally.
No hard-coded profile-ID branches anywhere in this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Media ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MediaInfo:
    """Result of FFprobe inspection."""
    path: str                        # original path (not stored in JSON)
    sha256: str                      # file SHA-256
    duration_us: int                 # duration in microseconds
    width: int
    height: int
    fps: float
    has_audio: bool
    has_video: bool
    codec_name: str                  # primary video codec
    size_bytes: int

    @property
    def duration_seconds(self) -> float:
        return self.duration_us / 1_000_000


# ── Scenes ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Keyframe:
    """A single extracted keyframe."""
    scene_index: int
    slot: int                        # 0=20%, 1=50%, 2=80%
    timestamp_us: int                # position in source video
    path: str                        # absolute local path (NOT committed)
    sha256: str | None               # sha256 of JPEG bytes; None if extraction failed
    status: str                      # "ok" | "failed"


@dataclass(frozen=True)
class TranscriptContext:
    """Transcript data associated with a scene (Phase 3 output)."""
    full_text: str                   # concatenation of overlapping segment texts
    word_count: int
    char_count: int
    # segments list kept as raw dicts to avoid coupling to Phase 3 internals
    segments: tuple[dict, ...]


@dataclass(frozen=True)
class Scene:
    """A normalized scene: half-open interval [start_us, end_us).

    Invariants (enforced by SceneDetector):
    - start_us < end_us
    - No gap or overlap with adjacent scenes
    - First scene: start_us == 0
    - Last scene: end_us == source duration_us
    """
    index: int
    start_us: int
    end_us: int
    raw_score: float | None          # scene-change score from FFmpeg; None for synthetic

    @property
    def start_seconds(self) -> float:
        return self.start_us / 1_000_000

    @property
    def end_seconds(self) -> float:
        return self.end_us / 1_000_000

    @property
    def duration_us(self) -> int:
        return self.end_us - self.start_us

    @property
    def duration_seconds(self) -> float:
        return self.duration_us / 1_000_000


# ── Scoring ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DimensionScore:
    """Score for a single profile scoring dimension."""
    dimension: str
    weight: int                      # profile weight [1..100]
    score: float | None              # [0..100] or None if insufficient evidence
    confidence: float | None         # [0..1] or None if no evidence
    status: str                      # "scored" | "insufficient_evidence"

    def __post_init__(self) -> None:
        if self.status not in ("scored", "insufficient_evidence"):
            raise ValueError(f"Invalid status: {self.status!r}")
        if self.status == "scored" and self.score is None:
            raise ValueError("scored status requires a non-None score")


@dataclass(frozen=True)
class SceneScore:
    """Complete scoring result for one scene."""
    scene_index: int
    provider: str                    # "mock" | "openai"
    model_id: str | None             # model identifier or None for mock
    prompt_version: str
    dimensions: tuple[DimensionScore, ...]
    weighted_score: float | None     # host-computed weighted average, None if no dims scored
    keyframes_used: int              # number of keyframes that contributed
    status: str                      # "scored" | "insufficient_evidence" | "failed"


# ── Full output ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ClipAnalysis:
    """Complete Phase 4 analysis result."""
    schema_version: str
    status: str                      # "complete" | "partial" | "failed"
    source: MediaInfo
    profile_id: str
    profile_hash: str                # SHA-256 of profile JSON (canonical)
    detector_config: dict            # SceneDetectorConfig.as_dict()
    scenes: tuple[Scene, ...]
    keyframes: tuple[Keyframe, ...]
    scores: tuple[SceneScore, ...]
    warnings: tuple[str, ...]
    metrics: dict[str, Any]
    provenance: dict[str, Any]
