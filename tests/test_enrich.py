from __future__ import annotations

from typing import Any

from rpgnotes.chatevents import ChatEvent
from rpgnotes.enrich import build_enriched_transcript
from rpgnotes.visual import VisualEntry


def _segment(start: float, speaker: str, text: str) -> dict[str, Any]:
    return {"start": start, "end": start + 1.0, "speaker": speaker, "text": text}


def _chat(offset: float, speaker: str = "Sydon", kind: str = "chat", text: str = "tekst") -> ChatEvent:
    return ChatEvent(offset_secs=offset, speaker=speaker, kind=kind, text=text)


def test_enriched_merges_all_three_streams_chronologically() -> None:
    segments = [
        _segment(10.0, "DM", "Wchodzicie do świątyni."),
        _segment(100.0, "Orestes", "Rozglądam się."),
        _segment(200.0, "DM", "Widzisz ołtarz."),
    ]
    visuals = [
        VisualEntry(offset_secs=150.0, caption="Mapa: Świątynia Sydona.", path="shot_2.png"),
        VisualEntry(offset_secs=5.0, caption="Mapa: brama miasta.", path="shot_1.png"),
    ]
    chats = [
        _chat(50.0, "Orestes", "roll", "Percepcja | rzuty: 1d20 + 5 = 17"),
        _chat(999.0, "Sydon", "chat", "Koniec sesji."),
    ]

    text = build_enriched_transcript(segments, visuals, chats)
    assert (
        text.index("[VISUAL 00:00:05] Mapa: brama miasta.")
        < text.index("Wchodzicie do świątyni.")
        < text.index("[CZAT 00:00:50] Orestes (rzut): Percepcja | rzuty: 1d20 + 5 = 17")
        < text.index("Rozglądam się.")
        < text.index("[VISUAL 00:02:30] Mapa: Świątynia Sydona.")
        < text.index("Widzisz ołtarz.")
        < text.index("[CZAT 00:16:39] Sydon: Koniec sesji.")
    )


def test_enriched_visual_precedes_chat_at_equal_offset() -> None:
    segments = [_segment(100.0, "DM", "Kwestia.")]
    visuals = [VisualEntry(offset_secs=50.0, caption="Scena.", path="s.png")]
    chats = [_chat(50.0, "Sydon", "chat", "Wiadomość.")]

    text = build_enriched_transcript(segments, visuals, chats)
    assert text.index("[VISUAL 00:00:50] Scena.") < text.index("[CZAT 00:00:50] Sydon: Wiadomość.")


def test_enriched_pre_recording_chat_goes_at_the_top() -> None:
    segments = [_segment(1.0, "DM", "Start.")]
    chats = [
        _chat(30.0, "Sydon", "roll", "atak | rzuty: 1d20 = 3"),
        _chat(-120.0, "GM", "chat", "Przygotowania przed sesją."),
        _chat(-300.0, "GM", "chat", "Jeszcze wcześniejsza wiadomość."),
    ]

    text = build_enriched_transcript(segments, [], chats)
    top = "\n\n[CZAT PRZED NAGRANIEM] GM: Jeszcze wcześniejsza wiadomość.\n"
    assert text.startswith(top)
    assert (
        text.index("Jeszcze wcześniejsza wiadomość.")
        < text.index("[CZAT PRZED NAGRANIEM] GM: Przygotowania przed sesją.")
        < text.index("Start.")
        < text.index("[CZAT 00:00:30] Sydon (rzut): atak | rzuty: 1d20 = 3")
    )


def test_enriched_visual_only_matches_interleave_format() -> None:
    segments = [
        _segment(10.0, "DM", "Pierwsza kwestia."),
        _segment(100.0, "DM", "Druga kwestia."),
    ]
    visuals = [VisualEntry(offset_secs=50.0, caption="Zmiana mapy.", path="s.png")]

    text = build_enriched_transcript(segments, visuals, [])
    # Speaker header re-emitted after the annotation line.
    assert text.count("[DM]") == 2
    assert "[VISUAL 00:00:50] Zmiana mapy." in text
    assert "[CZAT" not in text


def test_enriched_chat_only() -> None:
    segments = [
        _segment(1.0, "Orestes", "Witaj"),
        _segment(2.0, "DM", "Hello"),
    ]
    chats = [_chat(1.5, "Orestes", "roll", "rzuty: 1d20 = 20")]

    text = build_enriched_transcript(segments, [], chats)
    assert "[CZAT 00:00:01] Orestes (rzut): rzuty: 1d20 = 20" in text
    # Header re-emitted only for the speaker change and after the annotation.
    assert text.count("[DM]") == 1
    assert text.count("[Orestes]") == 1


def test_enriched_without_annotations_matches_combine_format() -> None:
    segments = [
        _segment(1.0, "Orestes", "Witaj"),
        _segment(2.0, "DM", "Hello"),
    ]
    text = build_enriched_transcript(segments, [], [])
    assert text == "\n\n[Orestes]\nWitaj \n\n[DM]\nHello "


def test_enriched_kind_chat_has_no_roll_tag_and_key_visual_is_marked() -> None:
    segments = [_segment(100.0, "DM", "Kwestia.")]
    visuals = [VisualEntry(offset_secs=10.0, caption="List.", path="s.png", is_key=True)]
    chats = [_chat(20.0, "Sydon", "chat", "Zwykła wiadomość.")]

    text = build_enriched_transcript(segments, visuals, chats)
    assert "[VISUAL 00:00:10 KEY] List." in text
    assert "[CZAT 00:00:20] Sydon: Zwykła wiadomość." in text
    assert "(rzut)" not in text
