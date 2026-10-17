from __future__ import annotations

import logging
import re
from collections import defaultdict
from pathlib import Path

log = logging.getLogger("rpgnotes")

# Entity sub-directories inside the campaign context dir (OotD wiki layout).
# Canonical names are the markdown filenames (minus ".md") under these dirs.
_ENTITY_DIRS = ("02-People", "03-Locations", "04-Items-and-Loot", "05-Lore")
_WIKILINK = re.compile(r"\[\[([^\]|]+)\|([^\]]+)\]\]")

_CATEGORY_LABELS = {
    "02-People": "## Postacie / Frakcje",
    "03-Locations": "## Lokacje",
    "04-Items-and-Loot": "## Przedmioty",
    "05-Lore": "## Lore / koncepcje świata",
}


def _collect_canonical_names(context_dir: Path) -> dict[str, list[str]]:
    """Return {category_dir: [canonical name, ...]} from entity markdown files."""
    result: dict[str, list[str]] = {}
    for entity_dir in _ENTITY_DIRS:
        base = context_dir / entity_dir
        if not base.is_dir():
            continue
        names = {
            path.stem
            for path in base.rglob("*.md")
            if path.name != "index.md"
        }
        if names:
            result[entity_dir] = sorted(names)
    return result


def _collect_aliases(context_dir: Path) -> dict[str, set[str]]:
    """Harvest `[[Canonical|Alias]]` aliases from every markdown file."""
    aliases: dict[str, set[str]] = defaultdict(set)
    for path in context_dir.rglob("*.md"):
        if "assets" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for match in _WIKILINK.finditer(text):
            canonical = match.group(1).strip()
            alias = match.group(2).strip()
            if alias and alias != canonical:
                aliases[canonical].add(alias)
    return aliases


def _load_phonetic_corrections(path: Path | None) -> str:
    if path is None:
        return ""
    if not path.exists():
        log.warning("Phonetic corrections file not found at %s. Skipping.", path)
        return ""
    if not path.is_file():
        # Docker Compose silently creates a missing bind-mount source as an
        # empty directory, so a stale host path shows up here as a dir.
        log.warning("Phonetic corrections path %s is not a file. Skipping.", path)
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as e:
        log.warning("Could not read phonetic corrections file %s: %s", path, e)
        return ""


def build_session_glossary(
    context_dir: Path,
    phonetic_corrections_file: Path | None = None,
    include_aliases: bool = True,
) -> str:
    """Build a session glossary block for embedding into chunk system prompts.

    Combines every canonical entity name harvested from `context_dir` with the
    phonetic-corrections knowledge base. Names are deliberately NOT filtered by
    what appears in the transcript: the names worth listing are exactly the
    ones the ASR mangles ("Cant i main" → Kentimane, "Seidon" → Sydon), so a
    transcript filter drops them (measured: ~27% of entities linked in final
    recaps were missing). The full list is only a few thousand tokens.
    Degrades gracefully: any missing source is simply omitted.
    """
    by_category = _collect_canonical_names(context_dir)
    aliases = _collect_aliases(context_dir) if by_category and include_aliases else {}

    sections: list[str] = []
    for category, label in _CATEGORY_LABELS.items():
        names = by_category.get(category, [])
        if not names:
            continue
        lines = [label]
        for name in names:
            line = f"- **{name}**"
            if aliases.get(name):
                line += f" — aliasy: {', '.join(sorted(aliases[name]))}"
            lines.append(line)
        sections.append("\n".join(lines))

    phonetic = _load_phonetic_corrections(phonetic_corrections_file)

    if not sections and not phonetic:
        log.info("Session glossary is empty (no entity dirs or phonetic file).")
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
