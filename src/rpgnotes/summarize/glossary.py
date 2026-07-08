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


def _name_appears(name: str, aliases: dict[str, set[str]], transcript_lower: str) -> bool:
    """Whether `name` (or an alias) plausibly appears in the transcript.

    Polish names are heavily inflected ("Sybolkorax" -> "Sybolkoraxa") and the
    transcript may split compound names, so we match a 5-char prefix of the
    first word rather than the whole name. With no transcript, keep everything.
    """
    if not transcript_lower:
        return True
    for candidate in (name, *aliases.get(name, set())):
        words = candidate.split()
        if not words:
            continue
        first = words[0].lower()
        if len(first) >= 5 and first[:5] in transcript_lower:
            return True
    return False


def _load_phonetic_corrections(path: Path | None) -> str:
    if path is None:
        return ""
    if not path.exists():
        log.warning("Phonetic corrections file not found at %s. Skipping.", path)
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as e:
        log.warning("Could not read phonetic corrections file %s: %s", path, e)
        return ""


def build_session_glossary(
    context_dir: Path,
    phonetic_corrections_file: Path | None = None,
    transcript_content: str = "",
) -> str:
    """Build a session glossary block for embedding into chunk system prompts.

    Combines canonical entity names harvested from `context_dir` (filtered to
    those appearing in the transcript) with the phonetic-corrections knowledge
    base. Degrades gracefully: any missing source is simply omitted.
    """
    transcript_lower = transcript_content.lower()
    by_category = _collect_canonical_names(context_dir)
    aliases = _collect_aliases(context_dir) if by_category else {}

    sections: list[str] = []
    for category, label in _CATEGORY_LABELS.items():
        names = by_category.get(category, [])
        matched = [n for n in names if _name_appears(n, aliases, transcript_lower)]
        if not matched:
            continue
        lines = [label]
        for name in matched:
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
