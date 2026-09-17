"""Content-addressed two-level cache for Phase 4 scene analysis.

Cache Format Version: 4.1.0
Vision Adapter Version: 1.4.0

Level A — Preprocessing Cache Identity:
  source_sha256, ffmpeg_version, ffprobe_version,
  scene_detector_config, extractor_config (slots, max_dim).

Level B — Strict Canonical Job Envelope (no external preprocessing_sha256):
  Hashed over a single JSON envelope:
    {
      "cache_schema_version": "4.1.0",
      "request_count": <int>,
      "semantic_requests": [<ordered canonical request dicts>]
    }
  Each canonical dict includes preprocessing_identity_sha256 directly, so
  the Level-A identity is embedded inside the Level-B hash — no separate
  preprocessing_sha256 parameter is accepted or needed.

Provider cache MUST NOT be queried with unverified/placeholder data.
Old cache entries (version != CACHE_SCHEMA_VERSION) are safe misses.
V1.0.0 output in cache entries is rejected.
No hard-coded profile-ID branches.

Atomic write contract (enforced via atomic_io module):
  1. Temp file in same directory as destination.
  2. Unique temp name via mkstemp.
  3. Write + flush + fsync (best-effort on Windows).
  4. Pre-replace TOCTOU check (symlink/reparse on parent + destination).
  5. os.replace(temp, destination).
  6. Re-read and verify SHA-256.

Publication order:
  clip_analysis.json is written BEFORE manifest.json.
  A manifest without a valid clip_analysis.json is never published.

Writer exclusion:
  WriterLock (exclusive O_CREAT|O_EXCL, random UUID token) prevents concurrent
  writers from publishing to the same cache entry simultaneously.
  Release is token-verified: only the owning process can delete the lock.
  Stale locks are only removed when the owning PID is provably dead.

Cache hit validation:
  get() verifies artifact SHA-256 from manifest, strictly parses JSON,
  checks schema_version == "2.0.0", and runs full Draft 2020-12 JSON Schema
  validation before returning cached data.
  A missing schema file or jsonschema package is a configuration failure
  (CacheSchemaValidationError), not a silent cache miss.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from auto_video_editor.analysis.atomic_io import (
    ArtifactIntegrityError,
    WriterLock,
    WriterLockError,
    atomic_write_text,
)
from auto_video_editor.analysis.models import CacheSchemaValidationError

# Bumped: 4.0.0 → 4.1.0 (preprocessing_identity_sha256 in canonical request;
# strict job-ID envelope; explicit raw-content binding; output transaction lock)
CACHE_SCHEMA_VERSION = "4.1.0"
VISION_ADAPTER_VERSION = "1.4.0"

# Path to the public clip_analysis JSON Schema (Draft 2020-12)
_SCHEMA_PATH = (
    Path(__file__).parent.parent.parent.parent / "schemas" / "clip_analysis.schema.json"
)


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
    scene_canonical_dicts: list[dict],
) -> str:
    """Level-B identity: strict JSON envelope over all per-scene semantic requests.

    Each canonical dict (from SceneVisionSemanticRequest.to_canonical_identity_dict())
    already contains preprocessing_identity_sha256, source_sha256, and all other
    semantic fields. No external preprocessing_sha256 argument is accepted.

    The envelope format is:
    {
      "cache_schema_version": "4.1.0",
      "request_count": <int>,
      "semantic_requests": [<ordered canonical dicts>]
    }

    Provider cache MUST NOT be queried before all semantic requests are built
    and all keyframe bytes are verified.
    """
    envelope = {
        "cache_schema_version": CACHE_SCHEMA_VERSION,
        "request_count": len(scene_canonical_dicts),
        "semantic_requests": scene_canonical_dicts,
    }
    return _sha256_of(_canonical_json(envelope))


def _validate_cached_analysis_strict(analysis: dict) -> None:
    """Full Draft 2020-12 validation of cached analysis.

    Raises CacheSchemaValidationError (not returns None) when:
    - The schema file is missing (configuration failure).
    - The jsonschema package is not installed (configuration failure).
    - The analysis fails schema validation.

    This function is called on every cache hit before the cached data is
    returned or written to the public output directory.
    """
    if not _SCHEMA_PATH.exists():
        raise CacheSchemaValidationError(
            f"clip_analysis.schema.json not found at {_SCHEMA_PATH!s}. "
            "This is a configuration failure; the pipeline cannot validate a cache hit."
        )
    try:
        from jsonschema import Draft202012Validator  # noqa: PLC0415
    except ImportError as exc:
        raise CacheSchemaValidationError(
            "jsonschema package is required for cache-hit schema validation "
            "but is not installed. This is a configuration failure."
        ) from exc

    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(analysis))
    if errors:
        msgs = [str(e.message) for e in errors[:3]]
        raise CacheSchemaValidationError(
            f"Cached analysis fails Draft 2020-12 schema validation: {'; '.join(msgs)}"
        )


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

        Validation steps:
        1. Both manifest.json and clip_analysis.json must exist.
        2. manifest.cache_schema_version must match CACHE_SCHEMA_VERSION.
        3. manifest.job_id must match the requested job_id.
        4. clip_analysis artifact SHA-256 must match manifest.clip_analysis_sha256.
        5. analysis JSON must strict-parse and have schema_version != "1.0.0".
        6. Output schema version must be "2.0.0".
        7. Full Draft 2020-12 JSON Schema validation (CacheSchemaValidationError on failure).

        Any failure in steps 1–6 → safe miss (return None).
        Step 7 failure → raises CacheSchemaValidationError (configuration failure,
        not a silent miss — the caller must not accept an unvalidated cache hit).
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

            # Verify artifact SHA-256 from manifest
            expected_artifact_sha = manifest.get("clip_analysis_sha256")
            if expected_artifact_sha:
                actual_bytes = analysis_path.read_bytes()
                actual_sha = _sha256_bytes(actual_bytes)
                if actual_sha.lower() != expected_artifact_sha.lower():
                    return None  # corrupt artifact — safe miss
                analysis_text = actual_bytes.decode("utf-8")
            else:
                analysis_text = analysis_path.read_text(encoding="utf-8")

            analysis = json.loads(analysis_text)
            if analysis.get("schema_version") == "1.0.0":
                return None
            if analysis.get("schema_version") != "2.0.0":
                return None

            # Step 7: Full Draft 2020-12 schema validation — configuration failure on error
            _validate_cached_analysis_strict(analysis)

            return {"job_id": job_id, "analysis": analysis, "manifest": manifest}
        except CacheSchemaValidationError:
            raise  # Propagate — this is a configuration failure, not a safe miss
        except Exception:  # noqa: BLE001
            return None

    def put(
        self, job_id: str, analysis_json: str, *, extra_manifest: dict | None = None
    ) -> str:
        """Store analysis JSON atomically under job_id.

        Publication order:
        1. Acquire exclusive WriterLock (random UUID token, token-verified release).
        2. Create/validate entry directory.
        3. Atomic write clip_analysis.json (with post-replace SHA verification).
        4. Compute clip_analysis SHA-256.
        5. Atomic write manifest.json LAST (includes clip_analysis_sha256).
        6. Release lock.
        """
        entry = self._entry_dir(job_id)
        entry.mkdir(parents=True, exist_ok=True)

        try:
            with WriterLock(entry, timeout=10.0):
                # Step 3: Atomic write clip_analysis.json
                analysis_bytes = analysis_json.encode("utf-8")
                analysis_sha = hashlib.sha256(analysis_bytes).hexdigest()
                try:
                    atomic_write_text(
                        entry / "clip_analysis.json",
                        analysis_json,
                        expected_sha256=analysis_sha,
                    )
                except ArtifactIntegrityError:
                    raise  # propagate integrity errors

                # Step 5: Build manifest with clip_analysis SHA, write LAST
                manifest: dict = {
                    "job_id": job_id,
                    "cache_schema_version": CACHE_SCHEMA_VERSION,
                    "normalized_request_payload_sha256": job_id,
                    "clip_analysis_sha256": analysis_sha,
                }
                if extra_manifest:
                    manifest.update(extra_manifest)

                manifest_text = json.dumps(manifest, indent=2, ensure_ascii=False)
                manifest_bytes = manifest_text.encode("utf-8")
                manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
                atomic_write_text(
                    entry / "manifest.json",
                    manifest_text,
                    expected_sha256=manifest_sha,
                )
        except WriterLockError:
            # Lock acquisition failed — not an integrity error, skip cache store
            pass

        return job_id
