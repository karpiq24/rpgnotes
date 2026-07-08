from __future__ import annotations

import zipfile
from pathlib import Path

from rpgnotes.audio import extract_recording_start

_INFO_TXT = """Recording SVtMYbqpKCA9

Guild:\t\tSome Guild (123)
Channel:\tGłówny (456)
Requester:\tkarpiq24#0 (789)
Start time:\t2026-07-07T16:48:24.265Z

Tracks:
\tkentos9#0 (1)
"""


def _make_craig_zip(directory: Path, info: str | None = _INFO_TXT) -> Path:
    zip_path = directory / "craig-abc123.flac.zip"
    with zipfile.ZipFile(zip_path, "w") as zip_ref:
        zip_ref.writestr("1-speaker.flac", b"fake")
        if info is not None:
            zip_ref.writestr("info.txt", info)
    return zip_path


def test_extract_recording_start_parses_start_time(tmp_path: Path) -> None:
    _make_craig_zip(tmp_path)

    assert extract_recording_start(tmp_path) == 1783442904


def test_extract_recording_start_searches_multiple_dirs(tmp_path: Path) -> None:
    downloads = tmp_path / "downloads"
    processed = tmp_path / "processed"
    downloads.mkdir()
    processed.mkdir()
    _make_craig_zip(processed)

    assert extract_recording_start(downloads, processed) == 1783442904


def test_extract_recording_start_missing_zip_or_info(tmp_path: Path) -> None:
    assert extract_recording_start(tmp_path) is None

    _make_craig_zip(tmp_path, info=None)
    assert extract_recording_start(tmp_path) is None
