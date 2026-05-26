from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def mapping_file(tmp_path: Path) -> Path:
    path = tmp_path / "mapping.json"
    path.write_text(
        json.dumps({"karpiq24": "Dungeon Master", "barabaszek": "Orestes"}),
        encoding="utf-8",
    )
    return path
