"""Session files saved by the RPG Notes Recorder Foundry module (foundry/rpgnotes-recorder).

The file replaces both the chat archive macro and the screenshot script: one
`session<NN>.json` with structured events (chat, rolls, scenes, combat,
handouts, music) and embedded map snapshots. It keeps the macro's `title` and
`archiveDate` keys, so session discovery works unchanged.
"""

from __future__ import annotations

import base64
import binascii
import datetime as _dt
import logging
from pathlib import Path
from typing import Any

from .chatevents import ChatEvent

log = logging.getLogger("rpgnotes")

FORMAT = "rpgnotes-foundry"

_MIME_SUFFIX = {"image/webp": ".webp", "image/png": ".png", "image/jpeg": ".jpg"}
_ROLL_TYPES = {"roll", "attack", "damage", "save", "check", "skill", "tool", "ability", "death"}


def is_foundry_export(data: object) -> bool:
    return isinstance(data, dict) and data.get("format") == FORMAT


def without_snapshot_data(data: dict[str, Any]) -> dict[str, Any]:
    """The export minus the embedded images (for the copy kept in the wiki)."""
    snapshots = [
        {key: value for key, value in shot.items() if key != "data"}
        for shot in data.get("snapshots", [])
        if isinstance(shot, dict)
    ]
    return {**data, "snapshots": snapshots}


def _timestamp(raw: object) -> float | None:
    try:
        return _dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def extract_snapshots(data: dict[str, Any], out_dir: Path) -> int:
    """Write the embedded snapshots as `shot_<unix_ts>[_key].<ext>` into an emptied `out_dir`.

    Handouts, combat starts and manual `/rpgnotes key` frames are key frames
    (never deduped away). Returns the number of files written.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("shot_*"):
        old.unlink()
    written = 0
    for shot in data.get("snapshots", []):
        if not isinstance(shot, dict):
            continue
        ts = _timestamp(shot.get("t"))
        header, _, payload = str(shot.get("data", "")).partition(",")
        mime = header.removeprefix("data:").removesuffix(";base64")
        if ts is None or mime not in _MIME_SUFFIX:
            continue
        try:
            image = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError):
            log.warning("Skipping a snapshot with broken image data at %s.", shot.get("t"))
            continue
        second = int(ts)
        suffix = ("_key" if shot.get("key") else "") + _MIME_SUFFIX[mime]
        while (out_dir / f"shot_{second}{suffix}").exists():
            second += 1  # two snapshots in the same second
        (out_dir / f"shot_{second}{suffix}").write_bytes(image)
        written += 1
    return written


def _roll_text(rolls: list[dict[str, Any]]) -> str:
    parts = []
    for roll in rolls:
        text = f"{roll.get('formula', '?')} = {roll.get('total', '?')}"
        if roll.get("damageType"):
            text += f" {roll['damageType']}"
        if roll.get("target") is not None:
            text += f" (ST {roll['target']})"
        if roll.get("critical"):
            text += " KRYTYK"
        if roll.get("fumble"):
            text += " PORAŻKA"
        parts.append(text)
    return "; ".join(parts)


def _chat_event(event: dict[str, Any]) -> tuple[str, str, str] | None:
    """(speaker, kind, text) for a chat/roll event, or None when it carries nothing."""
    speaker = str(event.get("actor") or event.get("speaker") or event.get("user") or "?")
    prefixes = []
    if event.get("whisperTo"):
        prefixes.append(f"(szept do: {', '.join(event['whisperTo'])})")
    if event.get("blind"):
        prefixes.append("(ukryty rzut)")
    if event.get("style") == "ooc":
        prefixes.append("(OOC)")

    message_type = str(event.get("type", "chat"))
    label = event.get("flavor") or " ".join(
        part for part in (event.get("item"), f"({event['activity']})" if event.get("activity") else "") if part
    )
    if message_type == "usage":
        kind, body = "event", f"używa: {label}" if label else ""
    elif event.get("rolls") or message_type in _ROLL_TYPES:
        kind = "roll"
        rolls = _roll_text(event.get("rolls", []))
        body = " | ".join(part for part in (label, f"rzuty: {rolls}" if rolls else "") if part)
    else:
        kind, body = "chat", str(event.get("text") or label or "")
    if not body:
        return None
    return speaker, kind, " ".join([*prefixes, body])


def _world_event(event: dict[str, Any]) -> tuple[str, str, str] | None:
    kind = event.get("kind")
    if kind == "scene":
        return "Scena", "event", f"aktywna scena: {event.get('scene')}"
    if kind == "combat_start":
        combatants = ", ".join(event.get("combatants", []))
        return "Walka", "event", f"początek walki: {combatants}" if combatants else "początek walki"
    if kind == "combat_round":
        return "Walka", "event", f"runda {event.get('round')}"
    if kind == "combat_end":
        return "Walka", "event", f"koniec walki po {event.get('rounds')} rundach"
    if kind == "down":
        return "Walka", "event", f"{event.get('actor')} pada (0 PW)"
    if kind == "handout":
        return "Handout", "event", f"pokazano graczom obraz: {event.get('title') or 'bez tytułu'}"
    if kind == "journal":
        text = f"pokazano graczom dziennik: {event.get('title')}"
        if event.get("text"):
            text += f" — {event['text']}"
        return "Handout", "event", text
    if kind == "music":
        return "Muzyka", "event", f"{event.get('track')} ({event.get('playlist')})"
    return None  # session/player bookkeeping, combat turns


def events_from_export(data: dict[str, Any], recording_start: int | None) -> list[ChatEvent]:
    """Timeline-anchored `ChatEvent`s from the module's events (offsets from `recording_start`)."""
    raw_events = [event for event in data.get("events", []) if isinstance(event, dict)]
    anchor = float(recording_start) if recording_start is not None else _timestamp(data.get("startedAt"))
    if anchor is None:
        log.warning("Foundry export has no usable start time.")
        return []
    if recording_start is None:
        log.warning("No recording start available — using the Foundry recording start as t=0.")

    events: list[ChatEvent] = []
    for event in raw_events:
        ts = _timestamp(event.get("t"))
        rendered = _chat_event(event) if event.get("kind") == "chat" else _world_event(event)
        if ts is None or rendered is None:
            continue
        speaker, kind, text = rendered
        events.append(ChatEvent(offset_secs=ts - anchor, speaker=speaker, kind=kind, text=text))
    events.sort(key=lambda event: event.offset_secs)
    log.info("Read %d event(s) from the Foundry recorder export.", len(events))
    return events
