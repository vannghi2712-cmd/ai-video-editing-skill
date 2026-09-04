"""Optional OpenAI Vision adapter for Phase 4.

LAZY IMPORT: openai is NOT imported at module level.
Requires explicit consent flags: --allow-external-upload and OPENAI_API_KEY.
Uses Base64 data URLs for keyframes (ephemeral, NOT Files API, NOT public URLs).

Official API contract (verified 2026-09-04):
  POST /v1/chat/completions
  model: gpt-4o (or user-specified vision-capable model)
  messages[0].content: list of image_url + text parts
  image_url.url: "data:image/jpeg;base64,{b64}"
  response_format: {"type": "json_schema", "json_schema": {"name":..., "strict": True, "schema":{...}}}
  Refusal: response.choices[0].message.refusal (non-None means refusal)
  Rate limits: 429 with Retry-After header → retry up to 3 times, 60s total
  Do NOT retry: 400, 401, 403, or schema-validation failures

No hard-coded profile-ID branches.
No raw-video upload. No transcript disclosure without consent flag.
No credentials in logs.
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

from auto_video_editor.analysis.models import DimensionScore, Keyframe, Scene, SceneScore
from auto_video_editor.analysis.scoring.base import PROMPT_VERSION
from auto_video_editor.profiles.models import ContentProfile

_MAX_RETRIES = 3
_MAX_TOTAL_S = 60.0
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_NON_RETRYABLE_STATUS = {400, 401, 403}


class OpenAIVisionBackend:
    """OpenAI Vision adapter — lazy-loads `openai` SDK.

    Parameters
    ----------
    model        : vision-capable model (e.g. 'gpt-4o')
    api_key_env  : name of the environment variable holding the API key
    """

    def __init__(self, model: str, api_key_env: str = "OPENAI_API_KEY") -> None:
        self._model = model
        self._api_key_env = api_key_env
        self._client = None  # lazy

    @property
    def provider_id(self) -> str:
        return "openai"

    @property
    def model_id(self) -> str | None:
        return self._model

    def _get_client(self):
        if self._client is None:
            try:
                import openai  # noqa: PLC0415
            except ImportError as exc:
                raise ImportError(
                    "openai SDK not installed. "
                    "Install with: pip install -e '.[vision-openai]'"
                ) from exc
            api_key = os.environ.get(self._api_key_env, "")
            if not api_key:
                raise PermissionError(
                    f"OPENAI_API_KEY environment variable is not set or empty. "
                    "Set it or use --provider mock."
                )
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def score_scene(
        self,
        scene: Scene,
        keyframes: list[Keyframe],
        profile: ContentProfile,
        transcript_context: str | None,
    ) -> SceneScore:
        client = self._get_client()
        ok_kf = [kf for kf in keyframes if kf.status == "ok" and kf.sha256]

        if not ok_kf:
            dims = tuple(
                DimensionScore(dim, w, None, None, "insufficient_evidence")
                for dim, w in profile.scoring.items()
            )
            return SceneScore(
                scene_index=scene.index,
                provider="openai",
                model_id=self._model,
                prompt_version=PROMPT_VERSION,
                dimensions=dims,
                weighted_score=None,
                keyframes_used=0,
                status="insufficient_evidence",
            )

        # Build prompt listing dimensions dynamically (no profile-ID branches)
        dimensions_list = ", ".join(
            f"{dim}(weight={w})" for dim, w in profile.scoring.items()
        )
        prompt_text = (
            f"You are a professional video quality evaluator for short-form social media.\n"
            f"Evaluate these {len(ok_kf)} keyframe(s) from a scene "
            f"({scene.start_seconds:.2f}s – {scene.end_seconds:.2f}s).\n"
            f"Scoring dimensions (name:weight out of 100): {dimensions_list}.\n"
        )
        if transcript_context:
            prompt_text += f"Transcript context: \"{transcript_context[:500]}\"\n"
        prompt_text += (
            "Return JSON with keys: dimensions (array of objects with dimension, "
            "score 0-100, confidence 0-1, status 'scored'|'insufficient_evidence'), "
            "reasoning (string, max 100 chars)."
        )

        # Build response schema dynamically from profile dimensions
        dim_names = list(profile.scoring.weights.keys())
        schema = _build_response_schema(dim_names)

        # Build message content with images
        content: list[dict] = []
        for kf in ok_kf:
            b64 = _encode_image(kf.path)
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })
        content.append({"type": "text", "text": prompt_text})

        # Retry loop
        start_time = time.monotonic()
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            if time.monotonic() - start_time > _MAX_TOTAL_S:
                break
            try:
                response = client.chat.completions.create(
                    model=self._model,
                    messages=[{"role": "user", "content": content}],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "scene_score",
                            "strict": True,
                            "schema": schema,
                        },
                    },
                    timeout=30,
                )
                # Check for refusal
                choice = response.choices[0]
                if getattr(choice.message, "refusal", None):
                    return _make_insufficient(scene, self._model, len(ok_kf))

                raw = choice.message.content
                parsed = json.loads(raw)
                return _build_scene_score(scene, self._model, parsed, ok_kf, profile)

            except Exception as exc:  # noqa: BLE001
                status_code = getattr(exc, "status_code", None)
                if status_code in _NON_RETRYABLE_STATUS:
                    raise
                retry_after = _get_retry_after(exc)
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    wait = retry_after if retry_after else (2 ** attempt)
                    if time.monotonic() - start_time + wait < _MAX_TOTAL_S:
                        time.sleep(wait)
                    else:
                        break

        raise RuntimeError(
            f"OpenAI backend failed after {_MAX_RETRIES} attempts: {last_exc}"
        )


def _encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def _get_retry_after(exc: Exception) -> float | None:
    headers = getattr(exc, "response", None) and getattr(exc.response, "headers", {})
    if headers:
        val = headers.get("Retry-After")
        if val:
            try:
                return float(val)
            except ValueError:
                pass
    return None


def _build_response_schema(dim_names: list[str]) -> dict:
    """Build a strict JSON Schema for the model response."""
    return {
        "type": "object",
        "required": ["dimensions", "reasoning"],
        "additionalProperties": False,
        "properties": {
            "dimensions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["dimension", "score", "confidence", "status"],
                    "additionalProperties": False,
                    "properties": {
                        "dimension": {"type": "string"},
                        "score": {"type": "number"},
                        "confidence": {"type": "number"},
                        "status": {"type": "string", "enum": ["scored", "insufficient_evidence"]},
                    },
                },
            },
            "reasoning": {"type": "string"},
        },
    }


def _build_scene_score(
    scene: Scene,
    model: str,
    parsed: dict,
    ok_kf: list[Keyframe],
    profile: ContentProfile,
) -> SceneScore:
    api_dims = {d["dimension"]: d for d in parsed.get("dimensions", [])}
    dims = []
    weighted_sum = 0.0
    weight_total = 0
    any_scored = False

    for dim, weight in profile.scoring.items():
        api_d = api_dims.get(dim)
        if api_d and api_d.get("status") == "scored":
            score = float(api_d["score"])
            conf = float(api_d["confidence"])
            dims.append(DimensionScore(dim, weight, score, conf, "scored"))
            weighted_sum += weight * score
            weight_total += weight
            any_scored = True
        else:
            dims.append(DimensionScore(dim, weight, None, None, "insufficient_evidence"))

    ws = round(weighted_sum / weight_total, 2) if weight_total else None
    return SceneScore(
        scene_index=scene.index,
        provider="openai",
        model_id=model,
        prompt_version=PROMPT_VERSION,
        dimensions=tuple(dims),
        weighted_score=ws,
        keyframes_used=len(ok_kf),
        status="scored" if any_scored else "insufficient_evidence",
    )


def _make_insufficient(scene: Scene, model: str, kf_used: int) -> SceneScore:
    return SceneScore(
        scene_index=scene.index,
        provider="openai",
        model_id=model,
        prompt_version=PROMPT_VERSION,
        dimensions=(),
        weighted_score=None,
        keyframes_used=kf_used,
        status="insufficient_evidence",
    )
