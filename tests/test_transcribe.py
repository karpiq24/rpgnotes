from __future__ import annotations

import json
from pathlib import Path

from rpgnotes.transcribe.base import Segment, TranscriberProtocol
from rpgnotes.transcribe.runner import transcribe_audio_dir


class FakeTranscriber:
    def __init__(self, segments: list[Segment]) -> None:
        self.segments = segments
        self.calls: list[Path] = []

    def transcribe(self, audio_path: Path) -> list[Segment]:
        self.calls.append(audio_path)
        return self.segments


def _make_flac(path: Path) -> None:
    path.write_bytes(b"fake-flac")


def test_transcribes_every_flac_and_writes_json(tmp_path: Path) -> None:
    audio = tmp_path / "audio"
    transcripts = tmp_path / "transcriptions"
    audio.mkdir()
    _make_flac(audio / "a.flac")
    _make_flac(audio / "b.flac")

    fake = FakeTranscriber([Segment(start=0.0, end=1.0, text="hi")])
    ok = transcribe_audio_dir(audio, transcripts, lambda: fake)
    assert ok is True

    assert (transcripts / "a.json").exists()
    assert (transcripts / "b.json").exists()
    assert json.loads((transcripts / "a.json").read_text())[0]["text"] == "hi"
    assert {p.name for p in fake.calls} == {"a.flac", "b.flac"}


def test_skips_already_transcribed_files(tmp_path: Path) -> None:
    audio = tmp_path / "audio"
    transcripts = tmp_path / "transcriptions"
    audio.mkdir()
    transcripts.mkdir()
    _make_flac(audio / "a.flac")
    (transcripts / "a.json").write_text("[]", encoding="utf-8")
    _make_flac(audio / "b.flac")

    fake = FakeTranscriber([Segment(start=0.0, end=1.0, text="hi")])
    transcribe_audio_dir(audio, transcripts, lambda: fake)
    assert [p.name for p in fake.calls] == ["b.flac"]


def test_does_not_load_model_when_nothing_to_do(tmp_path: Path) -> None:
    audio = tmp_path / "audio"
    transcripts = tmp_path / "transcriptions"
    audio.mkdir()
    transcripts.mkdir()
    _make_flac(audio / "a.flac")
    (transcripts / "a.json").write_text("[]", encoding="utf-8")

    factory_calls = 0

    def factory() -> TranscriberProtocol:
        nonlocal factory_calls
        factory_calls += 1
        return FakeTranscriber([])

    transcribe_audio_dir(audio, transcripts, factory)
    assert factory_calls == 0


def test_returns_false_when_factory_raises(tmp_path: Path) -> None:
    audio = tmp_path / "audio"
    transcripts = tmp_path / "transcriptions"
    audio.mkdir()
    _make_flac(audio / "a.flac")

    def boom() -> TranscriberProtocol:
        raise RuntimeError("no GPU")

    assert transcribe_audio_dir(audio, transcripts, boom) is False
    assert not (transcripts / "a.json").exists()


def test_returns_false_when_transcribe_raises(tmp_path: Path) -> None:
    audio = tmp_path / "audio"
    transcripts = tmp_path / "transcriptions"
    audio.mkdir()
    _make_flac(audio / "a.flac")

    class Boom:
        def transcribe(self, audio_path: Path) -> list[Segment]:
            raise RuntimeError("kaboom")

    assert transcribe_audio_dir(audio, transcripts, Boom) is False


def test_segment_shape_matches_combiner_expectations(tmp_path: Path) -> None:
    """The JSON written by the runner must use the keys combine_transcriptions consumes."""
    audio = tmp_path / "audio"
    transcripts = tmp_path / "transcriptions"
    audio.mkdir()
    _make_flac(audio / "a.flac")

    fake = FakeTranscriber(
        [Segment(start=0.0, end=1.0, text="hi", avg_logprob=-0.1, no_speech_prob=0.1)]
    )
    transcribe_audio_dir(audio, transcripts, lambda: fake)
    payload = json.loads((transcripts / "a.json").read_text())
    assert {"start", "end", "text"}.issubset(payload[0].keys())
