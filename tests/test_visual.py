from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import rpgnotes.visual as visual
from rpgnotes.visual import (
    VisualEntry,
    caption_screenshots,
    format_offset,
    interleave_visuals,
    load_session_start,
    mean_abs_diff,
    parse_screenshot_timestamp,
)


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeModel:
    """Stands in for genai.GenerativeModel; counts calls and echoes captions."""

    instances: list[_FakeModel] = []

    def __init__(self, *, model_name: str, system_instruction: str) -> None:
        self.model_name = model_name
        self.system_instruction = system_instruction
        self.calls = 0
        _FakeModel.instances.append(self)

    def generate_content(self, parts: list[Any], **_kwargs: Any) -> _FakeResponse:
        self.calls += 1
        return _FakeResponse(f"Opis klatki nr {self.calls}.")


@pytest.fixture
def fake_genai(monkeypatch: pytest.MonkeyPatch) -> type[_FakeModel]:
    _FakeModel.instances = []
    monkeypatch.setattr(visual.genai, "GenerativeModel", _FakeModel)
    return _FakeModel


def _total_calls() -> int:
    return sum(m.calls for m in _FakeModel.instances)


def _make_shots(directory: Path, timestamps: list[int], key: set[int] | None = None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for ts in timestamps:
        suffix = "_key" if key and ts in key else ""
        (directory / f"shot_{ts}{suffix}.png").write_bytes(b"png" + str(ts).encode())


def _caption(shots_dir: Path, tmp_path: Path, **overrides: Any) -> list[VisualEntry]:
    kwargs: dict[str, Any] = {
        "screenshots_dir": shots_dir,
        "caption_prompt": "Opisz zrzut.",
        "glossary": "# Glosariusz\n- **Praxys**",
        "model_name": "flash-test",
        "temp_dir": tmp_path / "temp",
        "session_number": 7,
        "visual_log_file": tmp_path / "assets" / "visual_log.json",
        "dedupe": False,
    }
    kwargs.update(overrides)
    return caption_screenshots(**kwargs)


# --------------------------------------------------------------------------
# Filename / offset mapping
# --------------------------------------------------------------------------


def test_parse_screenshot_timestamp() -> None:
    assert parse_screenshot_timestamp(Path("shot_1783440528.png")) == (1783440528, False)
    assert parse_screenshot_timestamp(Path("shot_1783440528_key.png")) == (1783440528, True)
    assert parse_screenshot_timestamp(Path("screenshot.png")) is None
    assert parse_screenshot_timestamp(Path("shot_abc.png")) is None


def test_load_session_start(tmp_path: Path) -> None:
    assert load_session_start(tmp_path) is None
    (tmp_path / "session_start.txt").write_text("1783440000\n", encoding="utf-8")
    assert load_session_start(tmp_path) == 1783440000


def test_offsets_use_session_start(fake_genai: type[_FakeModel], tmp_path: Path) -> None:
    shots = tmp_path / "shots"
    _make_shots(shots, [1783440090, 1783443725])
    (shots / "session_start.txt").write_text("1783440000", encoding="utf-8")

    entries = _caption(shots, tmp_path)
    assert [e.offset_secs for e in entries] == [90.0, 3725.0]


def test_offsets_fall_back_to_earliest_shot(
    fake_genai: type[_FakeModel], tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    shots = tmp_path / "shots"
    _make_shots(shots, [1783440100, 1783440400])

    with caplog.at_level("WARNING", logger="rpgnotes"):
        entries = _caption(shots, tmp_path)
    assert [e.offset_secs for e in entries] == [0.0, 300.0]
    assert any("session_start.txt missing" in r.message for r in caplog.records)


# --------------------------------------------------------------------------
# Dedupe comparison
# --------------------------------------------------------------------------


def test_mean_abs_diff() -> None:
    assert mean_abs_diff(bytes([10, 20, 30]), bytes([10, 20, 30])) == 0.0
    assert mean_abs_diff(bytes([0, 0]), bytes([10, 30])) == 20.0
    # Mismatched / empty buffers are maximally different.
    assert mean_abs_diff(b"", b"") == 255.0
    assert mean_abs_diff(bytes([1]), bytes([1, 2])) == 255.0


def test_dedupe_drops_near_identical_frames(
    fake_genai: type[_FakeModel], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shots = tmp_path / "shots"
    _make_shots(shots, [100, 200, 300])
    (shots / "session_start.txt").write_text("100", encoding="utf-8")

    signatures = {
        "shot_100.png": bytes([0] * 16),
        "shot_200.png": bytes([1] * 16),  # diff 1.0 < threshold → dropped
        "shot_300.png": bytes([50] * 16),  # diff 50.0 vs kept frame → kept
    }
    monkeypatch.setattr(visual, "frame_signature", lambda p, crop="": signatures[p.name])

    entries = _caption(shots, tmp_path, dedupe=True, dedupe_threshold=4.0)
    assert [Path(e.path).name for e in entries] == ["shot_100.png", "shot_300.png"]


def test_dedupe_always_keeps_key_frames(
    fake_genai: type[_FakeModel], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shots = tmp_path / "shots"
    _make_shots(shots, [100, 200], key={200})
    (shots / "session_start.txt").write_text("100", encoding="utf-8")
    monkeypatch.setattr(visual, "frame_signature", lambda p, crop="": bytes([0] * 16))

    entries = _caption(shots, tmp_path, dedupe=True)
    assert [e.is_key for e in entries] == [False, True]


# --------------------------------------------------------------------------
# Captioning: caching / visual_log.json
# --------------------------------------------------------------------------


def test_caption_cache_makes_step_resumable(
    fake_genai: type[_FakeModel], tmp_path: Path
) -> None:
    shots = tmp_path / "shots"
    _make_shots(shots, [100, 200])
    (shots / "session_start.txt").write_text("100", encoding="utf-8")

    first = _caption(shots, tmp_path)
    assert _total_calls() == 2

    # Second run loads visual_log.json without touching the API.
    second = _caption(shots, tmp_path)
    assert _total_calls() == 2
    assert second == first

    # With the log removed, per-frame caption caches still avoid API calls.
    (tmp_path / "assets" / "visual_log.json").unlink()
    third = _caption(shots, tmp_path)
    assert _total_calls() == 2
    assert [e.caption for e in third] == [e.caption for e in first]


def test_visual_log_contents(fake_genai: type[_FakeModel], tmp_path: Path) -> None:
    shots = tmp_path / "shots"
    _make_shots(shots, [100, 250], key={250})
    (shots / "session_start.txt").write_text("100", encoding="utf-8")

    _caption(shots, tmp_path)
    raw = json.loads((tmp_path / "assets" / "visual_log.json").read_text(encoding="utf-8"))
    assert [sorted(item) for item in raw] == [["caption", "is_key", "offset_secs", "path"]] * 2
    assert raw[0]["offset_secs"] == 0.0
    assert raw[1] == {
        "offset_secs": 150.0,
        "caption": raw[1]["caption"],
        "path": str(shots / "shot_250_key.png"),
        "is_key": True,
    }


def test_no_screenshots_returns_empty(fake_genai: type[_FakeModel], tmp_path: Path) -> None:
    shots = tmp_path / "shots"
    shots.mkdir()
    assert _caption(shots, tmp_path) == []
    assert _total_calls() == 0


# --------------------------------------------------------------------------
# Interleaving
# --------------------------------------------------------------------------


def _segment(start: float, speaker: str, text: str) -> dict[str, Any]:
    return {"start": start, "end": start + 1.0, "speaker": speaker, "text": text}


def test_format_offset() -> None:
    assert format_offset(0) == "00:00:00"
    assert format_offset(5025.7) == "01:23:45"
    assert format_offset(-3) == "00:00:00"


def test_interleave_positions_are_chronological() -> None:
    segments = [
        _segment(10.0, "DM", "Wchodzicie do świątyni."),
        _segment(100.0, "Orestes", "Rozglądam się."),
        _segment(200.0, "DM", "Widzisz ołtarz."),
    ]
    entries = [
        VisualEntry(offset_secs=150.0, caption="Mapa: Świątynia Sydona.", path="shot_2.png"),
        VisualEntry(offset_secs=5.0, caption="Mapa: brama miasta.", path="shot_1.png"),
        VisualEntry(offset_secs=999.0, caption="Handout: list.", path="shot_3.png", is_key=True),
    ]

    text = interleave_visuals(segments, entries)
    assert (
        text.index("[VISUAL 00:00:05] Mapa: brama miasta.")
        < text.index("Wchodzicie do świątyni.")
        < text.index("Rozglądam się.")
        < text.index("[VISUAL 00:02:30] Mapa: Świątynia Sydona.")
        < text.index("Widzisz ołtarz.")
        < text.index("[VISUAL 00:16:39 KEY] Handout: list.")
    )


def test_interleave_reemits_speaker_header_after_visual_line() -> None:
    segments = [
        _segment(10.0, "DM", "Pierwsza kwestia."),
        _segment(100.0, "DM", "Druga kwestia."),
    ]
    entries = [VisualEntry(offset_secs=50.0, caption="Zmiana mapy.", path="s.png")]

    text = interleave_visuals(segments, entries)
    # The same speaker keeps talking across the visual line, so the header
    # must appear again — visual lines are clearly not part of the speech.
    assert text.count("[DM]") == 2
    assert "[VISUAL 00:00:50] Zmiana mapy." in text


def test_interleave_without_entries_matches_combine_format() -> None:
    segments = [
        _segment(1.0, "Orestes", "Witaj"),
        _segment(2.0, "DM", "Hello"),
    ]
    text = interleave_visuals(segments, [])
    assert text == "\n\n[Orestes]\nWitaj \n\n[DM]\nHello "


# --------------------------------------------------------------------------
# Upload preparation
# --------------------------------------------------------------------------


def _make_test_png(path: Path, size: int = 512) -> None:
    import shutil as _shutil
    import subprocess as _subprocess

    magick = _shutil.which("magick") or _shutil.which("convert")
    if magick is None:
        pytest.skip("ImageMagick not available")
    _subprocess.run(
        [magick, "-size", f"{size}x{size}", "plasma:fractal", str(path)],
        check=True,
        capture_output=True,
        timeout=60,
    )


def test_prepare_upload_downscales_to_jpeg(tmp_path: Path) -> None:
    frame = tmp_path / "shot_100.png"
    _make_test_png(frame, size=512)
    original_size = frame.stat().st_size

    data, mime = visual.prepare_upload(frame, max_dim=128, jpeg_quality=80)

    assert mime == "image/jpeg"
    assert data[:3] == b"\xff\xd8\xff"  # JPEG magic bytes
    assert len(data) < original_size
    assert frame.stat().st_size == original_size  # original untouched


def test_prepare_upload_disabled_returns_original_png(tmp_path: Path) -> None:
    frame = tmp_path / "shot_100.png"
    frame.write_bytes(b"\x89PNG\r\n\x1a\nfakepng")

    data, mime = visual.prepare_upload(frame, max_dim=0)

    assert mime == "image/png"
    assert data == frame.read_bytes()


def test_prepare_upload_falls_back_without_imagemagick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frame = tmp_path / "shot_100.png"
    frame.write_bytes(b"\x89PNG\r\n\x1a\nfakepng")
    monkeypatch.setattr(visual.shutil, "which", lambda _name: None)

    data, mime = visual.prepare_upload(frame, max_dim=1536)

    assert mime == "image/png"
    assert data == frame.read_bytes()


def test_prepare_upload_crops_before_resize(tmp_path: Path) -> None:
    frame = tmp_path / "shot_100.png"
    _make_test_png(frame, size=512)

    data, mime = visual.prepare_upload(frame, max_dim=0, crop="200x100+10+20")

    assert mime == "image/jpeg"
    # Decode the JPEG dimensions from the SOF0 marker via ImageMagick identify.
    import subprocess as _subprocess

    out = tmp_path / "cropped.jpg"
    out.write_bytes(data)
    magick = visual.shutil.which("magick") or visual.shutil.which("convert")
    proc = _subprocess.run(
        [magick, "identify", "-format", "%wx%h", str(out)],
        capture_output=True,
        timeout=30,
        text=True,
    )
    assert proc.stdout == "200x100"


def test_prepare_upload_invalid_crop_falls_back_to_original(tmp_path: Path) -> None:
    frame = tmp_path / "shot_100.png"
    _make_test_png(frame, size=64)

    data, mime = visual.prepare_upload(frame, max_dim=128, crop="not-a-geometry")

    assert mime == "image/png"
    assert data == frame.read_bytes()


def test_frame_signature_crop_changes_signature(tmp_path: Path) -> None:
    frame = tmp_path / "shot_100.png"
    _make_test_png(frame, size=512)

    full = visual.frame_signature(frame)
    cropped = visual.frame_signature(frame, crop="256x256+0+0")

    assert full is not None and cropped is not None
    assert len(full) == len(cropped) == visual.SIGNATURE_SIZE**2
    assert full != cropped
