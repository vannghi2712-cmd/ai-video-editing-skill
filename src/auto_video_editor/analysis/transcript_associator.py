"""Phase 3 transcript association for Phase 4 scenes.

Associates transcript segments with scenes via half-open interval overlap [scene_start, scene_end).
Extracts ONLY result.full_text and result.segments from the Phase 3 transcript.json.
Transcript content is NEVER disclosed to APIs unless --include-transcript-context is set.

No hard-coded profile-ID branches.
"""
from __future__ import annotations

import json
from pathlib import Path

from auto_video_editor.analysis.models import Scene, TranscriptContext

# Key invariant: we only access these two keys from the transcript.json
_TRANSCRIPT_RESULT_KEY = "result"
_SEGMENTS_KEY = "segments"
_FULL_TEXT_KEY = "full_text"


def load_transcript(transcript_path: str) -> dict:
    """Load and minimally validate a Phase 3 transcript.json.

    Returns the parsed dict.
    Raises RuntimeError if the file is missing or malformed.
    """
    p = Path(transcript_path)
    if not p.exists():
        raise RuntimeError(f"Transcript not found: {transcript_path}")
    try:
        with open(p, encoding="utf-8") as f:
            doc = json.load(f)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Transcript is not valid JSON: {exc}") from exc

    result = doc.get(_TRANSCRIPT_RESULT_KEY)
    if not isinstance(result, dict):
        raise RuntimeError(
            "Transcript missing 'result' key — expected Phase 3 schema v1.0.0"
        )
    if _SEGMENTS_KEY not in result:
        raise RuntimeError("Transcript result missing 'segments' key")
    return doc


def associate_transcript(
    scenes: list[Scene],
    transcript: dict,
    include_context: bool,
) -> dict[int, TranscriptContext | None]:
    """Associate transcript segments with scenes.

    Parameters
    ----------
    scenes          : normalized scene list
    transcript      : parsed transcript.json (from load_transcript)
    include_context : if False, returns empty contexts (consent not given)

    Returns dict mapping scene.index -> TranscriptContext or None.
    None means no segments overlap that scene.
    """
    result_block = transcript.get(_TRANSCRIPT_RESULT_KEY, {})
    segments = result_block.get(_SEGMENTS_KEY, [])

    associations: dict[int, TranscriptContext | None] = {}
    for scene in scenes:
        ctx = _associate_scene(scene, segments, include_context)
        associations[scene.index] = ctx
    return associations


def _associate_scene(
    scene: Scene,
    segments: list[dict],
    include_context: bool,
) -> TranscriptContext | None:
    """Find segments overlapping scene [start_s, end_s) and build context."""
    scene_start_s = scene.start_seconds
    scene_end_s = scene.end_seconds

    overlapping = []
    for seg in segments:
        seg_start = seg.get("start", 0.0)
        seg_end = seg.get("end", 0.0)
        # Half-open interval overlap: [seg_start, seg_end) ∩ [scene_start, scene_end) ≠ ∅
        if seg_end > scene_start_s and seg_start < scene_end_s:
            overlapping.append(seg)

    if not overlapping:
        return None

    if not include_context:
        # Consent not given: count only, no text
        word_count = sum(len(s.get("text", "").split()) for s in overlapping)
        char_count = sum(len(s.get("text", "")) for s in overlapping)
        return TranscriptContext(
            full_text="[REDACTED — use --include-transcript-context to enable]",
            word_count=word_count,
            char_count=char_count,
            segments=(),
        )

    texts = [s.get("text", "") for s in overlapping]
    full_text = " ".join(t for t in texts if t).strip()
    word_count = len(full_text.split()) if full_text else 0
    char_count = len(full_text)

    return TranscriptContext(
        full_text=full_text,
        word_count=word_count,
        char_count=char_count,
        segments=tuple(overlapping),
    )
