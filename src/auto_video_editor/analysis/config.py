"""Configuration dataclasses for Phase 4 scene analysis.

All fields use only standard-library types.
No hard-coded profile-ID branches anywhere in this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SceneDetectorConfig:
    """Parameters for scene-change detection and normalization."""

    # FFmpeg scdet threshold [0.0, 1.0]
    threshold: float = 0.30
    # Minimum scene duration in seconds
    min_duration_seconds: float = 1.0
    # Maximum scene duration in seconds (long scenes are split)
    max_duration_seconds: float = 15.0

    def __post_init__(self) -> None:
        if not 0.0 < self.threshold < 1.0:
            raise ValueError(f"threshold must be in (0, 1), got {self.threshold}")
        if self.min_duration_seconds <= 0:
            raise ValueError("min_duration_seconds must be > 0")
        if self.max_duration_seconds < self.min_duration_seconds:
            raise ValueError("max_duration_seconds must be >= min_duration_seconds")

    def as_dict(self) -> dict:
        return {
            "threshold": self.threshold,
            "min_duration_seconds": self.min_duration_seconds,
            "max_duration_seconds": self.max_duration_seconds,
        }


@dataclass(frozen=True)
class AnalysisConfig:
    """Full analysis request configuration."""

    input_path: str
    profile_id: str
    output_dir: str
    provider: str = "mock"             # "mock" | "openai"
    vision_model: str | None = None
    dry_run: bool = False
    resume: bool = False
    force: bool = False
    allow_external_upload: bool = False
    include_transcript_context: bool = False
    allow_paid_recompute: bool = False
    transcript_path: str | None = None   # path to transcript.json (Phase 3 output)
    detector: SceneDetectorConfig = field(default_factory=SceneDetectorConfig)
    # Maximum keyframe slots per scene (1..3)
    keyframe_slots: int = 3
    # Cache directory (default: .scene-analysis-cache relative to cwd)
    cache_dir: str = ".scene-analysis-cache"

    def __post_init__(self) -> None:
        if self.provider not in ("mock", "openai"):
            raise ValueError(f"provider must be 'mock' or 'openai', got {self.provider!r}")
        if self.keyframe_slots not in (1, 2, 3):
            raise ValueError("keyframe_slots must be 1, 2, or 3")
