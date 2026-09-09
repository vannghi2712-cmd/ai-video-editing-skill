"""Content-addressed two-level cache for Phase 4 scene analysis.

Cache Format Version: 3.0.0
Adapter Version: 1.2.0

Level A — Preprocessing Cache Identity:
  source_sha256, ffmpeg_version, ffprobe_version,
  scene_detector_config, extractor_config (slots, max_dim).

Level B — Provider Cache Identity (extends Level A):
  preprocessing_identity_sha256, ordered_keyframe_sha256s (VERIFIED from bytes),
  resolved_profile_hash, provider_id, requested_model_id,
  adapter_version, prompt_version, output_schema_version,
  output_schema_sha256, transcript_context_mode,
  transcript_context_sha256 (exact UTF-8 excerpt SHA or "not-included"),
  external_upload_mode, normalized_request_payload_sha256.

Provider cache MUST NOT be queried with unverified/placeholder keyframe hashes.
Old cache entries (version != CACHE_SCHEMA_VERSION) are treated as safe misses.
No hard-coded profile-ID branches.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

# Bumped: 1.0.0 → 2.0.0 (scoring contract), 2.0.0 → 3.0.0 (schema v2 + keyframe verification order).
CACHE_SCHEMA_VERSION = "3.0.0"

# Adapter version bumped when prompt/schema contract changes.
ADAPTER_VERSION = "1.2.0"


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


def provider_job_id(
    *,
    preprocessing_sha256: str,
    ordered_keyframe_sha256s: list[str],   # VERIFIED from bytes — no placeholders
    resolved_profile_hash: str,
    provider_id: str,
    requested_model_id: str | None,
    adapter_version: str,
    prompt_version: str,
    output_schema_version: str,
    output_schema_sha256: str,
    transcript_context_mode: str,          # "not_included" | "included" | "redacted"
    transcript_context_sha256: str,        # SHA of exact UTF-8 excerpt or "not-included"
    external_upload_mode: str,             # "allowed" | "denied"
) -> str:
    """Level-B identity — canonical request payload SHA-256.

    ALL fields are required. Verified keyframe SHAs must be computed from
    bytes on disk before this function is called (no empty-list placeholders).
    """
    request_identity = {
        "preprocessing_sha256": preprocessing_sha256,
        "ordered_keyframe_sha256s": list(ordered_keyframe_sha256s),
        "resolved_profile_hash": resolved_profile_hash,
        "provider_id": provider_id,
        "requested_model_id": requested_model_id or "",
        "adapter_version": adapter_version,
        "prompt_version": prompt_version,
        "output_schema_version": output_schema_version,
        "output_schema_sha256": output_schema_sha256,
        "transcript_context_mode": transcript_context_mode,
        "transcript_context_sha256": transcript_context_sha256,
        "external_upload_mode": external_upload_mode,
        "cache_schema_version": CACHE_SCHEMA_VERSION,
    }
    # Canonical serialization: sorted keys, compact, no NaN
    return _sha256_of(_canonical_json(request_identity))


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
        This MUST be called before building provider_job_id.
        """
        try:
            data = Path(file_path).read_bytes()
            return _sha256_bytes(data)
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # get / put by provider job_id
    # ------------------------------------------------------------------

    def get(self, job_id: str) -> dict | None:
        """Return cached entry if valid, else None.

        Rejects entries whose cache_schema_version != CACHE_SCHEMA_VERSION (safe miss).
        """
        entry = self._entry_dir(job_id)
        manifest_path = entry / "manifest.json"
        analysis_path = entry / "clip_analysis.json"
        if not manifest_path.exists() or not analysis_path.exists():
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            # Version guard: reject stale caches
            if manifest.get("cache_schema_version") != CACHE_SCHEMA_VERSION:
                return None
            if manifest.get("job_id") != job_id:
                return None
            analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
            # V1 output schema is REJECTED
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
