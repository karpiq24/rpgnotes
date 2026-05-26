from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from rpgnotes.chatlog import process_chat_log


def _write_chat_log(path: Path, *, archive_date: str | None = "2026-05-20") -> None:
    payload: dict[str, object] = {"messages": []}
    if archive_date is not None:
        payload["archiveDate"] = archive_date
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_extracts_number_and_date(tmp_path: Path) -> None:
    downloads = tmp_path / "downloads"
    assets = tmp_path / "assets"
    downloads.mkdir()
    _write_chat_log(downloads / "session53.json")

    number, date = process_chat_log(downloads, assets)
    assert number == 53
    assert date == _dt.date(2026, 5, 20)
    assert (assets / "053" / "chat_log.json").exists()


def test_returns_none_when_no_chat_log(tmp_path: Path) -> None:
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    assert process_chat_log(downloads, tmp_path / "assets") == (None, None)


def test_handles_missing_archive_date(tmp_path: Path) -> None:
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    _write_chat_log(downloads / "session7.json", archive_date=None)
    number, date = process_chat_log(downloads, tmp_path / "assets")
    assert number == 7
    assert date is None


def test_skips_when_chat_log_already_copied(tmp_path: Path) -> None:
    downloads = tmp_path / "downloads"
    assets = tmp_path / "assets"
    downloads.mkdir()
    _write_chat_log(downloads / "session99.json")

    # First call copies it.
    process_chat_log(downloads, assets)
    target = assets / "099" / "chat_log.json"
    target.write_text("PREEXISTING", encoding="utf-8")

    # Second call should NOT overwrite, returning the same number+date.
    number, date = process_chat_log(downloads, assets)
    assert number == 99
    assert date == _dt.date(2026, 5, 20)
    assert target.read_text(encoding="utf-8") == "PREEXISTING"


def test_picks_newest_when_multiple_logs(tmp_path: Path) -> None:
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    _write_chat_log(downloads / "session10.json", archive_date="2026-01-01")
    # Newer file:
    newer = downloads / "session11.json"
    _write_chat_log(newer, archive_date="2026-05-01")
    import os
    # Ensure mtime ordering is unambiguous.
    os.utime(downloads / "session10.json", (1, 1))
    os.utime(newer, (10**9, 10**9))

    number, date = process_chat_log(downloads, tmp_path / "assets")
    assert number == 11
    assert date == _dt.date(2026, 5, 1)
