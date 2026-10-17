from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from .base import Segment
from .hotwords import pack_hotwords

log = logging.getLogger("rpgnotes")

SAMPLING_RATE = 16000
# Speech regions are grouped into clips of at most one Whisper window. Each
# clip is decoded on the ORIGINAL timeline (real pauses kept, exact
# timestamps) instead of faster-whisper's `vad_filter`, which concatenates all
# speech into one stream: on a quiet player's Discord track that glues
# utterances minutes apart into one window, which loses speech and smears
# segment timestamps across the removed silence.
CLIP_MAX_SECS = 30.0
CLIP_MAX_GAP_SECS = 3.0
# A segment is split wherever two consecutive words are further apart than
# this, so speaker turns interleave at the right moments in the transcript.
PAUSE_SPLIT_SECS = 1.5


def group_speech_clips(
    speech: Sequence[tuple[float, float]],
    max_span: float = CLIP_MAX_SECS,
    max_gap: float = CLIP_MAX_GAP_SECS,
) -> list[float]:
    """Merge (start, end) speech regions into clips; return faster-whisper's flat clip list.

    Consecutive regions join the current clip while the gap between them is at
    most `max_gap` and the whole clip stays within `max_span` seconds.
    """
    clips: list[list[float]] = []
    for start, end in speech:
        if clips and start - clips[-1][1] <= max_gap and end - clips[-1][0] <= max_span:
            clips[-1][1] = end
        else:
            clips.append([start, end])
    return [ts for clip in clips for ts in clip]


def split_on_pauses(
    words: Sequence[tuple[float, float, str]],
    max_pause: float = PAUSE_SPLIT_SECS,
) -> list[tuple[float, float, str]]:
    """Split timed words into (start, end, text) runs wherever a pause exceeds `max_pause`."""
    runs: list[tuple[float, float, str]] = []
    current: list[tuple[float, float, str]] = []
    for word in words:
        if current and word[0] - current[-1][1] > max_pause:
            runs.append((current[0][0], current[-1][1], "".join(w[2] for w in current)))
            current = []
        current.append(word)
    if current:
        runs.append((current[0][0], current[-1][1], "".join(w[2] for w in current)))
    return runs


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
        hotwords: Sequence[str] = (),
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
        self.hotwords = pack_hotwords(hotwords, self._count_tokens)
        if self.hotwords:
            log.info(
                "Whisper hotwords (%d tokens): %s",
                self._count_tokens(self.hotwords),
                self.hotwords,
            )
        self.language = language
        self.vad_filter = vad_filter

    def _count_tokens(self, text: str) -> int:
        return len(self._model.hf_tokenizer.encode(" " + text, add_special_tokens=False).ids)

    def transcribe(self, audio_path: Path) -> list[Segment]:
        from faster_whisper.audio import decode_audio
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        audio = decode_audio(str(audio_path), sampling_rate=SAMPLING_RATE)
        clip_timestamps: str | list[float] = "0"
        if self.vad_filter:
            # 400 ms padding (faster-whisper's default) — tighter padding
            # clipped word onsets and raised WER in testing.
            speech = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=500))
            if not speech:
                return []
            clip_timestamps = group_speech_clips(
                [(c["start"] / SAMPLING_RATE, c["end"] / SAMPLING_RATE) for c in speech]
            )

        segments_iter, _info = self._model.transcribe(
            audio,
            language=self.language,
            hotwords=self.hotwords or None,
            condition_on_previous_text=False,
            temperature=[0.0, 0.2, 0.4, 0.6],
            log_prob_threshold=-1.0,
            no_speech_threshold=0.6,
            compression_ratio_threshold=2.4,
            vad_filter=False,
            clip_timestamps=clip_timestamps,
            word_timestamps=True,
        )
        out: list[Segment] = []
        for s in segments_iter:
            words = [(float(w.start), float(w.end), str(w.word)) for w in (s.words or [])]
            runs = split_on_pauses(words) if words else [(float(s.start), float(s.end), str(s.text))]
            for start, end, text in runs:
                # Decode-window metrics: shared by every segment of the window.
                out.append(
                    Segment(
                        start=start,
                        end=end,
                        text=text,
                        avg_logprob=float(s.avg_logprob),
                        no_speech_prob=float(s.no_speech_prob),
                        compression_ratio=float(s.compression_ratio),
                    )
                )
        return out
