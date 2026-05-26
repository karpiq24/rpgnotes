from __future__ import annotations

import argparse
import logging
import sys

from .config import load_settings
from .logging_setup import setup_logging
from .pipeline import (
    handle_temp_directory,
    run_full_workflow,
    run_manual_workflow,
    run_transcription_workflow,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rpgnotes",
        description="Turn a TTRPG session bundle (audio zip + chat log) into Markdown notes.",
    )
    parser.add_argument(
        "--menu",
        action="store_true",
        help="Show the legacy interactive menu instead of running directly.",
    )
    parser.add_argument(
        "--clean-temp",
        action="store_true",
        help="Wipe the temp directory before running.",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("full", help="(default) Transcribe and generate AI notes for the newest session.")
    sub.add_parser("transcribe", help="Run only chat-log + audio + transcription.")
    sub.add_parser("manual", help="Generate notes from manually pasted summary/details/quotes.")
    return parser


def _interactive_menu() -> str:
    print("\n" + "=" * 50)
    print("🚀 D&D Session Processing Workflow 🚀")
    print("=" * 50)
    print("  [1] Full Workflow (Transcribe + AI Notes)")
    print("  [2] Transcription only")
    print("  [3] Manual note entry")
    print("  [4] Exit")
    print("=" * 50)
    while True:
        choice = input("Enter your choice [1-4]: ").strip()
        if choice in {"1", "2", "3", "4"}:
            return choice
        print("❌ Invalid choice.")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = load_settings()
    setup_logging(settings.log_file)
    settings.ensure_directories()

    log = logging.getLogger("rpgnotes")

    if args.clean_temp:
        handle_temp_directory(settings, interactive=True)
    else:
        handle_temp_directory(settings, interactive=sys.stdin.isatty() and args.menu)

    if args.menu:
        while True:
            choice = _interactive_menu()
            if choice == "1":
                run_full_workflow(settings)
            elif choice == "2":
                run_transcription_workflow(settings)
            elif choice == "3":
                run_manual_workflow(settings)
            elif choice == "4":
                log.info("👋 Goodbye!")
                return 0

    command = args.command or "full"
    if command == "full":
        run_full_workflow(settings)
    elif command == "transcribe":
        run_transcription_workflow(settings)
    elif command == "manual":
        run_manual_workflow(settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
