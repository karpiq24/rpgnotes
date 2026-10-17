from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from rpgnotes.summarize import gemini
from rpgnotes.summarize.models import QuotesData

# --- generate_quotes --------------------------------------------------------

_QUOTES_PAYLOAD = QuotesData(quotes=["a", "b"])


def test_generate_quotes_returns_cached(tmp_path: Path) -> None:
    cache = tmp_path / "quotes.json"
    cache.write_text(_QUOTES_PAYLOAD.model_dump_json(), encoding="utf-8")

    out = gemini.generate_quotes(
        transcript_content="…",
        quotes_prompt="prompt",
        model_name="gemini-flash",
        cache_file=cache,
    )
    assert out == _QUOTES_PAYLOAD


def test_generate_quotes_requests_structured_output_with_transcript(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache = tmp_path / "quotes.json"

    fake = MagicMock(return_value=_QUOTES_PAYLOAD)
    monkeypatch.setattr(gemini.llm, "generate_structured", fake)

    gemini.generate_quotes(
        transcript_content="THE TRANSCRIPT",
        quotes_prompt="…",
        model_name="gemini-flash",
        cache_file=cache,
    )

    kwargs = fake.call_args.kwargs
    assert kwargs["schema"] is QuotesData
    assert "THE TRANSCRIPT" in kwargs["contents"]
    assert QuotesData.model_validate_json(cache.read_text(encoding="utf-8")) == _QUOTES_PAYLOAD
