"""Main orchestration service for Phase 4 scene analysis.

No hard-coded profile-ID branches.
No shell=True. No GPU/CUDA.
Ownership: --force cannot override source SHA mismatch or legacy-v1 output.

Cache order (ENFORCED):
  1. Inspect source  2. Source SHA  3. Scene boundaries
  4. Preprocessing identity  5. Extract keyframes
  6. VERIFY KEYFRAME BYTES & RECALCULATE SHA-256 (fail-closed on mismatch)
  7. Build per-scene SemanticRequests + ContentBundles
  8. Point A: validate_content_bundle_against_semantic_request() per scene
  9. Aggregate canonical identity  10. Semantic job SHA
  11. Provider cache lookup (ONLY after steps 6-10 complete)
  12. Point B: validate_content_bundle_against_semantic_request() per scene (cache miss only)
  13. Provider invocation (cache miss only)

Symlink/reparse protection:
  Raw output path is checked via is_symlink() and Windows reparse attribute
  BEFORE resolve() is ever called. Symlinks and reparse points are rejected.

Legacy v1 protection:
  If clip_analysis.json already exists with schema_version=="1.0.0", the
  pipeline raises LegacyOutputSchemaError (exit 5) without any mutation,
  regardless of --force.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat as _stat
import time
import uuid
from pathlib import Path

from auto_video_editor.analysis.atomic_io import (
    ArtifactIntegrityError,
    WriterLock,
    WriterLockError,
    atomic_write_bytes,
    atomic_write_text,
)
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
    LegacyOutputSchemaError,
    ProviderContentBundle,
    ProviderContentIntegrityError,
    SceneVisionSemanticRequest,
    validate_content_bundle_against_semantic_request,
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

# Exit codes
EXIT_SUCCESS = 0
EXIT_PROFILE_ERROR = 3
EXIT_MEDIA_ERROR = 4
EXIT_SCHEMA_OUTPUT_ERROR = 5
EXIT_CONSENT_ERROR = 6
EXIT_PARTIAL = 7
EXIT_BACKEND_ERROR = 8
EXIT_CONTENT_INTEGRITY_ERROR = 9

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
    """Atomically write the root marker file (written once, never rotated)."""
    marker_path = out_dir / _ROOT_MARKER_FILENAME
    atomic_write_text(marker_path, root_id)


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


def _is_symlink_or_reparse(path: Path) -> bool:
    """Return True if path is a symlink or Windows reparse point.

    Uses lstat() to check the raw path WITHOUT following any links.
    This check MUST be done before resolve() to prevent symlink-based bypass.
    """
    if path.is_symlink():
        return True
    # Windows reparse point check via st_file_attributes
    try:
        lst = path.lstat()
        reparse_flag = getattr(_stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        win_attrs = getattr(lst, "st_file_attributes", 0)
        if win_attrs & reparse_flag:
            return True
    except (OSError, AttributeError):
        pass
    return False


def _check_ownership(out_dir: Path, source_sha256: str, force: bool) -> tuple[bool, str]:
    # ── Raw-path symlink/reparse check FIRST (before resolve) ──────────────
    if out_dir.exists() and _is_symlink_or_reparse(out_dir):
        return False, (
            "Output dir is a symlink or Windows reparse point. "
            "Use a real directory as --output-dir."
        )

    if not out_dir.exists():
        return True, ""
    try:
        if not out_dir.resolve().is_dir():
            return False, "Output dir is not a regular directory."
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
    """Recompute SHA-256 from bytes on disk for each ok keyframe.

    SHA comparison is case-insensitive: the keyframe extractor stores uppercase
    hex digests; hashlib always returns lowercase. Normalization is applied to
    both sides so case difference is never a false-positive integrity failure.

    Raises ProviderContentIntegrityError only when actual content differs.
    Always returns keyframes with SHA-256 normalized to lowercase.
    """
    verified = []
    for kf in keyframes:
        if kf.status == "ok" and kf.path:
            disk_sha = AnalysisCache.verify_keyframe_sha256(kf.path)
            if disk_sha is None:
                # File unreadable — keep keyframe as-is; will be excluded downstream
                verified.append(kf)
                continue
            disk_sha_lower = disk_sha.lower()
            stored_sha_lower = (kf.sha256 or "").lower()
            if disk_sha_lower != stored_sha_lower:
                raise ProviderContentIntegrityError(
                    f"Keyframe SHA-256 mismatch for scene={kf.scene_index} slot={kf.slot}: "
                    f"expected suffix ...{stored_sha_lower[-12:]}, "
                    f"on-disk suffix ...{disk_sha_lower[-12:]}"
                )
            # Normalize SHA to lowercase in the stored keyframe object
            from auto_video_editor.analysis.models import Keyframe  # noqa: PLC0415
            kf = Keyframe(
                kf.scene_index, kf.slot, kf.timestamp_us, kf.path,
                disk_sha_lower, kf.status,
            )
        verified.append(kf)
    return verified



def _build_semantic_request(
    scene,
    ok_kf,
    image_bytes_tuple: tuple[bytes, ...],
    profile,
    profile_hash: str,
    config: AnalysisConfig,
    schema_sha: str,
    ctx_text: str | None,
    source_sha256: str,
) -> tuple[SceneVisionSemanticRequest, ProviderContentBundle]:
    """Build one immutable SceneVisionSemanticRequest and its ProviderContentBundle."""

    # Image descriptors — SHAs from actual bytes (already verified)
    images = []
    for order, (kf, b) in enumerate(zip(ok_kf, image_bytes_tuple)):
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
        source_sha256=source_sha256.lower(),
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
        image_bytes=image_bytes_tuple,
        transcript_excerpt=ctx_text if ctx_mode == "included" else None,
    )

    return semantic_req, bundle


class AnalysisService:
    """Orchestrates the full Phase 4 pipeline."""

    def run(self, config: AnalysisConfig) -> tuple[int, str]:
        """Execute the analysis pipeline.

        Returns (exit_code, message).
          0=success, 3=profile, 4=media, 5=schema/output/legacy-v1, 6=consent,
          7=partial, 8=backend, 9=content-integrity
        """
        t_start = time.monotonic()
        warnings: list[str] = []
        out_dir = Path(config.output_dir)

        # ── Consent checks ────────────────────────────────────────────────────
        if config.provider == "openai" and not config.allow_external_upload:
            return EXIT_CONSENT_ERROR, (
                "External upload requires --allow-external-upload. "
                "Keyframes would be sent to OpenAI API."
            )
        if config.provider == "openai":
            if not os.environ.get("OPENAI_API_KEY"):
                return EXIT_CONSENT_ERROR, "OPENAI_API_KEY environment variable is not set."

        # ── Load profile ──────────────────────────────────────────────────────
        try:
            profile = load_profile(config.profile_id)
        except Exception as exc:  # noqa: BLE001
            return EXIT_PROFILE_ERROR, f"Profile error: {exc}"

        profile_dict = profile.to_dict()
        profile_hash = AnalysisCache.profile_hash(profile_dict)

        # ── Step 1: Inspect source ────────────────────────────────────────────
        try:
            media_info, media_warnings = inspect_media(config.input_path)
        except Exception as exc:  # noqa: BLE001
            return EXIT_MEDIA_ERROR, f"Media inspection failed: {exc}"
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
            return EXIT_SUCCESS, "Dry-run complete"

        # ── Output directory: raw-path checks before resolve ──────────────────
        out_dir.mkdir(parents=True, exist_ok=True)

        # ── Ownership check (includes symlink/reparse rejection) ──────────────
        ok, err_msg = _check_ownership(out_dir, media_info.sha256, config.force)
        if not ok:
            return EXIT_SCHEMA_OUTPUT_ERROR, err_msg

        # ── Root marker (written once; never rotated) ─────────────────────────
        marker_path = out_dir / _ROOT_MARKER_FILENAME
        marker_id = _read_root_marker(out_dir)
        if marker_id is None:
            marker_id = str(uuid.uuid4())
            _write_root_marker(out_dir, marker_id)

        manifest_path = out_dir / "manifest.json"

        # ── Legacy v1 output detection (BEFORE any mutation) ──────────────────
        # If clip_analysis.json exists with schema_version==1.0.0, reject.
        # --force does NOT bypass this check.
        existing_analysis_path = out_dir / "clip_analysis.json"
        if existing_analysis_path.exists():
            try:
                existing_data = json.loads(
                    existing_analysis_path.read_text(encoding="utf-8")
                )
                if existing_data.get("schema_version") == "1.0.0":
                    raise LegacyOutputSchemaError(
                        "Existing clip_analysis.json has schema_version='1.0.0' (legacy V1). "
                        "This directory requires manual migration. "
                        "--force does not bypass legacy V1 rejection."
                    )
            except LegacyOutputSchemaError:
                return EXIT_SCHEMA_OUTPUT_ERROR, (
                    "Existing output contains legacy V1 schema (1.0.0). "
                    "Manual migration required; pipeline stopped without mutation."
                )
            except Exception:  # noqa: BLE001
                # Unreadable / invalid JSON — proceed; schema validation later will catch issues
                pass

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
            return EXIT_BACKEND_ERROR, f"Scene detection failed: {exc}"
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
            return EXIT_BACKEND_ERROR, f"Keyframe extraction failed: {exc}"
        warnings.extend(kf_warnings)

        # ── Step 6: VERIFY KEYFRAME BYTES & RECALCULATE SHA-256 ──────────────
        # FAIL-CLOSED: ProviderContentIntegrityError if SHA mismatch detected
        try:
            keyframes = _verify_keyframe_bytes(keyframes)
        except ProviderContentIntegrityError as exc:
            return EXIT_CONTENT_INTEGRITY_ERROR, f"Keyframe integrity failure: {exc}"

        # ── Associate transcript ──────────────────────────────────────────────
        transcript_associations = associate_transcript(
            scenes, transcript_dict or {}, config.include_transcript_context
        )

        # ── Schema identity ───────────────────────────────────────────────────
        schema_sha = AnalysisCache.output_schema_sha256(_SCHEMA_PATH)

        # ── Step 7: Build per-scene SemanticRequests + ContentBundles ─────────
        source_sha256_lower = media_info.sha256.lower()
        semantic_requests: list[SceneVisionSemanticRequest] = []
        content_bundles: list[ProviderContentBundle] = []

        for scene in scenes:
            scene_kf = [kf for kf in keyframes if kf.scene_index == scene.index]
            ok_kf = [kf for kf in scene_kf if kf.status == "ok" and kf.sha256]

            # Read image bytes for this scene
            image_bytes_list: list[bytes] = []
            verified_kf = []
            for kf in ok_kf:
                try:
                    b = Path(kf.path).read_bytes()
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"Scene {scene.index}: cannot read keyframe: {exc}")
                    continue
                image_bytes_list.append(b)
                verified_kf.append(kf)

            ctx_obj = transcript_associations.get(scene.index)
            ctx_text = (
                ctx_obj.full_text
                if ctx_obj and config.include_transcript_context
                else None
            )

            sem_req, bundle = _build_semantic_request(
                scene, verified_kf, tuple(image_bytes_list),
                profile, profile_hash, config, schema_sha, ctx_text,
                source_sha256=source_sha256_lower,
            )
            semantic_requests.append(sem_req)
            content_bundles.append(bundle)

        # ── Step 8: Point A — Validate all bundles BEFORE cache lookup ────────
        for sem_req, bundle in zip(semantic_requests, content_bundles):
            try:
                validate_content_bundle_against_semantic_request(sem_req, bundle)
            except ProviderContentIntegrityError as exc:
                return EXIT_CONTENT_INTEGRITY_ERROR, (
                    f"Content bundle integrity failure (Point A) for "
                    f"scene {sem_req.scene.get('scene_id', '?')}: {exc}"
                )

        # ── Step 9-10: Aggregate canonical identity → job SHA ─────────────────
        scene_canonical_dicts = [req.to_canonical_identity_dict() for req in semantic_requests]
        job_id = semantic_request_job_id(
            preprocessing_sha256=pre_id,
            scene_canonical_dicts=scene_canonical_dicts,
        )

        # ── Step 11: Provider cache lookup (ONLY after Point A) ───────────────
        cache = AnalysisCache(config.cache_dir)
        if config.resume and not config.force:
            cached = cache.get(job_id)
            if cached:
                print("Cache hit (OK) -- restoring from cache")
                analysis_json = json.dumps(cached["analysis"], indent=2, ensure_ascii=False)
                atomic_write_text(out_dir / "clip_analysis.json", analysis_json)
                return EXIT_SUCCESS, "Analysis restored from cache"

        # ── Step 12: Point B — Validate bundles again BEFORE provider ────────
        # (cache miss only; cache hit path does not reach here)
        for sem_req, bundle in zip(semantic_requests, content_bundles):
            try:
                validate_content_bundle_against_semantic_request(sem_req, bundle)
            except ProviderContentIntegrityError as exc:
                return EXIT_CONTENT_INTEGRITY_ERROR, (
                    f"Content bundle integrity failure (Point B) for "
                    f"scene {sem_req.scene.get('scene_id', '?')}: {exc}"
                )

        # ── Step 13: Vision backend ───────────────────────────────────────────
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

        # ── Export and validate ───────────────────────────────────────────────
        analysis_json = export_clip_analysis(analysis)

        if _SCHEMA_PATH.exists():
            schema_errors = validate_against_schema(analysis_json, str(_SCHEMA_PATH))
            if schema_errors:
                return EXIT_SCHEMA_OUTPUT_ERROR, f"Schema validation failed: {'; '.join(schema_errors[:3])}"

        # ── Atomic write clip_analysis.json ───────────────────────────────────
        analysis_bytes = analysis_json.encode("utf-8")
        analysis_sha = hashlib.sha256(analysis_bytes).hexdigest()
        try:
            atomic_write_bytes(
                out_dir / "clip_analysis.json",
                analysis_bytes,
                expected_sha256=analysis_sha,
            )
        except ArtifactIntegrityError as exc:
            return EXIT_SCHEMA_OUTPUT_ERROR, f"Artifact integrity error writing clip_analysis.json: {exc}"

        # ── Atomic write manifest.json (LAST) ─────────────────────────────────
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
            "clip_analysis_sha256": analysis_sha,
            "generated_artifacts": [
                "clip_analysis.json", "manifest.json", _ROOT_MARKER_FILENAME,
            ],
        }
        manifest_text = json.dumps(manifest, indent=2)
        try:
            atomic_write_text(manifest_path, manifest_text)
        except ArtifactIntegrityError as exc:
            return EXIT_SCHEMA_OUTPUT_ERROR, f"Artifact integrity error writing manifest.json: {exc}"

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
            return EXIT_PARTIAL, f"Partial - {backend_errors}/{n_scenes} scenes failed scoring"
        if overall_status == "failed":
            return EXIT_BACKEND_ERROR, "All scenes failed scoring"
        return EXIT_SUCCESS, "Success"


def _build_backend(config: AnalysisConfig):
    if config.provider == "mock":
        from auto_video_editor.analysis.scoring.mock_backend import MockVisionBackend  # noqa: PLC0415
        return MockVisionBackend()
    if config.provider == "openai":
        from auto_video_editor.analysis.scoring.openai_backend import OpenAIVisionBackend  # noqa: PLC0415
        model = config.vision_model or "gpt-4o"
        return OpenAIVisionBackend(model=model)
    raise ValueError(f"Unknown provider: {config.provider!r}")
