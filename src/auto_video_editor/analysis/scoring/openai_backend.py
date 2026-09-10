"""Optional OpenAI Vision adapter for Phase 4.

LAZY IMPORT: openai is NOT imported at module level.
Requires explicit consent flags: --allow-external-upload and OPENAI_API_KEY.
Uses Base64 data URLs for keyframes (ephemeral, NOT Files API, NOT public URLs).

Official API contract (verified 2026-09-09):
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

from auto_video_editor.analysis.models import (
    DimensionScore,
    ProviderContentBundle,
    SceneScore,
    SceneVisionSemanticRequest,
)
from auto_video_editor.analysis.scoring.base import PROMPT_VERSION

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
        semantic_request: SceneVisionSemanticRequest,
        content: ProviderContentBundle,
    ) -> SceneScore:
        """Score one scene using OpenAI Vision API.

        Builds prompt and image content from the validated semantic request
        and content bundle. No raw bytes or API keys are stored.
        """
        client = self._get_client()
        ordered_criteria = semantic_request.profile.get("ordered_criteria", [])
        image_bytes_list = content.image_bytes
        n_images = len(image_bytes_list)

        if n_images == 0:
            return _make_insufficient(
                semantic_request.scene["scene_id"], self._model, 0
            )

        # Build prompt from semantic request fields (no absolute paths, no keys)
        dimensions_list = ", ".join(
            f"{c['criterion_id']}(weight={c['finite_weight']:.0f})"
            for c in ordered_criteria
        )
        scene = semantic_request.scene
        start_s = scene["start_us"] / 1_000_000
        end_s = scene["end_us"] / 1_000_000
        prompt_text = (
            f"You are a professional video quality evaluator for short-form social media.\n"
            f"Evaluate these {n_images} keyframe(s) from a scene "
            f"({start_s:.2f}s – {end_s:.2f}s).\n"
            f"Scoring dimensions (name:weight out of 100): {dimensions_list}.\n"
        )
        # Transcript context: read ONLY from content bundle (not from semantic request)
        if (
            semantic_request.transcript_context.get("mode") == "included"
            and content.transcript_excerpt
        ):
            prompt_text += f"Transcript context: \"{content.transcript_excerpt[:500]}\"\n"
        prompt_text += (
            "Return JSON with keys: dimensions (array of objects with dimension, "
            "score 0-100, confidence 0-1, status 'scored'|'insufficient_evidence'), "
            "reasoning (string, max 100 chars)."
        )

        # Build response schema from ordered criteria
        dim_names = [c["criterion_id"] for c in ordered_criteria]
        schema = _build_response_schema(dim_names)

        # Build image content from bytes in content bundle (Base64 ephemeral)
        message_content: list[dict] = []
        for img_bytes in image_bytes_list:
            b64 = base64.b64encode(img_bytes).decode("ascii")
            message_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })
        message_content.append({"type": "text", "text": prompt_text})

        # Retry loop
        start_time = time.monotonic()
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            if time.monotonic() - start_time > _MAX_TOTAL_S:
                break
            try:
                response = client.chat.completions.create(
                    model=self._model,
                    messages=[{"role": "user", "content": message_content}],
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
                choice = response.choices[0]
                if getattr(choice.message, "refusal", None):
                    return _make_insufficient(
                        semantic_request.scene["scene_id"], self._model, n_images
                    )

                raw = choice.message.content
                parsed = json.loads(raw)
                return _build_scene_score(
                    semantic_request.scene["scene_id"],
                    self._model,
                    parsed,
                    n_images,
                    ordered_criteria,
                )

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
    scene_id: int,
    model: str,
    parsed: dict,
    n_images: int,
    ordered_criteria: list[dict],
) -> SceneScore:
    import math as _math  # noqa: PLC0415
    api_dims = {d["dimension"]: d for d in parsed.get("dimensions", [])}
    dims = []

    for c in ordered_criteria:
        dim = c["criterion_id"]
        weight = int(c["finite_weight"])
        api_d = api_dims.get(dim)
        if api_d and api_d.get("status") == "scored":
            raw_score = api_d["score"]
            score = float(raw_score) if raw_score is not None else None
            conf = float(api_d["confidence"]) if api_d.get("confidence") is not None else None
            dims.append(DimensionScore(dim, weight, score, conf, "scored"))
        else:
            dims.append(DimensionScore(dim, weight, None, None, "insufficient_evidence"))

    scored_dims = [
        d for d in dims
        if d.status == "scored" and d.score is not None and _math.isfinite(d.score)
        and 0.0 <= d.score <= 100.0
    ]
    score_coverage_percent = float(sum(d.weight for d in scored_dims))
    partial_ws = round(sum(d.score * d.weight / 100.0 for d in scored_dims), 4) if scored_dims else 0.0
    weighted_score = partial_ws if score_coverage_percent == 100.0 else None

    return SceneScore(
        scene_index=scene_id,
        provider="openai",
        model_id=model,
        prompt_version=PROMPT_VERSION,
        dimensions=tuple(dims),
        score_coverage_percent=score_coverage_percent,
        partial_weighted_score=partial_ws,
        weighted_score=weighted_score,
        keyframes_used=n_images,
        status="scored" if scored_dims else "insufficient_evidence",
    )


def _make_insufficient(scene_id: int, model: str, kf_used: int) -> SceneScore:
    return SceneScore(
        scene_index=scene_id,
        provider="openai",
        model_id=model,
        prompt_version=PROMPT_VERSION,
        dimensions=(),
        score_coverage_percent=0.0,
        partial_weighted_score=0.0,
        weighted_score=None,
        keyframes_used=kf_used,
        status="insufficient_evidence",
    )
