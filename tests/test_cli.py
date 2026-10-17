from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

import rpgnotes.cli as cli
from rpgnotes.config import Settings
from rpgnotes.status import collect_status, format_status


def _settings(tmp_path: Path) -> Settings:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        output_dir=tmp_path / "output",
        temp_dir=tmp_path / "temp",
        downloads_dir=tmp_path / "downloads",
        discord_mapping_file=tmp_path / "mapping.json",
        whisper_prompt_file=tmp_path / "whisper.txt",
        summary_prompt_file=tmp_path / "summary.txt",
        quotes_prompt_file=tmp_path / "quotes.txt",
        template_file=tmp_path / "template.md",
        context_dir=tmp_path / "context",
        screenshots_dir=str(tmp_path / "temp" / "screenshots"),
        host_downloads_dir="~/Pobrane",
    )
    settings.ensure_directories()
    return settings


def _drop_session(settings: Settings, number: int = 81) -> None:
    (settings.downloads_dir / f"session{number}.json").write_text(
        json.dumps({"archiveDate": "2026-10-12"}), encoding="utf-8"
    )
    with zipfile.ZipFile(settings.downloads_dir / "craig-abc.flac.zip", "w") as zip_ref:
        zip_ref.writestr("1-dm.flac", b"fake")
        zip_ref.writestr("info.txt", "Start time:\t2026-10-12T16:00:00Z\n")


def test_status_without_session_says_what_to_download(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    text = format_status(collect_status(settings), settings)
    assert "No session found" in text
    assert "~/Pobrane" in text


def test_status_lists_inputs_progress_and_stale_temp(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _drop_session(settings)
    shots = settings.temp_dir / "screenshots"
    shots.mkdir()
    start = 1791820800  # 2026-10-12T16:00:00Z
    for ts in (start - 7 * 24 * 3600, start + 60, start + 660):
        (shots / f"shot_{ts}.png").write_bytes(b"png")
    (settings.temp_dir / "session.txt").write_text("80\n", encoding="utf-8")
    (settings.audio_output_dir / "1-dm.flac").write_bytes(b"old")
    assets = settings.assets_base_dir / "081"
    assets.mkdir(parents=True)
    (assets / "transcript.txt").write_text("x", encoding="utf-8")

    status = collect_status(settings)
    assert status.session_number == 81
    assert status.temp_is_other_session
    text = format_status(status, settings)
    assert "Sesja 81 · 2026-10-12" in text
    assert "craig-abc.flac.zip" in text
    assert "3 frames, 1 from an earlier session (skipped)" in text
    assert "GEMINI_API_KEY not set" in text
    assert "✓ transcript" in text and "· draft0.md" in text
    assert "temp holds work for session 80" in text


def test_menu_enter_runs_default_action_then_quit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = _settings(tmp_path)
    _drop_session(settings)
    ran: list[str] = []
    monkeypatch.setattr(cli, "run_full_workflow", lambda _s: ran.append("full"))
    answers = iter(["", "q"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    assert cli._run_menu(settings) == 0
    assert ran == ["full"]
    out = capsys.readouterr().out
    assert "[1] Process session 81: transcribe + AI notes   (Enter)" in out
    assert "Start over" not in out


def test_menu_offers_continue_and_start_over_for_started_session(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _drop_session(settings)
    (settings.temp_dir / "session.txt").write_text("81\n", encoding="utf-8")
    (settings.audio_output_dir / "1-dm.flac").write_bytes(b"flac")
    labels = [label for _key, label, _a in cli._menu_actions(settings, collect_status(settings))]
    assert labels[0].startswith("Continue session 81")
    assert any(label.startswith("Start over") for label in labels)


def test_eof_quits_menu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path)

    def eof(_prompt: str) -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert cli._run_menu(settings) == 0


def test_status_shows_foundry_recorder_file(tmp_path: Path) -> None:
    from tests.test_foundry import _export

    settings = _settings(tmp_path)
    (settings.downloads_dir / "session85.json").write_text(json.dumps(_export()), encoding="utf-8")
    text = format_status(collect_status(settings), settings)
    assert "Foundry      session85.json: 14 events, 4 map snapshots" in text
    assert "Screenshots" not in text
