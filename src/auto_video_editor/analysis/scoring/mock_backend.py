"""Deterministic Mock vision backend for Phase 4.

Network-free. Score derived from keyframe SHA-256 bytes.
Deterministic: same keyframe SHAs always produce same scores.
No hard-coded profile-ID branches — dimensions come from profile.scoring.weights.
"""
from __future__ import annotations

import hashlib

from auto_video_editor.analysis.models import DimensionScore, Keyframe, Scene, SceneScore
from auto_video_editor.analysis.scoring.base import PROMPT_VERSION
from auto_video_editor.profiles.models import ContentProfile

_CONFIDENCE_FULL = 0.72
_CONFIDENCE_PARTIAL = 0.45
_CONFIDENCE_NONE = 0.0


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
        scene: Scene,
        keyframes: list[Keyframe],
        profile: ContentProfile,
        transcript_context: str | None,
    ) -> SceneScore:
        ok_kf = [kf for kf in keyframes if kf.status == "ok" and kf.sha256]
        n_ok = len(ok_kf)
        n_total = len(keyframes)

        if n_ok == 0:
            # No evidence — all dimensions are insufficient
            dims = tuple(
                DimensionScore(dim, w, None, None, "insufficient_evidence")
                for dim, w in profile.scoring.items()
            )
            return SceneScore(
                scene_index=scene.index,
                provider="mock",
                model_id=None,
                prompt_version=PROMPT_VERSION,
                dimensions=dims,
                weighted_score=None,
                keyframes_used=0,
                status="insufficient_evidence",
            )

        # Derive a deterministic seed from all OK keyframe SHAs combined
        combined = "".join(kf.sha256 for kf in ok_kf)
        seed_bytes = hashlib.sha256(combined.encode()).digest()

        confidence = _CONFIDENCE_FULL if n_ok == n_total else _CONFIDENCE_PARTIAL
        dims = []
        weighted_sum = 0.0
        weight_total = 0

        for idx, (dim, weight) in enumerate(profile.scoring.items()):
            # Use different byte offsets per dimension for independence
            byte_idx = (idx * 4) % len(seed_bytes)
            raw = int.from_bytes(seed_bytes[byte_idx: byte_idx + 4], "big")
            score = float(raw % 101)  # [0, 100]
            dims.append(DimensionScore(dim, weight, score, confidence, "scored"))
            weighted_sum += weight * score
            weight_total += weight

        weight_total = weight_total or 1
        weighted_score = round(weighted_sum / weight_total, 2)

        return SceneScore(
            scene_index=scene.index,
            provider="mock",
            model_id=None,
            prompt_version=PROMPT_VERSION,
            dimensions=tuple(dims),
            weighted_score=weighted_score,
            keyframes_used=n_ok,
            status="scored",
        )
