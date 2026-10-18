from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from rpgnotes.summarize import gemini


def _make_transcript(turns: int, lines_per_turn: int) -> str:
    out: list[str] = []
    for turn in range(turns):
        out.append(f"[Speaker {turn % 2}]")
        out.extend(f"line {turn}-{i}" for i in range(lines_per_turn))
    return "\n".join(out)


def _fake_llm(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Fake llm.generate_text responding with NARRATIVE/ROLLING blocks in call order."""
    counter = {"n": 0}

    def generate_text(**_kwargs: object) -> str:
        counter["n"] += 1
        n = counter["n"]
        return (
            f"NARRATIVE:\n### Sekcja {n}\n\nTreść fragmentu {n}.\n\n"
            f"ROLLING_SUMMARY:\n- stan po fragmencie {n}"
        )

    fake = MagicMock(side_effect=generate_text)
    monkeypatch.setattr(gemini.llm, "generate_text", fake)
    return fake


def test_parse_chunk_response_extracts_blocks() -> None:
    text = "NARRATIVE:\n### Tytuł\n\nAkapit.\n\nROLLING_SUMMARY:\n- punkt 1\n- punkt 2"
    narrative, rolling = gemini._parse_chunk_response(text)
    assert narrative == "### Tytuł\n\nAkapit."
    assert rolling == "- punkt 1\n- punkt 2"


def test_parse_chunk_response_falls_back_without_markers() -> None:
    narrative, rolling = gemini._parse_chunk_response("### Tylko narracja\n\nTekst.")
    assert "Tylko narracja" in narrative
    assert rolling == ""


def test_chunked_summary_concatenates_in_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _fake_llm(monkeypatch)
    transcript = _make_transcript(turns=30, lines_per_turn=10)

    summary, rollings = gemini.generate_summary_chunked(
        transcript_content=transcript,
        style_rules="STYL",
        anti_hallucination="ZAKAZY",
        glossary="GLOSARIUSZ",
        model_name="gemini-pro",
        temp_dir=tmp_path / "temp",
        session_number=7,
        cache_file=tmp_path / "summary.txt",
        chunk_lines=100,
        polish_pass=False,
    )

    n_chunks = fake.call_count
    assert n_chunks > 1
    # Narrative blocks appear in strict call order.
    positions = [summary.index(f"Treść fragmentu {i}.") for i in range(1, n_chunks + 1)]
    assert positions == sorted(positions)
    assert len(rollings) == n_chunks
    assert rollings[0] == "- stan po fragmencie 1"
    # Per-chunk caches exist for resumability.
    assert len(list((tmp_path / "temp").glob("summary_chunk_7_*.txt"))) == 2 * n_chunks


def test_chunked_summary_passes_rolling_summary_forward(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _fake_llm(monkeypatch)
    transcript = _make_transcript(turns=30, lines_per_turn=10)

    gemini.generate_summary_chunked(
        transcript_content=transcript,
        style_rules="STYL",
        anti_hallucination="ZAKAZY",
        glossary="",
        model_name="gemini-pro",
        temp_dir=tmp_path / "temp",
        session_number=7,
        cache_file=tmp_path / "summary.txt",
        chunk_lines=100,
        polish_pass=False,
    )

    second_call = fake.call_args_list[1].kwargs
    payload = second_call["contents"]
    assert "ROLLING_SUMMARY" in payload
    assert "stan po fragmencie 1" in payload
    # The previous chunk's tail rides along as context.
    assert "KONIEC POPRZEDNIEGO FRAGMENTU" in payload
    assert "line 9-9" in payload


def test_chunked_summary_sends_campaign_context_with_every_chunk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _fake_llm(monkeypatch)
    gemini.generate_summary_chunked(
        transcript_content=_make_transcript(turns=30, lines_per_turn=10),
        style_rules="STYL",
        anti_hallucination="ZAKAZY",
        glossary="GLOSARIUSZ",
        model_name="gemini-pro",
        background="KONTEKST KAMPANII XYZ",
        campaign_rules="DRUŻYNA ABC",
        temp_dir=tmp_path / "temp",
        session_number=7,
        cache_file=tmp_path / "summary.txt",
        chunk_lines=100,
        polish_pass=False,
    )

    assert fake.call_count > 1
    for call in fake.call_args_list:
        assert "KONTEKST KAMPANII XYZ" in call.kwargs["system_instruction"]
        assert "GLOSARIUSZ" in call.kwargs["system_instruction"]
        assert "DRUŻYNA ABC" in call.kwargs["system_instruction"]


def test_chunked_summary_resumes_from_chunk_caches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _fake_llm(monkeypatch)
    transcript = _make_transcript(turns=30, lines_per_turn=10)
    temp_dir = tmp_path / "temp"
    kwargs = dict(
        transcript_content=transcript,
        style_rules="STYL",
        anti_hallucination="ZAKAZY",
        glossary="",
        model_name="gemini-pro",
        temp_dir=temp_dir,
        session_number=7,
        chunk_lines=100,
        polish_pass=False,
    )

    first, _ = gemini.generate_summary_chunked(cache_file=tmp_path / "summary.txt", **kwargs)  # type: ignore[arg-type]
    calls_first_run = fake.call_count

    # Re-run with a missing final cache: chunk caches must be reused, no new calls.
    second, _ = gemini.generate_summary_chunked(cache_file=tmp_path / "summary2.txt", **kwargs)  # type: ignore[arg-type]
    assert fake.call_count == calls_first_run
    assert second == first


def test_chunked_summary_returns_final_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(gemini.llm, "generate_text", MagicMock())
    cache = tmp_path / "summary.txt"
    cache.write_text("CACHED SUMMARY", encoding="utf-8")

    summary, rollings = gemini.generate_summary_chunked(
        transcript_content="…",
        style_rules="…",
        anti_hallucination="…",
        glossary="",
        model_name="gemini-pro",
        temp_dir=tmp_path / "temp",
        session_number=7,
        cache_file=cache,
    )
    assert summary == "CACHED SUMMARY"
    assert rollings == []


def test_polish_pass_runs_when_enabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = MagicMock(
        side_effect=[
            "NARRATIVE:\n### Sekcja\n\nTreść.\n\nROLLING_SUMMARY:\n- stan",
            "WYPOLEROWANE PODSUMOWANIE",
        ]
    )
    monkeypatch.setattr(gemini.llm, "generate_text", fake)

    summary, _ = gemini.generate_summary_chunked(
        transcript_content="[A]\nkrótki transkrypt",
        style_rules="…",
        anti_hallucination="…",
        glossary="",
        model_name="gemini-pro",
        temp_dir=tmp_path / "temp",
        session_number=1,
        cache_file=tmp_path / "summary.txt",
        polish_pass=True,
    )
    assert summary == "WYPOLEROWANE PODSUMOWANIE"
    assert fake.call_count == 2
