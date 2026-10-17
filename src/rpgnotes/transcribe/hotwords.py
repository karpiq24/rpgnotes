from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Callable, Iterable
from pathlib import Path

log = logging.getLogger("rpgnotes")

# faster-whisper prepends hotwords to EVERY decode window (unlike
# `initial_prompt`, which only reaches the first window when
# condition_on_previous_text=False). The prompt shares Whisper's 448-token
# decoder budget with the window's own output, so keep it well below the
# library's 223-token cap.
HOTWORDS_TOKEN_BUDGET = 150

_WIKILINK_TARGET = re.compile(r"\[\[([^\]|#]+)")
_PARENTHETICAL = re.compile(r"\s*\([^)]*\)")


def parse_hotwords_file(text: str) -> list[str]:
    """Split a hotwords file into names: comma/newline separated, `#` comments ignored."""
    names: list[str] = []
    for line in text.splitlines():
        line = line.split("#", 1)[0]
        names.extend(part.strip() for part in line.split(","))
    return [name for name in names if name]


def recent_timeline_names(context_dir: Path, recent_sessions: int) -> list[str]:
    """Entity names linked in the last `recent_sessions` sections of Timeline.md, most-linked first.

    Parenthetical disambiguators ("Nephele (Smok)") are stripped — Whisper
    only needs the spoken form. Links to session notes are skipped.
    """
    timeline = context_dir / "Timeline.md"
    if recent_sessions <= 0 or not timeline.is_file():
        return []
    try:
        content = timeline.read_text(encoding="utf-8")
    except OSError as e:
        log.warning("Could not read %s for Whisper hotwords: %s", timeline, e)
        return []
    sections = re.split(r"(?m)^(?=## )", content)[1:]
    counts: Counter[str] = Counter()
    for section in sections[-recent_sessions:]:
        for target in _WIKILINK_TARGET.findall(section):
            name = _PARENTHETICAL.sub("", target).strip()
            if name and not name.startswith("Sesja "):
                counts[name] += 1
    return [name for name, _ in counts.most_common()]


def pack_hotwords(
    names: Iterable[str],
    count_tokens: Callable[[str], int],
    budget: int = HOTWORDS_TOKEN_BUDGET,
) -> str:
    """Join unique names with ", " in priority order, keeping whole names within `budget` tokens.

    A name whose first word is already listed ("Felicjan Janus Twardowski"
    after "Felicjan") is skipped — Whisper already has the hard part.
    """
    packed: list[str] = []
    seen: set[str] = set()
    for name in names:
        key = name.strip().casefold()
        if not key or key in seen or key.split()[0] in seen:
            continue
        candidate = ", ".join([*packed, name])
        if count_tokens(candidate) > budget:
            continue
        packed.append(name)
        seen.add(key)
    return ", ".join(packed)
