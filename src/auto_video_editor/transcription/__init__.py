"""
auto_video_editor.transcription
================================
CPU-first Vietnamese transcription subsystem.

Phase 3 — WhisperX-backed. WhisperX is a LAZY import; the base `.venv`
CLI works without it (transcribe doctor will exit 3 cleanly).

Public API intentionally kept narrow. Do not expose backend internals.
"""
from __future__ import annotations

from auto_video_editor.transcription.config import TranscriptionConfig
from auto_video_editor.transcription.models import (
    AlignmentInfo,
    EngineInfo,
    SourceInfo,
    TranscriptResult,
    TranscriptSegment,
    TranscriptWord,
    TimingStatus,
)

__all__ = [
    "TranscriptionConfig",
    "TranscriptResult",
    "TranscriptSegment",
    "TranscriptWord",
    "AlignmentInfo",
    "EngineInfo",
    "SourceInfo",
    "TimingStatus",
]

SCHEMA_VERSION = "1.0.0"
ADAPTER_VERSION = "1.0.0"
