"""Content-addressed two-level cache for Phase 4 scene analysis.

Cache Format Version: 4.0.0
Vision Adapter Version: 1.3.0

Level A — Preprocessing Cache Identity:
  source_sha256, ffmpeg_version, ffprobe_version,
  scene_detector_config, extractor_config (slots, max_dim).

Level B — Semantic Request Job Identity:
  SHA-256 of sorted canonical JSON of all per-scene SceneVisionSemanticRequest
  canonical identity dicts, combined with preprocessing_sha256 and
  cache_schema_version. Each scene request includes:
    provider_id, requested_model_id, adapter_version, prompt identity,
    provider_options, scene timing, ordered profile criteria,
    ordered keyframe SHAs (VERIFIED from bytes), transcript mode/sha,
    response schema version/sha.

Provider cache MUST NOT be queried with unverified/placeholder data.
Old cache entries (version != CACHE_SCHEMA_VERSION) are safe misses.
V1.0.0 output in cache entries is rejected.
No hard-coded profile-ID branches.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

# Bumped: 3.0.0 → 4.0.0 (SceneVisionSemanticRequest canonical identity)
CACHE_SCHEMA_VERSION = "4.0.0"
VISION_ADAPTER_VERSION = "1.3.0"


def _sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(obj: object) -> str:
    """Canonical deterministic JSON: sorted keys, no spaces, no NaN."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def preprocessing_job_id(
    *,
    source_sha256: str,
    ffmpeg_version: str,
    ffprobe_version: str,
    scene_detector_config: dict,
    extractor_slots: int,
    extractor_max_dim: int,
) -> str:
    """Level-A identity: source + tool versions + detection/extractor config."""
    identity = {
        "source_sha256": source_sha256,
        "ffmpeg_version": ffmpeg_version,
        "ffprobe_version": ffprobe_version,
        "scene_detector_config": scene_detector_config,
        "extractor_slots": extractor_slots,
        "extractor_max_dim": extractor_max_dim,
        "cache_schema_version": CACHE_SCHEMA_VERSION,
    }
    return _sha256_of(_canonical_json(identity))


def semantic_request_job_id(
    *,
    preprocessing_sha256: str,
    scene_canonical_dicts: list[dict],
) -> str:
    """Level-B identity: aggregated SHA of all per-scene semantic request dicts.

    scene_canonical_dicts must be ordered by scene_id ascending.
    Each dict is produced by SceneVisionSemanticRequest.to_canonical_identity_dict().
    preprocessing_sha256 is the Level-A identity (preprocessing_job_id result).

    Provider cache MUST NOT be queried before all semantic requests are built
    and all keyframe bytes are verified.
    """
    aggregated = {
        "cache_schema_version": CACHE_SCHEMA_VERSION,
        "preprocessing_sha256": preprocessing_sha256,
        "scene_requests": scene_canonical_dicts,
    }
    return _sha256_of(_canonical_json(aggregated))


class AnalysisCache:
    def __init__(self, cache_dir: str | Path) -> None:
        self._root = Path(cache_dir)

    def _entry_dir(self, job_id: str) -> Path:
        return self._root / job_id

    # ------------------------------------------------------------------
    # Public helpers for computing identity hashes
    # ------------------------------------------------------------------

    @staticmethod
    def profile_hash(profile_dict: dict) -> str:
        return _sha256_of(_canonical_json(profile_dict))

    @staticmethod
    def transcript_hash(transcript_dict: dict | None) -> str:
        if not transcript_dict:
            return "no-transcript"
        return _sha256_of(_canonical_json(transcript_dict))

    @staticmethod
    def transcript_context_sha256(context_text: str | None) -> str:
        """SHA-256 of exact UTF-8 transcript excerpt, or 'not-included'."""
        if context_text is None:
            return "not-included"
        return _sha256_of(context_text)

    @staticmethod
    def output_schema_sha256(schema_path: str | Path) -> str:
        p = Path(schema_path)
        if not p.exists():
            return "schema-missing"
        return _sha256_of(p.read_text(encoding="utf-8"))

    @staticmethod
    def verify_keyframe_sha256(file_path: str | Path) -> str | None:
        """Read keyframe bytes from disk and compute SHA-256.

        Returns None if file does not exist or cannot be read.
        MUST be called before building semantic requests.
        """
        try:
            data = Path(file_path).read_bytes()
            return _sha256_bytes(data)
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # get / put by semantic request job_id
    # ------------------------------------------------------------------

    def get(self, job_id: str) -> dict | None:
        """Return cached entry if valid, else None.

        Rejects entries whose cache_schema_version != CACHE_SCHEMA_VERSION (safe miss).
        Rejects entries whose analysis has schema_version == "1.0.0" (legacy).
        """
        entry = self._entry_dir(job_id)
        manifest_path = entry / "manifest.json"
        analysis_path = entry / "clip_analysis.json"
        if not manifest_path.exists() or not analysis_path.exists():
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("cache_schema_version") != CACHE_SCHEMA_VERSION:
                return None
            if manifest.get("job_id") != job_id:
                return None
            analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
            if analysis.get("schema_version") == "1.0.0":
                return None
            return {"job_id": job_id, "analysis": analysis, "manifest": manifest}
        except Exception:  # noqa: BLE001
            return None

    def put(self, job_id: str, analysis_json: str, *, extra_manifest: dict | None = None) -> str:
        """Store analysis JSON under job_id."""
        entry = self._entry_dir(job_id)
        entry.mkdir(parents=True, exist_ok=True)
        manifest = {
            "job_id": job_id,
            "cache_schema_version": CACHE_SCHEMA_VERSION,
            "normalized_request_payload_sha256": job_id,
        }
        if extra_manifest:
            manifest.update(extra_manifest)
        (entry / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (entry / "clip_analysis.json").write_text(analysis_json, encoding="utf-8")
        return job_id
