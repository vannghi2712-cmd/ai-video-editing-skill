"""
Content-addressed transcript cache.

Cache key is a deterministic SHA-256 over:
  source_sha256 + normalized_config_json + schema_version + adapter_version
  + whisperx_version + asr_model_fingerprint + alignment_model_fingerprint

The literal string 'UNVERIFIED' is NOT a valid fingerprint.
If a remote revision is unavailable, caller MUST compute a local fingerprint.

Cache entry validity:
  - Directory must contain a manifest.json with a matching job_id.
  - transcript.json schema_version must match current SCHEMA_VERSION.
  - Any corruption (missing files, bad JSON) = cache miss, not an error.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional

SCHEMA_VERSION = "1.0.0"
ADAPTER_VERSION = "1.0.0"

# Artifact filenames
MANIFEST_FILE = "manifest.json"
TRANSCRIPT_RAW_FILE = "transcript.raw.json"
TRANSCRIPT_FILE = "transcript.json"
SRT_FILE = "transcript.srt"
WORDS_FILE = "words.json"

# Files always written for every transcription (raw is excluded by default — opt-in via --include-raw)
ALL_ARTIFACT_FILES = (
    MANIFEST_FILE,
    TRANSCRIPT_FILE,
    SRT_FILE,
    WORDS_FILE,
)
# Raw file is only written when explicitly requested (privacy-safe default)
RAW_ARTIFACT_FILE = TRANSCRIPT_RAW_FILE


class CacheIdentity:
    """Encapsulates everything needed to produce a deterministic cache key."""

    def __init__(
        self,
        source_sha256: str,
        normalized_config: dict,
        schema_version: str,
        adapter_version: str,
        whisperx_version: str,
        asr_model_fingerprint: str,
        alignment_model_fingerprint: str,
    ) -> None:
        if not source_sha256 or source_sha256.upper() == "UNVERIFIED":
            raise ValueError("source_sha256 must be a real hash, not 'UNVERIFIED'.")
        if not asr_model_fingerprint or asr_model_fingerprint.upper() == "UNVERIFIED":
            raise ValueError("asr_model_fingerprint must be a real fingerprint.")
        if not alignment_model_fingerprint or alignment_model_fingerprint.upper() == "UNVERIFIED":
            raise ValueError("alignment_model_fingerprint must be a real fingerprint.")

        self.source_sha256 = source_sha256.upper()
        self.normalized_config = normalized_config
        self.schema_version = schema_version
        self.adapter_version = adapter_version
        self.whisperx_version = whisperx_version
        self.asr_model_fingerprint = asr_model_fingerprint
        self.alignment_model_fingerprint = alignment_model_fingerprint

    def job_id(self) -> str:
        """Return a deterministic hex job ID (first 16 chars of SHA-256)."""
        payload = json.dumps(
            {
                "source_sha256": self.source_sha256,
                "config": self.normalized_config,
                "schema_version": self.schema_version,
                "adapter_version": self.adapter_version,
                "whisperx_version": self.whisperx_version,
                "asr_model_fingerprint": self.asr_model_fingerprint,
                "alignment_model_fingerprint": self.alignment_model_fingerprint,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(payload).hexdigest()[:32]

    def full_dict(self) -> dict:
        return {
            "source_sha256": self.source_sha256,
            "config": self.normalized_config,
            "schema_version": self.schema_version,
            "adapter_version": self.adapter_version,
            "whisperx_version": self.whisperx_version,
            "asr_model_fingerprint": self.asr_model_fingerprint,
            "alignment_model_fingerprint": self.alignment_model_fingerprint,
        }


class TranscriptCache:
    """Content-addressed cache storing transcript artifacts on disk."""

    def __init__(self, cache_dir: str | Path) -> None:
        self._root = Path(cache_dir).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _entry_dir(self, identity: CacheIdentity) -> Path:
        job_id = identity.job_id()
        # Two-level layout: first 2 chars / rest (like git object store)
        return self._root / job_id[:2] / job_id[2:]

    # ── Cache read ────────────────────────────────────────────────────────

    def get(self, identity: CacheIdentity) -> Optional[dict]:
        """
        Return cached artifact paths if a valid cache entry exists.

        Returns None on: miss, missing files, schema mismatch, corrupt JSON.
        Never raises — corruption is silently treated as a cache miss.
        """
        entry = self._entry_dir(identity)
        manifest_path = entry / MANIFEST_FILE
        if not manifest_path.exists():
            return None

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None  # corrupt manifest → miss

        # Validate manifest ownership
        if manifest.get("job_id") != identity.job_id():
            return None
        if manifest.get("schema_version") != identity.schema_version:
            return None

        # Verify all artifact files are present
        for fname in ALL_ARTIFACT_FILES:
            if not (entry / fname).exists():
                return None

        # Validate transcript.json schema_version field
        try:
            tx = json.loads((entry / TRANSCRIPT_FILE).read_text(encoding="utf-8"))
            if tx.get("schema_version") != SCHEMA_VERSION:
                return None
        except (json.JSONDecodeError, OSError):
            return None

        return {
            "job_id": identity.job_id(),
            "entry_dir": str(entry),
            "artifacts": {f: str(entry / f) for f in ALL_ARTIFACT_FILES},
            "manifest": manifest,
        }

    # ── Cache write ───────────────────────────────────────────────────────

    def put(
        self,
        identity: CacheIdentity,
        artifacts: dict[str, str | bytes],
        source_path: str,
        duration_seconds: float,
    ) -> dict:
        """
        Write artifact contents to cache atomically.

        artifacts: dict mapping filename → str content (UTF-8) or bytes.
        Each file is written to a temp path then renamed (atomic on same fs).
        Returns the manifest dict.
        """
        entry = self._entry_dir(identity)
        entry.mkdir(parents=True, exist_ok=True)

        written_hashes: dict[str, str] = {}
        for fname, content in artifacts.items():
            if isinstance(content, str):
                data = content.encode("utf-8")
            else:
                data = content
            _write_atomic(entry / fname, data)
            written_hashes[fname] = hashlib.sha256(data).hexdigest()

        manifest = {
            "schema_version": identity.schema_version,
            "job_id": identity.job_id(),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source_path": source_path,
            "duration_seconds": duration_seconds,
            "identity": identity.full_dict(),
            "artifact_hashes": written_hashes,
            "artifact_files": list(ALL_ARTIFACT_FILES),
        }
        _write_atomic(
            entry / MANIFEST_FILE,
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        return manifest

    # ── Output directory ownership ────────────────────────────────────────

    @staticmethod
    def validate_output_dir_ownership(
        output_dir: Path, identity: CacheIdentity
    ) -> None:
        """
        If output_dir exists and is non-empty, it MUST contain a manifest.json
        whose job_id matches this identity. Otherwise raise ValueError so the
        caller can either abort or pass --force.
        """
        if not output_dir.exists():
            return  # Empty / absent → OK to create
        manifest_path = output_dir / MANIFEST_FILE
        contents = [p for p in output_dir.iterdir()]
        if not contents:
            return  # Empty dir → OK

        if not manifest_path.exists():
            raise ValueError(
                f"Output directory {output_dir} is non-empty but has no "
                "manifest.json. Will not overwrite without --force."
            )
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(
                f"Output directory {output_dir} has an unreadable manifest.json: {exc}"
            ) from exc

        if existing.get("job_id") != identity.job_id():
            raise ValueError(
                f"Output directory {output_dir} is owned by a different job "
                f"(job_id={existing.get('job_id')!r}). "
                "Re-run with --force to overwrite."
            )

    @staticmethod
    def populate_output_dir(output_dir: Path, cache_entry: dict) -> None:
        """Copy or symlink cached artifacts into the user-facing output dir."""
        output_dir.mkdir(parents=True, exist_ok=True)
        for fname, cached_path in cache_entry["artifacts"].items():
            src = Path(cached_path)
            dst = output_dir / fname
            if src.exists():
                _write_atomic(dst, src.read_bytes())


def _write_atomic(dest: Path, data: bytes) -> None:
    """Write data to a temp file then rename to dest (atomic on same filesystem)."""
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def compute_local_fingerprint(path: str | Path) -> str:
    """
    Compute a local fingerprint for a file or directory.

    Used when remote model revision is unavailable, to produce a
    deterministic non-'UNVERIFIED' cache key component.
    """
    p = Path(path)
    h = hashlib.sha256()
    if p.is_file():
        with open(p, "rb") as f:
            while chunk := f.read(1 << 20):
                h.update(chunk)
    elif p.is_dir():
        for child in sorted(p.rglob("*")):
            if child.is_file():
                h.update(child.name.encode())
                h.update(str(child.stat().st_size).encode())
    else:
        h.update(str(p).encode())
    return h.hexdigest()[:16]
