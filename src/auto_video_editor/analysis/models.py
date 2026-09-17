"""In-memory data models for Phase 4 scene analysis.

All time values are stored in MICROSECONDS (int) internally.
No hard-coded profile-ID branches anywhere in this module.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any


# ── Exceptions ────────────────────────────────────────────────────────────────

class LegacyOutputSchemaError(ValueError):
    """Raised when a legacy (V1) clip_analysis schema version is encountered.

    The writer always emits 2.0.0. The validator always rejects 1.0.0.
    No silent conversion is performed.
    """


class ProviderContentIntegrityError(ValueError):
    """Raised when a ProviderContentBundle does not match its SemanticRequest.

    This is a content-integrity failure, NOT an insufficient-evidence condition.
    The message does NOT contain raw bytes, transcript plaintext, or private paths.
    Exit code: EXIT_CONTENT_INTEGRITY_ERROR (9).
    """


class CacheSchemaValidationError(ValueError):
    """Raised when a cached analysis fails full Draft 2020-12 schema validation.

    This is a configuration failure (missing schema file or jsonschema package),
    not a cache miss. The pipeline must not continue with an unvalidated cache hit.
    """


_HEX64_RE = re.compile(r'^[0-9a-fA-F]{64}$')


def _is_valid_sha256(value: str) -> bool:
    return bool(_HEX64_RE.match(value))


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


# ── Provider Content (Explicit Binding) ───────────────────────────────────────

@dataclass(frozen=True)
class ProviderImageContent:
    """Immutable, explicitly-bound raw image record for one keyframe slot.

    Each instance binds raw JPEG bytes to an exact (order, frame_id) pair
    that matches the corresponding image descriptor in SceneVisionSemanticRequest.

    Fields
    ------
    order     : Zero-based canonical position index. Must equal position in bundle.
    frame_id  : Unique, non-empty string matching semantic_request.images[order].frame_id.
    image_bytes: Raw JPEG bytes. Not serialized, not logged, not stored in cache.
    """
    order: int
    frame_id: str
    image_bytes: bytes = field(repr=False)


@dataclass(frozen=True)
class ProviderContentBundle:
    """Non-serializable in-memory content payload for provider construction.

    NOT part of cache identity. MUST be built from verified semantic request
    fields. The images tuple is in the same canonical order as
    semantic_request.images (images[i].order == i, frame_id matches descriptor).

    IMMUTABLE: frozen dataclass with tuple[ProviderImageContent, ...].
    This object is never serialized, logged, or stored in cache.

    Explicit binding contract:
    - Each ProviderImageContent carries its own (order, frame_id) — never
      matched by tuple position alone.
    - validate_content_bundle_against_semantic_request() verifies every
      (order, frame_id) pair is present, unique, and matches its descriptor.
    """
    images: tuple[ProviderImageContent, ...]
    transcript_excerpt: str | None = field(default=None, repr=False)


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
    source_sha256               : SHA-256 of the source media file (64 hex chars, normalized lowercase)
    preprocessing_identity_sha256: SHA-256 of the canonical Level-A preprocessing identity
                                   (64 hex chars, normalized lowercase). Eliminates external
                                   preprocessing_sha256 parameter from job-ID computation.
    provider_id                 : "mock" | "openai"
    requested_model_id          : model name or "" for mock
    adapter_version             : "1.4.0"
    prompt                      : {"version": str, "content_sha256": str}
    provider_options            : non-secret options affecting the response
    scene                       : {"scene_id": int, "start_us": int, "end_us": int, "duration_us": int}
    profile                     : {"profile_id": str, "resolved_profile_sha256": str,
                                   "ordered_criteria": [{"order": int, "criterion_id": str, "finite_weight": float}]}
    images                      : ordered tuple of {"order": int, "frame_id": str, "full_sha256": str,
                                   "mime_type": str, "width": int, "height": int, "detail": str}
    transcript_context          : {"mode": str, "character_count": int, "content_sha256": str}
                                  mode: "not_included" | "included" | "redacted"
                                  content_sha256: SHA-256 of exact UTF-8 excerpt or "not_included"
    response_schema             : {"schema_version": str, "full_schema_sha256": str}
    """
    source_sha256: str
    preprocessing_identity_sha256: str
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

    def __post_init__(self) -> None:
        if not _is_valid_sha256(self.source_sha256):
            raise ValueError(
                f"source_sha256 must be exactly 64 lowercase hexadecimal characters; "
                f"got {len(self.source_sha256)!r} characters"
            )
        if not _is_valid_sha256(self.preprocessing_identity_sha256):
            raise ValueError(
                f"preprocessing_identity_sha256 must be exactly 64 hexadecimal characters; "
                f"got {len(self.preprocessing_identity_sha256)!r} characters"
            )

    def to_canonical_identity_dict(self) -> dict:
        """Return a deterministic, JSON-serializable dict for cache hashing.

        The returned dict contains only primitive types (str, int, float, bool,
        None, list, dict). It is safe to pass to json.dumps(sort_keys=True).
        source_sha256 and preprocessing_identity_sha256 are always lowercased
        for canonical normalization.
        """
        return {
            "source_sha256": self.source_sha256.lower(),
            "preprocessing_identity_sha256": self.preprocessing_identity_sha256.lower(),
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


# ── Content bundle validation ─────────────────────────────────────────────────

def _read_jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    """Parse JPEG SOF markers to extract (width, height). Returns None on failure."""
    try:
        if len(data) < 4 or data[:2] != b'\xff\xd8':
            return None
        i = 2
        while i < len(data) - 8:
            if data[i] != 0xFF:
                return None
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):  # SOF0, SOF1, SOF2
                height = (data[i + 5] << 8) | data[i + 6]
                width = (data[i + 7] << 8) | data[i + 8]
                return (width, height)
            if marker in (0xD8, 0xD9):
                return None
            segment_len = (data[i + 2] << 8) | data[i + 3]
            i += 2 + segment_len
        return None
    except (IndexError, TypeError):
        return None


