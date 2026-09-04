"""CLI commands for Phase 4 scene analysis.

Registers `analyze scenes` subcommand on the main CLI parser.
Exit codes: 0=success, 2=syntax, 3=profile, 4=media, 5=schema, 6=consent, 7=partial, 8=backend
"""
from __future__ import annotations

import argparse
import sys


def register_analyze_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register the `analyze` command group."""
    analyze_parser = subparsers.add_parser(
        "analyze", help="Scene detection and vision scoring (Phase 4)."
    )
    analyze_sub = analyze_parser.add_subparsers(dest="analyze_command", required=True)

    # --- analyze scenes ---
    scenes_parser = analyze_sub.add_parser(
        "scenes",
        help="Detect scenes, extract keyframes, and score with a vision backend.",
    )
    scenes_parser.add_argument(
        "--input", required=True, dest="input", help="Path to source video file."
    )
    scenes_parser.add_argument(
        "--profile", required=True, dest="profile", help="Content profile ID."
    )
    scenes_parser.add_argument(
        "--output-dir", required=True, dest="output_dir", help="Directory for outputs."
    )
    scenes_parser.add_argument(
        "--provider",
        choices=["mock", "openai"],
        default="mock",
        dest="provider",
        help="Vision backend provider (default: mock).",
    )
    scenes_parser.add_argument(
        "--vision-model",
        default=None,
        dest="vision_model",
        help="Vision model ID (required for openai provider).",
    )
    scenes_parser.add_argument(
        "--transcript",
        default=None,
        dest="transcript",
        help="Optional path to Phase 3 transcript.json for scene association.",
    )
    scenes_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        dest="dry_run",
        help="Plan only — no network calls, no outputs written.",
    )
    scenes_parser.add_argument(
        "--resume",
        action="store_true",
        default=False,
        dest="resume",
        help="Restore from cache if available.",
    )
    scenes_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        dest="force",
        help="Overwrite existing outputs and bypass cache.",
    )
    scenes_parser.add_argument(
        "--allow-external-upload",
        action="store_true",
        default=False,
        dest="allow_external_upload",
        help="Consent: allow keyframes to be sent to external vision API.",
    )
    scenes_parser.add_argument(
        "--include-transcript-context",
        action="store_true",
        default=False,
        dest="include_transcript_context",
        help="Consent: include transcript text as context in vision API calls.",
    )
    scenes_parser.add_argument(
        "--allow-paid-recompute",
        action="store_true",
        default=False,
        dest="allow_paid_recompute",
        help="Allow paid API recomputation even if a cached result exists.",
    )
    scenes_parser.add_argument(
        "--threshold",
        type=float,
        default=0.30,
        dest="threshold",
        help="Scene change detection threshold [0.0, 1.0] (default: 0.30).",
    )
    scenes_parser.add_argument(
        "--min-duration",
        type=float,
        default=1.0,
        dest="min_duration",
        help="Minimum scene duration in seconds (default: 1.0).",
    )
    scenes_parser.add_argument(
        "--max-duration",
        type=float,
        default=15.0,
        dest="max_duration",
        help="Maximum scene duration in seconds (default: 15.0).",
    )
    scenes_parser.add_argument(
        "--cache-dir",
        default=".scene-analysis-cache",
        dest="cache_dir",
        help="Cache directory (default: .scene-analysis-cache).",
    )
    scenes_parser.set_defaults(func=_cmd_analyze_scenes)


def _cmd_analyze_scenes(args: argparse.Namespace) -> int:
    """Execute `analyze scenes` command."""
    # Validate provider-specific requirements
    if args.provider == "openai" and not args.vision_model:
        print(
            "ERROR: --vision-model is required when --provider openai is selected.",
            file=sys.stderr,
        )
        return 2

    try:
        from auto_video_editor.analysis.config import (  # noqa: PLC0415
            AnalysisConfig,
            SceneDetectorConfig,
        )
        from auto_video_editor.analysis.service import AnalysisService  # noqa: PLC0415
    except ImportError as exc:
        print(f"ERROR: Phase 4 dependencies not available: {exc}", file=sys.stderr)
        return 8

    try:
        detector_config = SceneDetectorConfig(
            threshold=args.threshold,
            min_duration_seconds=args.min_duration,
            max_duration_seconds=args.max_duration,
        )
    except ValueError as exc:
        print(f"ERROR: Invalid detector config: {exc}", file=sys.stderr)
        return 2

    config = AnalysisConfig(
        input_path=args.input,
        profile_id=args.profile,
        output_dir=args.output_dir,
        provider=args.provider,
        vision_model=args.vision_model,
        dry_run=args.dry_run,
        resume=args.resume,
        force=args.force,
        allow_external_upload=args.allow_external_upload,
        include_transcript_context=args.include_transcript_context,
        allow_paid_recompute=args.allow_paid_recompute,
        transcript_path=getattr(args, "transcript", None),
        detector=detector_config,
        cache_dir=args.cache_dir,
    )

    service = AnalysisService()
    exit_code, message = service.run(config)
    if exit_code != 0:
        print(f"{'ERROR' if exit_code >= 3 else 'INFO'}: {message}", file=sys.stderr)
    return exit_code
