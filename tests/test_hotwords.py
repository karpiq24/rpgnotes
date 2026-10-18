from __future__ import annotations

from rpgnotes.campaign import CampaignContext, TimelineSession
from rpgnotes.transcribe.hotwords import pack_hotwords, recent_timeline_names


def _count_words(text: str) -> int:
    return len(text.replace(",", " ").split())


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


def _timeline(*links: list[str]) -> CampaignContext:
    return CampaignContext(
        timeline=[
            TimelineSession(heading=f"## Sesja {n}", text="", links=names)
            for n, names in enumerate(links, start=1)
        ]
    )


def test_recent_timeline_names_ranks_recent_links() -> None:
    context = _timeline(
        ["Stary NPC"],
        ["Kentimane", "Sydon"],
        ["Kentimane", "Nephele (Smok)"],
    )
    names = recent_timeline_names(context, recent_sessions=2)
    assert names[0] == "Kentimane"  # linked twice
    assert set(names) == {"Kentimane", "Sydon", "Nephele"}  # parenthetical stripped


def test_recent_timeline_names_degrades_gracefully() -> None:
    assert recent_timeline_names(CampaignContext(), recent_sessions=3) == []
    assert recent_timeline_names(_timeline(["Sydon"]), recent_sessions=0) == []
