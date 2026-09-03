"""
Exporters: convert TranscriptResult into SRT, words.json, and raw ASR JSON.

Word-timing honesty contract:
  - Words with timing_status != "aligned" MUST NOT appear with timing in SRT
  - SRT cues use segment-level times (always available from ASR)
  - SRT cues MUST be sequential, non-overlapping, valid UTF-8 Vietnamese
  - SRT index starts at 1
"""
from __future__ import annotations

import json
from typing import Any

from auto_video_editor.transcription.models import (
    AlignmentInfo,
    TranscriptResult,
    TranscriptSegment,
    TranscriptWord,
)


# ── SRT export ────────────────────────────────────────────────────────────────

def _format_srt_time(seconds: float) -> str:
    """Format seconds as SRT timestamp: HH:MM:SS,mmm"""
    s = max(0.0, seconds)
    ms = int(round((s % 1) * 1000))
    total_s = int(s)
    h = total_s // 3600
    m = (total_s % 3600) // 60
    sec = total_s % 60
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


def export_srt(result: TranscriptResult) -> str:
    """
    Generate a valid SRT file from TranscriptResult.

    Rules enforced:
    - Sequential index starting at 1
    - Non-overlapping cues (clamp end to next start if needed)
    - UTF-8 Vietnamese text
    - Skip empty segments
    """
    lines: list[str] = []
    idx = 1
    segments = [s for s in result.segments if s.text.strip()]

    for i, seg in enumerate(segments):
        start_s = seg.start
        end_s = seg.end

        # Clamp: end must be > start
        if end_s <= start_s:
            end_s = start_s + 0.001

        # Clamp: must not overlap with next segment
        if i + 1 < len(segments):
            next_start = segments[i + 1].start
            if end_s > next_start and next_start > start_s:
                end_s = next_start

        lines.append(str(idx))
        lines.append(
            f"{_format_srt_time(start_s)} --> {_format_srt_time(end_s)}"
        )
        lines.append(seg.text.strip())
        lines.append("")
        idx += 1

    return "\n".join(lines)


# ── Words JSON export ─────────────────────────────────────────────────────────

def export_words_json(result: TranscriptResult) -> str:
    """
    Generate words.json: flat array of word objects with timing_status.

    For each word:
      - text: the word string
      - timing_status: "aligned" | "unaligned" | "failed"
      - start, end, score: ONLY present when timing_status == "aligned"
      - segment_start, segment_end: the parent segment boundaries (always set)
    """
    words: list[dict] = []
    for seg in result.segments:
        for w in seg.words:
            entry: dict[str, Any] = {
                "text": w.text,
                "timing_status": w.timing_status,
                "segment_start": seg.start,
                "segment_end": seg.end,
            }
            if w.timing_status == "aligned":
                entry["start"] = w.start
                entry["end"] = w.end
                if w.score is not None:
                    entry["score"] = w.score
            words.append(entry)

    return json.dumps(words, ensure_ascii=False, indent=2)


# ── Transcript JSON export ────────────────────────────────────────────────────

def _word_to_dict(w: TranscriptWord, seg_start: float, seg_end: float) -> dict:
    d: dict[str, Any] = {
        "text": w.text,
        "timing_status": w.timing_status,
        "segment_start": seg_start,
        "segment_end": seg_end,
    }
    if w.timing_status == "aligned":
        d["start"] = w.start
        d["end"] = w.end
        if w.score is not None:
            d["score"] = w.score
    return d


def _seg_to_dict(seg: TranscriptSegment) -> dict:
    return {
        "start": seg.start,
        "end": seg.end,
        "text": seg.text,
        "words": [_word_to_dict(w, seg.start, seg.end) for w in seg.words],
    }


def export_transcript_json(result: TranscriptResult) -> str:
    """Generate the canonical transcript.json (schema v1.0.0)."""
    doc = {
        "schema_version": result.schema_version,
        "source": {
            "path": result.source.path,
            "sha256": result.source.sha256,
            "duration_seconds": result.source.duration_seconds,
            "size_bytes": result.source.size_bytes,
        },
        "engine": {
            "name": result.engine.name,
            "version": result.engine.version,
            "asr_model": result.engine.asr_model,
            "device": result.engine.device,
            "compute_type": result.engine.compute_type,
        },
        "request": result.request,
        "result": {
            "segments": [_seg_to_dict(s) for s in result.segments],
            "full_text": result.full_text,
        },
        "alignment": {
            "requested_mode": result.alignment.requested_mode,
            "actual_status": result.alignment.actual_status,
            "model_id": result.alignment.model_id,
            "model_fingerprint": result.alignment.model_fingerprint,
            "words_total": result.alignment.words_total,
            "words_aligned": result.alignment.words_aligned,
            "coverage_fraction": result.alignment.coverage_fraction,
        },
        "metrics": result.metrics,
        "provenance": result.provenance,
    }
    return json.dumps(doc, ensure_ascii=False, indent=2)


def export_raw_json(raw_asr_result: Any) -> str:
    """Serialize the raw backend output as-is (transcript.raw.json)."""
    try:
        return json.dumps(raw_asr_result, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return json.dumps({"error": "raw result is not JSON-serializable"}, indent=2)
