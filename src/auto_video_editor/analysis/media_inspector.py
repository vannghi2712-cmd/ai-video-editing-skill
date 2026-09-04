"""FFprobe-based media inspection for Phase 4.

Uses subprocess (no shell=True). Parses JSON output from ffprobe.
No hard-coded profile-ID branches.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from auto_video_editor.analysis.models import MediaInfo


_FFPROBE_TIMEOUT_S = 30


def inspect_media(path: str | os.PathLike) -> tuple[MediaInfo, list[str]]:
    """Inspect a media file with ffprobe.

    Returns (MediaInfo, warnings).
    Raises FileNotFoundError if the file does not exist.
    Raises RuntimeError if ffprobe fails or output is unparseable.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Media file not found: {path}")

    warnings: list[str] = []

    # ── SHA-256 ───────────────────────────────────────────────────────────────
    sha256 = _sha256_file(p)
    size_bytes = p.stat().st_size

    # ── ffprobe JSON ──────────────────────────────────────────────────────────
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        str(p),
    ]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=_FFPROBE_TIMEOUT_S,
        )
    except FileNotFoundError:
        raise RuntimeError("ffprobe not found on PATH")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"ffprobe timed out after {_FFPROBE_TIMEOUT_S}s")

    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"ffprobe exited {result.returncode}: {stderr[:400]}")

    try:
        probe = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ffprobe produced invalid JSON: {exc}") from exc

    streams = probe.get("streams", [])
    fmt = probe.get("format", {})

    # ── Video stream ──────────────────────────────────────────────────────────
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

    has_video = bool(video_streams)
    has_audio = bool(audio_streams)

    if not has_video:
        raise RuntimeError("No video stream found in media file")
    if not has_audio:
        warnings.append("NO_AUDIO_STREAM: file has no audio track; processing continues")

    vs = video_streams[0]
    width = int(vs.get("width", 0))
    height = int(vs.get("height", 0))
    codec_name = vs.get("codec_name", "unknown")

    # FPS: prefer avg_frame_rate, fall back to r_frame_rate
    fps = _parse_rational(vs.get("avg_frame_rate") or vs.get("r_frame_rate", "0/1"))

    # Duration: prefer stream duration, fall back to format duration
    duration_s = _parse_duration(vs.get("duration") or fmt.get("duration"))
    if duration_s is None or duration_s <= 0:
        raise RuntimeError("Unable to determine video duration from ffprobe output")
    duration_us = int(round(duration_s * 1_000_000))

    return MediaInfo(
        path=str(p),
        sha256=sha256,
        duration_us=duration_us,
        width=width,
        height=height,
        fps=fps,
        has_audio=has_audio,
        has_video=has_video,
        codec_name=codec_name,
        size_bytes=size_bytes,
    ), warnings


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest().upper()


def _parse_rational(s: str) -> float:
    """Parse a rational like '30000/1001' or '30'."""
    try:
        if "/" in s:
            num, den = s.split("/", 1)
            d = int(den)
            return float(int(num)) / d if d else 0.0
        return float(s)
    except (ValueError, ZeroDivisionError):
        return 0.0


def _parse_duration(s: str | None) -> float | None:
    if s is None:
        return None
    try:
        return float(s)
    except ValueError:
        return None
