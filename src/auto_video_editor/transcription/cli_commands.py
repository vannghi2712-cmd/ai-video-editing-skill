"""
CLI commands for the transcription subsystem.

Implements:
  transcribe doctor  — read-only; reports dependency/readiness status
  transcribe run     — runs transcription on a local media file

Doctor exit codes:
  0 = ready (all ML deps present, CUDA absent)
  3 = optional ML dependency missing (expected in base .venv)

Run policy enforcement:
  --device cuda  → exit 2
  --diarize      → exit 2
  --language X   (not 'vi') → exit 2
  --task translate → exit 2
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


# ── Doctor ─────────────────────────────────────────────────────────────────────

def cmd_doctor(args: argparse.Namespace) -> int:
    """
    Report transcription environment readiness.

    Exit 0: ready. Exit 3: dependency missing.
    No tracebacks emitted — clean human-readable output only.
    """
    out = sys.stdout

    def _emit(line: str) -> None:
        sys.stdout.buffer.write((line + "\n").encode("utf-8", errors="replace"))

    def _row(label: str, value: str, ok: bool | None = None) -> None:
        icon = "  OK" if ok is True else ("  NG" if ok is False else "  --")
        _emit(f"{icon}  {label}: {value}")

    _emit("transcribe doctor -- environment readiness")
    _emit("-" * 48)

    # Python
    _row("Python", sys.version.split()[0], True)

    # OS
    import platform
    _row("OS", f"{platform.system()} {platform.machine()}", True)

    # FFprobe
    try:
        r = subprocess.run(
            ["ffprobe", "-version"],
            capture_output=True, timeout=5
        )
        ffprobe_ver = r.stdout.decode(errors="replace").splitlines()[0] if r.returncode == 0 else "not found"
        ffprobe_ok = r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        ffprobe_ver = "not found"
        ffprobe_ok = False
    _row("FFprobe", ffprobe_ver.split("version")[-1].strip().split()[0] if ffprobe_ok else "MISSING", ffprobe_ok)

    # Torch
    torch_ok = False
    torch_ver = "not installed"
    cuda_available = "n/a"
    cuda_ver = "n/a"
    try:
        import torch  # noqa: PLC0415
        torch_ver = torch.__version__
        cuda_available = str(torch.cuda.is_available())
        cuda_ver = str(torch.version.cuda)
        torch_ok = True
        # Policy: CUDA must NOT be available
        if torch.cuda.is_available():
            _row("PyTorch", torch_ver, False)
            _row("CUDA policy", "CUDA is available — CPU-only policy violated", False)
            return 1
    except ImportError:
        pass
    _row("PyTorch", torch_ver, torch_ok)
    _row("CUDA available", cuda_available, cuda_available == "False" if torch_ok else None)
    _row("torch.version.cuda", cuda_ver, cuda_ver in ("None", "n/a") if torch_ok else None)

    # WhisperX
    wx_ok = False
    wx_ver = "not installed"
    try:
        import whisperx  # noqa: PLC0415
        wx_ver = getattr(whisperx, "__version__", "installed (version unknown)")
        wx_ok = True
    except ImportError:
        pass
    _row("WhisperX", wx_ver, wx_ok)

    # faster-whisper
    fw_ok = False
    fw_ver = "not installed"
    try:
        import faster_whisper  # noqa: PLC0415
        fw_ver = getattr(faster_whisper, "__version__", "installed")
        fw_ok = True
    except ImportError:
        pass
    _row("faster-whisper", fw_ver, fw_ok)

    # ctranslate2
    ct2_ok = False
    ct2_ver = "not installed"
    try:
        import ctranslate2  # noqa: PLC0415
        ct2_ver = getattr(ctranslate2, "__version__", "installed")
        ct2_ok = True
    except ImportError:
        pass
    _row("CTranslate2", ct2_ver, ct2_ok)

    _emit("-" * 48)
    if torch_ok and wx_ok and fw_ok and ct2_ok and ffprobe_ok:
        _emit("Status: READY -- CPU transcription available")
        return 0
    else:
        missing = []
        if not ffprobe_ok:
            missing.append("ffprobe (install FFmpeg)")
        if not torch_ok:
            missing.append("torch (install in .venv-whisperx)")
        if not wx_ok:
            missing.append("whisperx (install in .venv-whisperx)")
        if not fw_ok:
            missing.append("faster-whisper (install in .venv-whisperx)")
        if not ct2_ok:
            missing.append("ctranslate2 (install in .venv-whisperx)")
        _emit(
            f"Status: NOT READY -- optional dependencies missing: {', '.join(missing)}"
        )
        _emit(
            "Run this command in .venv-whisperx to install: "
            "pip install -e '.[transcription]'"
        )
        return 3


# ── Run ────────────────────────────────────────────────────────────────────────

def cmd_run(args: argparse.Namespace) -> int:
    """Execute transcription on a local media file."""
    # Policy enforcement (these are exit 2 = usage error)
    if getattr(args, "device", "cpu") == "cuda":
        print(
            "Error: --device cuda is prohibited by policy. Use --device cpu.",
            file=sys.stderr,
        )
        return 2

    if getattr(args, "diarize", False):
        print(
            "Error: --diarize is prohibited by policy.",
            file=sys.stderr,
        )
        return 2

    if getattr(args, "language", "vi") != "vi":
        print(
            f"Error: language {args.language!r} is not supported. Only 'vi' is permitted.",
            file=sys.stderr,
        )
        return 2

    if getattr(args, "task", "transcribe") == "translate":
        print(
            "Error: translation task is prohibited by policy.",
            file=sys.stderr,
        )
        return 2

    # Build config
    try:
        from auto_video_editor.transcription.config import TranscriptionConfig  # noqa: PLC0415
        config = TranscriptionConfig(
            language=args.language,
            device=args.device,
            compute_type=args.compute_type,
            model=args.model,
            batch_size=args.batch_size,
            alignment_mode=args.alignment,
            diarization=False,
            force=args.force,
        )
    except ValueError as exc:
        print(f"Error: invalid configuration — {exc}", file=sys.stderr)
        return 2

    # Check for ML dependencies first (fail cleanly without traceback)
    try:
        from auto_video_editor.transcription.backends.whisperx_backend import (  # noqa: PLC0415
            _require_whisperx,
        )
        _require_whisperx()
    except Exception as exc:
        print(f"Error: ML dependencies not available — {exc}", file=sys.stderr)
        print(
            "Run 'transcribe doctor' for details. "
            "Install WhisperX in .venv-whisperx.",
            file=sys.stderr,
        )
        return 3

    # Run transcription
    try:
        from auto_video_editor.transcription.service import TranscriptionService  # noqa: PLC0415
        cache_dir = os.environ.get("TRANSCRIPTION_CACHE_DIR", ".transcription-cache")
        model_cache_dir = os.environ.get("WHISPERX_MODEL_CACHE", "model-cache")
        service = TranscriptionService(
            cache_dir=cache_dir,
            model_cache_dir=model_cache_dir,
        )
        result = service.run(
            source=args.input,
            output_dir=args.output_dir,
            config=config,
        )
    except Exception as exc:
        print(f"Error: transcription failed — {exc}", file=sys.stderr)
        return 4

    if result.get("cache_hit"):
        print(f"Cache hit — outputs restored from cache to: {result['output_dir']}")
    else:
        print(f"Transcription complete. Outputs written to: {result['output_dir']}")
        if "metrics" in result:
            m = result["metrics"]
            print(
                f"  Elapsed: {m.get('total_elapsed_seconds', '?')}s  "
                f"RTF: {m.get('realtime_factor', '?')}x  "
                f"Segments: {m.get('segment_count', '?')}  "
                f"Words: {m.get('word_count', '?')}"
            )
        print(
            f"  Alignment: {result.get('alignment_status', '?')}  "
            f"Aligned words: {result.get('words_aligned', '?')}/{result.get('words_total', '?')}"
        )
    return 0


# ── Registration ───────────────────────────────────────────────────────────────

def register_transcribe_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register 'transcribe' subcommand and its sub-subcommands."""
    tx_parser = subparsers.add_parser(
        "transcribe",
        help="Transcription commands (Phase 3 — Vietnamese, CPU-first).",
    )
    tx_sub = tx_parser.add_subparsers(dest="tx_command", metavar="command")
    tx_sub.required = True

    # doctor
    doctor_p = tx_sub.add_parser(
        "doctor",
        help="Check transcription environment readiness (read-only).",
    )
    doctor_p.set_defaults(func=cmd_doctor)

    # run
    run_p = tx_sub.add_parser(
        "run",
        help="Transcribe a local media file.",
    )
    run_p.add_argument("input", help="Path to local media file (no URLs).")
    run_p.add_argument("--output-dir", required=True, help="Directory to write outputs.")
    run_p.add_argument("--language", default="vi", choices=["vi"], help="Language (only 'vi').")
    run_p.add_argument("--model", default="base", help="Whisper model size (tiny/base/small/…).")
    run_p.add_argument("--device", default="cpu", help="Inference device (only 'cpu').")
    run_p.add_argument(
        "--compute-type", default="int8", choices=["int8", "float32", "float16"],
        dest="compute_type", help="Compute type."
    )
    run_p.add_argument(
        "--alignment", default="auto", choices=["auto", "on", "off"],
        help="Word alignment mode."
    )
    run_p.add_argument("--batch-size", type=int, default=4, dest="batch_size")
    run_p.add_argument("--force", action="store_true", help="Bypass cache.")
    # Explicitly rejected options (parse but reject at runtime)
    run_p.add_argument("--diarize", action="store_true", help=argparse.SUPPRESS)
    run_p.set_defaults(func=cmd_run)
