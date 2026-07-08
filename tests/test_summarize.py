from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from rpgnotes.summarize import gemini
from rpgnotes.summarize.models import QuotesData

# --- generate_summary -------------------------------------------------------

def test_generate_summary_returns_cached_when_file_exists(tmp_path: Path) -> None:
    cache = tmp_path / "summary.txt"
    cache.write_text("CACHED", encoding="utf-8")

    out = gemini.generate_summary(
        transcript_content="…",
        summary_prompt="prompt",
        model_name="gemini-pro",
        context_dir=tmp_path / "ctx",
        cache_file=cache,
    )
    assert out == "CACHED"


def test_generate_summary_calls_gemini_and_caches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cache = tmp_path / "summary.txt"

    fake_response = MagicMock()
    fake_response.text = "FRESHLY GENERATED"

    fake_model = MagicMock()
    fake_model.generate_content.return_value = fake_response

    fake_genai = MagicMock()
    fake_genai.GenerativeModel.return_value = fake_model
    fake_genai.GenerationConfig.return_value = MagicMock()
    monkeypatch.setattr(gemini, "genai", fake_genai)

    out = gemini.generate_summary(
        transcript_content="full transcript",
        summary_prompt="be a chronicler",
        model_name="gemini-pro",
        context_dir=tmp_path / "ctx",
        cache_file=cache,
    )

    assert out == "FRESHLY GENERATED"
    assert cache.read_text(encoding="utf-8") == "FRESHLY GENERATED"
    fake_genai.GenerativeModel.assert_called_once_with(
        model_name="gemini-pro", system_instruction="be a chronicler"
    )
    fake_model.generate_content.assert_called_once()


def test_generate_summary_retries_on_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cache = tmp_path / "summary.txt"

    ok_response = MagicMock()
    ok_response.text = "OK"

    fake_model = MagicMock()
    fake_model.generate_content.side_effect = [RuntimeError("rate-limit"), ok_response]

    fake_genai = MagicMock()
    fake_genai.GenerativeModel.return_value = fake_model
    fake_genai.GenerationConfig.return_value = MagicMock()
    monkeypatch.setattr(gemini, "genai", fake_genai)
    monkeypatch.setattr(gemini.time, "sleep", lambda *_a, **_k: None)

    out = gemini.generate_summary(
        transcript_content="…",
        summary_prompt="…",
        model_name="gemini-pro",
        context_dir=tmp_path / "ctx",
        cache_file=cache,
    )
    assert out == "OK"
    assert fake_model.generate_content.call_count == 2


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


def test_generate_quotes_calls_instructor_with_transcript(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache = tmp_path / "quotes.json"

    fake_completions = MagicMock()
    fake_completions.create.return_value = _QUOTES_PAYLOAD
    fake_client = MagicMock()
    fake_client.chat.completions = fake_completions

    fake_instructor = MagicMock()
    fake_instructor.from_gemini.return_value = fake_client
    fake_instructor.Mode.GEMINI_JSON = "GEMINI_JSON"
    monkeypatch.setattr(gemini, "instructor", fake_instructor)
    monkeypatch.setattr(gemini, "genai", MagicMock())

    gemini.generate_quotes(
        transcript_content="THE TRANSCRIPT",
        quotes_prompt="…",
        model_name="gemini-flash",
        cache_file=cache,
    )

    _, kwargs = fake_completions.create.call_args
    assert kwargs["response_model"] is QuotesData
    assert "THE TRANSCRIPT" in kwargs["messages"][0]["content"]
