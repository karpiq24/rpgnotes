from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import rpgnotes.pipeline as pipeline
from rpgnotes.config import Settings
from rpgnotes.summarize import QuotesData
from rpgnotes.summarize.models import ValidationReport


def _make_settings(tmp_path: Path) -> Settings:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    for name in (
        "whisper",
        "summary",
        "quotes",
        "style_rules",
        "anti_hallucination",
        "validation",
    ):
        (prompts / f"{name}.txt").write_text(f"{name} prompt", encoding="utf-8")
    (tmp_path / "template.md").write_text("$summary", encoding="utf-8")
    (tmp_path / "mapping.json").write_text("{}", encoding="utf-8")
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        output_dir=tmp_path / "output",
        temp_dir=tmp_path / "temp",
        downloads_dir=tmp_path / "downloads",
        discord_mapping_file=tmp_path / "mapping.json",
        whisper_prompt_file=prompts / "whisper.txt",
        summary_prompt_file=prompts / "summary.txt",
        quotes_prompt_file=prompts / "quotes.txt",
        style_rules_file=prompts / "style_rules.txt",
        anti_hallucination_file=prompts / "anti_hallucination.txt",
        validation_prompt_file=prompts / "validation.txt",
        template_file=tmp_path / "template.md",
        context_dir=tmp_path / "context",
        gemini_api_key="test-key",
        gemini_api_sleep_secs=0.0,
    )


def _make_session_assets(settings: Settings, session_number: int = 7) -> Path:
    session_assets_dir = settings.assets_base_dir / f"{session_number:03d}"
    session_assets_dir.mkdir(parents=True, exist_ok=True)
    segments = [
        {"start": 1.0, "end": 2.0, "speaker": "Orestes", "text": "Witaj"},
        {"start": 60.0, "end": 61.0, "speaker": "DM", "text": "Hello"},
    ]
    (session_assets_dir / "transcript.json").write_text(
        json.dumps(segments), encoding="utf-8"
    )
    return session_assets_dir


def _write_chat_events(session_assets_dir: Path) -> None:
    events = [
        {"offset_secs": 30.0, "speaker": "Orestes", "kind": "roll", "text": "rzuty: 1d20 = 20"},
        {"offset_secs": -10.0, "speaker": "GM", "kind": "chat", "text": "Przed sesją."},
    ]
    (session_assets_dir / "chat_events.json").write_text(json.dumps(events), encoding="utf-8")


# --- _apply_enrichment --------------------------------------------------------


def test_apply_enrichment_chat_only_builds_and_caches(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    session_assets_dir = _make_session_assets(settings)
    _write_chat_events(session_assets_dir)

    enriched = pipeline._apply_enrichment(settings, session_assets_dir, "PLAIN", "", 7)

    assert enriched.startswith("\n\n[CZAT PRZED NAGRANIEM] GM: Przed sesją.\n")
    assert "[CZAT 00:00:30] Orestes (rzut): rzuty: 1d20 = 20" in enriched
    enriched_file = session_assets_dir / "transcript_enriched.txt"
    assert enriched_file.read_text(encoding="utf-8") == enriched

    # Resumable: an existing file is loaded verbatim, nothing is rebuilt.
    enriched_file.write_text("CACHED", encoding="utf-8")
    assert pipeline._apply_enrichment(settings, session_assets_dir, "PLAIN", "", 7) == "CACHED"


def test_apply_enrichment_without_sources_returns_plain_and_writes_nothing(
    tmp_path: Path,
) -> None:
    settings = _make_settings(tmp_path)
    session_assets_dir = _make_session_assets(settings)

    out = pipeline._apply_enrichment(settings, session_assets_dir, "PLAIN", "", 7)

    assert out == "PLAIN"
    assert not (session_assets_dir / "transcript_enriched.txt").exists()


def test_apply_enrichment_survives_broken_chat_events(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    session_assets_dir = _make_session_assets(settings)
    (session_assets_dir / "chat_events.json").write_text("not-json", encoding="utf-8")

    out = pipeline._apply_enrichment(settings, session_assets_dir, "PLAIN", "", 7)

    assert out == "PLAIN"
    assert not (session_assets_dir / "transcript_enriched.txt").exists()


# --- _generate_notes ------------------------------------------------------------


def test_generate_notes_returns_summary_and_quotes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _make_settings(tmp_path)
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    session_assets_dir = _make_session_assets(settings)
    _write_chat_events(session_assets_dir)
    transcript_file = session_assets_dir / "transcript.txt"
    transcript_file.write_text("PLAIN TRANSCRIPT", encoding="utf-8")

    calls: dict[str, Any] = {}

    monkeypatch.setattr(pipeline.genai, "configure", lambda **_kw: None)
    monkeypatch.setattr(pipeline.time, "sleep", lambda *_a: None)
    monkeypatch.setattr(
        pipeline, "build_session_glossary", lambda **_kw: "GLOSSARY"
    )

    def fake_summary(**kwargs: Any) -> tuple[str, list[str]]:
        calls["summary_transcript"] = kwargs["transcript_content"]
        return "SUMMARY", []

    def fake_validate(**kwargs: Any) -> tuple[str, ValidationReport]:
        calls["validate_transcript"] = kwargs["transcript_content"]
        assert "chat_events" not in kwargs
        return "VALIDATED", ValidationReport(findings=[])

    def fake_quotes(**kwargs: Any) -> QuotesData:
        calls["quotes_transcript"] = kwargs["transcript_content"]
        return QuotesData(quotes=["q"])

    monkeypatch.setattr(pipeline, "generate_summary_chunked", fake_summary)
    monkeypatch.setattr(pipeline, "validate_summary", fake_validate)
    monkeypatch.setattr(pipeline, "generate_quotes", fake_quotes)
    monkeypatch.setattr(pipeline, "verify_quotes", lambda quotes, _t: quotes)

    notes = pipeline._generate_notes(settings, transcript_file, 7)

    assert notes == ("VALIDATED", QuotesData(quotes=["q"]))
    # Summary + validation see the enriched transcript; quotes see the plain one.
    assert "[CZAT 00:00:30]" in calls["summary_transcript"]
    assert calls["validate_transcript"] == calls["summary_transcript"]
    assert calls["quotes_transcript"] == "PLAIN TRANSCRIPT"
    assert (session_assets_dir / "draft0.md").read_text(encoding="utf-8") == "VALIDATED"
