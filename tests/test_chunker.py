from __future__ import annotations

import pytest

from rpgnotes.summarize.chunker import is_speaker_line, split_transcript


def _make_transcript(turns: int, lines_per_turn: int) -> str:
    """Build a synthetic combined transcript with `turns` speaker turns."""
    out: list[str] = []
    for turn in range(turns):
        out.append(f"[Speaker {turn % 3}]")
        out.extend(f"line {turn}-{i}" for i in range(lines_per_turn))
    return "\n".join(out)


def test_is_speaker_line() -> None:
    assert is_speaker_line("[Orestes]")
    assert is_speaker_line("  [Dungeon Master]  ")
    assert not is_speaker_line("plain narration line")
    assert not is_speaker_line("[Orestes] said something")
    assert not is_speaker_line("")


def test_split_short_transcript_is_single_chunk() -> None:
    transcript = _make_transcript(turns=3, lines_per_turn=5)
    chunks = split_transcript(transcript, chunk_lines=800)
    assert len(chunks) == 1
    assert chunks[0] == transcript


def test_chunks_break_only_at_speaker_boundaries() -> None:
    transcript = _make_transcript(turns=40, lines_per_turn=10)
    chunks = split_transcript(transcript, chunk_lines=100)
    assert len(chunks) > 1
    # Every chunk after the first must start with a speaker-turn header.
    for chunk in chunks:
        assert is_speaker_line(chunk.splitlines()[0])
    # No content lost, order preserved.
    rejoined = "\n".join(chunks)
    assert [ln for ln in rejoined.splitlines() if ln] == [
        ln for ln in transcript.splitlines() if ln
    ]


def test_chunk_sizes_are_close_to_target() -> None:
    transcript = _make_transcript(turns=100, lines_per_turn=10)
    chunks = split_transcript(transcript, chunk_lines=100)
    # Each chunk should be >= the target (cut happens at the first boundary
    # after the threshold) but not overshoot by more than one turn.
    for chunk in chunks[:-1]:
        n_lines = len(chunk.splitlines())
        assert 100 <= n_lines <= 100 + 11


def test_oversized_single_turn_stays_whole() -> None:
    lines = ["[Narrator]"] + [f"line {i}" for i in range(300)]
    transcript = "\n".join(lines)
    chunks = split_transcript(transcript, chunk_lines=100)
    assert len(chunks) == 1


def test_invalid_chunk_lines_raises() -> None:
    with pytest.raises(ValueError):
        split_transcript("x", chunk_lines=0)


def test_empty_transcript_gives_no_chunks() -> None:
    assert split_transcript("", chunk_lines=100) == []
