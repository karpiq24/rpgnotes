from __future__ import annotations

import logging

from ..campaign import ENTITY_CATEGORIES, CampaignContext

log = logging.getLogger("rpgnotes")


def build_session_glossary(
    context: CampaignContext,
    include_aliases: bool = True,
    include_phonetic: bool = True,
) -> str:
    """Build a session glossary block for embedding into chunk system prompts.

    Combines every canonical entity name from the campaign context with the
    phonetic-corrections knowledge base. Names are deliberately NOT filtered by
    what appears in the transcript: the names worth listing are exactly the
    ones the ASR mangles ("Cant i main" → Kentimane, "Seidon" → Sydon), so a
    transcript filter drops them (measured: ~27% of entities linked in final
    recaps were missing). The full list is only a few thousand tokens.
    Degrades gracefully: any missing source is simply omitted.
    """
    sections: list[str] = []
    for category, label in ENTITY_CATEGORIES.items():
        entities = sorted(context.entities.get(category, []), key=lambda e: e.name)
        if not entities:
            continue
        lines = [label]
        for entity in entities:
            line = f"- **{entity.name}**"
            if include_aliases and entity.aliases:
                line += f" — aliasy: {', '.join(sorted(entity.aliases))}"
            lines.append(line)
        sections.append("\n".join(lines))

    phonetic = context.phonetic_corrections.strip() if include_phonetic else ""

    if not sections and not phonetic:
        log.info("Session glossary is empty (no entities or phonetic corrections in the context).")
        return ""

    parts = ["# Glosariusz sesji (nazwy kanoniczne)"]
    parts.append(
        "Te nazwy są kanoniczne — jeśli w transkrypcji widzisz fonetycznie zbliżoną\n"
        "formę, zastosuj wariant z tej listy. Nie wymyślaj imion spoza tej listy\n"
        "i kontekstu kampanii. Pomijaj imiona graczy i terminy mechaniczne."
    )
    parts.extend(sections)
    if phonetic:
        parts.append(phonetic)

    glossary = "\n\n".join(parts).strip() + "\n"
    log.info(
        "Built session glossary: %d categories, phonetic corrections %s.",
        len(sections),
        "included" if phonetic else "absent",
    )
    return glossary
