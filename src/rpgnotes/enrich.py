from __future__ import annotations

import logging
from typing import Any

from .chatevents import ChatEvent
from .visual import VisualEntry, format_offset

log = logging.getLogger("rpgnotes")


def _visual_line(entry: VisualEntry) -> str:
    marker = f"[VISUAL {format_offset(entry.offset_secs)}"
    if entry.is_key:
        marker += " KEY"
    return f"{marker}] {entry.caption}"


def _chat_line(event: ChatEvent, *, pre_recording: bool = False) -> str:
    stamp = (
        "[CZAT PRZED NAGRANIEM]"
        if pre_recording
        else f"[CZAT {format_offset(event.offset_secs)}]"
    )
    tag = " (rzut)" if event.kind == "roll" else ""
    return f"{stamp} {event.speaker}{tag}: {event.text}"


def build_enriched_transcript(
    segments: list[dict[str, Any]],
    visual_entries: list[VisualEntry],
    chat_events: list[ChatEvent],
) -> str:
    """Render one time-sorted transcript with visual and chat annotations.

    Produces the same speaker-header text format as `combine_transcriptions`,
    with `[VISUAL HH:MM:SS] …` and `[CZAT HH:MM:SS] …` lines merged in at
    their chronological positions on the shared recording clock (each
    annotation lands before the first speech segment starting at or after its
    offset; at equal offsets visual lines come before chat lines). Chat events
    with negative offsets (`[CZAT PRZED NAGRANIEM] …`) go at the very top.
    Annotation lines are clearly non-speech; a speaker header is re-emitted
    after each one.
    """
    annotations: list[tuple[float, int, str]] = [
        (entry.offset_secs, 0, _visual_line(entry)) for entry in visual_entries
    ]
    pre_recording = sorted(
        (event for event in chat_events if event.offset_secs < 0),
        key=lambda event: event.offset_secs,
    )
    annotations.extend(
        (event.offset_secs, 1, _chat_line(event))
        for event in chat_events
        if event.offset_secs >= 0
    )
    annotations.sort(key=lambda item: (item[0], item[1]))

    lines: list[str] = []
    for event in pre_recording:
        lines.append(f"\n\n{_chat_line(event, pre_recording=True)}\n")

    current_speaker: str | None = None
    index = 0
    for segment in segments:
        start = float(segment.get("start", 0.0))
        while index < len(annotations) and annotations[index][0] <= start:
            lines.append(f"\n\n{annotations[index][2]}\n")
            current_speaker = None
            index += 1
        if segment["speaker"] != current_speaker:
            lines.append(f"\n\n[{segment['speaker']}]\n")
            current_speaker = segment["speaker"]
        lines.append(str(segment["text"]).strip() + " ")

    for _, _, line in annotations[index:]:
        lines.append(f"\n\n{line}\n")

    return "".join(lines)
