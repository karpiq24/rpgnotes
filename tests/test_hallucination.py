from __future__ import annotations

import pytest

from rpgnotes.hallucination import HALLUCINATION_BLOCKLIST, is_hallucination


@pytest.mark.parametrize(
    "text",
    [
        "Napisy by Jacek Makarewicz",
        "Subtitles by Amara.org community",
        "Dziękuję za oglądanie!",
        "Thanks for watching, like and subscribe",
        "Wszelkie prawa zastrzeżone",
        "[Muzyka]",
        "(music)",
        "Some intro... amara.org community ...some outro",
    ],
)
def test_known_hallucinations_match(text: str) -> None:
    assert is_hallucination(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Dobra, atakuję smoka mieczem.",
        "Wchodzę do tawerny.",
        "I cast fireball at the goblin.",
        "",
    ],
)
def test_real_dialogue_passes(text: str) -> None:
    assert is_hallucination(text) is False


def test_blocklist_is_non_empty() -> None:
    # Sanity check — guard against accidental clearing of the set.
    assert len(HALLUCINATION_BLOCKLIST) > 10
