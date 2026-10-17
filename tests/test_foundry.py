from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from rpgnotes import foundry
from rpgnotes.chatlog import process_chat_log
from rpgnotes.enrich import build_enriched_transcript

_PIXEL = "data:image/webp;base64," + base64.b64encode(b"RIFF....WEBPVP8 fake").decode()
START = "2026-10-19T16:00:00.000Z"  # recording start below: 1792425600


def _export(**overrides: Any) -> dict[str, Any]:
    """Shaped like a real export from the module (Foundry 14, dnd5e 6)."""
    data: dict[str, Any] = {
        "format": "rpgnotes-foundry",
        "version": 1,
        "title": "session85",
        "archiveDate": "2026-10-19",
        "session": 85,
        "startedAt": START,
        "events": [
            {"kind": "session_start", "t": START},
            {"kind": "scene", "scene": "Thylea", "t": "2026-10-19T16:00:05.000Z"},
            {"kind": "chat", "type": "chat", "style": "ic", "speaker": "Arevon Elorrenthi",
             "actor": "Arevon Elorrenthi", "user": "kentos", "text": "villain monologue!",
             "t": "2026-10-19T16:01:00.000Z"},
            {"kind": "chat", "type": "attack", "speaker": "Giant Shark", "actor": "Giant Shark",
             "flavor": "Bite - Attack Roll (Advantage)",
             "rolls": [{"formula": "2d20kh + 7", "total": 24, "critical": True}],
             "t": "2026-10-19T16:02:00.000Z"},
            {"kind": "chat", "type": "damage", "actor": "Nephele", "item": "Cold Breath",
             "flavor": "Cold Breath - Damage Roll",
             "rolls": [{"formula": "12d8[cold]", "total": 54, "damageType": "cold"}],
             "t": "2026-10-19T16:02:30.000Z"},
            {"kind": "chat", "type": "save", "actor": "Sydon", "flavor": "Constitution Saving Throw",
             "rolls": [{"formula": "1d20 + 9", "total": 12, "target": 18}],
             "t": "2026-10-19T16:02:40.000Z"},
            {"kind": "chat", "type": "usage", "actor": "Nephele", "item": "Cold Breath",
             "activity": "Save", "t": "2026-10-19T16:02:20.000Z"},
            {"kind": "chat", "type": "chat", "speaker": "Versir", "actor": "Versir",
             "whisperTo": ["karpiq"], "text": "Czy widzę pułapkę?", "t": "2026-10-19T16:03:00.000Z"},
            {"kind": "combat_start", "combatants": ["Giant Shark", "Orestes"],
             "t": "2026-10-19T16:01:30.000Z"},
            {"kind": "combat_turn", "round": 1, "combatant": "Orestes", "t": "2026-10-19T16:01:31.000Z"},
            {"kind": "down", "actor": "Giant Shark", "type": "npc", "t": "2026-10-19T16:04:00.000Z"},
            {"kind": "journal", "title": "Listy: List od Sydona", "text": "Przybądźcie do Mytros.",
             "t": "2026-10-19T16:05:00.000Z"},
            {"kind": "music", "track": "Storm", "playlist": "Combat", "t": "2026-10-19T16:01:40.000Z"},
            {"kind": "player_join", "user": "kentos", "t": START},
        ],
        "snapshots": [
            {"t": "2026-10-19T16:00:01.000Z", "reason": "start", "scene": "Thylea", "data": _PIXEL},
            {"t": "2026-10-19T16:05:00.000Z", "reason": "handout", "key": True, "title": "List",
             "data": _PIXEL},
            {"t": "2026-10-19T16:05:00.400Z", "reason": "manual", "key": True, "data": _PIXEL},
            {"t": "2026-10-19T16:06:00.000Z", "reason": "interval", "data": "data:image/webp;base64,@@@"},
        ],
    }
    data.update(overrides)
    return data


def test_events_render_as_timeline_lines() -> None:
    events = foundry.events_from_export(_export(), recording_start=1792425600)
    lines = [(e.offset_secs, e.speaker, e.kind, e.text) for e in events]
    assert lines == [
        (5.0, "Scena", "event", "aktywna scena: Thylea"),
        (60.0, "Arevon Elorrenthi", "chat", "villain monologue!"),
        (90.0, "Walka", "event", "początek walki: Giant Shark, Orestes"),
        (100.0, "Muzyka", "event", "Storm (Combat)"),
        (120.0, "Giant Shark", "roll", "Bite - Attack Roll (Advantage) | rzuty: 2d20kh + 7 = 24 KRYTYK"),
        (140.0, "Nephele", "event", "używa: Cold Breath (Save)"),
        (150.0, "Nephele", "roll", "Cold Breath - Damage Roll | rzuty: 12d8[cold] = 54 cold"),
        (160.0, "Sydon", "roll", "Constitution Saving Throw | rzuty: 1d20 + 9 = 12 (ST 18)"),
        (180.0, "Versir", "chat", "(szept do: karpiq) Czy widzę pułapkę?"),
        (240.0, "Walka", "event", "Giant Shark pada (0 PW)"),
        (300.0, "Handout", "event", "pokazano graczom dziennik: Listy: List od Sydona — Przybądźcie do Mytros."),
    ]


def test_without_recording_start_the_module_start_is_t0() -> None:
    events = foundry.events_from_export(_export(), recording_start=None)
    assert events[0].offset_secs == 5.0


def test_snapshots_are_extracted_with_key_markers(tmp_path: Path) -> None:
    out = tmp_path / "snaps"
    out.mkdir()
    (out / "shot_1.webp").write_bytes(b"stale")
    assert foundry.extract_snapshots(_export(), out) == 3
    assert sorted(p.name for p in out.iterdir()) == [
        "shot_1792425601.webp",
        "shot_1792425900_key.webp",
        "shot_1792425901_key.webp",  # same second as the handout: moved by one
    ]


def test_wiki_copy_drops_image_data(tmp_path: Path) -> None:
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    (downloads / "session85.json").write_text(json.dumps(_export()), encoding="utf-8")

    number, date = process_chat_log(downloads, tmp_path / "assets")

    assert number == 85 and str(date) == "2026-10-19"
    copy = json.loads((tmp_path / "assets" / "085" / "chat_log.json").read_text(encoding="utf-8"))
    assert copy["snapshots"][1] == {
        "t": "2026-10-19T16:05:00.000Z", "reason": "handout", "key": True, "title": "List",
    }
    assert len(copy["events"]) == len(_export()["events"])


def test_events_enrich_the_transcript() -> None:
    events = foundry.events_from_export(_export(), recording_start=1792425600)
    segments = [{"start": 0.0, "end": 200.0, "speaker": "DM", "text": "Witajcie."}]
    enriched = build_enriched_transcript(segments, [], events)
    assert "[CZAT 00:02:00] Giant Shark (rzut): Bite - Attack Roll" in enriched
    assert "[CZAT 00:04:00] Walka: Giant Shark pada (0 PW)" in enriched
