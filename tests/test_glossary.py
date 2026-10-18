from __future__ import annotations

from rpgnotes.campaign import CampaignContext, Entity
from rpgnotes.summarize.glossary import build_session_glossary


def _context(**kwargs: object) -> CampaignContext:
    return CampaignContext.model_validate(
        {
            "entities": {
                "people": [
                    {"name": "Sybolkorax", "aliases": ["Sybol Korax"]},
                    {"name": "Acastus"},
                ],
                "locations": [{"name": "Mytros"}],
            },
            **kwargs,
        }
    )


def test_glossary_includes_names_and_aliases() -> None:
    glossary = build_session_glossary(_context())
    assert "Sybolkorax" in glossary
    assert "Sybol Korax" in glossary  # alias
    assert "Acastus" in glossary
    assert "Mytros" in glossary
    assert glossary.index("## Postacie") < glossary.index("## Lokacje")


def test_glossary_includes_phonetic_corrections() -> None:
    glossary = build_session_glossary(
        _context(phonetic_corrections="| Pytrion | **Raspytrion** |")
    )
    assert "Raspytrion" in glossary


def test_glossary_without_phonetic_corrections() -> None:
    context = _context(phonetic_corrections="| Pytrion | **Raspytrion** |")
    assert "Raspytrion" not in build_session_glossary(context, include_phonetic=False)


def test_glossary_degrades_gracefully_when_context_empty() -> None:
    assert build_session_glossary(CampaignContext()) == ""


def test_glossary_works_with_only_phonetic_corrections() -> None:
    glossary = build_session_glossary(CampaignContext(phonetic_corrections="| a | **B** |"))
    assert "**B**" in glossary


def test_glossary_without_aliases_lists_names_only() -> None:
    glossary = build_session_glossary(_context(), include_aliases=False)
    assert "Sybolkorax" in glossary
    assert "Sybol Korax" not in glossary
    assert "aliasy" not in glossary


def test_glossary_ignores_unknown_categories() -> None:
    context = CampaignContext(entities={"other": [Entity(name="Ktoś")]})
    assert "Ktoś" not in build_session_glossary(context)
