from __future__ import annotations

import os
from pathlib import Path


def get_newest_file(directory: Path, pattern: str) -> Path | None:
    files = list(directory.glob(pattern))
    return max(files, key=os.path.getmtime) if files else None
