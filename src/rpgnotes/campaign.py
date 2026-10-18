"""The campaign context file: everything rpgnotes knows about the campaign.

The wiki (OotD) exports it as `campaign_context.json` (its
`scripts/export_context.py`); rpgnotes reads only this file and never the wiki
itself, so the wiki's folder layout can change freely. Without the file the
pipeline still runs, just without names, party or background.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

log = logging.getLogger("rpgnotes")

SCHEMA_VERSION = 1

# Entity categories in the export, in the order the glossary lists them.
ENTITY_CATEGORIES = {
    "people": "## Postacie / Frakcje",
    "locations": "## Lokacje",
    "items": "## Przedmioty",
    "lore": "## Lore / koncepcje świata",
}


class CampaignContextError(RuntimeError):
    """The context file exists but cannot be used (bad JSON or unknown schema)."""


class Entity(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)


class PartyMember(BaseModel):
    name: str
    # One line in the wiki's words, e.g. "Minotaur Barbarian, The Doomed One".
    description: str = ""


class TimelineSession(BaseModel):
    heading: str
    text: str
    # Canonical names of the entities linked in this session's events.
    links: list[str] = Field(default_factory=list)


class CampaignContext(BaseModel):
    schema_version: int = SCHEMA_VERSION
    party: list[PartyMember] = Field(default_factory=list)
    entities: dict[str, list[Entity]] = Field(default_factory=dict)
    phonetic_corrections: str = ""
    # Campaign-specific rules learned from the user's edits (harvest loop).
    learned_rules: str = ""
    # Names the ASR gets wrong, in priority order.
    hotwords: list[str] = Field(default_factory=list)
    campaign_context: str = ""
    timeline_preamble: str = ""
    timeline: list[TimelineSession] = Field(default_factory=list)


def load_campaign_context(path: Path | None) -> CampaignContext:
    """Read the context file; an empty context when it is unset, missing or empty.

    Raises `CampaignContextError` for a file that exists but is broken or has a
    schema version this code does not know: running on a misread context would
    silently produce a worse draft.
    """
    if path is None:
        log.warning("CAMPAIGN_CONTEXT_FILE is not set. Running without campaign context.")
        return CampaignContext()
    if not path.is_file():
        # Docker Compose creates a missing bind-mount source as an empty dir.
        log.warning("Campaign context %s not found. Running without campaign context.", path)
        return CampaignContext()
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        log.warning("Campaign context %s is empty. Running without campaign context.", path)
        return CampaignContext()
    try:
        context = CampaignContext.model_validate_json(raw)
    except ValidationError as e:
        raise CampaignContextError(f"Campaign context {path} is invalid: {e}") from e
    if context.schema_version != SCHEMA_VERSION:
        raise CampaignContextError(
            f"Campaign context {path} has schema version {context.schema_version}, "
            f"this rpgnotes reads version {SCHEMA_VERSION}. Update one of the two repos."
        )
    return context


def render_party(context: CampaignContext) -> str:
    if not context.party:
        return ""
    lines = ["# Drużyna (postacie graczy)"]
    for member in context.party:
        line = f"- **{member.name}**"
        if member.description:
            line += f" — {member.description}"
        lines.append(line)
    return "\n".join(lines)


def render_learned_rules(context: CampaignContext) -> str:
    rules = context.learned_rules.strip()
    return f"# Reguły tej kampanii\n\n{rules}" if rules else ""


def render_campaign_rules(context: CampaignContext) -> str:
    """Party + learned rules: the campaign part of every prompt."""
    return "\n\n".join(part for part in (render_party(context), render_learned_rules(context)) if part)


def render_background(context: CampaignContext, recent_sessions: int = 0) -> str:
    """Campaign summary plus the last `recent_sessions` timeline sections (0 = all)."""
    parts: list[str] = []
    if context.campaign_context.strip():
        parts.append(context.campaign_context.strip())
    sessions = context.timeline
    if sessions:
        skipped = 0
        if 0 < recent_sessions < len(sessions):
            skipped = len(sessions) - recent_sessions
            sessions = sessions[-recent_sessions:]
        timeline = [context.timeline_preamble.strip()] if context.timeline_preamble.strip() else []
        if skipped:
            timeline.append(f"(pominięto {skipped} wcześniejszych sesji)")
        timeline.extend(f"{s.heading}\n{s.text.strip()}" for s in sessions)
        parts.append("\n\n".join(timeline))
    return "\n\n".join(parts)
