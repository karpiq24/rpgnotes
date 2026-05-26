from __future__ import annotations

import datetime as _dt
import logging
import re
from pathlib import Path
from string import Template

from .summarize.models import QuotesData, SessionData

log = logging.getLogger("rpgnotes")

_INVALID_FILENAME_CHARS = re.compile(r'[\\/*?:"<>|]')


def render_session_note(
    template_file: Path,
    session_summary: str,
    session_data: SessionData,
    quotes_data: QuotesData,
    session_number: int,
    session_date: _dt.date,
) -> str:
    raw_template = template_file.read_text(encoding="utf-8")
    template = Template(raw_template)
    return template.safe_substitute(
        number=session_number,
        padded_number=f"{session_number:03d}",
        title=session_data.title,
        date=session_date.strftime("%d.%m.%Y"),
        summary=session_summary,
        events="\n".join(f"* {event}" for event in session_data.events),
        npcs="\n".join(f"* {npc}" for npc in session_data.npcs),
        locations="\n".join(f"* {loc}" for loc in session_data.locations),
        items="\n".join(f"* {item}" for item in session_data.items),
        quotes="\n".join(f"* {quote}" for quote in quotes_data.quotes),
    )


def save_summary_file(
    template_file: Path,
    sessions_recap_dir: Path,
    session_summary: str,
    session_data: SessionData,
    quotes_data: QuotesData,
    session_number: int,
    session_date: _dt.date,
) -> Path:
    output = render_session_note(
        template_file,
        session_summary,
        session_data,
        quotes_data,
        session_number,
        session_date,
    )
    sane_title = _INVALID_FILENAME_CHARS.sub("", session_data.title)
    output_file = sessions_recap_dir / f"Sesja {session_number} - {sane_title}.md"
    sessions_recap_dir.mkdir(parents=True, exist_ok=True)
    output_file.write_text(output, encoding="utf-8")
    log.info("Session notes saved to %s", output_file)
    return output_file
