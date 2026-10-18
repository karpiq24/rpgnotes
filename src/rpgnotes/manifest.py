"""`manifest.json`: what a session folder in the outbox holds, for the wiki to import.

The wiki reads only the manifest and the files it lists. `publish` files belong
on the public site next to the session note; `working` files feed the import
(the draft and its details, open validation findings) and stay private.
Anything else in the folder is rpgnotes' own bookkeeping.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from pathlib import Path

from . import __version__

log = logging.getLogger("rpgnotes")

SCHEMA_VERSION = 1
MANIFEST_FILE = "manifest.json"
# Written by the wiki's import into the session folder; rpgnotes only reads it.
IMPORTED_MARKER = ".imported"

PUBLISH_FILES = (
    "transcript.txt",
    "transcript.json",
    "transcript_enriched.txt",
    "chat_log.json",
    "chat_events.json",
    "chat_events.txt",
    "visual_log.json",
    "quotes.json",
)
WORKING_FILES = (
    "draft0.md",
    "details.json",
    "validation_report.json",
)
# What the import needs to assemble a session note.
REQUIRED_FILES = ("draft0.md", "details.json", "quotes.json", "transcript.txt")


def write_manifest(
    session_dir: Path,
    session_number: int,
    session_date: _dt.date | None,
    models: dict[str, str],
) -> Path:
    """(Re)write the manifest for whatever the session folder holds right now."""
    files = {
        **{name: "publish" for name in PUBLISH_FILES if (session_dir / name).is_file()},
        **{name: "working" for name in WORKING_FILES if (session_dir / name).is_file()},
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "session_number": session_number,
        "session_date": session_date.isoformat() if session_date else None,
        # datetime.UTC needs 3.11; the package still supports 3.10.
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),  # noqa: UP017
        "rpgnotes_version": __version__,
        "models": models,
        "complete": all(name in files for name in REQUIRED_FILES),
        "files": files,
    }
    path = session_dir / MANIFEST_FILE
    session_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log.info("Manifest saved to %s (%s).", path, "complete" if manifest["complete"] else "incomplete")
    return path


def imported_since_last_run(session_dir: Path) -> bool | None:
    """True when the wiki imported the current manifest, False when it is newer, None if never."""
    marker = session_dir / IMPORTED_MARKER
    manifest = session_dir / MANIFEST_FILE
    if not marker.is_file():
        return None
    if not manifest.is_file():
        return True
    return marker.stat().st_mtime >= manifest.stat().st_mtime
