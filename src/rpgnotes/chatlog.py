from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import re
from pathlib import Path
from typing import NamedTuple

from .helpers import prettify_json

log = logging.getLogger("rpgnotes")


class ChatLogInfo(NamedTuple):
    path: Path
    session_number: int
    session_date: _dt.date | None


def find_chat_log(source_dir: Path) -> ChatLogInfo | None:
    """The newest ``session<NN>.json`` with its session number and archive date.

    No side effects, so the menu can call it to show what it found.
    """
    chat_logs = [
        path for path in source_dir.glob("session*.json") if re.search(r"session\d+", path.name)
    ]
    if not chat_logs:
        return None
    newest_chat_log = max(chat_logs, key=os.path.getmtime)
    match = re.search(r"session(\d+)", newest_chat_log.name)
    assert match is not None

    session_date: _dt.date | None = None
    try:
        with newest_chat_log.open(encoding="utf-8") as f:
            data = json.load(f)
        date_str = data.get("archiveDate") if isinstance(data, dict) else None
        if date_str:
            session_date = _dt.datetime.strptime(date_str, "%Y-%m-%d").date()
    except (json.JSONDecodeError, ValueError) as e:
        log.warning("Could not extract date from chat log %s: %s.", newest_chat_log.name, e)
    return ChatLogInfo(newest_chat_log, int(match.group(1)), session_date)


def process_chat_log(
    source_dir: Path,
    assets_base_dir: Path,
) -> tuple[int | None, _dt.date | None]:
    """Find the newest ``session*.json``, extract number+date, copy prettified into assets."""
    info = find_chat_log(source_dir)
    if info is None:
        log.error("No session chat log (e.g., 'session53.json') found in %s.", source_dir)
        return None, None
    newest_chat_log, session_number, session_date = info

    session_assets_dir = assets_base_dir / f"{session_number:03d}"
    session_assets_dir.mkdir(parents=True, exist_ok=True)
    output_filepath = session_assets_dir / "chat_log.json"

    if output_filepath.exists():
        log.info("Chat log for session %d already exists. Skipping copy.", session_number)
        return session_number, session_date

    prettified = prettify_json(newest_chat_log)
    if prettified is None:
        return session_number, session_date

    output_filepath.write_text(prettified, encoding="utf-8")
    log.info("Prettified chat log saved to: %s", output_filepath)
    return session_number, session_date
