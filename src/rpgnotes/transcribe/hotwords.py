from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable

from ..campaign import CampaignContext

# faster-whisper prepends hotwords to EVERY decode window (unlike
# `initial_prompt`, which only reaches the first window when
# condition_on_previous_text=False). The prompt shares Whisper's 448-token
# decoder budget with the window's own output, so keep it well below the
# library's 223-token cap.
HOTWORDS_TOKEN_BUDGET = 150

_PARENTHETICAL = re.compile(r"\s*\([^)]*\)")


def recent_timeline_names(context: CampaignContext, recent_sessions: int) -> list[str]:
    """Entity names linked in the last `recent_sessions` timeline sessions, most-linked first.

    Parenthetical disambiguators ("Nephele (Smok)") are stripped — Whisper
    only needs the spoken form.
    """
    if recent_sessions <= 0:
        return []
    counts: Counter[str] = Counter()
    for session in context.timeline[-recent_sessions:]:
        for target in session.links:
            name = _PARENTHETICAL.sub("", target).strip()
            if name:
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
