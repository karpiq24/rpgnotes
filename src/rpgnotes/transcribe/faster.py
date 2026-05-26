from __future__ import annotations

import logging
from pathlib import Path

from .base import Segment

log = logging.getLogger("rpgnotes")


class FasterWhisperTranscriber:
    """faster-whisper backend.

    On AMD GPUs use the CTranslate2 v4.7.1+ ROCm wheels; ``device="cuda"`` is the
    correct value even on ROCm (CT2 keeps the name).
    """

    def __init__(
        self,
        model_size: str,
        device: str,
        compute_type: str,
        download_root: Path,
        initial_prompt: str,
        language: str = "pl",
        vad_filter: bool = True,
    ) -> None:
        from faster_whisper import WhisperModel

        log.info(
            "Loading faster-whisper model '%s' on %s (compute_type=%s)…",
            model_size,
            device,
            compute_type,
        )
        self._model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            download_root=str(download_root),
        )
        self.initial_prompt = initial_prompt
        self.language = language
        self.vad_filter = vad_filter

    def transcribe(self, audio_path: Path) -> list[Segment]:
        segments_iter, _info = self._model.transcribe(
            str(audio_path),
            language=self.language,
            initial_prompt=self.initial_prompt,
            condition_on_previous_text=False,
            temperature=[0.0, 0.2],
            log_prob_threshold=-1.0,
            no_speech_threshold=0.6,
            compression_ratio_threshold=2.4,
            vad_filter=self.vad_filter,
            word_timestamps=False,
        )
        out: list[Segment] = []
        for s in segments_iter:
            seg: Segment = {
                "start": float(s.start),
                "end": float(s.end),
                "text": str(s.text),
            }
            avg_logprob = getattr(s, "avg_logprob", None)
            if avg_logprob is not None:
                seg["avg_logprob"] = float(avg_logprob)
            no_speech_prob = getattr(s, "no_speech_prob", None)
            if no_speech_prob is not None:
                seg["no_speech_prob"] = float(no_speech_prob)
            out.append(seg)
        return out
