from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("rpgnotes")


def load_mapping(mapping_file: Path) -> dict[str, str]:
    """Load a Discord-username → character-name mapping. Empty dict if missing."""
    try:
        with mapping_file.open(encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        log.warning("Mapping file '%s' not found. Using raw Discord usernames.", mapping_file)
        return {}
    if not isinstance(data, dict):
        log.warning("Mapping file '%s' is not a JSON object. Using raw Discord usernames.", mapping_file)
        return {}
    return {str(k): str(v) for k, v in data.items()}


def extract_speaker(json_file: Path, mapping: dict[str, str]) -> str:
    """
    Extract and map a speaker name from a Craig-bot per-user filename.

    Expected stem: ``<snowflake_id>-<DiscordUser>_<discriminator>`` — falls back
    gracefully at each parsing stage if the shape is unexpected.
    """
    stem = json_file.stem
    parts = stem.split("-", 1)
    if len(parts) < 2:
        log.warning(
            "Unexpected filename format '%s' — could not split on '-'. Using full stem.",
            json_file.name,
        )
        return stem

    raw_user_part = parts[1].lstrip("_")
    discord_user = raw_user_part.split("_")[0]

    if not discord_user:
        log.warning(
            "Empty discord username parsed from '%s'. Using raw segment '%s'.",
            json_file.name,
            raw_user_part,
        )
        return raw_user_part or stem

    if discord_user not in mapping:
        log.warning(
            "Discord user '%s' not found in mapping. Using raw username as speaker label.",
            discord_user,
        )

    return mapping.get(discord_user, discord_user)
