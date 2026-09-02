"""Typed in-memory models for content profiles.

All models are plain data classes using only Python standard library.
They represent the fully-merged, validated state of a profile.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class NarrativeStage:
    """A single narrative stage within a content profile."""

    name: str
    label: str
    start_seconds: float
    end_seconds: float
    description: str = ""

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


@dataclass(frozen=True)
class ScoringWeights:
    """Scoring weight configuration. Values must sum to 100."""

    weights: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.weights.values())

    def items(self):
        return self.weights.items()


@dataclass(frozen=True)
class Resolution:
    width: int = 1080
    height: int = 1920


@dataclass(frozen=True)
class CodecConfig:
    video: str = "libx264"
    audio: str = "aac"
    pixel_format: str = "yuv420p"
    crf: int = 18
    audio_bitrate_kbps: int = 128
    audio_sample_rate: int = 44100
    audio_channels: int = 2


@dataclass(frozen=True)
class SafeZone:
    top_percent: float = 15.0
    bottom_percent: float = 20.0
    left_percent: float = 5.0
    right_percent: float = 5.0


@dataclass(frozen=True)
class FontConfig:
    family: str = "Arial"
    size: int = 42
    bold: bool = True
    color_hex: str = "#FFFFFF"
    outline_color_hex: str = "#000000"
    outline_width: float = 2.0


@dataclass(frozen=True)
class SubtitleConfig:
    enabled: bool = True
    format: str = "ass"
    safe_zone: SafeZone = field(default_factory=SafeZone)
    font: FontConfig = field(default_factory=FontConfig)


@dataclass(frozen=True)
class AudioConfig:
    normalize_speech: bool = True
    bgm_volume_percent: float = 12.0
    duck_bgm_under_speech: bool = True
    preserve_ambient: bool = False


@dataclass(frozen=True)
class CaptionGrouping:
    enabled: bool = False
    words_per_group: int = 4
    words_per_group_min: int | None = None
    words_per_group_max: int | None = None


@dataclass(frozen=True)
class PunchInConfig:
    enabled: bool = False
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreprocessingConfig:
    mode: str = "normal"
    remove_recording_cues: bool = True
    remove_filler_words: bool = False
    remove_configured_pauses: bool = False
    hallucination_volume_threshold_db: float = -40.0
    caption_grouping: CaptionGrouping = field(default_factory=CaptionGrouping)
    punch_in: PunchInConfig = field(default_factory=PunchInConfig)


@dataclass(frozen=True)
class ContentProfile:
    """Fully merged and validated content profile.

    This is the immutable result of loading and merging a child profile
    with its base. All fields have been validated.
    """

    schema_version: str
    profile_id: str
    display_name: str
    description: str = ""
    account: str = ""
    extends: str = ""
    platform: str = "tiktok"
    aspect_ratio: str = "9:16"
    resolution: Resolution = field(default_factory=Resolution)
    framerate: int = 30
    codec: CodecConfig = field(default_factory=CodecConfig)
    reference_duration_seconds: float = 60.0
    subtitle: SubtitleConfig = field(default_factory=SubtitleConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    narrative_stages: tuple[NarrativeStage, ...] = ()
    scoring: ScoringWeights = field(default_factory=ScoringWeights)
    preprocessing: PreprocessingConfig = field(default_factory=PreprocessingConfig)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return _profile_to_dict(self)


def _profile_to_dict(profile: ContentProfile) -> dict[str, Any]:
    """Convert a ContentProfile to a JSON-serializable dict."""
    result: dict[str, Any] = {
        "$schema_version": profile.schema_version,
        "profile_id": profile.profile_id,
        "display_name": profile.display_name,
        "description": profile.description,
        "platform": profile.platform,
        "aspect_ratio": profile.aspect_ratio,
        "resolution": {"width": profile.resolution.width, "height": profile.resolution.height},
        "framerate": profile.framerate,
        "codec": {
            "video": profile.codec.video,
            "audio": profile.codec.audio,
            "pixel_format": profile.codec.pixel_format,
            "crf": profile.codec.crf,
            "audio_bitrate_kbps": profile.codec.audio_bitrate_kbps,
            "audio_sample_rate": profile.codec.audio_sample_rate,
            "audio_channels": profile.codec.audio_channels,
        },
        "reference_duration_seconds": profile.reference_duration_seconds,
        "subtitle": {
            "enabled": profile.subtitle.enabled,
            "format": profile.subtitle.format,
            "safe_zone": {
                "top_percent": profile.subtitle.safe_zone.top_percent,
                "bottom_percent": profile.subtitle.safe_zone.bottom_percent,
                "left_percent": profile.subtitle.safe_zone.left_percent,
                "right_percent": profile.subtitle.safe_zone.right_percent,
            },
            "font": {
                "family": profile.subtitle.font.family,
                "size": profile.subtitle.font.size,
                "bold": profile.subtitle.font.bold,
                "color_hex": profile.subtitle.font.color_hex,
                "outline_color_hex": profile.subtitle.font.outline_color_hex,
                "outline_width": profile.subtitle.font.outline_width,
            },
        },
        "audio": {
            "normalize_speech": profile.audio.normalize_speech,
            "bgm_volume_percent": profile.audio.bgm_volume_percent,
            "duck_bgm_under_speech": profile.audio.duck_bgm_under_speech,
            "preserve_ambient": profile.audio.preserve_ambient,
        },
        "narrative": {
            "stages": [
                {
                    "name": s.name,
                    "label": s.label,
                    "start_seconds": s.start_seconds,
                    "end_seconds": s.end_seconds,
                    "description": s.description,
                }
                for s in profile.narrative_stages
            ]
        },
        "scoring": {"weights": dict(profile.scoring.weights)},
        "preprocessing": {
            "mode": profile.preprocessing.mode,
            "remove_recording_cues": profile.preprocessing.remove_recording_cues,
            "remove_filler_words": profile.preprocessing.remove_filler_words,
            "remove_configured_pauses": profile.preprocessing.remove_configured_pauses,
            "hallucination_volume_threshold_db": profile.preprocessing.hallucination_volume_threshold_db,
            "caption_grouping": {
                "enabled": profile.preprocessing.caption_grouping.enabled,
                "words_per_group": profile.preprocessing.caption_grouping.words_per_group,
            },
            "punch_in": {
                "enabled": profile.preprocessing.punch_in.enabled,
                "keywords": list(profile.preprocessing.punch_in.keywords),
            },
        },
    }
    if profile.account:
        result["account"] = profile.account
    if profile.extends:
        result["extends"] = profile.extends
    cg = profile.preprocessing.caption_grouping
    if cg.words_per_group_min is not None:
        result["preprocessing"]["caption_grouping"]["words_per_group_min"] = cg.words_per_group_min
    if cg.words_per_group_max is not None:
        result["preprocessing"]["caption_grouping"]["words_per_group_max"] = cg.words_per_group_max
    return result
