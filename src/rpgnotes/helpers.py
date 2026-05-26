from __future__ import annotations

import json
import logging
import os
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


def load_context_files(context_dir: Path) -> str:
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
        chunks.append(f"--- CONTEXT FROM {file_path.name} ---\n{content}\n\n")
    return "".join(chunks)
