from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from rpgnotes import llm
from rpgnotes.summarize.models import QuotesData


def _fake_client(monkeypatch: pytest.MonkeyPatch, texts: list[str | Exception]) -> MagicMock:
    responses: list[object] = []
    for text in texts:
        if isinstance(text, Exception):
            responses.append(text)
        else:
            response = MagicMock()
            response.text = text
            response.usage_metadata = None
            responses.append(response)
    client = MagicMock()
    client.models.generate_content.side_effect = responses
    monkeypatch.setattr(llm, "_client", client)
    monkeypatch.setattr(llm, "_service_tier", "standard")
    monkeypatch.setattr(llm.time, "sleep", lambda *_a: None)
    return client


def test_generate_text_retries_api_errors_and_empty_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _fake_client(monkeypatch, [RuntimeError("429"), "  ", "Gotowe."])
    out = llm.generate_text(model="m", contents="hi", system_instruction="sys")
    assert out == "Gotowe."
    assert client.models.generate_content.call_count == 3


def test_generate_text_passes_thinking_level_and_default_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _fake_client(monkeypatch, ["ok"])
    llm.generate_text(model="gemini-4-argon", contents="hi", thinking_level="high")
    kwargs = client.models.generate_content.call_args.kwargs
    assert kwargs["model"] == "gemini-4-argon"
    assert kwargs["config"].temperature is None
    assert kwargs["config"].thinking_config.thinking_level.value == "HIGH"


def test_generate_structured_parses_and_retries_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _fake_client(monkeypatch, ['{"nope": 1}', '{"quotes": ["Orestes: \\"Hej\\""]}'])
    out = llm.generate_structured(model="m", contents="t", schema=QuotesData)
    assert out == QuotesData(quotes=['Orestes: "Hej"'])
    config = client.models.generate_content.call_args.kwargs["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == QuotesData.model_json_schema()


def test_unconfigured_client_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, "_client", None)
    monkeypatch.setattr(llm.time, "sleep", lambda *_a: None)
    with pytest.raises(RuntimeError, match="not configured"):
        llm.generate_text(model="m", contents="hi")


def test_flex_tier_is_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _fake_client(monkeypatch, ["ok"])
    monkeypatch.setattr(llm, "_service_tier", "flex")
    llm.generate_text(model="m", contents="hi")
    config = client.models.generate_content.call_args.kwargs["config"]
    assert config.service_tier == llm.types.ServiceTier.FLEX


def test_flex_falls_back_to_standard_after_repeated_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unavailable = RuntimeError("503 UNAVAILABLE")
    client = _fake_client(monkeypatch, [unavailable, unavailable, unavailable, "ok"])
    monkeypatch.setattr(llm, "_service_tier", "flex")
    assert llm.generate_text(model="m", contents="hi") == "ok"
    tiers = [c.kwargs["config"].service_tier for c in client.models.generate_content.call_args_list]
    assert tiers == [llm.types.ServiceTier.FLEX] * 3 + [None]


def test_usage_is_recorded_per_model(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _fake_client(monkeypatch, [])
    response = MagicMock()
    response.text = "ok"
    client.models.generate_content.side_effect = None
    client.models.generate_content.return_value = response
    response.usage_metadata = llm.types.GenerateContentResponseUsageMetadata(
        prompt_token_count=1000,
        cached_content_token_count=800,
        candidates_token_count=50,
        thoughts_token_count=200,
    )
    monkeypatch.setattr(llm, "_usage", llm.defaultdict(llm.Counter))
    llm.generate_text(model="argon", contents="hi")
    assert llm._usage["argon"] == {
        "input": 1000, "cached": 800, "output": 50, "thinking": 200, "calls": 1,
    }
