"""CPU-only keyframe extraction via FFmpeg for Phase 4.

Target slots per scene: 20%, 50%, 80% of scene duration.
Output: JPEG files, max 1280×1280, stored in output_dir/keyframes/.
Files are runtime artifacts — NEVER committed to git.

No hard-coded profile-ID branches.
No shell=True.
No GPU/CUDA flags.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from auto_video_editor.analysis.models import Keyframe, Scene


_FFMPEG_TIMEOUT_S = 60
_SLOT_FRACTIONS = (0.20, 0.50, 0.80)
_MAX_DIM = 1280


def extract_keyframes(
    source_path: str,
    scenes: list[Scene],
    output_dir: str | os.PathLike,
    slots: int = 3,
) -> tuple[list[Keyframe], list[str]]:
    """Extract keyframes for all scenes.

    Parameters
    ----------
    source_path : path to source video
    scenes      : normalized scene list
    output_dir  : directory where keyframes/ sub-folder is created
    slots       : number of slots per scene (1..3)

    Returns (keyframes, warnings).
    """
    kf_dir = Path(output_dir) / "keyframes"
    kf_dir.mkdir(parents=True, exist_ok=True)

    keyframes: list[Keyframe] = []
    warnings: list[str] = []
    fractions = _SLOT_FRACTIONS[:slots]

    for scene in scenes:
        for slot_idx, frac in enumerate(fractions):
            ts_us = scene.start_us + int(scene.duration_us * frac)
            ts_s = ts_us / 1_000_000
            out_path = kf_dir / f"scene_{scene.index:04d}_slot_{slot_idx}.jpg"

            ok, sha, warn = _extract_one(source_path, ts_s, out_path)
            if warn:
                warnings.append(warn)
            keyframes.append(
                Keyframe(
                    scene_index=scene.index,
                    slot=slot_idx,
                    timestamp_us=ts_us,
                    path=str(out_path),
                    sha256=sha,
                    status="ok" if ok else "failed",
                )
            )

    return keyframes, warnings


def _extract_one(
    source_path: str,
    timestamp_s: float,
    out_path: Path,
) -> tuple[bool, str | None, str | None]:
    """Extract a single JPEG frame.

    Returns (success, sha256_or_None, warning_or_None).
    """
    # Scale filter: fit within 1280×1280, preserve aspect ratio
    scale_filter = (
        f"scale='min(iw,{_MAX_DIM})':'min(ih,{_MAX_DIM})'"
        ":force_original_aspect_ratio=decrease"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-ss", f"{timestamp_s:.6f}",
        "-i", source_path,
        "-frames:v", "1",
        "-vf", scale_filter,
        "-q:v", "2",          # JPEG quality (lower = better)
        str(out_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=_FFMPEG_TIMEOUT_S,
        )
    except FileNotFoundError:
        return False, None, "ffmpeg not found on PATH"
    except subprocess.TimeoutExpired:
        return False, None, f"ffmpeg keyframe extraction timed out at {timestamp_s:.3f}s"

    if result.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        warn = f"Keyframe extraction failed at {timestamp_s:.3f}s: {stderr[:200]}"
        return False, None, warn

    sha = _sha256_file(out_path)
    return True, sha, None


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(1 << 16):
            h.update(chunk)
    return h.hexdigest().upper()
