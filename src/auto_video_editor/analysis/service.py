"""Main orchestration service for Phase 4 scene analysis.

No hard-coded profile-ID branches.
No shell=True. No GPU/CUDA.
Ownership contract: --force does NOT bypass source ownership check.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from auto_video_editor.analysis.cache import (
    ADAPTER_VERSION,
    CACHE_SCHEMA_VERSION,
    AnalysisCache,
    preprocessing_job_id,
    provider_job_id,
)
from auto_video_editor.analysis.config import AnalysisConfig
from auto_video_editor.analysis.exporters import export_clip_analysis, validate_against_schema
from auto_video_editor.analysis.keyframe_extractor import extract_keyframes
from auto_video_editor.analysis.media_inspector import inspect_media
from auto_video_editor.analysis.models import ClipAnalysis
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
_OWNER_TAG = "auto_video_editor.scene_analysis"

# FFmpeg/FFprobe version placeholders — detected at runtime when available.
_TOOL_VERSION_UNKNOWN = "unknown"


def _get_tool_version(tool: str) -> str:
    """Get FFmpeg/FFprobe version string without shell=True."""
    import subprocess  # noqa: PLC0415
    try:
        r = subprocess.run(
            [tool, "-version"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        first_line = (r.stdout or r.stderr or b"").decode("utf-8", errors="replace").splitlines()
        return first_line[0].strip() if first_line else _TOOL_VERSION_UNKNOWN
    except Exception:  # noqa: BLE001
        return _TOOL_VERSION_UNKNOWN


def _check_ownership(out_dir: Path, source_sha256: str, force: bool) -> tuple[bool, str]:
    """
    Check output directory ownership.

    Rules (--force does NOT bypass source ownership):
    - Directory does not exist: OK
    - Directory exists but is empty: OK
    - Directory has valid manifest owned by _OWNER_TAG with matching source_sha256: OK
    - Directory has manifest owned by _OWNER_TAG but different source_sha256: FAIL (even with --force)
    - Directory has no manifest but is non-empty: FAIL
    - Manifest exists but unreadable or unknown owner: FAIL

    Returns (ok: bool, error_message: str)
    """
    if not out_dir.exists():
        return True, ""

    # Reject symlinks and traversal attempts
    try:
        resolved = out_dir.resolve()
        if out_dir != resolved and not str(resolved).startswith(str(out_dir.parent.resolve())):
            return False, "Output dir resolves outside expected parent (symlink escape)."
    except Exception:  # noqa: BLE001
        pass

    # Empty dir is always OK
    children = list(out_dir.iterdir())
    if not children:
        return True, ""

    manifest_path = out_dir / "manifest.json"
    if not manifest_path.exists():
        return False, (
            "Output dir is non-empty but has no manifest.json. "
            "Use a different --output-dir or clear the directory manually."
        )

    try:
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return False, "Output dir has an unreadable manifest.json. Cannot safely overwrite."

    owner = existing.get("owner", "")
    if owner != _OWNER_TAG:
        return False, (
            f"Output dir is owned by '{owner or 'unknown'}', not '{_OWNER_TAG}'. "
            "Use a different --output-dir."
        )

    existing_src = existing.get("source_sha256", "")
    if existing_src and existing_src != source_sha256:
        return False, (
            "Output dir is owned by a different source file (source SHA mismatch). "
            "--force cannot override a different-source directory. Use a different --output-dir."
        )

    # Owned by us and matching source: OK (--force may replace declared artifacts)
    return True, ""


class AnalysisService:
    """Orchestrates the full Phase 4 pipeline."""

    def run(self, config: AnalysisConfig) -> tuple[int, str]:
        """Execute the analysis pipeline.

        Returns (exit_code, message).
        exit_code semantics match CLI contract:
          0=success, 3=profile, 4=media, 5=schema/output, 6=consent, 7=partial, 8=backend
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
                f"DRY_RUN - Estimated: ~{est_scenes} scenes, "
                f"~{est_kf} keyframes (~{est_kf_bytes//1024}KB), "
                f"{est_api_calls} API calls, "
                f"{transcript_chars} transcript chars"
            )
            return 0, "Dry-run complete"

        # ── Output directory ownership (--force does NOT bypass) ──────────────
        out_dir.mkdir(parents=True, exist_ok=True)
        ok, err_msg = _check_ownership(out_dir, media_info.sha256, config.force)
        if not ok:
            return 5, err_msg
        manifest_path = out_dir / "manifest.json"

        # ── Transcript ────────────────────────────────────────────────────────
        transcript_dict: dict | None = None
        if config.transcript_path:
            try:
                transcript_dict = load_transcript(config.transcript_path)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Transcript load failed: {exc}")

        transcript_hash = AnalysisCache.transcript_hash(transcript_dict)

        # ── Tool versions (for cache identity) ───────────────────────────────
        ffmpeg_version = _get_tool_version("ffmpeg")
        ffprobe_version = _get_tool_version("ffprobe")

        # Level-A (preprocessing) cache identity
        pre_id = preprocessing_job_id(
            source_sha256=media_info.sha256,
            ffmpeg_version=ffmpeg_version,
            ffprobe_version=ffprobe_version,
            scene_detector_config=config.detector.as_dict(),
            extractor_slots=config.keyframe_slots,
            extractor_max_dim=1280,
        )

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
        output_schema_sha = AnalysisCache.output_schema_sha256(_SCHEMA_PATH)
        transcript_ctx_mode = (
            "included" if (transcript_dict and config.include_transcript_context)
            else ("redacted" if transcript_dict else "none")
        )

        if config.resume and not config.force:
            # We don't have keyframe SHAs yet — do a pre-check with empty list
            # (will be confirmed after extraction)
            pre_job_id = provider_job_id(
                preprocessing_sha256=pre_id,
                ordered_keyframe_sha256s=[],
                resolved_profile_hash=profile_hash,
                provider_id=config.provider,
                requested_model_id=config.vision_model,
                adapter_version=ADAPTER_VERSION,
                prompt_version=PROMPT_VERSION,
                output_schema_version=_ANALYSIS_SCHEMA_VERSION,
                output_schema_sha256=output_schema_sha,
                transcript_context_mode=transcript_ctx_mode,
                transcript_context_sha256=transcript_hash,
                external_upload_mode="allowed" if config.allow_external_upload else "denied",
            )
            cached = cache.get(pre_job_id)
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

        ordered_kf_shas = [kf.sha256 or "" for kf in keyframes]

        # Level-B (provider) job ID — now with real keyframe SHAs
        job_id = provider_job_id(
            preprocessing_sha256=pre_id,
            ordered_keyframe_sha256s=ordered_kf_shas,
            resolved_profile_hash=profile_hash,
            provider_id=config.provider,
            requested_model_id=config.vision_model,
            adapter_version=ADAPTER_VERSION,
            prompt_version=PROMPT_VERSION,
            output_schema_version=_ANALYSIS_SCHEMA_VERSION,
            output_schema_sha256=output_schema_sha,
            transcript_context_mode=transcript_ctx_mode,
            transcript_context_sha256=transcript_hash,
            external_upload_mode="allowed" if config.allow_external_upload else "denied",
        )

        # Second cache check — after keyframe extraction (exact identity)
        if config.resume and not config.force:
            cached = cache.get(job_id)
            if cached:
                print("Cache hit (OK) -- restoring from cache")
                (out_dir / "clip_analysis.json").write_text(
                    json.dumps(cached["analysis"], indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                return 0, "Analysis restored from cache"

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
                "cache_schema_version": CACHE_SCHEMA_VERSION,
                "provider": config.provider,
                "model_id": config.vision_model,
                "prompt_version": PROMPT_VERSION,
                "adapter_version": ADAPTER_VERSION,
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

        # Write output manifest (owner tag for future ownership checks)
        manifest = {
            "owner": _OWNER_TAG,
            "source_sha256": media_info.sha256,
            "profile_id": config.profile_id,
            "analysis_schema_version": _ANALYSIS_SCHEMA_VERSION,
            "cache_schema_version": CACHE_SCHEMA_VERSION,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        # ── Cache store ───────────────────────────────────────────────────────
        cache.put(
            job_id,
            analysis_json,
            extra_manifest={
                "source_sha256": media_info.sha256,
                "provider_id": config.provider,
            },
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
            return 7, f"Partial - {backend_errors}/{n_scenes} scenes failed scoring"
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
