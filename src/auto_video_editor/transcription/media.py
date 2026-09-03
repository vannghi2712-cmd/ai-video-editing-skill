"""
Media probing, safety validation, and SHA-256 fingerprinting.

Uses ffprobe (external process). Never modifies source media.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


_FFPROBE_CMD = "ffprobe"


class MediaProbeError(Exception):
    """Raised when a source file fails safety or probe validation."""


class MediaProbe:
    """Probes a media file via ffprobe and computes its SHA-256."""

    def __init__(
        self,
        path: str | Path,
        sha256: str,
        duration_seconds: float,
        size_bytes: int,
        has_audio: bool,
    ) -> None:
        self.path = Path(path).resolve()
        self.sha256 = sha256
        self.duration_seconds = duration_seconds
        self.size_bytes = size_bytes
        self.has_audio = has_audio


def probe_media(source: str | Path) -> MediaProbe:
    """
    Validate and probe a source media file.

    Safety rules enforced:
    - Must be an absolute, resolved path to an existing regular file
    - Must NOT be a URL (http://, https://, rtmp://, etc.)
    - Must NOT be a directory
    - Must have a decodable audio stream
    - Must have a finite duration > 0
    - SHA-256 computed BEFORE any processing

    Returns MediaProbe on success. Raises MediaProbeError on any failure.
    """
    src = str(source)

    # Reject URLs
    for scheme in ("http://", "https://", "rtmp://", "rtsp://", "ftp://", "//"):
        if src.lower().startswith(scheme):
            raise MediaProbeError(f"URL inputs are not permitted: {src!r}")

    p = Path(src).resolve()

    if not p.exists():
        raise MediaProbeError(f"Source file not found: {p}")
    if not p.is_file():
        raise MediaProbeError(f"Source is not a regular file: {p}")
    if p.stat().st_size == 0:
        raise MediaProbeError(f"Source file is empty (0 bytes): {p}")

    # Run ffprobe
    cmd = [
        _FFPROBE_CMD,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(p),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=30,
        )
    except FileNotFoundError:
        raise MediaProbeError(
            "ffprobe not found. Install FFmpeg (ffprobe must be on PATH)."
        )
    except subprocess.TimeoutExpired:
        raise MediaProbeError("ffprobe timed out probing source file.")

    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise MediaProbeError(
            f"ffprobe failed (exit {result.returncode}): {stderr}"
        )

    try:
        info = json.loads(result.stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise MediaProbeError(f"ffprobe output is not valid JSON: {exc}") from exc

    # Check for audio stream
    streams = info.get("streams", [])
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    if not has_audio:
        raise MediaProbeError(
            f"Source file has no decodable audio stream: {p}"
        )

    # Check duration
    fmt = info.get("format", {})
    raw_duration = fmt.get("duration")
    if raw_duration is None:
        # Try stream durations
        durations = [
            float(s["duration"])
            for s in streams
            if s.get("duration") not in (None, "N/A")
        ]
        if not durations:
            raise MediaProbeError(f"Cannot determine duration of: {p}")
        raw_duration = max(durations)

    try:
        duration = float(raw_duration)
    except (ValueError, TypeError):
        raise MediaProbeError(
            f"Duration is not a finite number ({raw_duration!r}): {p}"
        )

    if duration <= 0:
        raise MediaProbeError(
            f"Source has zero or negative duration ({duration}s): {p}"
        )

    # Compute SHA-256 of source before any processing
    sha256 = _sha256_file(p)
    size_bytes = p.stat().st_size

    return MediaProbe(
        path=p,
        sha256=sha256,
        duration_seconds=duration,
        size_bytes=size_bytes,
        has_audio=has_audio,
    )


def verify_source_integrity(probe: MediaProbe) -> None:
    """
    Recompute SHA-256 and assert it matches the pre-run value.

    Raises MediaProbeError if the file has been modified.
    MUST be called after all backend processing completes.
    """
    actual = _sha256_file(probe.path)
    if actual.lower() != probe.sha256.lower():
        raise MediaProbeError(
            f"Source file integrity violation! "
            f"SHA-256 changed for {probe.path}\n"
            f"  Expected: {probe.sha256}\n"
            f"  Actual:   {actual}"
        )


def _sha256_file(path: Path) -> str:
    """Return uppercase hex SHA-256 of a file without loading it all at once."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):  # 1 MiB chunks
            h.update(chunk)
    return h.hexdigest().upper()
