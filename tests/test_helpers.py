from __future__ import annotations

from rpgnotes.helpers import trim_timeline


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
