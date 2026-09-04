"""clip_analysis.json exporter for Phase 4.

Produces Draft 2020-12 compliant JSON.
- allow_nan=False (reject NaN/Infinity)
- No absolute paths in output (use basename only for keyframe paths)
- Strict schema validation via jsonschema if available
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from auto_video_editor.analysis.models import (
    ClipAnalysis, Keyframe, Scene, SceneScore,
)

SCHEMA_VERSION = "1.0.0"


def export_clip_analysis(analysis: ClipAnalysis) -> str:
    """Serialize ClipAnalysis to a JSON string (allow_nan=False)."""
    doc = _to_dict(analysis)
    # Strict: reject NaN/Infinity before serialization
    _check_finite(doc)
    return json.dumps(doc, ensure_ascii=False, indent=2, allow_nan=False)


def _to_dict(analysis: ClipAnalysis) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": analysis.status,
        "source": {
            # No absolute paths — basename + SHA only
            "filename": Path(analysis.source.path).name,
            "sha256": analysis.source.sha256,
            "duration_seconds": round(analysis.source.duration_us / 1_000_000, 6),
            "size_bytes": analysis.source.size_bytes,
            "width": analysis.source.width,
            "height": analysis.source.height,
            "fps": analysis.source.fps,
            "has_audio": analysis.source.has_audio,
            "codec": analysis.source.codec_name,
        },
        "profile": {
            "profile_id": analysis.profile_id,
            "profile_hash": analysis.profile_hash,
        },
        "detector_config": analysis.detector_config,
        "scenes": [_scene_dict(s) for s in analysis.scenes],
        "scores": [_score_dict(sc) for sc in analysis.scores],
        "keyframe_summary": {
            "total": len(analysis.keyframes),
            "successful": sum(1 for kf in analysis.keyframes if kf.status == "ok"),
            "failed": sum(1 for kf in analysis.keyframes if kf.status != "ok"),
            # Only SHAs, never paths or image data
            "sha256s": [kf.sha256 for kf in analysis.keyframes if kf.sha256],
        },
        "summary": {
            "scene_count": len(analysis.scenes),
            "scenes_scored": sum(1 for sc in analysis.scores if sc.status == "scored"),
            "average_weighted_score": _safe_avg(
                [sc.weighted_score for sc in analysis.scores if sc.weighted_score is not None]
            ),
        },
        "warnings": list(analysis.warnings),
        "metrics": analysis.metrics,
        "provenance": analysis.provenance,
    }


def _scene_dict(s: Scene) -> dict:
    return {
        "index": s.index,
        "start_seconds": round(s.start_seconds, 6),
        "end_seconds": round(s.end_seconds, 6),
        "duration_seconds": round(s.duration_seconds, 6),
        "raw_score": s.raw_score,
    }


def _score_dict(sc: SceneScore) -> dict:
    return {
        "scene_index": sc.scene_index,
        "provider": sc.provider,
        "model_id": sc.model_id,
        "prompt_version": sc.prompt_version,
        "status": sc.status,
        "weighted_score": sc.weighted_score,
        "keyframes_used": sc.keyframes_used,
        "dimensions": [
            {
                "dimension": d.dimension,
                "weight": d.weight,
                "score": d.score,
                "confidence": d.confidence,
                "status": d.status,
            }
            for d in sc.dimensions
        ],
    }


def _safe_avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _check_finite(obj, path: str = "") -> None:
    """Recursively check that no float values are NaN or Infinity."""
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise ValueError(f"Non-finite float at '{path}': {obj}")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _check_finite(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _check_finite(v, f"{path}[{i}]")


def validate_against_schema(analysis_json: str, schema_path: str) -> list[str]:
    """Validate JSON string against clip_analysis.schema.json.

    Returns list of error messages (empty = valid).
    Silently skips validation if jsonschema is not installed.
    """
    try:
        from jsonschema import Draft202012Validator  # noqa: PLC0415
    except ImportError:
        return []

    import json as _json  # noqa: PLC0415
    instance = _json.loads(analysis_json)
    import pathlib  # noqa: PLC0415
    schema = _json.loads(pathlib.Path(schema_path).read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(instance))
    return [str(e.message) for e in errors]
