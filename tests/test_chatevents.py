from __future__ import annotations

import json
from pathlib import Path

from rpgnotes import chatevents
from rpgnotes.chatevents import ChatEvent, extract_chat_events, format_chat_events


def _write_chat_log(path: Path, messages: list[dict[str, str]]) -> Path:
    path.write_text(
        json.dumps({"title": "session99", "messages": messages}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_extract_chat_events_strips_html_and_anchors_offsets(tmp_path: Path) -> None:
    log_file = _write_chat_log(
        tmp_path / "chat_log.json",
        [
            {
                "speaker": "Orion Xul",
                "content": "<p>Rzucam <b>Fireball</b>!</p>",
                "timestamp": "2026-07-07T17:00:00.000Z",
            }
        ],
    )
    # recording started at 16:48:24Z = unix 1783442904
    events = extract_chat_events(log_file, 1783442904)

    assert len(events) == 1
    assert events[0].speaker == "Orion Xul"
    assert events[0].text == "Rzucam Fireball !"
    assert events[0].kind == "chat"
    assert events[0].offset_secs == 696.0  # 11m36s after recording start


def test_extract_chat_events_classifies_rolls_and_keeps_numbers(tmp_path: Path) -> None:
    log_file = _write_chat_log(
        tmp_path / "chat_log.json",
        [
            {
                "speaker": "Colossus of Pythor",
                "content": (
                    '<div class="dice-roll"><div class="dice-formula">8d6 + 13</div>'
                    '<h4 class="dice-total">60</h4></div>'
                ),
                "timestamp": "2026-07-07T17:00:00.000Z",
            }
        ],
    )
    events = extract_chat_events(log_file, 1783442904)

    assert events[0].kind == "roll"
    assert "8d6 + 13" in events[0].text
    assert "60" in events[0].text


def test_extract_chat_events_drops_noise_and_empty(tmp_path: Path) -> None:
    log_file = _write_chat_log(
        tmp_path / "chat_log.json",
        [
            {"speaker": "Tidbits", "content": "<p>Did you know?</p>", "timestamp": "2026-07-07T17:00:00Z"},
            {"content": "<p>Welcome to Plutonium!</p>", "timestamp": "2026-07-07T17:00:01Z"},
            {"speaker": "Versir", "content": "<div>   </div>", "timestamp": "2026-07-07T17:00:02Z"},
            {"speaker": "Versir", "content": "<p>Atakuję!</p>"},  # no timestamp
            {"speaker": "Versir", "content": "<p>Uciekamy!</p>", "timestamp": "2026-07-07T17:00:03Z"},
        ],
    )
    events = extract_chat_events(log_file, 1783442904)

    assert [event.text for event in events] == ["Uciekamy!"]


def test_extract_chat_events_without_anchor_uses_first_message(tmp_path: Path) -> None:
    log_file = _write_chat_log(
        tmp_path / "chat_log.json",
        [
            {"speaker": "A", "content": "pierwsza", "timestamp": "2026-07-07T17:00:00Z"},
            {"speaker": "B", "content": "druga", "timestamp": "2026-07-07T17:01:00Z"},
        ],
    )
    events = extract_chat_events(log_file, None)

    assert [event.offset_secs for event in events] == [0.0, 60.0]


def test_extract_chat_events_truncates_long_messages(tmp_path: Path) -> None:
    log_file = _write_chat_log(
        tmp_path / "chat_log.json",
        [{"speaker": "GM", "content": "x" * 2000, "timestamp": "2026-07-07T17:00:00Z"}],
    )
    events = extract_chat_events(log_file, None)

    assert len(events[0].text) == chatevents._MAX_TEXT_CHARS
    assert events[0].text.endswith("…")


def test_format_chat_events_marks_pre_recording_messages() -> None:
    rendered = format_chat_events(
        [
            ChatEvent(offset_secs=-120.0, speaker="GM", kind="chat", text="setup"),
            ChatEvent(offset_secs=3725.0, speaker="Versir", kind="roll", text="1d20 + 5 22"),
        ]
    )

    lines = rendered.splitlines()
    assert lines[0] == "[PRZED NAGRANIEM] GM: setup"
    assert lines[1] == "[01:02:05] Versir (rzut): 1d20 + 5 22"
