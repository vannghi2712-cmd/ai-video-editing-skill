"""Base protocol for vision scoring backends."""
from __future__ import annotations
from typing import Protocol, runtime_checkable
from auto_video_editor.analysis.models import Keyframe, SceneScore, Scene
from auto_video_editor.profiles.models import ContentProfile

PROMPT_VERSION = "1.0.0"


@runtime_checkable
class VisionBackend(Protocol):
    """Protocol all vision backends must satisfy."""

    @property
    def provider_id(self) -> str: ...

    @property
    def model_id(self) -> str | None: ...

    def score_scene(
        self,
        scene: Scene,
        keyframes: list[Keyframe],
        profile: ContentProfile,
        transcript_context: str | None,
    ) -> SceneScore: ...
