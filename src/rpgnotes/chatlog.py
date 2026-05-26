from __future__ import annotations

import datetime as _dt
import json
import logging
import re
from pathlib import Path

from .helpers import get_newest_file, prettify_json

log = logging.getLogger("rpgnotes")


def process_chat_log(
    source_dir: Path,
    assets_base_dir: Path,
) -> tuple[int | None, _dt.date | None]:
    """Find the newest ``session*.json``, extract number+date, copy prettified into assets."""
    newest_chat_log = get_newest_file(source_dir, "session*.json")
    if not newest_chat_log:
        log.error("No session chat log found (e.g., 'session53.json').")
        return None, None

    match = re.search(r"session(\d+)", newest_chat_log.name)
    if not match:
        log.error("Could not extract session number from filename: %s", newest_chat_log.name)
        return None, None

    session_number = int(match.group(1))
    session_date: _dt.date | None = None

    try:
        with newest_chat_log.open(encoding="utf-8") as f:
            data = json.load(f)
        date_str = data.get("archiveDate") if isinstance(data, dict) else None
        if date_str:
            session_date = _dt.datetime.strptime(date_str, "%Y-%m-%d").date()
    except (json.JSONDecodeError, ValueError) as e:
        log.warning("Could not extract date from chat log %s: %s.", newest_chat_log.name, e)

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
