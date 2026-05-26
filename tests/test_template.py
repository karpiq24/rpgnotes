from __future__ import annotations

import datetime as _dt
from pathlib import Path

from rpgnotes.summarize.models import QuotesData, SessionData
from rpgnotes.template import render_session_note, save_summary_file

_TEMPLATE = """---
title: "Sesja ${number}: ${title}"
---

# Sesja ${number}: ${title}

**Data:** ${date}

## Podsumowanie
${summary}

## Wydarzenia
${events}

## NPC
${npcs}

## Lokacje
${locations}

## Przedmioty
${items}

## Cytaty
${quotes}
"""


def _write_template(tmp_path: Path) -> Path:
    p = tmp_path / "template.md"
    p.write_text(_TEMPLATE, encoding="utf-8")
    return p


def _sample_data() -> tuple[str, SessionData, QuotesData]:
    summary = "Bohaterowie ruszyli do podziemi."
    details = SessionData(
        title="Pierwsza wyprawa",
        events=["Spotkanie z goblinem", "Znalezienie skarbu"],
        npcs=["Goblin Bob"],
        locations=["Podziemia"],
        items=["Miecz +1"],
    )
    quotes = QuotesData(quotes=['DM: "Rzuć inicjatywę."', 'Orestes: "Atakuję!"'])
    return summary, details, quotes


def test_render_session_note_substitutes_fields(tmp_path: Path) -> None:
    template = _write_template(tmp_path)
    summary, details, quotes = _sample_data()
    out = render_session_note(template, summary, details, quotes, 7, _dt.date(2026, 5, 20))

    assert "Sesja 7: Pierwsza wyprawa" in out
    assert "**Data:** 20.05.2026" in out
    assert "Bohaterowie ruszyli do podziemi." in out
    assert "* Spotkanie z goblinem" in out
    assert "* Goblin Bob" in out
    assert "* Miecz +1" in out
    assert '* DM: "Rzuć inicjatywę."' in out


def test_render_session_note_tolerates_dollar_in_summary(tmp_path: Path) -> None:
    """A summary containing $ chars must not crash safe_substitute."""
    template = _write_template(tmp_path)
    _, details, quotes = _sample_data()
    weird_summary = "Cena to $5 i {nawias}"
    out = render_session_note(template, weird_summary, details, quotes, 1, _dt.date(2026, 1, 1))
    assert weird_summary in out


def test_save_summary_file_writes_to_correct_path(tmp_path: Path) -> None:
    template = _write_template(tmp_path)
    sessions_dir = tmp_path / "sessions"
    summary, details, quotes = _sample_data()
    out = save_summary_file(
        template, sessions_dir, summary, details, quotes, 12, _dt.date(2026, 5, 20)
    )
    assert out.exists()
    assert out.name == "Sesja 12 - Pierwsza wyprawa.md"


def test_save_summary_file_sanitizes_title_for_filesystem(tmp_path: Path) -> None:
    template = _write_template(tmp_path)
    sessions_dir = tmp_path / "sessions"
    _, _, quotes = _sample_data()
    details = SessionData(
        title='Bad/title:with*chars?"|<>',
        events=[],
        npcs=[],
        locations=[],
        items=[],
    )
    out = save_summary_file(
        template, sessions_dir, "summary", details, quotes, 1, _dt.date(2026, 1, 1)
    )
    assert "/" not in out.name
    assert "?" not in out.name
    assert "*" not in out.name
