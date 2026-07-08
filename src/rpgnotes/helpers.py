from __future__ import annotations

import json
import logging
import os
import re
import shutil
from pathlib import Path

log = logging.getLogger("rpgnotes")


def get_newest_file(directory: Path, pattern: str) -> Path | None:
    files = list(directory.glob(pattern))
    return max(files, key=os.path.getmtime) if files else None


def prettify_json(filepath: Path) -> str | None:
    try:
        with filepath.open(encoding="utf-8") as f:
            data = json.load(f)
        return json.dumps(data, indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, FileNotFoundError, UnicodeDecodeError) as e:
        log.error("Error processing JSON in %s: %s", filepath, e)
        return None


def assemble_handoff_bundle(
    handoff_dir: Path | None,
    session_number: int,
    session_assets_dir: Path,
    temp_dir: Path,
) -> Path | None:
    """Copy the OotD handoff bundle into `HANDOFF_DIR/session_<NNN>/`.

    Copies (never moves) `transcript.txt`, `transcript_enriched.txt`,
    `chat_log.json`, `chat_events.{json,txt}`, `draft0.md` and
    `validation_report.md` from `session_assets_dir`, plus
    `quotes_session_<N>.json` from `temp_dir` (renamed to `quotes.json`).
    Missing source files are skipped with a warning. If `handoff_dir` is None
    (unset/empty), bundling is skipped entirely. Never raises — failures are
    logged as warnings so a handoff problem never fails the pipeline run.
    """
    if handoff_dir is None:
        log.info("HANDOFF_DIR is unset. Skipping handoff bundle.")
        return None

    bundle_dir = handoff_dir / f"session_{session_number:03d}"
    sources = {
        "transcript.txt": session_assets_dir / "transcript.txt",
        "transcript_enriched.txt": session_assets_dir / "transcript_enriched.txt",
        "chat_log.json": session_assets_dir / "chat_log.json",
        "chat_events.json": session_assets_dir / "chat_events.json",
        "chat_events.txt": session_assets_dir / "chat_events.txt",
        "draft0.md": session_assets_dir / "draft0.md",
        "validation_report.md": session_assets_dir / "validation_report.md",
        "quotes.json": temp_dir / f"quotes_session_{session_number}.json",
    }

    try:
        bundle_dir.mkdir(parents=True, exist_ok=True)
        copied = 0
        for name, src in sources.items():
            if not src.exists():
                log.warning("Handoff bundle: %s not found at %s. Skipping.", name, src)
                continue
            shutil.copy2(src, bundle_dir / name)
            copied += 1
        log.info(
            "Handoff bundle assembled at %s (%d/%d files).", bundle_dir, copied, len(sources)
        )
    except OSError as e:
        log.warning("Failed to assemble handoff bundle at %s: %s", bundle_dir, e)
        return None
    return bundle_dir


def trim_timeline(content: str, recent_sessions: int) -> str:
    """Keep the preamble plus only the last `recent_sessions` `## ` sections.

    Timeline.md grows by one `## Sesja N …` section per session; for the
    summarizer only the recent ones matter. `recent_sessions <= 0` or a file
    with no `## ` sections is returned unchanged.
    """
    if recent_sessions <= 0:
        return content
    parts = re.split(r"(?m)^(?=## )", content)
    header, sections = parts[0], parts[1:]
    if len(sections) <= recent_sessions:
        return content
    note = f"(pominięto {len(sections) - recent_sessions} wcześniejszych sesji)\n\n"
    return header + note + "".join(sections[-recent_sessions:])


def load_context_files(context_dir: Path, timeline_recent_sessions: int = 0) -> str:
    if not context_dir.exists():
        return ""
    all_files: set[Path] = set()
    for pattern in ("*.txt", "*.md"):
        all_files.update(context_dir.glob(pattern))

    chunks: list[str] = []
    for file_path in sorted(all_files):
        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError as e:
            log.warning("Error reading context file %s: %s", file_path, e)
            continue
        if file_path.name == "Timeline.md":
            content = trim_timeline(content, timeline_recent_sessions)
        chunks.append(f"--- CONTEXT FROM {file_path.name} ---\n{content}\n\n")
    return "".join(chunks)
