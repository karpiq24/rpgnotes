from __future__ import annotations

import re
import unicodedata

# Matched against the text folded to lowercase ASCII (`fold`): Whisper writes
# the same outro with and without diacritics ("Dziękuje za oglądanie!").
HALLUCINATION_BLOCKLIST: frozenset[str] = frozenset(
    {
        # Whisper / YouTube subtitle artifacts
        "napisy by",
        "napisy stworzone przez",
        "napisy pobrane z",
        "napisy wykonane",
        "napisy-",
        "wytfurnia",
        "wytwornia.pl",
        "jacek makarewicz",
        "subtitles by",
        "subtitle by",
        "captioned by",
        "translated by",
        "amara.org",
        "org community",
        "ted.com",
        "ted talks",
        "zdjecia i montaz",
        # YouTube outros
        "dzieki za ogladanie",
        "dziekuje za ogladanie",
        "dziekujemy za ogladanie",
        "thanks for watching",
        "wielkie dzieki i do zobaczenia",
        "do zobaczenia w kolejnym",
        "do zobaczenia w kolejnych",
        "do zobaczenia w nastepnym",
        "do zobaczenia na kolejnym",
        "w kolejnym odcinku",
        "w kolejnych odcinkach",
        "w nastepnym odcinku",
        "dziekuje za uwage",
        "proszę o subskrypcje",
        "subskrybuj",
        "zasubskrybowac",
        "kliknij dzwoneczek",
        "like, share and subscribe",
        # Copyright / legal
        "wszelkie prawa zastrzezone",
        "wszystkie prawa zastrzezone",
        "all rights reserved",
        "copyright",
        # Audio descriptions
        "[muzyka]",
        "(muzyka)",
        "[cisza]",
        "(cisza)",
        "[music]",
        "(music)",
    }
)
# Mojibake: matched against the raw text (folding would turn "â" into "a").
_RAW_GLITCHES = ("ï¿½", "â")


def fold(text: str) -> str:
    """Lowercase without diacritics (ł → l), for matching Whisper's spelling variants."""
    decomposed = unicodedata.normalize("NFD", text.lower().replace("ł", "l"))
    return "".join(c for c in decomposed if not unicodedata.combining(c))


_FOLDED_BLOCKLIST = tuple(sorted({fold(p) for p in HALLUCINATION_BLOCKLIST}))
# A whole segment that is only "KONIEC" (a film's end card), or one letter
# held for six or more characters ("Yyyyyyyyyy").
_WHOLE = re.compile(r"\W*koniec\W*")
_HELD_LETTER = re.compile(r"(\w)\1{5,}")


def is_hallucination(text: str) -> bool:
    """Return True if `text` matches a known Whisper hallucination pattern."""
    folded = fold(text)
    return (
        any(glitch in text for glitch in _RAW_GLITCHES)
        or any(phrase in folded for phrase in _FOLDED_BLOCKLIST)
        or _WHOLE.fullmatch(folded) is not None
        or _HELD_LETTER.search(folded) is not None
    )
