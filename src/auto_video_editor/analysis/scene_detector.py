"""FFmpeg-based scene detection and normalization for Phase 4.

Algorithm (all times in microseconds):
  1. Run FFmpeg with `scdet` filter to extract raw cut timestamps.
  2. Treat 0 and source_duration as mandatory boundaries.
  3. Sort + dedup within 1μs.
  4. Build half-open intervals [start_us, end_us).
  5. Merge scenes < min_duration_us with the lower-scored neighbor.
  6. Split scenes > max_duration_us into equal integer sub-intervals.
  7. Validate: no gaps, no overlaps, full coverage [0, duration_us).

No hard-coded profile-ID branches.
No shell=True.
"""
from __future__ import annotations

import re
import subprocess
from typing import NamedTuple

from auto_video_editor.analysis.config import SceneDetectorConfig
from auto_video_editor.analysis.models import Scene


_FFMPEG_TIMEOUT_S = 300
_DEDUP_THRESHOLD_US = 1  # 1 microsecond


class _RawCut(NamedTuple):
    timestamp_us: int
    score: float


def detect_scenes(
    source_path: str,
    duration_us: int,
    config: SceneDetectorConfig,
) -> tuple[list[Scene], list[str]]:
    """Detect and normalize scenes in *source_path*.

    Returns (scenes, warnings).
    Raises RuntimeError on FFmpeg failure.
    """
    warnings: list[str] = []
    raw_cuts = _run_scdet(source_path, config.threshold, warnings)
    scenes = _normalize(raw_cuts, duration_us, config)
    _validate(scenes, duration_us)
    return scenes, warnings


# ── FFmpeg invocation ─────────────────────────────────────────────────────────

def _run_scdet(source_path: str, threshold: float, warnings: list[str]) -> list[_RawCut]:
    """Run FFmpeg scdet filter and return raw cuts (timestamp_us, score)."""
    cmd = [
        "ffmpeg",
        "-i", source_path,
        "-vf", f"scdet=threshold={threshold:.4f}:sc_pass=0",
        "-an",
        "-f", "null",
        "-",
    ]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=_FFMPEG_TIMEOUT_S,
        )
    except FileNotFoundError:
        raise RuntimeError("ffmpeg not found on PATH")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"ffmpeg scene detection timed out after {_FFMPEG_TIMEOUT_S}s")

    # scdet outputs to stderr
    stderr = result.stderr.decode("utf-8", errors="replace")
    cuts = _parse_scdet_output(stderr)
    return cuts


def _parse_scdet_output(stderr: str) -> list[_RawCut]:
    """Parse scdet filter log lines.

    scdet log format (FFmpeg 5+):
      [scdet @ 0x...] lavfi.scd.score: 0.52, lavfi.scd.time: 1.234
    or newer compact:
      [Parsed_scdet_0 @ ...] scene_score: 0.34 pts_time: 2.567
    """
    cuts: list[_RawCut] = []

    # Pattern 1: lavfi.scd.time
    for m in re.finditer(
        r"lavfi\.scd\.score:\s*([\d.]+).*?lavfi\.scd\.time:\s*([\d.]+)",
        stderr,
        re.DOTALL,
    ):
        score = float(m.group(1))
        t_us = int(round(float(m.group(2)) * 1_000_000))
        cuts.append(_RawCut(t_us, score))

    # Pattern 2: scene_score / pts_time
    if not cuts:
        for m in re.finditer(
            r"scene_score:\s*([\d.]+)\s+pts_time:\s*([\d.]+)",
            stderr,
        ):
            score = float(m.group(1))
            t_us = int(round(float(m.group(2)) * 1_000_000))
            cuts.append(_RawCut(t_us, score))

    # Pattern 3: showinfo-style pts_time (older ffmpeg)
    if not cuts:
        for m in re.finditer(
            r"pts_time:([\d.]+).*?Parsed_scdet.*?score=([\d.]+)",
            stderr,
        ):
            t_us = int(round(float(m.group(1)) * 1_000_000))
            score = float(m.group(2))
            cuts.append(_RawCut(t_us, score))

    return cuts


# ── Normalization ─────────────────────────────────────────────────────────────

