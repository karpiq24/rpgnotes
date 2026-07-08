from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from rpgnotes.summarize import gemini
from rpgnotes.summarize.models import Finding, QuotesData, ValidationReport

# --- ValidationReport parsing ------------------------------------------------


def test_validation_report_parses_from_json() -> None:
    raw = """
    {
      "findings": [
        {
          "quote": "rzucił Fireball",
          "issue": "Nazwa zaklęcia nie pada w transkrypcji",
          "severity": "error",
          "suggested_fix": "rzucił zaklęcie ognia"
        },
        {
          "quote": "po raz pierwszy w kampanii",
          "issue": "Superlatyw niewypowiedziany przy stole",
          "severity": "suspicious",
          "suggested_fix": ""
        }
      ]
    }
    """
    report = ValidationReport.model_validate_json(raw)
    assert len(report.findings) == 2
    assert report.findings[0].severity == "error"
    assert report.findings[1].severity == "suspicious"


def test_validation_report_rejects_unknown_severity() -> None:
    with pytest.raises(ValidationError):
        Finding(quote="q", issue="i", severity="catastrophic")  # type: ignore[arg-type]


def test_validation_report_defaults() -> None:
    report = ValidationReport()
    assert report.findings == []
    finding = Finding(quote="q", issue="i", severity="error")
    assert finding.suggested_fix == ""


# --- validate_summary ---------------------------------------------------------


def _mock_instructor(monkeypatch: pytest.MonkeyPatch, reports: list[ValidationReport]) -> MagicMock:
    fake_completions = MagicMock()
    fake_completions.create.side_effect = reports
    fake_client = MagicMock()
    fake_client.chat.completions = fake_completions

    fake_instructor = MagicMock()
    fake_instructor.from_gemini.return_value = fake_client
    fake_instructor.Mode.GEMINI_JSON = "GEMINI_JSON"
    monkeypatch.setattr(gemini, "instructor", fake_instructor)
    monkeypatch.setattr(gemini, "genai", MagicMock())
    return fake_completions


def test_validate_summary_applies_error_fixes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    first = ValidationReport(
        findings=[
            Finding(
                quote="rzucił Fireball",
                issue="zmyślona nazwa zaklęcia",
                severity="error",
                suggested_fix="rzucił zaklęcie ognia",
            ),
            Finding(
                quote="po raz pierwszy w kampanii",
                issue="superlatyw",
                severity="suspicious",
            ),
        ]
    )
    second = ValidationReport(findings=[])
    fake = _mock_instructor(monkeypatch, [first, second])

    report_file = tmp_path / "validation_report.md"
    fixed, _ = gemini.validate_summary(
        summary="Felicjan rzucił Fireball, po raz pierwszy w kampanii.",
        transcript_content="[Felicjan]\nRzucam zaklęcie ognia.",
        validation_prompt="fact-check",
        model_name="gemini-pro",
        report_file=report_file,
    )

    assert fixed == "Felicjan rzucił zaklęcie ognia, po raz pierwszy w kampanii."
    assert fake.create.call_count == 2  # fix applied → one re-validation
    report_text = report_file.read_text(encoding="utf-8")
    assert "superlatyw" in report_text
    assert "suspicious" in report_text


def test_validate_summary_remove_fix_deletes_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    reports = [
        ValidationReport(
            findings=[
                Finding(quote=" (zmyślony detal)", issue="x", severity="error", suggested_fix="remove")
            ]
        ),
        ValidationReport(findings=[]),
    ]
    _mock_instructor(monkeypatch, reports)

    fixed, _ = gemini.validate_summary(
        summary="Orestes zaatakował (zmyślony detal).",
        transcript_content="…",
        validation_prompt="…",
        model_name="gemini-pro",
        report_file=tmp_path / "report.md",
    )
    assert fixed == "Orestes zaatakował."


