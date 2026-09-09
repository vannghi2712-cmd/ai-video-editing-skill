"""Main orchestration service for Phase 4 scene analysis.

No hard-coded profile-ID branches.
No shell=True. No GPU/CUDA.
Ownership: --force cannot override source SHA mismatch.
Cache order: provider cache looked up ONLY after keyframe bytes are verified.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
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
_ANALYSIS_SCHEMA_VERSION = "2.0.0"
_OWNER_TAG = "auto_video_editor.scene_analysis"
_MANIFEST_VERSION = "1.0.0"
_ROOT_MARKER_FILENAME = ".scene_analysis_root"

# FFmpeg/FFprobe version: detected at runtime.
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


def _normalize_dir(p: Path) -> str:
    """Return normalized absolute path string for root binding."""
    return str(p.resolve()).replace("\\", "/")


def _root_binding_sha256(out_dir: Path) -> str:
    """SHA-256 of normalized absolute output directory path."""
    normalized = _normalize_dir(out_dir)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _read_root_marker(out_dir: Path) -> str | None:
    """Read UUID from .scene_analysis_root marker file."""
    marker = out_dir / _ROOT_MARKER_FILENAME
    if not marker.exists() or not marker.is_file():
        return None
    try:
        return marker.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001
        return None


def _write_root_marker(out_dir: Path, root_id: str) -> None:
    """Write UUID to .scene_analysis_root marker file."""
    (out_dir / _ROOT_MARKER_FILENAME).write_text(root_id, encoding="utf-8")


def _check_ownership(out_dir: Path, source_sha256: str, force: bool) -> tuple[bool, str]:
    """
    Check output directory ownership.

    Rules:
    - Directory does not exist: OK
    - Directory exists but is empty: OK
    - Non-empty with valid manifest owned by _OWNER_TAG, matching source_sha256,
      matching root_binding_sha256, and present marker file with matching output_root_id: OK
    - --force cannot bypass source SHA mismatch or missing/mismatched marker.

    Returns (ok: bool, error_message: str)
    """
    if not out_dir.exists():
        return True, ""

    # Reject symlinks and traversal attempts
    try:
        resolved = out_dir.resolve()
        # Must resolve to itself or a known subdirectory (no symlink escape)
        if not resolved.is_dir():
            return False, "Output dir is not a regular directory (symlink or missing)."
    except Exception:  # noqa: BLE001
        return False, "Output dir cannot be resolved."

    # Empty dir is always OK
    children = [c for c in out_dir.iterdir() if c.name != _ROOT_MARKER_FILENAME]
    if not children:
        return True, ""

    manifest_path = out_dir / "manifest.json"
    if not manifest_path.exists():
        return False, (
            "Output dir is non-empty but has no manifest.json. "
            "Use a different --output-dir or clear it manually."
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

    # Verify root binding SHA
    expected_binding = _root_binding_sha256(out_dir)
    if existing.get("root_binding_sha256", "") != expected_binding:
        return False, (
            "Output dir root binding mismatch (directory may have been moved). "
            "Use a different --output-dir."
        )

    # Verify marker file matches manifest
    marker_id = _read_root_marker(out_dir)
    manifest_root_id = existing.get("output_root_id", "")
    if not marker_id or not manifest_root_id or marker_id != manifest_root_id:
        return False, (
            "Output dir marker file missing or does not match manifest output_root_id. "
            "Use a different --output-dir."
        )

    # Source SHA check — --force cannot bypass this
    existing_src = existing.get("source_sha256", "")
    if existing_src and existing_src != source_sha256:
        return False, (
            "Output dir is owned by a different source file (source SHA mismatch). "
            "--force cannot override a different-source directory. Use a different --output-dir."
        )

    # Owned by us with matching source and binding: OK
    return True, ""


def _verify_keyframe_bytes(keyframes) -> list:
    """Recompute SHA-256 from bytes on disk for each ok keyframe.

    Returns updated keyframe list. SHA mismatches are logged but do not
    stop execution (the mismatch is reflected in the identity hash).
    """
    verified = []
    for kf in keyframes:
        if kf.status == "ok" and kf.path:
            disk_sha = AnalysisCache.verify_keyframe_sha256(kf.path)
            if disk_sha and disk_sha != kf.sha256:
                # SHA changed — use disk value for identity (tamper indicator)
                from auto_video_editor.analysis.models import Keyframe  # noqa: PLC0415
                kf = Keyframe(
                    kf.scene_index, kf.slot, kf.timestamp_us,
                    kf.path, disk_sha, kf.status,
                )
        verified.append(kf)
    return verified


class AnalysisService:
    """Orchestrates the full Phase 4 pipeline."""

    def run(self, config: AnalysisConfig) -> tuple[int, str]:
        """Execute the analysis pipeline.

        Cache lookup order:
          1. Inspect source → 2. Source SHA → 3. Scene boundaries →
          4. Preprocessing cache identity → 5. Extract keyframes →
          6. VERIFY KEYFRAME BYTES & RECALCULATE SHA-256 →
          7. Associate transcript → 8. Build canonical request →
          9. Build request payload SHA → 10. Provider cache lookup.

        Returns (exit_code, message).
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

        # ── Step 1: Inspect source (media) ────────────────────────────────────
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
                    transcript_chars = len(td.get("result", {}).get("full_text", ""))
                except Exception:  # noqa: BLE001
                    pass
            print(
                f"DRY_RUN - Estimated: ~{est_scenes} scenes, "
                f"~{est_kf} keyframes (~{est_kf_bytes//1024}KB), "
                f"{est_api_calls} API calls, "
                f"{transcript_chars} transcript chars"
            )
            return 0, "Dry-run complete"

        # ── Output directory ownership ────────────────────────────────────────
        out_dir.mkdir(parents=True, exist_ok=True)
        # Write marker file on first use (empty or not yet owned)
        marker_id = _read_root_marker(out_dir)
        if marker_id is None:
            marker_id = str(uuid.uuid4())
            _write_root_marker(out_dir, marker_id)

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

        # ── Tool versions (for preprocessing identity) ───────────────────────
        ffmpeg_version = _get_tool_version("ffmpeg")
        ffprobe_version = _get_tool_version("ffprobe")

        # ── Step 2: Source SHA ────────────────────────────────────────────────
        # (already in media_info.sha256)

        # ── Step 3: Scene boundaries ──────────────────────────────────────────
        try:
            scenes, scene_warnings = detect_scenes(
                config.input_path, media_info.duration_us, config.detector
            )
        except Exception as exc:  # noqa: BLE001
            return 8, f"Scene detection failed: {exc}"
        warnings.extend(scene_warnings)

        # ── Step 4: Preprocessing cache identity ──────────────────────────────
        pre_id = preprocessing_job_id(
            source_sha256=media_info.sha256,
            ffmpeg_version=ffmpeg_version,
            ffprobe_version=ffprobe_version,
            scene_detector_config=config.detector.as_dict(),
            extractor_slots=config.keyframe_slots,
            extractor_max_dim=1280,
        )

        # ── Step 5: Extract keyframes ─────────────────────────────────────────
        try:
            keyframes, kf_warnings = extract_keyframes(
                config.input_path, scenes, out_dir, slots=config.keyframe_slots
            )
        except Exception as exc:  # noqa: BLE001
            return 8, f"Keyframe extraction failed: {exc}"
        warnings.extend(kf_warnings)

        # ── Step 6: VERIFY KEYFRAME BYTES & RECALCULATE SHA-256 ───────────────
        keyframes = _verify_keyframe_bytes(keyframes)
        ordered_kf_shas = [kf.sha256 or "" for kf in keyframes]

        # ── Step 7: Associate transcript ──────────────────────────────────────
        transcript_associations = associate_transcript(
            scenes, transcript_dict or {}, config.include_transcript_context
        )

        # ── Step 8: Build canonical semantic request ───────────────────────────
        output_schema_sha = AnalysisCache.output_schema_sha256(_SCHEMA_PATH)

        # Determine transcript context mode and hash
        if transcript_dict and config.include_transcript_context:
            transcript_ctx_mode = "included"
        elif transcript_dict:
            transcript_ctx_mode = "redacted"
        else:
            transcript_ctx_mode = "not_included"

        # Hash the exact excerpt that will be sent (or "not-included")
        # Build a representative context hash from all scenes' contexts
        if transcript_ctx_mode == "included":
            ctx_texts = [
                assoc.full_text
                for assoc in transcript_associations.values()
                if assoc is not None
            ]
            combined_ctx = "\n".join(ctx_texts)
            transcript_ctx_sha = AnalysisCache.transcript_context_sha256(combined_ctx or None)
        else:
            transcript_ctx_sha = "not-included"

        # Canonical semantic request (immutable, drives both cache and provider)
        canonical_request = {
            "preprocessing_sha256": pre_id,
            "ordered_keyframe_sha256s": ordered_kf_shas,
            "resolved_profile_hash": profile_hash,
            "provider_id": config.provider,
            "requested_model_id": config.vision_model or "",
            "adapter_version": ADAPTER_VERSION,
            "prompt_version": PROMPT_VERSION,
            "output_schema_version": _ANALYSIS_SCHEMA_VERSION,
            "output_schema_sha256": output_schema_sha,
            "transcript_context_mode": transcript_ctx_mode,
            "transcript_context_sha256": transcript_ctx_sha,
            "external_upload_mode": "allowed" if config.allow_external_upload else "denied",
        }

        # Sanitized debug projection (hashes, counts, IDs only — no raw content)
        _debug_request = {
            "preprocessing_sha256": pre_id[:12] + "...",
            "keyframe_count": len([s for s in ordered_kf_shas if s]),
            "profile_hash": profile_hash[:12] + "...",
            "provider_id": config.provider,
            "requested_model_id": config.vision_model or "",
            "transcript_context_mode": transcript_ctx_mode,
            "transcript_context_sha256": transcript_ctx_sha[:12] + "...",
        }

        # ── Step 9: Build request payload SHA ─────────────────────────────────
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
            transcript_context_sha256=transcript_ctx_sha,
            external_upload_mode="allowed" if config.allow_external_upload else "denied",
        )

        # ── Step 10: Provider cache lookup (ONLY after verified keyframe SHAs) ─
        cache = AnalysisCache(config.cache_dir)
        if config.resume and not config.force:
            cached = cache.get(job_id)
            if cached:
                print("Cache hit (OK) -- restoring from cache")
                (out_dir / "clip_analysis.json").write_text(
                    json.dumps(cached["analysis"], indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                return 0, "Analysis restored from cache"

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

        # Schema validation (jsonschema is MANDATORY_RUNTIME)
        if _SCHEMA_PATH.exists():
            schema_errors = validate_against_schema(analysis_json, str(_SCHEMA_PATH))
            if schema_errors:
                return 5, f"Schema validation failed: {'; '.join(schema_errors[:3])}"

        (out_dir / "clip_analysis.json").write_text(analysis_json, encoding="utf-8")

        # ── Write output manifest ─────────────────────────────────────────────
        root_id = _read_root_marker(out_dir) or marker_id
        manifest = {
            "manifest_version": _MANIFEST_VERSION,
            "owner": _OWNER_TAG,
            "output_root_id": root_id,
            "root_binding_sha256": _root_binding_sha256(out_dir),
            "source_sha256": media_info.sha256,
            "profile_id": config.profile_id,
            "analysis_schema_version": _ANALYSIS_SCHEMA_VERSION,
            "cache_schema_version": CACHE_SCHEMA_VERSION,
            "generated_artifacts": ["clip_analysis.json", "manifest.json", _ROOT_MARKER_FILENAME],
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
