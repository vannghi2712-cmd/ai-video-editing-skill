"""Main orchestration service for Phase 4 scene analysis.

No hard-coded profile-ID branches.
No shell=True. No GPU/CUDA.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from auto_video_editor.analysis.cache import AnalysisCache
from auto_video_editor.analysis.config import AnalysisConfig
from auto_video_editor.analysis.exporters import export_clip_analysis, validate_against_schema
from auto_video_editor.analysis.keyframe_extractor import extract_keyframes
from auto_video_editor.analysis.media_inspector import inspect_media
from auto_video_editor.analysis.models import ClipAnalysis, Scene
from auto_video_editor.analysis.scene_detector import detect_scenes
from auto_video_editor.analysis.scoring.base import PROMPT_VERSION
from auto_video_editor.analysis.transcript_associator import (
    associate_transcript,
    load_transcript,
)
from auto_video_editor.profiles.loader import load_profile

_SCHEMA_PATH = (
    Path(__file__).parent.parent.parent.parent / "schemas" / "clip_analysis.schema.json"
)
_ANALYSIS_SCHEMA_VERSION = "1.0.0"


class AnalysisService:
    """Orchestrates the full Phase 4 pipeline."""

    def run(self, config: AnalysisConfig) -> tuple[int, str]:
        """Execute the analysis pipeline.

        Returns (exit_code, message).
        exit_code semantics match CLI contract:
          0=success, 3=profile, 4=media, 5=schema, 6=consent, 7=partial, 8=backend
        """
        t_start = time.monotonic()
        warnings: list[str] = []
        out_dir = Path(config.output_dir)

        # ── Consent checks ────────────────────────────────────────────────────
        if config.provider == "openai" and not config.allow_external_upload:
            return 6, (
                "External upload requires --allow-external-upload. "
                "Keyframes would be sent to OpenAI API."
            )
        if config.provider == "openai":
            import os  # noqa: PLC0415
            if not os.environ.get("OPENAI_API_KEY"):
                return 6, "OPENAI_API_KEY environment variable is not set."

        # ── Load profile ──────────────────────────────────────────────────────
        try:
            profile = load_profile(config.profile_id)
        except Exception as exc:  # noqa: BLE001
            return 3, f"Profile error: {exc}"

        profile_dict = profile.to_dict()
        profile_hash = AnalysisCache.profile_hash(profile_dict)

        # ── Inspect media ─────────────────────────────────────────────────────
        try:
            media_info, media_warnings = inspect_media(config.input_path)
        except Exception as exc:  # noqa: BLE001
            return 4, f"Media inspection failed: {exc}"
        warnings.extend(media_warnings)

        # ── Dry-run: report estimates and stop ────────────────────────────────
        if config.dry_run:
            est_scenes = max(1, int(media_info.duration_seconds / 5))
            est_kf = est_scenes * config.keyframe_slots
            est_kf_bytes = est_kf * 150_000
            est_api_calls = est_scenes if config.provider == "openai" else 0
            transcript_chars = 0
            if config.transcript_path:
                try:
                    td = load_transcript(config.transcript_path)
                    transcript_chars = len(
                        td.get("result", {}).get("full_text", "")
                    )
                except Exception:  # noqa: BLE001
                    pass
            print(
                f"DRY_RUN — Estimated: ~{est_scenes} scenes, "
                f"~{est_kf} keyframes (~{est_kf_bytes//1024}KB), "
                f"{est_api_calls} API calls, "
                f"{transcript_chars} transcript chars"
            )
            return 0, "Dry-run complete"

        # ── Output directory ownership ────────────────────────────────────────
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = out_dir / "manifest.json"
        if manifest_path.exists() and not config.force:
            try:
                existing = json.loads(manifest_path.read_text(encoding="utf-8"))
                existing_src = existing.get("source_sha256", "")
                if existing_src and existing_src != media_info.sha256:
                    return 5, (
                        f"Output dir owned by different job (source SHA mismatch). "
                        "Use --force to overwrite."
                    )
            except Exception:  # noqa: BLE001
                return 5, "Output dir has unreadable manifest. Use --force to overwrite."

        # ── Transcript ────────────────────────────────────────────────────────
        transcript_dict: dict | None = None
        if config.transcript_path:
            try:
                transcript_dict = load_transcript(config.transcript_path)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Transcript load failed: {exc}")

        transcript_hash = AnalysisCache.transcript_hash(transcript_dict)

        # ── Scene detection ───────────────────────────────────────────────────
        try:
            scenes, scene_warnings = detect_scenes(
                config.input_path, media_info.duration_us, config.detector
            )
        except Exception as exc:  # noqa: BLE001
            return 8, f"Scene detection failed: {exc}"
        warnings.extend(scene_warnings)

        # ── Cache check (resume) — BEFORE keyframe extraction ─────────────────
        cache = AnalysisCache(config.cache_dir)
        if config.resume and not config.force:
            cached = cache.get(
                media_info.sha256, config.detector.as_dict(),
                profile_hash, transcript_hash,
                config.provider, config.vision_model, PROMPT_VERSION,
            )
            if cached:
                print("Cache hit (OK) -- restoring from cache")
                (out_dir / "clip_analysis.json").write_text(
                    json.dumps(cached["analysis"], indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                return 0, "Analysis restored from cache"

        # ── Keyframe extraction ───────────────────────────────────────────────
        try:
            keyframes, kf_warnings = extract_keyframes(
                config.input_path, scenes, out_dir, slots=config.keyframe_slots
            )
        except Exception as exc:  # noqa: BLE001
            return 8, f"Keyframe extraction failed: {exc}"
        warnings.extend(kf_warnings)

        # ── Transcript association ────────────────────────────────────────────
        transcript_associations = associate_transcript(
            scenes, transcript_dict or {}, config.include_transcript_context
        )

        # ── Vision backend ────────────────────────────────────────────────────
        backend = _build_backend(config)
        scores = []
        backend_errors = 0
        for scene in scenes:
            scene_kf = [kf for kf in keyframes if kf.scene_index == scene.index]
            ctx_obj = transcript_associations.get(scene.index)
            ctx_text = (
                ctx_obj.full_text
                if ctx_obj and config.include_transcript_context
                else None
            )
            try:
                score = backend.score_scene(scene, scene_kf, profile, ctx_text)
                scores.append(score)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Scene {scene.index} scoring failed: {exc}")
                backend_errors += 1

        # ── Build ClipAnalysis ────────────────────────────────────────────────
        elapsed = time.monotonic() - t_start
        overall_status = (
            "complete" if backend_errors == 0
            else ("partial" if backend_errors < len(scenes) else "failed")
        )
        analysis = ClipAnalysis(
            schema_version=_ANALYSIS_SCHEMA_VERSION,
            status=overall_status,
            source=media_info,
            profile_id=config.profile_id,
            profile_hash=profile_hash,
            detector_config=config.detector.as_dict(),
            scenes=tuple(scenes),
            keyframes=tuple(keyframes),
            scores=tuple(scores),
            warnings=tuple(warnings),
            metrics={
                "elapsed_seconds": round(elapsed, 3),
                "scenes_detected": len(scenes),
                "keyframes_extracted": sum(1 for kf in keyframes if kf.status == "ok"),
                "scenes_scored": sum(1 for sc in scores if sc.status == "scored"),
            },
            provenance={
                "analysis_schema_version": _ANALYSIS_SCHEMA_VERSION,
                "provider": config.provider,
                "model_id": config.vision_model,
                "prompt_version": PROMPT_VERSION,
            },
        )

        # ── Export ────────────────────────────────────────────────────────────
        analysis_json = export_clip_analysis(analysis)

        # Schema validation (if jsonschema installed)
        if _SCHEMA_PATH.exists():
            schema_errors = validate_against_schema(analysis_json, str(_SCHEMA_PATH))
            if schema_errors:
                return 5, f"Schema validation failed: {'; '.join(schema_errors[:3])}"

        (out_dir / "clip_analysis.json").write_text(analysis_json, encoding="utf-8")

        # Write output manifest
        manifest = {
            "source_sha256": media_info.sha256,
            "profile_id": config.profile_id,
            "analysis_schema_version": _ANALYSIS_SCHEMA_VERSION,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        # ── Cache store ───────────────────────────────────────────────────────
        cache.put(
            media_info.sha256, config.detector.as_dict(),
            profile_hash, transcript_hash,
            config.provider, config.vision_model, PROMPT_VERSION,
            analysis_json,
        )

        n_scenes = len(scenes)
        n_kf_ok = sum(1 for kf in keyframes if kf.status == "ok")
        n_scored = sum(1 for sc in scores if sc.status == "scored")
        print(
            f"Analysis complete. "
            f"Scenes: {n_scenes}  Keyframes: {n_kf_ok}/{len(keyframes)}  "
            f"Scored: {n_scored}/{n_scenes}  Elapsed: {elapsed:.1f}s"
        )
        if warnings:
            for w in warnings:
                print(f"  WARNING: {w}")

        if overall_status == "partial":
            return 7, f"Partial — {backend_errors}/{n_scenes} scenes failed scoring"
        if overall_status == "failed":
            return 8, "All scenes failed scoring"
        return 0, "Success"


def _build_backend(config: AnalysisConfig):
    if config.provider == "mock":
        from auto_video_editor.analysis.scoring.mock_backend import MockVisionBackend  # noqa: PLC0415
        return MockVisionBackend()
    if config.provider == "openai":
        from auto_video_editor.analysis.scoring.openai_backend import OpenAIVisionBackend  # noqa: PLC0415
        model = config.vision_model or "gpt-4o"
        return OpenAIVisionBackend(model=model)
    raise ValueError(f"Unknown provider: {config.provider!r}")
