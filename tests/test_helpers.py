from __future__ import annotations

from pathlib import Path

from rpgnotes.helpers import assemble_handoff_bundle, trim_timeline


def _make_session_assets(tmp_path: Path) -> Path:
    session_assets_dir = tmp_path / "output" / "assets" / "sessions" / "007"
    session_assets_dir.mkdir(parents=True)
    (session_assets_dir / "transcript.txt").write_text("transcript", encoding="utf-8")
    (session_assets_dir / "transcript_enriched.txt").write_text("enriched", encoding="utf-8")
    (session_assets_dir / "chat_log.json").write_text("{}", encoding="utf-8")
    (session_assets_dir / "chat_events.json").write_text("[]", encoding="utf-8")
    (session_assets_dir / "chat_events.txt").write_text("", encoding="utf-8")
    (session_assets_dir / "draft0.md").write_text("# Draft", encoding="utf-8")
    (session_assets_dir / "validation_report.md").write_text("# Report", encoding="utf-8")
    return session_assets_dir


def test_assemble_handoff_bundle_copies_all_files(tmp_path: Path) -> None:
    session_assets_dir = _make_session_assets(tmp_path)
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    (temp_dir / "quotes_session_7.json").write_text('{"quotes": []}', encoding="utf-8")

    handoff_dir = tmp_path / "handoff"
    bundle_dir = assemble_handoff_bundle(handoff_dir, 7, session_assets_dir, temp_dir)

    assert bundle_dir == handoff_dir / "session_007"
    assert sorted(p.name for p in bundle_dir.iterdir()) == [
        "chat_events.json",
        "chat_events.txt",
        "chat_log.json",
        "draft0.md",
        "quotes.json",
        "transcript.txt",
        "transcript_enriched.txt",
        "validation_report.md",
    ]

    # Sources remain in place — files are copied, not moved.
    assert (session_assets_dir / "transcript.txt").exists()
    assert (temp_dir / "quotes_session_7.json").exists()


def test_assemble_handoff_bundle_excludes_details_json(tmp_path: Path) -> None:
    session_assets_dir = _make_session_assets(tmp_path)
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    (temp_dir / "details_session_7.json").write_text('{"title": "x"}', encoding="utf-8")

    bundle_dir = assemble_handoff_bundle(tmp_path / "handoff", 7, session_assets_dir, temp_dir)

    assert bundle_dir is not None
    assert not (bundle_dir / "details.json").exists()


def test_assemble_handoff_bundle_skips_missing_files(tmp_path: Path) -> None:
    session_assets_dir = tmp_path / "output" / "assets" / "sessions" / "007"
    session_assets_dir.mkdir(parents=True)
    (session_assets_dir / "transcript.txt").write_text("transcript", encoding="utf-8")
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()

    handoff_dir = tmp_path / "handoff"
    bundle_dir = assemble_handoff_bundle(handoff_dir, 7, session_assets_dir, temp_dir)

    assert bundle_dir is not None
    assert (bundle_dir / "transcript.txt").exists()
    assert not (bundle_dir / "draft0.md").exists()
    assert not (bundle_dir / "details.json").exists()


def test_assemble_handoff_bundle_disabled_when_none(tmp_path: Path) -> None:
    session_assets_dir = _make_session_assets(tmp_path)
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()

    result = assemble_handoff_bundle(None, 7, session_assets_dir, temp_dir)

    assert result is None


def test_trim_timeline_keeps_header_and_recent_sections() -> None:
    content = "# Oś Czasu\n\nintro\n\n" + "".join(
        f"## Sesja {i} (data)\n- wydarzenie {i}\n\n" for i in range(1, 21)
    )

    trimmed = trim_timeline(content, recent_sessions=3)

    assert trimmed.startswith("# Oś Czasu\n\nintro")
    assert "pominięto 17" in trimmed
    assert "## Sesja 17" not in trimmed
    assert "## Sesja 18" in trimmed
    assert "## Sesja 20" in trimmed


def test_trim_timeline_disabled_or_small_returns_unchanged() -> None:
    content = "# T\n## Sesja 1\na\n## Sesja 2\nb\n"

    assert trim_timeline(content, recent_sessions=0) == content
    assert trim_timeline(content, recent_sessions=5) == content
