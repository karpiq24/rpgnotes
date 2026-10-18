from __future__ import annotations

import json
from pathlib import Path

import pytest

from rpgnotes.campaign import (
    SCHEMA_VERSION,
    CampaignContext,
    CampaignContextError,
    PartyMember,
    TimelineSession,
    load_campaign_context,
    render_background,
    render_campaign_rules,
)


def test_load_missing_or_empty_context_gives_empty_context(tmp_path: Path) -> None:
    assert load_campaign_context(None) == CampaignContext()
    assert load_campaign_context(tmp_path / "missing.json") == CampaignContext()
    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")
    assert load_campaign_context(empty) == CampaignContext()
    # Docker creates a missing bind-mount source as a directory.
    assert load_campaign_context(tmp_path) == CampaignContext()


def test_load_context_reads_the_export(tmp_path: Path) -> None:
    path = tmp_path / "campaign_context.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "party": [{"name": "Orestes", "description": "Minotaur Barbarian"}],
                "hotwords": ["Kentimane"],
                "extra_field_from_a_newer_wiki": True,
            }
        ),
        encoding="utf-8",
    )
    context = load_campaign_context(path)
    assert context.party[0].name == "Orestes"
    assert context.hotwords == ["Kentimane"]


def test_load_context_rejects_unknown_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "campaign_context.json"
    path.write_text(json.dumps({"schema_version": SCHEMA_VERSION + 1}), encoding="utf-8")
    with pytest.raises(CampaignContextError, match="schema version"):
        load_campaign_context(path)


def test_load_context_rejects_broken_json(tmp_path: Path) -> None:
    path = tmp_path / "campaign_context.json"
    path.write_text("{nope", encoding="utf-8")
    with pytest.raises(CampaignContextError):
        load_campaign_context(path)


def test_campaign_rules_render_party_and_learned_rules() -> None:
    context = CampaignContext(
        party=[PartyMember(name="Versir", description="Aasimar Paladin")],
        learned_rules="- Versir to nie Versi.",
    )
    rules = render_campaign_rules(context)
    assert "**Versir** — Aasimar Paladin" in rules
    assert "# Reguły tej kampanii" in rules
    assert render_campaign_rules(CampaignContext()) == ""


def test_background_keeps_summary_and_recent_sessions() -> None:
    context = CampaignContext(
        campaign_context="# Kontekst",
        timeline_preamble="# Oś czasu",
        timeline=[
            TimelineSession(heading=f"## Sesja {n}", text=f"* wydarzenie {n}") for n in (1, 2, 3)
        ],
    )
    background = render_background(context, recent_sessions=2)
    assert background.startswith("# Kontekst")
    assert "# Oś czasu" in background
    assert "pominięto 1 wcześniejszych sesji" in background
    assert "## Sesja 1" not in background
    assert "## Sesja 2\n* wydarzenie 2" in background
    assert "## Sesja 1" in render_background(context, recent_sessions=0)
