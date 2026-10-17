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


def read_recording_start(zip_path: Path) -> int | None:
    """Unix timestamp of the Craig recording start, from `info.txt` inside the zip.

    Craig's `info.txt` carries a line like ``Start time:\t2026-07-07T16:48:24.265Z``
    — the authoritative t=0 shared by the transcript, the screenshots, and the
    chat log. Returns None (with a warning) on any failure; callers treat the
    anchor as best-effort.
    """
    try:
        with zipfile.ZipFile(zip_path) as zip_ref:
            info_text = zip_ref.read("info.txt").decode("utf-8", errors="replace")
    except (OSError, KeyError, zipfile.BadZipFile) as e:
        log.warning("Could not read info.txt from %s: %s", zip_path.name, e)
        return None
    match = _START_TIME_RE.search(info_text)
    if not match:
        log.warning("No 'Start time:' line in info.txt of %s.", zip_path.name)
        return None
    try:
        started = _dt.datetime.fromisoformat(match.group("iso").replace("Z", "+00:00"))
    except ValueError as e:
        log.warning("Unparseable recording start %r: %s", match.group("iso"), e)
        return None
    return int(started.timestamp())


def extract_recording_start(*search_dirs: Path) -> int | None:
    """`read_recording_start` of the newest ``craig-*.flac.zip`` across `search_dirs`."""
    candidates = [
        newest
        for directory in search_dirs
        if (newest := get_newest_file(directory, "craig-*.flac.zip")) is not None
    ]
    if not candidates:
        log.warning("No craig-*.flac.zip found in %s — recording start unknown.", search_dirs)
        return None
    return read_recording_start(max(candidates, key=os.path.getmtime))


def find_audio_zip(source_dir: Path, processed_dir: Path, reuse: str | None = None) -> Path | None:
    """The zip `unzip_audio` would use: the newest ``craig-*.flac.zip`` in `source_dir`,
    else the already processed zip named `reuse`.

    Only a zip known to belong to the session is reused, so a missing download
    never silently brings back the previous session's audio.
    """
    newest = get_newest_file(source_dir, "craig-*.flac.zip")
    if newest is not None:
        return newest
    if reuse and (processed_dir / reuse).is_file():
        return processed_dir / reuse
    return None


def unzip_audio(
    source_dir: Path,
    audio_output_dir: Path,
    processed_dir: Path,
    *,
    reuse: str | None = None,
) -> Path | None:
    """Unzip the session's Craig zip (see `find_audio_zip`) into `audio_output_dir`.

    A zip taken from `source_dir` is moved to `processed_dir` afterwards.
    Returns the zip's final path, or None when nothing was extracted.
    """
    if any(audio_output_dir.glob("*.flac")):
        log.info("Audio files already exist. Skipping unzip.")
        return None

    zip_path = find_audio_zip(source_dir, processed_dir, reuse)
    if not zip_path:
        log.warning("No matching audio zip file (craig-*.flac.zip) found in %s.", source_dir)
        return None

    try:
        with zipfile.ZipFile(zip_path) as zip_ref:
            zip_ref.extractall(audio_output_dir)
    except zipfile.BadZipFile:
        log.error("%s is not a valid zip file.", zip_path.name)
        return None
    log.info("Extracted audio from %s to: %s", zip_path.name, audio_output_dir)

    for item in audio_output_dir.iterdir():
        if item.is_file() and item.suffix != ".flac":
            os.remove(item)
            log.info("Deleted non-FLAC file: %s", item.name)

    if zip_path.parent != processed_dir:
        processed_dir.mkdir(parents=True, exist_ok=True)
        dest = processed_dir / zip_path.name
        shutil.move(str(zip_path), dest)
        log.info("Moved source zip to: %s", dest)
        zip_path = dest
    return zip_path
