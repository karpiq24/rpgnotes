from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

from rpgnotes.manifest import (
    IMPORTED_MARKER,
    SCHEMA_VERSION,
    imported_since_last_run,
    write_manifest,
)


def test_manifest_lists_publish_and_working_files(tmp_path: Path) -> None:
    for name in ("transcript.txt", "chat_log.json", "draft0.md", "audio_source.txt"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    path = write_manifest(tmp_path, 85, dt.date(2026, 10, 12), {"summary": "pro"})
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == SCHEMA_VERSION
    assert manifest["session_number"] == 85
    assert manifest["session_date"] == "2026-10-12"
    assert manifest["files"] == {
        "transcript.txt": "publish",
        "chat_log.json": "publish",
        "draft0.md": "working",
    }
    assert manifest["complete"] is False  # no details.json / quotes.json yet


def test_manifest_is_complete_with_draft_details_and_quotes(tmp_path: Path) -> None:
    for name in ("transcript.txt", "draft0.md", "details.json", "quotes.json"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    manifest = json.loads(write_manifest(tmp_path, 85, None, {}).read_text(encoding="utf-8"))
    assert manifest["complete"] is True
    assert manifest["session_date"] is None


def test_imported_since_last_run(tmp_path: Path) -> None:
    assert imported_since_last_run(tmp_path) is None
    manifest = write_manifest(tmp_path, 85, None, {})
    marker = tmp_path / IMPORTED_MARKER
    marker.write_text("", encoding="utf-8")
    os.utime(manifest, (1000, 1000))
    os.utime(marker, (2000, 2000))
    assert imported_since_last_run(tmp_path) is True
    os.utime(manifest, (3000, 3000))  # rpgnotes ran again after the import
    assert imported_since_last_run(tmp_path) is False
