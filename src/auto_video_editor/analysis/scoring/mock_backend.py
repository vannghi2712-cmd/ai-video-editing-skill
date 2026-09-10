"""Deterministic Mock vision backend for Phase 4.

Network-free. Score derived from keyframe SHA-256 in semantic request.
Deterministic: same image SHAs always produce same scores.
No hard-coded profile-ID branches — dimensions come from profile criteria.
"""
from __future__ import annotations

import hashlib

from auto_video_editor.analysis.models import (
    DimensionScore,
    ProviderContentBundle,
    SceneScore,
    SceneVisionSemanticRequest,
)
from auto_video_editor.analysis.scoring.base import PROMPT_VERSION

_CONFIDENCE_FULL = 0.72
_CONFIDENCE_PARTIAL = 0.45


class MockVisionBackend:
    """Deterministic mock — no network, no credentials."""

    @property
    def provider_id(self) -> str:
        return "mock"

    @property
    def model_id(self) -> str | None:
        return None

    def score_scene(
        self,
        semantic_request: SceneVisionSemanticRequest,
        content: ProviderContentBundle,
    ) -> SceneScore:
        """Score deterministically from image SHAs in the semantic request."""
        ordered_criteria = semantic_request.profile.get("ordered_criteria", [])
        images = semantic_request.images
        n_images = len(images)

        if n_images == 0:
            # No evidence — all dimensions insufficient
            dims = tuple(
                DimensionScore(
                    c["criterion_id"], int(c["finite_weight"]),
                    None, None, "insufficient_evidence",
                )
                for c in ordered_criteria
            )
            return SceneScore(
                scene_index=semantic_request.scene["scene_id"],
                provider="mock",
                model_id=None,
                prompt_version=PROMPT_VERSION,
                dimensions=dims,
                score_coverage_percent=0.0,
                partial_weighted_score=0.0,
                weighted_score=None,
                keyframes_used=0,
                status="insufficient_evidence",
            )

        # Derive deterministic seed from all image SHAs combined
        combined = "".join(img["full_sha256"] for img in images)
        seed_bytes = hashlib.sha256(combined.encode("utf-8")).digest()

        n_total_slots = semantic_request.provider_options.get("expected_slots", n_images)
        confidence = _CONFIDENCE_FULL if n_images >= n_total_slots else _CONFIDENCE_PARTIAL

        import math as _math  # noqa: PLC0415
        dims = []
        for idx, c in enumerate(ordered_criteria):
            byte_idx = (idx * 4) % len(seed_bytes)
            raw = int.from_bytes(seed_bytes[byte_idx: byte_idx + 4], "big")
            score = float(raw % 101)
            dims.append(
                DimensionScore(
                    c["criterion_id"], int(c["finite_weight"]),
                    score, confidence, "scored",
                )
            )

        scored_dims = [
            d for d in dims
            if d.status == "scored" and d.score is not None and _math.isfinite(d.score)
        ]
        score_coverage_percent = float(sum(d.weight for d in scored_dims))
        partial_ws = round(sum(d.score * d.weight / 100.0 for d in scored_dims), 4) if scored_dims else 0.0
        weighted_score = partial_ws if score_coverage_percent == 100.0 else None

        return SceneScore(
            scene_index=semantic_request.scene["scene_id"],
            provider="mock",
            model_id=None,
            prompt_version=PROMPT_VERSION,
            dimensions=tuple(dims),
            score_coverage_percent=score_coverage_percent,
            partial_weighted_score=partial_ws,
            weighted_score=weighted_score,
            keyframes_used=n_images,
            status="scored" if scored_dims else "insufficient_evidence",
        )
