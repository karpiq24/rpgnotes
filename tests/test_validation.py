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


def _mock_llm(monkeypatch: pytest.MonkeyPatch, reports: list[ValidationReport]) -> MagicMock:
    fake = MagicMock(side_effect=reports)
    monkeypatch.setattr(gemini.llm, "generate_structured", fake)
    return fake


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
    fake = _mock_llm(monkeypatch, [first, second])

    report_file = tmp_path / "validation_report.md"
    fixed, _ = gemini.validate_summary(
        summary="Felicjan rzucił Fireball, po raz pierwszy w kampanii.",
        transcript_content="[Felicjan]\nRzucam zaklęcie ognia.",
        validation_prompt="fact-check",
        model_name="gemini-pro",
        report_file=report_file,
    )

    assert fixed == "Felicjan rzucił zaklęcie ognia, po raz pierwszy w kampanii."
    assert fake.call_count == 2  # fix applied → one re-validation
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
    _mock_llm(monkeypatch, reports)

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
    # Every round "fixes" alfa → alfa!, which leaves exactly one "alfa" behind.
    noisy = ValidationReport(
        findings=[
            Finding(quote="alfa", issue="x", severity="error", suggested_fix="alfa!"),
        ]
    )
    fake = _mock_llm(monkeypatch, [noisy, noisy, noisy, noisy])

    gemini.validate_summary(
        summary="alfa jest tutaj",
        transcript_content="…",
        validation_prompt="…",
        model_name="gemini-pro",
        report_file=tmp_path / "report.md",
        max_iterations=2,
    )
    assert fake.call_count == 2


def test_validate_summary_skips_ambiguous_quotes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A quote occurring twice can't be fixed by a blind string replacement.
    reports = [
        ValidationReport(
            findings=[Finding(quote="Sydon", issue="x", severity="error", suggested_fix="Sidon")]
        )
    ]
    _mock_llm(monkeypatch, reports)
    report_file = tmp_path / "report.md"

    fixed, _ = gemini.validate_summary(
        summary="Sydon przybył. Sydon odszedł.",
        transcript_content="…",
        validation_prompt="…",
        model_name="gemini-pro",
        report_file=report_file,
    )
    assert fixed == "Sydon przybył. Sydon odszedł."
    assert "Sydon" in report_file.read_text(encoding="utf-8")


def test_validate_summary_puts_glossary_in_system_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _mock_llm(monkeypatch, [ValidationReport(findings=[])])
    gemini.validate_summary(
        summary="Kentimane nadchodzi.",
        transcript_content="[DM]\nIdzie po was, Cant i main.",
        validation_prompt="FACT-CHECK",
        model_name="gemini-pro",
        report_file=tmp_path / "report.md",
        glossary="GLOSARIUSZ: Kentimane",
    )
    system = fake.call_args.kwargs["system_instruction"]
    assert "FACT-CHECK" in system
    assert "GLOSARIUSZ: Kentimane" in system


def test_validate_summary_clean_draft_writes_empty_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock_llm(monkeypatch, [ValidationReport(findings=[])])
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

    fake = _mock_llm(monkeypatch, [ValidationReport(findings=[])])
    gemini.validate_summary(
        summary="Draft.",
        transcript_content="[CZAT 00:00:30] Orestes (rzut): rzuty: 1d20 = 20",
        validation_prompt="…",
        model_name="gemini-pro",
        report_file=tmp_path / "report.md",
    )
    content = fake.call_args.kwargs["contents"]
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


def test_verify_quotes_fixes_misattributed_speaker() -> None:
    quotes = QuotesData(quotes=['Orestes: "Zaraz wszystko wyleci w powietrze!"'])
    out = gemini.verify_quotes(quotes, _TRANSCRIPT)
    assert out.quotes == ['Felicjan: "Zaraz wszystko wyleci w powietrze!"']


def test_verify_quotes_matches_full_character_names() -> None:
    quotes = QuotesData(quotes=['Felicjan Janus Twardowski: "Zaraz wszystko wyleci w powietrze!"'])
    out = gemini.verify_quotes(quotes, _TRANSCRIPT)
    assert out.quotes == quotes.quotes


def test_verify_quotes_keeps_unknown_speaker_label() -> None:
    # "Mistrz Gry" isn't a transcript header, so the attribution can't be checked.
    quotes = QuotesData(quotes=['Mistrz Gry: "Zaraz wszystko wyleci w powietrze!"'])
    out = gemini.verify_quotes(quotes, _TRANSCRIPT)
    assert out.quotes == quotes.quotes
