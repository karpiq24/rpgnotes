from __future__ import annotations

import json
from pathlib import Path

from rpgnotes.speakers import extract_speaker, load_mapping


def test_load_mapping_returns_dict(mapping_file: Path) -> None:
    assert load_mapping(mapping_file) == {
        "karpiq24": "Dungeon Master",
        "barabaszek": "Orestes",
    }


def test_load_mapping_missing_file(tmp_path: Path) -> None:
    assert load_mapping(tmp_path / "nope.json") == {}


def test_load_mapping_not_a_dict(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(["a", "b"]), encoding="utf-8")
    assert load_mapping(bad) == {}


def test_extract_speaker_maps_known_user(tmp_path: Path) -> None:
    f = tmp_path / "12345-karpiq24_0001.json"
    f.touch()
    assert extract_speaker(f, {"karpiq24": "Dungeon Master"}) == "Dungeon Master"


def test_extract_speaker_falls_back_to_raw_username(tmp_path: Path) -> None:
    f = tmp_path / "12345-someoneNew_0042.json"
    f.touch()
    assert extract_speaker(f, {}) == "someoneNew"


def test_extract_speaker_without_dash_uses_stem(tmp_path: Path) -> None:
    f = tmp_path / "weirdfilename.json"
    f.touch()
    assert extract_speaker(f, {}) == "weirdfilename"


def test_extract_speaker_handles_leading_underscore(tmp_path: Path) -> None:
    # Real Craig filenames sometimes have an underscore right after the dash
    f = tmp_path / "12345-_barabaszek_9999.json"
    f.touch()
    assert extract_speaker(f, {"barabaszek": "Orestes"}) == "Orestes"
