from __future__ import annotations

import logging
import os
import shutil
import zipfile
from pathlib import Path

from .helpers import get_newest_file

log = logging.getLogger("rpgnotes")


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