def validate_content_bundle_against_semantic_request(
    semantic_request: SceneVisionSemanticRequest,
    content_bundle: ProviderContentBundle,
) -> None:
    """Validate that content_bundle matches semantic_request exactly.

    Uses explicit (order, frame_id) binding — NOT positional zip matching.
    Every semantic descriptor is mapped to exactly one ProviderImageContent
    record by its (order, frame_id) pair.

    Verifies ALL of the following (raises ProviderContentIntegrityError on any):
    1. Bundle images are in canonical order (images[i].order == i, contiguous 0..n-1).
    2. All frame_id values in the bundle are unique and non-empty.
    3. All (order, frame_id) pairs in the bundle are unique.
    4. Image count matches descriptor count.
    5. Each descriptor (order, frame_id) has exactly one matching bundle record.
    6. Each image SHA-256 matches its descriptor.
    7. Each image MIME magic matches its descriptor.
    8. Each image JPEG dimensions match its descriptor (where parseable).
    9. Transcript consent mode and hash consistency.
    10. Character count matches when transcript is included.

    Does NOT disclose raw bytes or transcript text in exception messages.
    This function is called at Point A (before cache lookup) and
    Point B (before provider invocation on cache miss).
    """
    images = content_bundle.images
    descriptors = semantic_request.images

    # ── Bundle self-consistency checks ───────────────────────────────────────

    # 1. Canonical order: images[i].order must equal i, contiguous 0..n-1
    for i, pic in enumerate(images):
        if pic.order != i:
            raise ProviderContentIntegrityError(
                f"Bundle images are not in canonical order: "
                f"images[{i}].order == {pic.order!r}, expected {i}"
            )

    # 2. frame_id must be non-empty
    for pic in images:
        if not pic.frame_id:
            raise ProviderContentIntegrityError(
                f"Bundle image at order={pic.order} has an empty frame_id"
            )

    # 3. (order, frame_id) uniqueness
    seen_keys: set[tuple[int, str]] = set()
    for pic in images:
        key = (pic.order, pic.frame_id)
        if key in seen_keys:
            raise ProviderContentIntegrityError(
                f"Duplicate (order, frame_id) in bundle: order={pic.order}, "
                f"frame_id={pic.frame_id!r}"
            )
        seen_keys.add(key)

    # ── Build (order, frame_id) → ProviderImageContent lookup ────────────────
    bundle_lookup: dict[tuple[int, str], ProviderImageContent] = {
        (pic.order, pic.frame_id): pic for pic in images
    }

    # 4. Count check
    if len(images) != len(descriptors):
        raise ProviderContentIntegrityError(
            f"Image count mismatch: semantic descriptor has {len(descriptors)} image(s), "
            f"content bundle has {len(images)} image(s)"
        )

    # 5–8. Per-descriptor validation using explicit (order, frame_id) lookup
    for idx, desc in enumerate(descriptors):
        desc_order = desc.get("order")
        desc_frame_id = desc.get("frame_id", "")
        key = (desc_order, desc_frame_id)

        # 5. Explicit binding: find matching bundle record
        if key not in bundle_lookup:
            raise ProviderContentIntegrityError(
                f"No bundle record for descriptor at position {idx}: "
                f"(order={desc_order!r}, frame_id={desc_frame_id!r})"
            )
        pic = bundle_lookup[key]

        # 6. SHA-256 check
        actual_sha = hashlib.sha256(pic.image_bytes).hexdigest()
        expected_sha = desc.get("full_sha256", "")
        if actual_sha.lower() != expected_sha.lower():
            raise ProviderContentIntegrityError(
                f"Image SHA-256 mismatch at descriptor position {idx} "
                f"(order={desc_order}, frame_id={desc_frame_id!r}): "
                f"expected suffix ...{expected_sha[-12:]}, got ...{actual_sha[-12:]}"
            )

        # 7. MIME magic check
        mime = desc.get("mime_type", "")
        is_jpeg = len(pic.image_bytes) >= 2 and pic.image_bytes[:2] == b'\xff\xd8'
        if mime == "image/jpeg" and not is_jpeg:
            raise ProviderContentIntegrityError(
                f"MIME mismatch at descriptor position {idx}: descriptor declares image/jpeg "
                f"but bytes do not start with JPEG magic (FF D8)"
            )

        # 8. JPEG dimension check (only when parseable and mime is JPEG)
        if mime == "image/jpeg" and is_jpeg:
            dims = _read_jpeg_dimensions(pic.image_bytes)
            if dims is not None:
                exp_w = desc.get("width", -1)
                exp_h = desc.get("height", -1)
                if dims[0] != exp_w or dims[1] != exp_h:
                    raise ProviderContentIntegrityError(
                        f"JPEG dimension mismatch at descriptor position {idx}: "
                        f"descriptor says {exp_w}x{exp_h}, parsed {dims[0]}x{dims[1]}"
                    )

    # 9 & 10. Transcript consent and hash verification
    tc = semantic_request.transcript_context
    mode = tc.get("mode", "not_included")
    excerpt = content_bundle.transcript_excerpt

    if mode == "included":
        if excerpt is None:
            raise ProviderContentIntegrityError(
                "Transcript mode is 'included' but bundle.transcript_excerpt is None"
            )
        actual_sha = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
        expected_sha = tc.get("content_sha256", "")
        if actual_sha.lower() != expected_sha.lower():
            raise ProviderContentIntegrityError(
                "Transcript content hash mismatch between bundle and semantic descriptor"
            )
        expected_count = tc.get("character_count", -1)
        actual_count = len(excerpt.encode("utf-8"))
        if actual_count != expected_count:
            raise ProviderContentIntegrityError(
                f"Transcript UTF-8 byte count mismatch: "
                f"descriptor says {expected_count}, bundle is {actual_count}"
            )
    else:
        # not_included or redacted: excerpt MUST be None
        if excerpt is not None:
            raise ProviderContentIntegrityError(
                f"Transcript mode is '{mode}' but bundle.transcript_excerpt is not None"
            )
