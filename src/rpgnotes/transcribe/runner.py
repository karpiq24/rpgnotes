from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from pathlib import Path

from tqdm import tqdm

from .base import TranscriberProtocol

log = logging.getLogger("rpgnotes")


def _list_files_to_transcribe(audio_dir: Path, transcriptions_dir: Path) -> list[Path]:
    """Sort flac files by size (ascending) and skip ones that already have a JSON sidecar."""
    audio_files = sorted(audio_dir.glob("*.flac"), key=os.path.getsize)
    return [f for f in audio_files if not (transcriptions_dir / f"{f.stem}.json").exists()]


def transcribe_audio_dir(
    audio_dir: Path,
    transcriptions_dir: Path,
    transcriber_factory: Callable[[], TranscriberProtocol],
) -> bool:
    """Transcribe every FLAC in `audio_dir`, dumping JSON segments to `transcriptions_dir`.

    `transcriber_factory` is a zero-arg callable returning a `TranscriberProtocol`.
    Constructed lazily so the model isn't loaded when nothing needs transcribing.
    """
    transcriptions_dir.mkdir(parents=True, exist_ok=True)
    files_to_transcribe = _list_files_to_transcribe(audio_dir, transcriptions_dir)
    if not files_to_transcribe:
        log.info("All audio files already transcribed. Skipping.")
        return True

    try:
        transcriber: TranscriberProtocol = transcriber_factory()
    except Exception as e:
        log.error("Error loading Whisper model: %s", e)
        log.error(
            "Ensure CTranslate2 ROCm wheel is installed and /dev/kfd + /dev/dri are accessible."
        )
        return False

    for audio_file in tqdm(files_to_transcribe, desc="Transcribing Audio"):
        json_output_path = transcriptions_dir / f"{audio_file.stem}.json"
        log.info("Transcribing %s…", audio_file.name)
        try:
            segments = transcriber.transcribe(audio_file)
        except Exception as e:
            log.error("CRITICAL ERROR transcribing '%s': %s", audio_file.name, e)
            return False
        json_output_path.write_text(
            json.dumps(segments, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log.info("Transcription of '%s' saved.", audio_file.name)

    return True
