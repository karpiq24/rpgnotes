from __future__ import annotations

from pathlib import Path

from rpgnotes.summarize.glossary import build_session_glossary


def _make_context(tmp_path: Path) -> Path:
    ctx = tmp_path / "context"
    people = ctx / "02-People"
    locations = ctx / "03-Locations"
    people.mkdir(parents=True)
    locations.mkdir(parents=True)
    (people / "Sybolkorax.md").write_text("Smok.", encoding="utf-8")
    (people / "Acastus.md").write_text("Król.", encoding="utf-8")
    (people / "index.md").write_text("nie-encja", encoding="utf-8")
    (locations / "Mytros.md").write_text("Stolica.", encoding="utf-8")
    # Alias harvested from a wikilink elsewhere in the context.
    (ctx / "Campaign_Context.md").write_text(
        "Widzieli [[Sybolkorax|Sybol Korax]] nad miastem.", encoding="utf-8"
    )
    return ctx


def test_glossary_includes_names_and_aliases(tmp_path: Path) -> None:
    ctx = _make_context(tmp_path)
    glossary = build_session_glossary(ctx, phonetic_corrections_file=None)
    assert "Sybolkorax" in glossary
    assert "Sybol Korax" in glossary  # alias
    assert "Acastus" in glossary
    assert "Mytros" in glossary
    assert "index" not in glossary


def test_glossary_filters_by_transcript(tmp_path: Path) -> None:
    ctx = _make_context(tmp_path)
    transcript = "[Orestes]\nWidzę Sybolkoraxa na horyzoncie!"
    glossary = build_session_glossary(ctx, transcript_content=transcript)
    assert "Sybolkorax" in glossary  # inflected form matched by prefix
    assert "Acastus" not in glossary
    assert "Mytros" not in glossary


def test_glossary_includes_phonetic_corrections(tmp_path: Path) -> None:
    ctx = _make_context(tmp_path)
    phonetic = tmp_path / "phonetic_corrections.md"
    phonetic.write_text("| Pytrion | **Raspytrion** |", encoding="utf-8")
    glossary = build_session_glossary(ctx, phonetic_corrections_file=phonetic)
    assert "Raspytrion" in glossary


def test_glossary_degrades_gracefully_when_sources_missing(tmp_path: Path) -> None:
    empty_ctx = tmp_path / "nope"
    missing_phonetic = tmp_path / "missing.md"
    glossary = build_session_glossary(empty_ctx, phonetic_corrections_file=missing_phonetic)
    assert glossary == ""


def test_glossary_works_with_only_phonetic_file(tmp_path: Path) -> None:
    phonetic = tmp_path / "phonetic_corrections.md"
    phonetic.write_text("| Wersir | **Versir** |", encoding="utf-8")
    glossary = build_session_glossary(tmp_path / "nope", phonetic_corrections_file=phonetic)
    assert "Versir" in glossary
    assert glossary.startswith("# Glosariusz sesji")
