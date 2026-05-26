from __future__ import annotations

HALLUCINATION_BLOCKLIST: frozenset[str] = frozenset(
    {
        # Whisper / YouTube subtitle artifacts
        "napisy by",
        "napisy stworzone przez",
        "napisy pobrane z",
        "jacek makarewicz",
        "subtitles by",
        "subtitle by",
        "captioned by",
        "translated by",
        "amara.org",
        "org community",
        "ted.com",
        "ted talks",
        # YouTube outros
        "dzięki za oglądanie",
        "dziękuję za oglądanie",
        "thanks for watching",
        "proszę o subskrypcję",
        "nie zapomnij zasubskrybować",
        "kliknij dzwoneczek",
        "like, share and subscribe",
        # Copyright / legal
        "wszelkie prawa zastrzeżone",
        "all rights reserved",
        "copyright",
        # Unicode glitches
        "ï¿½",
        "â",
        # Audio descriptions
        "[muzyka]",
        "(muzyka)",
        "[cisza]",
        "(cisza)",
        "[music]",
        "(music)",
    }
)


def is_hallucination(text: str) -> bool:
    """Return True if `text` matches a known Whisper hallucination pattern."""
    lowered = text.lower()
    return any(phrase in lowered for phrase in HALLUCINATION_BLOCKLIST)
