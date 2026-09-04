"""Content-addressed cache for Phase 4 scene analysis.

Cache identity fields:
  source_sha256, detector_config_json, keyframe_shas_json,
  profile_hash, transcript_hash, provider_id, model_id, prompt_version

Cache directory: .scene-analysis-cache/ (gitignored)
Each entry: {cache_dir}/{job_id}/  with manifest.json + clip_analysis.json

No hard-coded profile-ID branches.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

CACHE_SCHEMA_VERSION = "1.0.0"


def _job_id(
    source_sha256: str,
    detector_config: dict,
    profile_hash: str,
    transcript_hash: str,
    provider_id: str,
    model_id: str | None,
    prompt_version: str,
) -> str:
    payload = json.dumps({
        "source_sha256": source_sha256,
        "detector_config": detector_config,
        "profile_hash": profile_hash,
        "transcript_hash": transcript_hash,
        "provider_id": provider_id,
        "model_id": model_id or "",
        "prompt_version": prompt_version,
        "cache_schema_version": CACHE_SCHEMA_VERSION,
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


class AnalysisCache:
    def __init__(self, cache_dir: str | Path) -> None:
        self._root = Path(cache_dir)

    def _entry_dir(self, job_id: str) -> Path:
        return self._root / job_id

    def get(
        self,
        source_sha256: str,
        detector_config: dict,
        profile_hash: str,
        transcript_hash: str,
        provider_id: str,
        model_id: str | None,
        prompt_version: str,
    ) -> dict | None:
        jid = _job_id(
            source_sha256, detector_config,
            profile_hash, transcript_hash, provider_id, model_id, prompt_version,
        )
        entry = self._entry_dir(jid)
        manifest_path = entry / "manifest.json"
        analysis_path = entry / "clip_analysis.json"
        if not manifest_path.exists() or not analysis_path.exists():
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("job_id") != jid:
                return None
            analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
            return {"job_id": jid, "analysis": analysis, "manifest": manifest}
        except Exception:  # noqa: BLE001
            return None

    def put(
        self,
        source_sha256: str,
        detector_config: dict,
        profile_hash: str,
        transcript_hash: str,
        provider_id: str,
        model_id: str | None,
        prompt_version: str,
        analysis_json: str,
    ) -> str:
        jid = _job_id(
            source_sha256, detector_config,
            profile_hash, transcript_hash, provider_id, model_id, prompt_version,
        )
        entry = self._entry_dir(jid)
        entry.mkdir(parents=True, exist_ok=True)
        manifest = {
            "job_id": jid,
            "cache_schema_version": CACHE_SCHEMA_VERSION,
            "source_sha256": source_sha256,
            "provider_id": provider_id,
            "model_id": model_id,
            "prompt_version": prompt_version,
        }
        (entry / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        (entry / "clip_analysis.json").write_text(analysis_json, encoding="utf-8")
        return jid

    @staticmethod
    def profile_hash(profile_dict: dict) -> str:
        canonical = json.dumps(profile_dict, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def transcript_hash(transcript_dict: dict | None) -> str:
        if transcript_dict is None:
            return "no-transcript"
        canonical = json.dumps(
            transcript_dict.get("result", {}), sort_keys=True, ensure_ascii=False
        )
        return hashlib.sha256(canonical.encode()).hexdigest()
