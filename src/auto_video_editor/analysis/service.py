"""Main orchestration service for Phase 4 scene analysis.

No hard-coded profile-ID branches.
No shell=True. No GPU/CUDA.
Ownership: --force cannot override source SHA mismatch.

Cache order (ENFORCED):
  1. Inspect source  2. Source SHA  3. Scene boundaries
  4. Preprocessing identity  5. Extract keyframes
  6. VERIFY KEYFRAME BYTES & RECALCULATE SHA-256
  7. Build per-scene SemanticRequests + ContentBundles (verifies all bytes)
  8. Aggregate canonical identity  9. Semantic job SHA
  10. Provider cache lookup (ONLY after steps 6-9 complete)
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from pathlib import Path

from auto_video_editor.analysis.cache import (
    CACHE_SCHEMA_VERSION,
    VISION_ADAPTER_VERSION,
    AnalysisCache,
    preprocessing_job_id,
    semantic_request_job_id,
)
from auto_video_editor.analysis.config import AnalysisConfig
from auto_video_editor.analysis.exporters import export_clip_analysis, validate_against_schema
from auto_video_editor.analysis.keyframe_extractor import extract_keyframes
from auto_video_editor.analysis.media_inspector import inspect_media
from auto_video_editor.analysis.models import (
    ClipAnalysis,
    ProviderContentBundle,
    SceneVisionSemanticRequest,
)
from auto_video_editor.analysis.scene_detector import detect_scenes
from auto_video_editor.analysis.scoring.base import PROMPT_VERSION, VISION_ADAPTER_VERSION as _ADAPTER_VER
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

_TOOL_VERSION_UNKNOWN = "unknown"

# SHA-256 of the prompt template string used by all providers.
# Recompute if the prompt template content changes.
_PROMPT_TEMPLATE_SHA = hashlib.sha256(
    b"You are a professional video quality evaluator for short-form social media."
).hexdigest()


def _get_tool_version(tool: str) -> str:
    import subprocess  # noqa: PLC0415
    try:
        r = subprocess.run([tool, "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        first_line = (r.stdout or r.stderr or b"").decode("utf-8", errors="replace").splitlines()
        return first_line[0].strip() if first_line else _TOOL_VERSION_UNKNOWN
    except Exception:  # noqa: BLE001
        return _TOOL_VERSION_UNKNOWN


def _normalize_dir(p: Path) -> str:
    return str(p.resolve()).replace("\\", "/")


def _root_binding_sha256(out_dir: Path) -> str:
    return hashlib.sha256(_normalize_dir(out_dir).encode("utf-8")).hexdigest()


def _read_root_marker(out_dir: Path) -> str | None:
    marker = out_dir / _ROOT_MARKER_FILENAME
    if not marker.exists() or not marker.is_file():
        return None
    try:
        return marker.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001
        return None


def _write_root_marker(out_dir: Path, root_id: str) -> None:
    (out_dir / _ROOT_MARKER_FILENAME).write_text(root_id, encoding="utf-8")


def _atomic_write(path: Path, data: bytes) -> None:
    """Write data atomically: write to temp file then os.replace() (same directory)."""
    parent = path.parent
    fd, tmp_path = tempfile.mkstemp(dir=str(parent), prefix=".tmp_", suffix=path.suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:  # noqa: BLE001
            pass
        raise


def _atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    _atomic_write(path, text.encode(encoding))


def _jpeg_dimensions(data: bytes) -> tuple[int, int]:
    """Parse JPEG bytes to extract (width, height). Returns (0, 0) on failure."""
    try:
        i = 2  # skip SOI marker (FF D8)
        while i < len(data) - 8:
            if data[i] != 0xFF:
                break
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):  # SOF0/SOF1/SOF2
                height = (data[i + 5] << 8) | data[i + 6]
                width = (data[i + 7] << 8) | data[i + 8]
                return width, height
            segment_len = (data[i + 2] << 8) | data[i + 3]
            i += 2 + segment_len
    except Exception:  # noqa: BLE001
        pass
    return 0, 0


def _check_ownership(out_dir: Path, source_sha256: str, force: bool) -> tuple[bool, str]:
    if not out_dir.exists():
        return True, ""
    try:
        if not out_dir.resolve().is_dir():
            return False, "Output dir is not a regular directory (symlink or missing)."
    except Exception:  # noqa: BLE001
        return False, "Output dir cannot be resolved."

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

    expected_binding = _root_binding_sha256(out_dir)
    if existing.get("root_binding_sha256", "") != expected_binding:
        return False, (
            "Output dir root binding mismatch (directory may have been moved). "
            "Use a different --output-dir."
        )

    marker_id = _read_root_marker(out_dir)
    manifest_root_id = existing.get("output_root_id", "")
    if not marker_id or not manifest_root_id or marker_id != manifest_root_id:
        return False, (
            "Output dir marker file missing or does not match manifest output_root_id. "
            "Use a different --output-dir."
        )

    existing_src = existing.get("source_sha256", "")
    if existing_src and existing_src != source_sha256:
        return False, (
            "Output dir is owned by a different source file (source SHA mismatch). "
            "--force cannot override a different-source directory. Use a different --output-dir."
        )

    return True, ""


def _verify_keyframe_bytes(keyframes) -> list:
    """Recompute SHA-256 from bytes on disk for each ok keyframe."""
    verified = []
    for kf in keyframes:
        if kf.status == "ok" and kf.path:
            disk_sha = AnalysisCache.verify_keyframe_sha256(kf.path)
            if disk_sha and disk_sha != kf.sha256:
                from auto_video_editor.analysis.models import Keyframe  # noqa: PLC0415
                kf = Keyframe(kf.scene_index, kf.slot, kf.timestamp_us, kf.path, disk_sha, kf.status)
        verified.append(kf)
    return verified


def _build_semantic_request(
    scene,
    ok_kf,
    image_bytes_list: list[bytes],
    profile,
    profile_hash: str,
    config: AnalysisConfig,
    schema_sha: str,
    ctx_text: str | None,
) -> tuple[SceneVisionSemanticRequest, ProviderContentBundle]:
    """Build one immutable SceneVisionSemanticRequest and its ProviderContentBundle."""

    # Image descriptors — SHAs from actual bytes (already verified)
    images = []
    for order, (kf, b) in enumerate(zip(ok_kf, image_bytes_list)):
        w, h = _jpeg_dimensions(b)
        sha = hashlib.sha256(b).hexdigest()
        images.append({
            "order": order,
            "frame_id": f"scene_{scene.index:04d}_slot_{kf.slot}",
            "full_sha256": sha,
            "mime_type": "image/jpeg",
            "width": w,
            "height": h,
            "detail": "auto",
        })

    # Transcript context
    if ctx_text is not None and config.include_transcript_context:
        ctx_sha = AnalysisCache.transcript_context_sha256(ctx_text)
        ctx_chars = len(ctx_text.encode("utf-8"))
        ctx_mode = "included"
    else:
        ctx_sha = "not_included"
        ctx_chars = 0
        ctx_mode = "not_included"

    # Ordered criteria from profile
    ordered_criteria = [
        {"order": i, "criterion_id": dim, "finite_weight": float(w)}
        for i, (dim, w) in enumerate(profile.scoring.items())
    ]

    semantic_req = SceneVisionSemanticRequest(
        provider_id=config.provider,
        requested_model_id=config.vision_model or "",
        adapter_version=_ADAPTER_VER,
        prompt={"version": PROMPT_VERSION, "content_sha256": _PROMPT_TEMPLATE_SHA},
        provider_options={
            "detail": "auto",
            "expected_slots": config.keyframe_slots,
        },
        scene={
            "scene_id": scene.index,
            "start_us": scene.start_us,
            "end_us": scene.end_us,
            "duration_us": scene.duration_us,
        },
        profile={
            "profile_id": config.profile_id,
            "resolved_profile_sha256": profile_hash,
            "ordered_criteria": ordered_criteria,
        },
        images=tuple(images),
        transcript_context={
            "mode": ctx_mode,
            "character_count": ctx_chars,
            "content_sha256": ctx_sha,
        },
        response_schema={
            "schema_version": _ANALYSIS_SCHEMA_VERSION,
            "full_schema_sha256": schema_sha,
        },
    )

    bundle = ProviderContentBundle(
        image_bytes=list(image_bytes_list),
        transcript_excerpt=ctx_text if ctx_mode == "included" else None,
    )

    return semantic_req, bundle


class AnalysisService:
    """Orchestrates the full Phase 4 pipeline."""

    def run(self, config: AnalysisConfig) -> tuple[int, str]:
        """Execute the analysis pipeline.

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
            if not os.environ.get("OPENAI_API_KEY"):
                return 6, "OPENAI_API_KEY environment variable is not set."

        # ── Load profile ──────────────────────────────────────────────────────
        try:
            profile = load_profile(config.profile_id)
        except Exception as exc:  # noqa: BLE001
            return 3, f"Profile error: {exc}"

        profile_dict = profile.to_dict()
        profile_hash = AnalysisCache.profile_hash(profile_dict)

        # ── Step 1: Inspect source ────────────────────────────────────────────
        try:
            media_info, media_warnings = inspect_media(config.input_path)
        except Exception as exc:  # noqa: BLE001
            return 4, f"Media inspection failed: {exc}"
        warnings.extend(media_warnings)

        # ── Dry-run ───────────────────────────────────────────────────────────
        if config.dry_run:
            est_scenes = max(1, int(media_info.duration_seconds / 5))
            est_kf = est_scenes * config.keyframe_slots
            print(
                f"DRY_RUN - Estimated: ~{est_scenes} scenes, "
                f"~{est_kf} keyframes (~{est_kf * 150_000 // 1024}KB), "
                f"{est_scenes if config.provider == 'openai' else 0} API calls"
            )
            return 0, "Dry-run complete"

        # ── Output directory ownership ────────────────────────────────────────
        out_dir.mkdir(parents=True, exist_ok=True)
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

        # ── Tool versions ─────────────────────────────────────────────────────
        ffmpeg_version = _get_tool_version("ffmpeg")
        ffprobe_version = _get_tool_version("ffprobe")

        # ── Step 2-3: Source SHA + Scene boundaries ───────────────────────────
        try:
            scenes, scene_warnings = detect_scenes(
                config.input_path, media_info.duration_us, config.detector
            )
        except Exception as exc:  # noqa: BLE001
            return 8, f"Scene detection failed: {exc}"
        warnings.extend(scene_warnings)

        # ── Step 4: Preprocessing identity ───────────────────────────────────
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

        # ── Step 6: VERIFY KEYFRAME BYTES & RECALCULATE SHA-256 ──────────────
        keyframes = _verify_keyframe_bytes(keyframes)

        # ── Associate transcript ──────────────────────────────────────────────
        transcript_associations = associate_transcript(
            scenes, transcript_dict or {}, config.include_transcript_context
        )

        # ── Schema identity ───────────────────────────────────────────────────
        schema_sha = AnalysisCache.output_schema_sha256(_SCHEMA_PATH)

        # ── Step 7: Build per-scene SemanticRequests + ContentBundles ─────────
        # All keyframe bytes verified in step 6. Image bytes re-read here.
        semantic_requests: list[SceneVisionSemanticRequest] = []
        content_bundles: list[ProviderContentBundle] = []

        for scene in scenes:
            scene_kf = [kf for kf in keyframes if kf.scene_index == scene.index]
            ok_kf = [kf for kf in scene_kf if kf.status == "ok" and kf.sha256]

            # Read and verify image bytes for this scene
            image_bytes_list: list[bytes] = []
            verified_kf = []
            for kf in ok_kf:
                try:
                    b = Path(kf.path).read_bytes()
                    disk_sha = hashlib.sha256(b).hexdigest()
                    if disk_sha != kf.sha256:
                        warnings.append(
                            f"Scene {scene.index}: keyframe SHA mismatch "
                            f"(expected {kf.sha256[:8]}…, got {disk_sha[:8]}…)"
                        )
                    image_bytes_list.append(b)
                    verified_kf.append(kf)
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"Scene {scene.index}: cannot read keyframe: {exc}")

            ctx_obj = transcript_associations.get(scene.index)
            ctx_text = (
                ctx_obj.full_text
                if ctx_obj and config.include_transcript_context
                else None
            )

            sem_req, bundle = _build_semantic_request(
                scene, verified_kf, image_bytes_list,
                profile, profile_hash, config, schema_sha, ctx_text,
            )
            semantic_requests.append(sem_req)
            content_bundles.append(bundle)

        # ── Step 8-9: Aggregate canonical identity → job SHA ──────────────────
        scene_canonical_dicts = [req.to_canonical_identity_dict() for req in semantic_requests]
        job_id = semantic_request_job_id(
            preprocessing_sha256=pre_id,
            scene_canonical_dicts=scene_canonical_dicts,
        )

        # ── Step 10: Provider cache lookup (ONLY after verified semantic reqs) ─
        cache = AnalysisCache(config.cache_dir)
        if config.resume and not config.force:
            cached = cache.get(job_id)
            if cached:
                print("Cache hit (OK) -- restoring from cache")
                _atomic_write_text(
                    out_dir / "clip_analysis.json",
                    json.dumps(cached["analysis"], indent=2, ensure_ascii=False),
                )
                return 0, "Analysis restored from cache"

        # ── Vision backend ────────────────────────────────────────────────────
        backend = _build_backend(config)
        scores = []
        backend_errors = 0
        for scene, sem_req, bundle in zip(scenes, semantic_requests, content_bundles):
            try:
                score = backend.score_scene(sem_req, bundle)
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
                "adapter_version": VISION_ADAPTER_VERSION,
            },
        )

        # ── Export (atomic write) ─────────────────────────────────────────────
        analysis_json = export_clip_analysis(analysis)

        if _SCHEMA_PATH.exists():
            schema_errors = validate_against_schema(analysis_json, str(_SCHEMA_PATH))
            if schema_errors:
                return 5, f"Schema validation failed: {'; '.join(schema_errors[:3])}"

        _atomic_write_text(out_dir / "clip_analysis.json", analysis_json)

        # ── Write manifest (atomic) ───────────────────────────────────────────
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
            "generated_artifacts": [
                "clip_analysis.json", "manifest.json", _ROOT_MARKER_FILENAME,
            ],
        }
        _atomic_write_text(manifest_path, json.dumps(manifest, indent=2))

        # ── Cache store ───────────────────────────────────────────────────────
        cache.put(
            job_id, analysis_json,
            extra_manifest={"source_sha256": media_info.sha256, "provider_id": config.provider},
        )

        n_scenes = len(scenes)
        n_kf_ok = sum(1 for kf in keyframes if kf.status == "ok")
        n_scored = sum(1 for sc in scores if sc.status == "scored")
        print(
            f"Analysis complete. "
            f"Scenes: {n_scenes}  Keyframes: {n_kf_ok}/{len(keyframes)}  "
            f"Scored: {n_scored}/{n_scenes}  Elapsed: {elapsed:.1f}s"
        )
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
