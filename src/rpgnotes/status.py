"""What the menu shows before running: the session it found and how far it got."""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass
from pathlib import Path

from .audio import read_recording_start
from .chatlog import find_chat_log
from .config import Settings
from .foundry import is_foundry_export
from .manifest import imported_since_last_run
from .pipeline import has_temp_work, session_audio_zip, temp_session
from .visual import STALE_FRAME_SECS, parse_screenshot_timestamp


@dataclass
class SessionStatus:
    session_number: int | None = None
    session_date: _dt.date | None = None
    chat_log: Path | None = None
    audio_zip: Path | None = None
    # Temp work belongs to this session (resume) or to another one (cleared on start).
    temp_session: int | None = None
    temp_has_work: bool = False
    tracks: int = 0
    transcribed_tracks: int = 0
    transcript: bool = False
    draft: bool = False
    details: bool = False
    quotes: bool = False
    # None: never imported into the wiki; False: rpgnotes ran again since.
    imported: bool | None = None
    campaign_context: bool = False
    screenshots_enabled: bool = False
    # Session file saved by the Foundry recorder module (events + map snapshots).
    foundry_events: int | None = None
    foundry_snapshots: int = 0
    screenshots: int = 0
    stale_screenshots: int = 0
    api_key: bool = False

    @property
    def temp_is_other_session(self) -> bool:
        return self.temp_has_work and self.temp_session not in (None, self.session_number)


def _recording_start(session_assets_dir: Path, audio_zip: Path | None) -> int | None:
    anchor_file = session_assets_dir / "recording_start.txt"
    try:
        return int(anchor_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pass
    return read_recording_start(audio_zip) if audio_zip is not None else None


def collect_status(settings: Settings) -> SessionStatus:
    context_file = settings.campaign_context_file
    status = SessionStatus(
        api_key=bool(settings.gemini_api_key),
        campaign_context=context_file is not None
        and context_file.is_file()
        and context_file.stat().st_size > 0,
        temp_session=temp_session(settings),
        temp_has_work=has_temp_work(settings),
    )
    info = find_chat_log(settings.downloads_dir)
    if info is None:
        return status
    status.chat_log, status.session_number, status.session_date = info

    session_assets_dir = settings.session_dir(status.session_number)
    status.audio_zip = session_audio_zip(settings, session_assets_dir)
    status.transcript = (session_assets_dir / "transcript.txt").exists()
    status.draft = (session_assets_dir / "draft0.md").exists()
    status.details = (session_assets_dir / "details.json").exists()
    status.quotes = (session_assets_dir / "quotes.json").exists()
    status.imported = imported_since_last_run(session_assets_dir)

    if status.temp_session == status.session_number:
        tracks = list(settings.audio_output_dir.glob("*.flac"))
        status.tracks = len(tracks)
        status.transcribed_tracks = sum(
            (settings.temp_transcriptions_dir / f"{track.stem}.json").exists() for track in tracks
        )

    try:
        data = json.loads(status.chat_log.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if is_foundry_export(data):
        assert isinstance(data, dict)
        status.foundry_events = len(data.get("events", []))
        status.foundry_snapshots = len(data.get("snapshots", []))
        return status

    screenshots_dir = settings.resolved_screenshots_dir
    status.screenshots_enabled = screenshots_dir is not None
    if screenshots_dir is not None and screenshots_dir.is_dir():
        stamps = [
            parsed[0]
            for path in screenshots_dir.glob("shot_*.png")
            if (parsed := parse_screenshot_timestamp(path)) is not None
        ]
        status.screenshots = len(stamps)
        start = _recording_start(session_assets_dir, status.audio_zip)
        if start is not None:
            status.stale_screenshots = sum(ts < start - STALE_FRAME_SECS for ts in stamps)
    return status


def _mark(done: bool) -> str:
    return "✓" if done else "·"


def format_status(status: SessionStatus, settings: Settings) -> str:
    downloads = settings.host_downloads_dir or str(settings.downloads_dir)
    rule = "═" * 60
    if status.session_number is None:
        return "\n".join(
            [
                rule,
                "  No session found",
                rule,
                f"  Put these two files into {downloads}:",
                "    craig-*.flac.zip    audio from the Craig bot",
                "    session<NN>.json    saved by the RPG Notes Recorder Foundry module",
            ]
        )

    title = f"  Sesja {status.session_number}"
    if status.session_date:
        title += f" · {status.session_date.isoformat()}"
    lines = [rule, title, rule]
    assert status.chat_log is not None
    if status.foundry_events is None:
        lines.append(f"  Chat log     {status.chat_log.name}")
    else:
        lines.append(
            f"  Foundry      {status.chat_log.name}: {status.foundry_events} events, "
            f"{status.foundry_snapshots} map snapshots"
        )

    if status.audio_zip is None:
        lines.append(f"  Audio        ✗ no craig-*.flac.zip in {downloads}")
    else:
        size_mb = status.audio_zip.stat().st_size / 1e6
        where = " (already processed)" if status.audio_zip.parent == settings.processed_dir else ""
        lines.append(f"  Audio        {status.audio_zip.name}, {size_mb:.0f} MB{where}")

    if status.foundry_events is not None:
        pass  # the map snapshots come with the Foundry file
    elif not status.screenshots_enabled:
        lines.append("  Screenshots  off (SCREENSHOTS_DIR is empty)")
    elif status.screenshots == 0:
        lines.append("  Screenshots  none")
    else:
        line = f"  Screenshots  {status.screenshots} frames"
        if status.stale_screenshots:
            line += f", {status.stale_screenshots} from an earlier session (skipped)"
        lines.append(line)

    if status.api_key:
        lines.append(f"  Gemini       {settings.gemini_pro_model}, {settings.gemini_service_tier} tier")
    else:
        lines.append("  Gemini       ✗ GEMINI_API_KEY not set in .env (only transcription will run)")
    if not status.campaign_context:
        lines.append(
            "  Campaign     ✗ no campaign context (CAMPAIGN_CONTEXT_FILE): no names, party "
            "or hotwords. Run scripts/export_context.py in the wiki."
        )

    lines.append("")
    lines.append(
        f"  Outbox       {_mark(status.transcript)} transcript   "
        f"{_mark(status.draft)} draft0.md   {_mark(status.details)} details   "
        f"{_mark(status.quotes)} quotes"
    )
    if status.imported:
        lines.append("  Wiki         ✓ imported")
    elif status.imported is False:
        lines.append(
            f"  Wiki         changed since the last import: run /import-session "
            f"{status.session_number} again"
        )
    elif status.draft and status.details and status.quotes:
        lines.append(f"  Wiki         not imported yet: run /import-session {status.session_number}")
    if status.tracks and status.transcribed_tracks < status.tracks:
        lines.append(
            f"  Resuming     {status.transcribed_tracks}/{status.tracks} audio tracks "
            "already transcribed"
        )
    if status.temp_is_other_session:
        lines.append(
            f"  Note         temp holds work for session {status.temp_session}; "
            "it is cleared when you start"
        )
    return "\n".join(lines)
