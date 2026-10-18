from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable

from .config import Settings, load_settings
from .logging_setup import setup_logging
from .pipeline import (
    clear_temp_work,
    run_full_workflow,
    run_transcription_workflow,
)
from .status import SessionStatus, collect_status, format_status

log = logging.getLogger("rpgnotes")

_COMMANDS = ("menu", "full", "transcribe", "status")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rpgnotes",
        description="Turn a TTRPG session bundle (audio zip + chat log) into a session package.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "commands:\n"
            "  menu        show the session found and ask what to do (default in a terminal)\n"
            "  full        transcribe + AI notes, no questions (default otherwise)\n"
            "  transcribe  transcription only, no Gemini calls\n"
            "  status      show the session found and its progress, then exit"
        ),
    )
    parser.add_argument("command", nargs="?", choices=_COMMANDS, metavar="command")
    parser.add_argument(
        "--fresh",
        "--clean-temp",
        dest="fresh",
        action="store_true",
        help="Clear temp work first: re-transcribe and re-run Gemini instead of resuming.",
    )
    parser.add_argument("--menu", action="store_true", help=argparse.SUPPRESS)
    return parser


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip().lower()
    except EOFError:
        return "q"


def _start_over(settings: Settings, status: SessionStatus) -> None:
    answer = _ask(
        f"Redo session {status.session_number} from scratch? This re-transcribes the audio "
        "and calls Gemini again (costs again). [y/N]: "
    )
    if answer not in {"y", "yes"}:
        return
    clear_temp_work(settings)
    log.info("Temp work cleared.")
    run_full_workflow(settings)


def _menu_actions(
    settings: Settings, status: SessionStatus
) -> list[tuple[str, str, Callable[[], object] | None]]:
    if status.session_number is None:
        return [("1", "Check again", lambda: None), ("q", "Quit", None)]
    number = status.session_number
    resumable = status.temp_session == number and status.temp_has_work
    process = f"{'Continue' if resumable else 'Process'} session {number}: transcribe + AI notes"
    actions: list[tuple[str, str, Callable[[], object] | None]] = [
        ("1", process, lambda: run_full_workflow(settings)),
        ("2", "Transcribe only (no Gemini cost)", lambda: run_transcription_workflow(settings)),
    ]
    if resumable or status.draft:
        actions.append(("3", "Start over: redo this session from scratch",
                        lambda: _start_over(settings, status)))
    actions.append(("q", "Quit", None))
    return actions


def _run_menu(settings: Settings) -> int:
    while True:
        status = collect_status(settings)
        print()
        print(format_status(status, settings))
        print()
        actions = _menu_actions(settings, status)
        for key, label, _action in actions:
            default = "   (Enter)" if key == actions[0][0] else ""
            print(f"  [{key}] {label}{default}")
        print()
        choice = _ask("Choose: ") or actions[0][0]
        match = next((action for action in actions if action[0] == choice), None)
        if match is None:
            print(f"Unknown choice {choice!r}.")
            continue
        _key, _label, action = match
        if action is None:
            return 0
        action()


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = load_settings()
    setup_logging(settings.log_file)
    settings.ensure_directories()

    command = args.command or ("menu" if args.menu or sys.stdin.isatty() else "full")
    if args.fresh:
        clear_temp_work(settings)
        log.info("Temp work cleared (--fresh).")

    try:
        if command == "menu":
            return _run_menu(settings)
        if command == "status":
            print(format_status(collect_status(settings), settings))
        elif command == "full":
            run_full_workflow(settings)
        elif command == "transcribe":
            run_transcription_workflow(settings)
    except KeyboardInterrupt:
        print("\nStopped. Run again to resume where it left off.")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
