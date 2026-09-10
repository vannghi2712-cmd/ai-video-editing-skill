"""In-memory data models for Phase 4 scene analysis.

All time values are stored in MICROSECONDS (int) internally.
No hard-coded profile-ID branches anywhere in this module.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


# ── Exceptions ────────────────────────────────────────────────────────────────

class LegacyOutputSchemaError(ValueError):
    """Raised when a legacy (V1) clip_analysis schema version is encountered.

    The writer always emits 2.0.0. The validator always rejects 1.0.0.
    No silent conversion is performed.
    """



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
    # score_coverage_percent: sum of weights of SCORED dimensions (0–100)
    score_coverage_percent: float
    # partial_weighted_score: sum(score * weight / 100) for scored dims only [0–100]
    # Always numeric. 0.0 when no dims are scored (zero coverage).
    partial_weighted_score: float
    # weighted_score: = partial_weighted_score ONLY when score_coverage_percent == 100, else null
    weighted_score: float | None
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


# ── Semantic Request Abstraction (Phase 4 Final Contract) ─────────────────────

@dataclass(frozen=True)
class SceneVisionSemanticRequest:
    """Immutable, JSON-compatible canonical scoring request for ONE scene.

    This object is the SINGLE source of truth for:
    - Cache identity (via to_canonical_identity_dict() → SHA-256)
    - Provider request construction (via ProviderContentBundle)

    CONTENT BOUNDARY: No raw bytes, secrets, or absolute paths. All image
    evidence is referenced by SHA-256. Raw bytes live in ProviderContentBundle.

    Fields
    ------
    provider_id         : "mock" | "openai"
    requested_model_id  : model name or "" for mock
    adapter_version     : "1.3.0"
    prompt              : {"version": str, "content_sha256": str}
    provider_options    : non-secret options affecting the response
    scene               : {"scene_id": int, "start_us": int, "end_us": int, "duration_us": int}
    profile             : {"profile_id": str, "resolved_profile_sha256": str,
                           "ordered_criteria": [{"order": int, "criterion_id": str, "finite_weight": float}]}
    images              : ordered tuple of {"order": int, "frame_id": str, "full_sha256": str,
                           "mime_type": str, "width": int, "height": int, "detail": str}
    transcript_context  : {"mode": str, "character_count": int, "content_sha256": str}
                          mode: "not_included" | "included" | "redacted"
                          content_sha256: SHA-256 of exact UTF-8 excerpt or "not_included"
    response_schema     : {"schema_version": str, "full_schema_sha256": str}
    """
    provider_id: str
    requested_model_id: str
    adapter_version: str
    prompt: dict
    provider_options: dict
    scene: dict
    profile: dict
    images: tuple[dict, ...]
    transcript_context: dict
    response_schema: dict

    def to_canonical_identity_dict(self) -> dict:
        """Return a deterministic, JSON-serializable dict for cache hashing.

        The returned dict contains only primitive types (str, int, float, bool,
        None, list, dict). It is safe to pass to json.dumps(sort_keys=True).
        """
        return {
            "provider_id": self.provider_id,
            "requested_model_id": self.requested_model_id,
            "adapter_version": self.adapter_version,
            "prompt": dict(self.prompt),
            "provider_options": dict(self.provider_options),
            "scene": dict(self.scene),
            "profile": {
                "profile_id": self.profile["profile_id"],
                "resolved_profile_sha256": self.profile["resolved_profile_sha256"],
                "ordered_criteria": list(self.profile["ordered_criteria"]),
            },
            "images": [dict(img) for img in self.images],
            "transcript_context": dict(self.transcript_context),
            "response_schema": dict(self.response_schema),
        }

    def canonical_sha256(self) -> str:
        """SHA-256 of the canonical JSON representation."""
        canonical = json.dumps(
            self.to_canonical_identity_dict(),
            sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


@dataclass
class ProviderContentBundle:
    """Non-serializable in-memory content payload for provider construction.

    NOT part of cache identity. MUST be built from verified semantic request
    fields. The image_bytes list is in the same order as semantic_request.images.
    transcript_excerpt is the raw UTF-8 text if mode=="included", else None.

    This object is never serialized, logged, or stored in cache.
    """
    image_bytes: list[bytes]         # raw JPEG bytes; order matches semantic_request.images
    transcript_excerpt: str | None   # raw UTF-8 text or None if not included