def _normalize(
    raw_cuts: list[_RawCut],
    duration_us: int,
    config: SceneDetectorConfig,
) -> list[Scene]:
    """Build normalized non-overlapping scenes covering [0, duration_us)."""
    min_us = int(config.min_duration_seconds * 1_000_000)
    max_us = int(config.max_duration_seconds * 1_000_000)

    # Build sorted unique boundary set (in μs)
    boundaries_us: list[int] = [0, duration_us]
    score_map: dict[int, float] = {}
    for cut in raw_cuts:
        t = cut.timestamp_us
        if 0 < t < duration_us:
            boundaries_us.append(t)
            score_map[t] = cut.score

    # Sort and dedup within _DEDUP_THRESHOLD_US
    boundaries_us.sort()
    deduped: list[int] = [boundaries_us[0]]
    for b in boundaries_us[1:]:
        if b - deduped[-1] > _DEDUP_THRESHOLD_US:
            deduped.append(b)
    boundaries_us = deduped

    # Build initial scenes
    scenes = _build_scenes(boundaries_us, score_map)

    # Merge too-short scenes
    scenes = _merge_short(scenes, min_us)

    # Split too-long scenes
    scenes = _split_long(scenes, max_us)

    # Re-index
    scenes = [Scene(i, s.start_us, s.end_us, s.raw_score) for i, s in enumerate(scenes)]
    return scenes


def _build_scenes(boundaries: list[int], score_map: dict[int, float]) -> list[Scene]:
    scenes = []
    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i + 1]
        # The raw_score of a scene is the scdet score at its START cut
        raw_score = score_map.get(start)
        scenes.append(Scene(i, start, end, raw_score))
    return scenes


def _merge_short(scenes: list[Scene], min_us: int) -> list[Scene]:
    """Iteratively merge scenes shorter than min_us with lower-scored neighbor."""
    if not scenes:
        return scenes
    changed = True
    while changed and len(scenes) > 1:
        changed = False
        for i, s in enumerate(scenes):
            if s.duration_us < min_us:
                # Prefer merging with the neighbor that has the lower raw_score
                # (keep the more distinct scene, drop the less distinct boundary)
                if i == 0:
                    # Merge with next
                    merged = _merge_pair(scenes[0], scenes[1])
                    scenes = [merged] + scenes[2:]
                elif i == len(scenes) - 1:
                    # Merge with prev
                    merged = _merge_pair(scenes[-2], scenes[-1])
                    scenes = scenes[:-2] + [merged]
                else:
                    prev_score = scenes[i - 1].raw_score or 0.0
                    next_score = scenes[i + 1].raw_score or 0.0
                    if prev_score <= next_score:
                        merged = _merge_pair(scenes[i - 1], scenes[i])
                        scenes = scenes[: i - 1] + [merged] + scenes[i + 1:]
                    else:
                        merged = _merge_pair(scenes[i], scenes[i + 1])
                        scenes = scenes[:i] + [merged] + scenes[i + 2:]
                changed = True
                break
    return scenes


def _split_long(scenes: list[Scene], max_us: int) -> list[Scene]:
    """Split scenes longer than max_us into equal integer sub-intervals."""
    result = []
    for s in scenes:
        if s.duration_us > max_us:
            n_parts = (s.duration_us + max_us - 1) // max_us  # ceil division
            part_dur = s.duration_us // n_parts
            start = s.start_us
            for k in range(n_parts):
                end = start + part_dur if k < n_parts - 1 else s.end_us
                result.append(Scene(0, start, end, None))
                start = end
        else:
            result.append(s)
    return result


def _merge_pair(a: Scene, b: Scene) -> Scene:
    """Merge two adjacent scenes; keep the higher raw_score."""
    score = None
    if a.raw_score is not None and b.raw_score is not None:
        score = max(a.raw_score, b.raw_score)
    elif a.raw_score is not None:
        score = a.raw_score
    elif b.raw_score is not None:
        score = b.raw_score
    return Scene(0, a.start_us, b.end_us, score)


# ── Validation ────────────────────────────────────────────────────────────────

def _validate(scenes: list[Scene], duration_us: int) -> None:
    if not scenes:
        raise RuntimeError("Scene normalization produced 0 scenes")
    if scenes[0].start_us != 0:
        raise RuntimeError(f"First scene does not start at 0: {scenes[0].start_us}")
    if scenes[-1].end_us != duration_us:
        raise RuntimeError(
            f"Last scene end {scenes[-1].end_us} != duration {duration_us}"
        )
    for i in range(1, len(scenes)):
        if scenes[i].start_us != scenes[i - 1].end_us:
            raise RuntimeError(
                f"Gap/overlap between scene {i-1} and {i}: "
                f"{scenes[i-1].end_us} vs {scenes[i].start_us}"
            )
