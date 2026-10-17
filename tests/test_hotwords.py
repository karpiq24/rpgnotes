from __future__ import annotations

from pathlib import Path

from rpgnotes.transcribe.hotwords import pack_hotwords, parse_hotwords_file, recent_timeline_names


def _count_words(text: str) -> int:
    return len(text.replace(",", " ").split())


def test_parse_hotwords_file_ignores_comments_and_blank_entries() -> None:
    text = "# komentarz\nArevon, Felicjan\n\nKentimane  # tytan\n, ,Sydon"
    assert parse_hotwords_file(text) == ["Arevon", "Felicjan", "Kentimane", "Sydon"]


def test_pack_hotwords_keeps_priority_order_within_budget() -> None:
    packed = pack_hotwords(["Arevon", "Kentimane", "Lutheria", "Sydon"], _count_words, budget=3)
    assert packed == "Arevon, Kentimane, Lutheria"


def test_pack_hotwords_skips_too_long_names_but_keeps_shorter_ones() -> None:
    packed = pack_hotwords(
        ["Arevon", "Kryształowa Kosa Lutherii", "Sydon"], _count_words, budget=3
    )
    assert packed == "Arevon, Sydon"


def test_pack_hotwords_dedupes_and_skips_names_already_covered() -> None:
    packed = pack_hotwords(
        ["Felicjan", "felicjan", "Felicjan Janus Twardowski", "Orion Xul"], _count_words, budget=50
    )
    assert packed == "Felicjan, Orion Xul"


def test_recent_timeline_names_ranks_recent_links(tmp_path: Path) -> None:
    (tmp_path / "Timeline.md").write_text(
        "# Oś czasu\n\n"
        "## Sesja 1\n* [[Stary NPC]] coś robi.\n\n"
        "## Sesja 2\n* [[Kentimane]] i [[Sydon|Sydona]] oraz [[Sesja 1 - Start|wcześniej]].\n\n"
        "## Sesja 3\n* [[Kentimane|Tytan]] atakuje, [[Nephele (Smok)|Nephele]] leci.\n",
        encoding="utf-8",
    )
    names = recent_timeline_names(tmp_path, recent_sessions=2)
    assert names[0] == "Kentimane"  # linked twice
    assert set(names) == {"Kentimane", "Sydon", "Nephele"}  # parenthetical stripped


def test_recent_timeline_names_degrades_gracefully(tmp_path: Path) -> None:
    assert recent_timeline_names(tmp_path, recent_sessions=3) == []
    (tmp_path / "Timeline.md").write_text("## Sesja 1\n* [[Sydon]]\n", encoding="utf-8")
    assert recent_timeline_names(tmp_path, recent_sessions=0) == []
