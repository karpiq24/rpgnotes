from __future__ import annotations

from pathlib import Path
from typing import Protocol, TypedDict


class Segment(TypedDict, total=False):
    start: float
    end: float
    text: str
    avg_logprob: float
    no_speech_prob: float


class TranscriberProtocol(Protocol):
    """Minimal contract any Whisper backend must implement."""

    def transcribe(self, audio_path: Path) -> list[Segment]: ...
