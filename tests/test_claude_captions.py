from __future__ import annotations

import json
from pathlib import Path

from rpgnotes.claude_captions import export_caption_tasks, import_captions, pending_captions
from rpgnotes.config import Settings
from rpgnotes.visual import caption_cache_file, caption_screenshots

START = 1_800_000_000


def _settings(tmp_path: Path) -> Settings:
    prompt = tmp_path / "visual_caption.txt"
    prompt.write_text("Opisz zrzut.", encoding="utf-8")
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        output_dir=tmp_path / "output",
        temp_dir=tmp_path / "temp",
        downloads_dir=tmp_path / "downloads",
        discord_mapping_file=tmp_path / "mapping.json",
        quotes_prompt_file=tmp_path / "quotes.txt",
        visual_caption_prompt_file=prompt,
        visual_captioner="claude",
        visual_dedupe=False,
        visual_upload_max_dim=0,  # originals as-is: no ImageMagick needed
    )


def _shots(tmp_path: Path) -> Path:
    shots = tmp_path / "temp" / "foundry_snapshots"
    shots.mkdir(parents=True)
    (shots / f"shot_{START + 60}.webp").write_bytes(b"map")
    (shots / f"shot_{START + 120}_key.webp").write_bytes(b"handout")
    (shots / "snapshots.json").write_text(
        json.dumps({f"shot_{START + 120}_key.webp": {"reason": "handout", "title": "Zythion"}}),
        encoding="utf-8",
    )
    return shots


def test_export_writes_frames_tasks_and_instructions(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    shots = _shots(tmp_path)

    assert export_caption_tasks(settings, 85, shots, "", START) == 2

    out = settings.claude_captions_dir
    tasks = json.loads((out / "tasks.json").read_text(encoding="utf-8"))
    assert tasks["session"] == 85
    assert [t["offset"] for t in tasks["frames"]] == ["00:01:00", "00:02:00"]
    handout = tasks["frames"][1]
    assert handout["key"] is True
    assert "Zythion" in handout["hint"]
    assert (out / handout["image"]).read_bytes() == b"handout"
    assert "Opisz zrzut." in (out / "instructions.md").read_text(encoding="utf-8")
    assert pending_captions(settings, 85) == 2


def test_import_stores_written_captions_and_reports_missing(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    shots = _shots(tmp_path)
    export_caption_tasks(settings, 85, shots, "", START)
    out = settings.claude_captions_dir
    (out / "captions" / f"{START + 60}.txt").write_text("Mapa Thylei.\n", encoding="utf-8")
    stale = settings.session_dir(85) / "visual_log.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("[]", encoding="utf-8")

    assert import_captions(settings, 85) == (1, 1)

    cache = caption_cache_file(settings.temp_dir, 85, START + 60)
    assert cache.read_text(encoding="utf-8") == "Mapa Thylei.\n"
    assert not stale.exists()  # rebuilt with the new captions on the next run
    assert pending_captions(settings, 85) == 1
    # A re-export only lists the frame still without a caption.
    assert export_caption_tasks(settings, 85, shots, "", START) == 1


def test_export_for_another_session_starts_clean(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    shots = _shots(tmp_path)
    export_caption_tasks(settings, 84, shots, "", START)
    (settings.claude_captions_dir / "captions" / f"{START + 60}.txt").write_text("stare")

    export_caption_tasks(settings, 85, shots, "", START)

    assert not (settings.claude_captions_dir / "captions" / f"{START + 60}.txt").exists()
    assert import_captions(settings, 85) == (0, 2)


def test_claude_mode_makes_no_calls_and_keeps_the_log_open(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    shots = _shots(tmp_path)
    caption_cache_file(settings.temp_dir, 85, START + 60).write_text("Mapa.", encoding="utf-8")
    log_file = tmp_path / "visual_log.json"

    entries = caption_screenshots(
        screenshots_dir=shots,
        caption_prompt="",
        glossary="",
        model_name=None,
        temp_dir=settings.temp_dir,
        session_number=85,
        visual_log_file=log_file,
        dedupe=False,
        recording_start=START,
    )

    assert [e.caption for e in entries] == ["Mapa."]
    assert not log_file.exists()  # one frame still missing: not frozen yet
