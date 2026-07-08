from __future__ import annotations

import json
import logging
import os
import re
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
