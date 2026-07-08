from __future__ import annotations

import datetime as _dt
import json
import logging
import re
from html.parser import HTMLParser
from pathlib import Path

from pydantic import BaseModel

from .visual import format_offset

log = logging.getLogger("rpgnotes")

# Speakers/content that carry no session information (Foundry module chatter).
_NOISE_SPEAKERS = {"Tidbits"}
_NOISE_MARKERS = ("Welcome to Plutonium",)

_ROLL_MARKERS = ("dice-roll", "inline-roll", "dice-total", "midi-qol", "chat-damage")

_MAX_TEXT_CHARS = 400
_MAX_ROLL_FLAVOR_CHARS = 200


class ChatEvent(BaseModel):
    """One distilled FoundryVTT chat message on the recording timeline.

    `offset_secs` counts from the Craig recording start (the same anchor the
    transcript and `[VISUAL]` lines use); negative means before the recording.
    """

    offset_secs: float
    speaker: str
    kind: str  # "roll" | "chat"
    text: str


class _TextExtractor(HTMLParser):
    """Flatten Foundry chat HTML to plain text, one space between elements."""

    _SKIP_TAGS = {"style", "script"}

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data.strip():
            self._parts.append(data.strip())

    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._parts)).strip()


class _RollExtractor(HTMLParser):
    """Collect dice formulas and totals (Foundry + Beyond20 markup) in order."""

    def __init__(self) -> None:
        super().__init__()
        self.items: list[tuple[str, str]] = []  # ("formula" | "total", text)
        self._capture: str | None = None
        self._depth = 0
        self._buffer: list[str] = []

    @staticmethod
    def _kind_for(classes: str) -> str | None:
        if "dice-formula" in classes:
            return "formula"
        if "dice-total" in classes or "beyond20-total-damage" in classes:
            return "total"
        return None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._capture is not None:
            self._depth += 1
            return
        classes = dict(attrs).get("class") or ""
        kind = self._kind_for(classes)
        if kind is not None:
            self._capture = kind
            self._depth = 1
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if self._capture is None:
            return
        self._depth -= 1
        if self._depth <= 0:
            text = re.sub(r"\s+", " ", " ".join(self._buffer)).strip()
            if text:
                self.items.append((self._capture, text))
            self._capture = None

    def handle_data(self, data: str) -> None:
        if self._capture is not None and data.strip():
            self._buffer.append(data.strip())


def _extract_rolls(content: str) -> str:
    """Render the rolls in a chat message as 'formula = total, …'.

    Formulas are paired with the next total that follows them; a total without
    a preceding formula stands alone. Returns "" when the message has no
    recognizable dice markup.
    """
    extractor = _RollExtractor()
    try:
        extractor.feed(content)
        extractor.close()
    except Exception:
        return ""
    rendered: list[str] = []
    pending_formula: str | None = None
    for kind, text in extractor.items:
        if kind == "formula":
            if pending_formula is not None:
                rendered.append(pending_formula)
            pending_formula = text
        elif pending_formula is not None:
            rendered.append(f"{pending_formula} = {text}")
            pending_formula = None
        else:
            rendered.append(f"= {text}")
    if pending_formula is not None:
        rendered.append(pending_formula)
    return ", ".join(rendered)


def _strip_html(content: str) -> str:
    extractor = _TextExtractor()
    try:
        extractor.feed(content)
        extractor.close()
    except Exception:  # malformed HTML — fall back to a crude tag strip
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", content)).strip()
    return extractor.text()


def _parse_timestamp(raw: str) -> float | None:
    try:
        return _dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def extract_chat_events(chat_log_file: Path, recording_start: int | None) -> list[ChatEvent]:
    """Distill a Foundry chat archive into compact, timeline-anchored events.

    Module noise (Tidbits trivia, Plutonium banners) and empty messages are
    dropped; everything else keeps its speaker, a roll/chat classification and
    the flattened text (dice formulas and totals survive the flattening, so
    exact damage numbers stay queryable). Without `recording_start` the first
    message is used as t=0 with a logged warning.
    """
    data = json.loads(chat_log_file.read_text(encoding="utf-8"))
    messages = data.get("messages", []) if isinstance(data, dict) else data

    timestamps = [
        ts
        for message in messages
        if isinstance(message, dict) and (ts := _parse_timestamp(str(message.get("timestamp", ""))))
    ]
    anchor: float
    if recording_start is not None:
        anchor = float(recording_start)
    elif timestamps:
        anchor = min(timestamps)
        log.warning(
            "No recording start available — using the first chat message as t=0. "
            "Chat offsets may drift from the transcript."
        )
    else:
        log.warning("Chat log %s has no usable timestamps.", chat_log_file)
        return []

    events: list[ChatEvent] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        speaker = str(message.get("speaker") or "").strip()
        content = str(message.get("content") or "")
        ts = _parse_timestamp(str(message.get("timestamp", "")))
        if ts is None or speaker in _NOISE_SPEAKERS:
            continue
        if any(marker in content for marker in _NOISE_MARKERS):
            continue
        text = _strip_html(content)
        if not text:
            continue
        kind = "roll" if any(marker in content for marker in _ROLL_MARKERS) else "chat"
        if kind == "roll":
            # Keep only a short flavor snippet; the numbers that matter come
            # from the structured markup, so long item descriptions can never
            # push the totals past the truncation point.
            rolls = _extract_rolls(content)
            if len(text) > _MAX_ROLL_FLAVOR_CHARS:
                text = text[: _MAX_ROLL_FLAVOR_CHARS - 1] + "…"
            if rolls:
                text += f" | rzuty: {rolls}"
        elif len(text) > _MAX_TEXT_CHARS:
            text = text[: _MAX_TEXT_CHARS - 1] + "…"
        events.append(
            ChatEvent(
                offset_secs=ts - anchor,
                speaker=speaker or "?",
                kind=kind,
                text=text,
            )
        )

    events.sort(key=lambda event: event.offset_secs)
    log.info("Distilled %d chat event(s) from %d message(s).", len(events), len(messages))
    return events


def format_chat_events(events: list[ChatEvent]) -> str:
    """Human/AI-readable one-line-per-event rendering with recording offsets."""
    lines = []
    for event in events:
        stamp = (
            f"[{format_offset(event.offset_secs)}]"
            if event.offset_secs >= 0
            else "[PRZED NAGRANIEM]"
        )
        tag = " (rzut)" if event.kind == "roll" else ""
        lines.append(f"{stamp} {event.speaker}{tag}: {event.text}")
    return "\n".join(lines) + ("\n" if lines else "")


def write_chat_events(
    events: list[ChatEvent], json_file: Path, txt_file: Path
) -> None:
    json_file.parent.mkdir(parents=True, exist_ok=True)
    json_file.write_text(
        json.dumps([event.model_dump() for event in events], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    txt_file.write_text(format_chat_events(events), encoding="utf-8")
    log.info("Chat events saved to %s and %s.", json_file, txt_file)
