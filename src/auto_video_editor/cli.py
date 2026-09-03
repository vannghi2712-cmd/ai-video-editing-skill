"""CLI implementation for auto_video_editor.

Commands:
  profiles list                   — list available child profiles (4 columns, lexicographic)
  profiles show <profile_id>      — print merged profile JSON to stdout
  profiles validate               — validate ALL child profiles (no-arg default)
  profiles validate --all         — alias: validate ALL child profiles
  profiles validate <profile_id>  — validate a single profile

Exit codes:
  0  success
  2  usage error (bad arguments or mutually exclusive args)
  3  profile not found / unsafe path
  4  parse or validation failure
  5  internal error
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from auto_video_editor.exceptions import (
    AutoVideoEditorError,
    ProfileNotFoundError,
    ProfileParseError,
    ProfilePathUnsafeError,
    ProfileSchemaVersionError,
    ProfileValidationError,
)
from auto_video_editor.profiles.loader import (
    _default_profiles_dir,
    list_profiles,
    load_profile,
    load_profile_raw,
)
from auto_video_editor.profiles.validation import validate_profile, validate_profile_from_dict

# Column widths for `profiles list` output
_COL_ID = 20
_COL_NAME = 36
_COL_HANDLE = 16
_COL_DURATION = 8


def _format_list_header() -> str:
    return (
        f"{'ID':<{_COL_ID}}  {'Display Name':<{_COL_NAME}}  "
        f"{'TikTok Handle':<{_COL_HANDLE}}  {'Duration':<{_COL_DURATION}}"
    )


def _format_list_row(profile_id: str, display_name: str, account: str, duration_s: float) -> str:
    dur_str = f"{int(duration_s)}s"
    return (
        f"{profile_id:<{_COL_ID}}  {display_name:<{_COL_NAME}}  "
        f"{account:<{_COL_HANDLE}}  {dur_str:<{_COL_DURATION}}"
    )


def _cmd_profiles_list(args: argparse.Namespace) -> int:
    """List all available child profiles with 4 columns."""
    profiles_dir = Path(args.profiles_dir) if args.profiles_dir else _default_profiles_dir()
    try:
        ids = list_profiles(profiles_dir)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 5

    sys.stdout.buffer.write((_format_list_header() + "\n").encode("utf-8"))
    for pid in ids:
        try:
            profile = load_profile(pid, profiles_dir)
            row = _format_list_row(
                pid,
                profile.display_name,
                profile.account,
                profile.reference_duration_seconds,
            )
        except Exception:
            row = _format_list_row(pid, "(load error)", "", 0)
        sys.stdout.buffer.write((row + "\n").encode("utf-8"))
    return 0


def _cmd_profiles_show(args: argparse.Namespace) -> int:
    """Print merged JSON for a single profile to stdout."""
    profiles_dir = Path(args.profiles_dir) if args.profiles_dir else _default_profiles_dir()
    try:
        raw = load_profile_raw(args.profile_id, profiles_dir)
        output = json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=False)
        # Write with explicit UTF-8 encoding to handle non-ASCII on Windows
        sys.stdout.buffer.write((output + "\n").encode("utf-8"))
        return 0
    except (ProfileNotFoundError, ProfilePathUnsafeError, ProfileSchemaVersionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.exit_code
    except ProfileParseError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.exit_code
    except AutoVideoEditorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        print(f"INTERNAL ERROR: {exc}", file=sys.stderr)
        return 5


def _cmd_profiles_validate(args: argparse.Namespace) -> int:
    """Validate one or all profiles.

    Behavior:
      profiles validate              → validate ALL (no-arg default)
      profiles validate --all        → validate ALL (explicit alias)
      profiles validate <profile_id> → validate ONE profile
      profiles validate <id> --all   → exit 2 (usage error: mutually exclusive)
    """
    profiles_dir = Path(args.profiles_dir) if args.profiles_dir else _default_profiles_dir()

    # Mutual exclusion check
    if args.profile_id and args.all:
        print(
            "ERROR: profile_id and --all are mutually exclusive. "
            "Provide one or the other, or neither (to validate all).",
            file=sys.stderr,
        )
        return 2

    # Validate ALL when no profile_id given, or --all given
    if not args.profile_id or args.all:
        try:
            ids = list_profiles(profiles_dir)
        except Exception as exc:
            print(f"ERROR listing profiles: {exc}", file=sys.stderr)
            return 5

        if not ids:
            print("No child profiles found.", file=sys.stderr)
            return 0

        overall_ok = True
        for pid in ids:
            ok = _validate_one(pid, profiles_dir)
            if not ok:
                overall_ok = False
        return 0 if overall_ok else 4
    else:
        ok = _validate_one(args.profile_id, profiles_dir)
        return 0 if ok else 4


def _validate_one(profile_id: str, profiles_dir: Path) -> bool:
    """Validate a single profile. Returns True if valid, False otherwise."""
    try:
        raw = load_profile_raw(profile_id, profiles_dir)
        validate_profile_from_dict(raw, profile_id)
        profile = load_profile(profile_id, profiles_dir)
        validate_profile(profile)
        sys.stdout.buffer.write(f"OK  {profile_id}\n".encode("utf-8"))
        return True
    except (ProfileNotFoundError, ProfilePathUnsafeError) as exc:
        print(f"NOT FOUND  {profile_id}: {exc}", file=sys.stderr)
        return False
    except (ProfileParseError, ProfileValidationError, ProfileSchemaVersionError) as exc:
        print(f"FAIL  {profile_id}: {exc}", file=sys.stderr)
        return False
    except AutoVideoEditorError as exc:
        print(f"ERROR  {profile_id}: {exc}", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"INTERNAL ERROR  {profile_id}: {exc}", file=sys.stderr)
        return False


def build_parser() -> argparse.ArgumentParser:
    """Build and return the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="auto_video_editor",
        description="Automated short-form video editing pipeline.",
    )
    parser.add_argument(
        "--profiles-dir",
        dest="profiles_dir",
        default=None,
        help="Override path to profiles directory (for testing).",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- profiles ---
    profiles_parser = subparsers.add_parser("profiles", help="Manage content profiles.")
    profiles_sub = profiles_parser.add_subparsers(dest="profiles_command", required=True)

    # profiles list
    profiles_sub.add_parser("list", help="List all available child profiles (4 columns).")

    # profiles show <profile_id>
    show_parser = profiles_sub.add_parser("show", help="Show merged profile JSON.")
    show_parser.add_argument("profile_id", help="Profile ID to show.")

    # profiles validate [<profile_id>] [--all]
    # No-arg validates all; --all is an explicit alias; specific ID validates only that ID.
    validate_parser = profiles_sub.add_parser("validate", help="Validate profiles.")
    validate_parser.add_argument(
        "profile_id",
        nargs="?",
        default=None,
        help="Profile ID to validate (omit to validate all).",
    )
    validate_parser.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="Validate all child profiles (alias for no-arg behavior).",
    )

    # --- transcribe (Phase 3) — ML deps are lazy-loaded ---
    from auto_video_editor.transcription.cli_commands import register_transcribe_commands  # noqa: PLC0415
    register_transcribe_commands(subparsers)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point. Returns an exit code."""
    parser = build_parser()

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 2

    try:
        if args.command == "profiles":
            if args.profiles_command == "list":
                return _cmd_profiles_list(args)
            elif args.profiles_command == "show":
                return _cmd_profiles_show(args)
            elif args.profiles_command == "validate":
                return _cmd_profiles_validate(args)

        if args.command == "transcribe":
            # Dispatch to transcribe sub-subcommand (func set by register_transcribe_commands)
            func = getattr(args, "func", None)
            if func is not None:
                return func(args)

        print(f"ERROR: Unknown command {args.command!r}", file=sys.stderr)
        return 2

    except AutoVideoEditorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        print(f"INTERNAL ERROR: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 5
