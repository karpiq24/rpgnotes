from __future__ import annotations

import datetime as _dt
import logging
import os
import re
import shutil
import zipfile
from pathlib import Path

from .helpers import get_newest_file

log = logging.getLogger("rpgnotes")

_START_TIME_RE = re.compile(r"^Start time:\s*(?P<iso>\S+)", re.MULTILINE)


def extract_recording_start(*search_dirs: Path) -> int | None:
    """Unix timestamp of the Craig recording start, from `info.txt` inside the zip.

    Looks for the newest ``craig-*.flac.zip`` across `search_dirs` (pass both
    the downloads dir and the processed dir so this works before and after the
    zip has been moved). Craig's `info.txt` carries a line like
    ``Start time:\t2026-07-07T16:48:24.265Z`` — the authoritative t=0 shared
    by the transcript, the screenshots, and the chat log. Returns None (with a
    warning) on any failure; callers treat the anchor as best-effort.
    """
    candidates = [
        newest
        for directory in search_dirs
        if (newest := get_newest_file(directory, "craig-*.flac.zip")) is not None
    ]
    if not candidates:
        log.warning("No craig-*.flac.zip found in %s — recording start unknown.", search_dirs)
        return None
    newest_zip = max(candidates, key=os.path.getmtime)
    try:
        with zipfile.ZipFile(newest_zip) as zip_ref:
            info_text = zip_ref.read("info.txt").decode("utf-8", errors="replace")
    except (OSError, KeyError, zipfile.BadZipFile) as e:
        log.warning("Could not read info.txt from %s: %s", newest_zip.name, e)
        return None
    match = _START_TIME_RE.search(info_text)
    if not match:
        log.warning("No 'Start time:' line in info.txt of %s.", newest_zip.name)
        return None
    try:
        started = _dt.datetime.fromisoformat(match.group("iso").replace("Z", "+00:00"))
    except ValueError as e:
        log.warning("Unparseable recording start %r: %s", match.group("iso"), e)
        return None
    return int(started.timestamp())


def unzip_audio(
    source_dir: Path,
    audio_output_dir: Path,
    processed_dir: Path,
) -> None:
    """Unzip the newest ``craig-*.flac.zip`` from `source_dir` into `audio_output_dir`."""
    if any(audio_output_dir.glob("*.flac")):
        log.info("Audio files already exist. Skipping unzip.")
        return

    newest_zip = get_newest_file(source_dir, "craig-*.flac.zip")
    if not newest_zip:
        log.warning("No matching audio zip file (craig-*.flac.zip) found in %s.", source_dir)
        return

    try:
        with zipfile.ZipFile(newest_zip) as zip_ref:
            zip_ref.extractall(audio_output_dir)
        log.info("Extracted audio to: %s", audio_output_dir)

        for item in audio_output_dir.iterdir():
            if item.is_file() and item.suffix != ".flac":
                os.remove(item)
                log.info("Deleted non-FLAC file: %s", item.name)

        processed_dir.mkdir(parents=True, exist_ok=True)
        dest = processed_dir / newest_zip.name
        shutil.move(str(newest_zip), dest)
        log.info("Moved source zip to: %s", dest)
    except zipfile.BadZipFile:
        log.error("%s is not a valid zip file.", newest_zip.name)