def test_validate_summary_stops_after_max_iterations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    noisy = ValidationReport(
        findings=[
            Finding(quote="alfa", issue="x", severity="error", suggested_fix="beta"),
        ]
    )
    fake = _mock_instructor(monkeypatch, [noisy, noisy, noisy, noisy])

    gemini.validate_summary(
        summary="alfa alfa alfa alfa",
        transcript_content="…",
        validation_prompt="…",
        model_name="gemini-pro",
        report_file=tmp_path / "report.md",
        max_iterations=2,
    )
    assert fake.create.call_count == 2


def test_validate_summary_clean_draft_writes_empty_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock_instructor(monkeypatch, [ValidationReport(findings=[])])
    report_file = tmp_path / "report.md"

    fixed, report = gemini.validate_summary(
        summary="Wszystko się zgadza.",
        transcript_content="…",
        validation_prompt="…",
        model_name="gemini-pro",
        report_file=report_file,
    )
    assert fixed == "Wszystko się zgadza."
    assert report.findings == []
    assert "Brak nierozwiązanych uwag" in report_file.read_text(encoding="utf-8")


def test_validate_summary_sends_only_the_transcript_as_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Chat events now live inside the enriched transcript itself; there is no
    # separate evidence appendix (and no chat_events parameter) anymore.
    import inspect

    assert "chat_events" not in inspect.signature(gemini.validate_summary).parameters

    fake = _mock_instructor(monkeypatch, [ValidationReport(findings=[])])
    gemini.validate_summary(
        summary="Draft.",
        transcript_content="[CZAT 00:00:30] Orestes (rzut): rzuty: 1d20 = 20",
        validation_prompt="…",
        model_name="gemini-pro",
        report_file=tmp_path / "report.md",
    )
    content = fake.create.call_args.kwargs["messages"][0]["content"]
    assert content.endswith("TRANSKRYPCJA:\n[CZAT 00:00:30] Orestes (rzut): rzuty: 1d20 = 20")


# --- verify_quotes -------------------------------------------------------------

_TRANSCRIPT = (
    "[Orestes]\n"
    "Chyba nie powinniśmy byli tego dotykać. No ale co zrobić.\n"
    "\n[Felicjan]\n"
    "Zaraz wszystko wyleci w powietrze, uciekajcie!"
)


def test_verify_quotes_keeps_exact_quotes() -> None:
    quotes = QuotesData(quotes=['Orestes: "Chyba nie powinniśmy byli tego dotykać."'])
    out = gemini.verify_quotes(quotes, _TRANSCRIPT)
    assert out.quotes == quotes.quotes


def test_verify_quotes_is_case_and_punctuation_insensitive() -> None:
    quotes = QuotesData(quotes=['Felicjan: "zaraz wszystko wyleci w powietrze, uciekajcie"'])
    out = gemini.verify_quotes(quotes, _TRANSCRIPT)
    assert len(out.quotes) == 1


def test_verify_quotes_drops_fabricated_quotes() -> None:
    quotes = QuotesData(quotes=['Versir: "Tego zdania nikt nie wypowiedział."'])
    out = gemini.verify_quotes(quotes, _TRANSCRIPT)
    assert out.quotes == []


def test_verify_quotes_accepts_prefix_window_for_long_quotes() -> None:
    # First six words match the transcript, the tail is paraphrased.
    quotes = QuotesData(
        quotes=['Orestes: "Chyba nie powinniśmy byli tego dotykać, mówiłem przecież od początku."']
    )
    out = gemini.verify_quotes(quotes, _TRANSCRIPT)
    assert len(out.quotes) == 1


def test_verify_quotes_mixed_keeps_order() -> None:
    quotes = QuotesData(
        quotes=[
            'Felicjan: "Zaraz wszystko wyleci w powietrze, uciekajcie!"',
            'Versir: "Zmyślony cytat."',
            'Orestes: "Chyba nie powinniśmy byli tego dotykać."',
        ]
    )
    out = gemini.verify_quotes(quotes, _TRANSCRIPT)
    assert len(out.quotes) == 2
    assert "Felicjan" in out.quotes[0]
    assert "Orestes" in out.quotes[1]
