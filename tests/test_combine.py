from __future__ import annotations

import json
from pathlib import Path

from rpgnotes.transcribe.combine import combine_transcriptions


def _write_segments(path: Path, segments: list[dict[str, object]]) -> None:
    path.write_text(json.dumps(segments), encoding="utf-8")


def _setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    transcripts = tmp_path / "transcriptions"
    assets = tmp_path / "assets"
    mapping = tmp_path / "mapping.json"
    transcripts.mkdir()
    mapping.write_text(json.dumps({"karpiq24": "DM", "barabaszek": "Orestes"}), encoding="utf-8")
    return transcripts, assets, mapping


def test_combine_sorts_by_start_and_applies_speakers(tmp_path: Path) -> None:
    transcripts, assets, mapping = _setup(tmp_path)
    _write_segments(
        transcripts / "1-karpiq24_0001.json",
        [{"start": 10.0, "end": 11.0, "text": "Drugi"}],
    )
    _write_segments(
        transcripts / "2-barabaszek_0002.json",
        [{"start": 1.0, "end": 2.0, "text": "Pierwszy"}],
    )

    out = combine_transcriptions(1, transcripts, assets, mapping)
    assert out is not None
    combined = json.loads((assets / "001" / "transcript.json").read_text(encoding="utf-8"))
    assert [s["text"] for s in combined] == ["Pierwszy", "Drugi"]
    assert [s["speaker"] for s in combined] == ["Orestes", "DM"]


def test_combine_drops_hallucinations(tmp_path: Path) -> None:
    transcripts, assets, mapping = _setup(tmp_path)
    _write_segments(
        transcripts / "1-karpiq24_0001.json",
        [
            {"start": 1.0, "end": 2.0, "text": "Napisy by Jacek Makarewicz"},
            {"start": 2.5, "end": 3.0, "text": "Atakuję."},
        ],
    )

    combine_transcriptions(1, transcripts, assets, mapping)
    combined = json.loads((assets / "001" / "transcript.json").read_text(encoding="utf-8"))
    assert [s["text"] for s in combined] == ["Atakuję."]


def test_combine_drops_low_confidence_and_silence(tmp_path: Path) -> None:
    transcripts, assets, mapping = _setup(tmp_path)
    _write_segments(
        transcripts / "1-karpiq24_0001.json",
        [
            {"start": 1.0, "end": 2.0, "text": "Niski logprob.", "avg_logprob": -1.5},
            {"start": 2.0, "end": 3.0, "text": "Sama cisza.", "no_speech_prob": 0.9},
            {"start": 3.0, "end": 4.0, "text": "..."},
            {"start": 4.0, "end": 5.0, "text": "Dobre."},
        ],
    )

    combine_transcriptions(1, transcripts, assets, mapping)
    combined = json.loads((assets / "001" / "transcript.json").read_text(encoding="utf-8"))
    assert [s["text"] for s in combined] == ["Dobre."]


def test_combine_dedupes_consecutive_identical_text_from_same_speaker(tmp_path: Path) -> None:
    transcripts, assets, mapping = _setup(tmp_path)
    _write_segments(
        transcripts / "1-karpiq24_0001.json",
        [
            {"start": 1.0, "end": 2.0, "text": "Idę."},
            {"start": 2.1, "end": 2.9, "text": "Idę."},
            {"start": 3.0, "end": 4.0, "text": "Atakuję."},
        ],
    )

    combine_transcriptions(1, transcripts, assets, mapping)
    combined = json.loads((assets / "001" / "transcript.json").read_text(encoding="utf-8"))
    assert [s["text"] for s in combined] == ["Idę.", "Atakuję."]


def test_combine_skips_when_outputs_exist(tmp_path: Path) -> None:
    transcripts, assets, mapping = _setup(tmp_path)
    session_dir = assets / "001"
    session_dir.mkdir(parents=True)
    (session_dir / "transcript.json").write_text("[]", encoding="utf-8")
    (session_dir / "transcript.txt").write_text("preexisting", encoding="utf-8")

    out = combine_transcriptions(1, transcripts, assets, mapping)
    assert out == session_dir / "transcript.txt"
    assert (session_dir / "transcript.txt").read_text(encoding="utf-8") == "preexisting"


def test_combine_emits_speaker_headers_in_txt(tmp_path: Path) -> None:
    transcripts, assets, mapping = _setup(tmp_path)
    _write_segments(
        transcripts / "1-karpiq24_0001.json",
        [{"start": 2.0, "end": 3.0, "text": "Hello"}],
    )
    _write_segments(
        transcripts / "2-barabaszek_0002.json",
        [{"start": 1.0, "end": 2.0, "text": "Witaj"}],
    )

    combine_transcriptions(1, transcripts, assets, mapping)
    txt = (assets / "001" / "transcript.txt").read_text(encoding="utf-8")
    assert "[Orestes]" in txt
    assert "[DM]" in txt
    # Orestes' "Witaj" came first by timestamp.
    assert txt.index("[Orestes]") < txt.index("[DM]")
