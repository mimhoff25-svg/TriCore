from __future__ import annotations

import json
from pathlib import Path

from .models import SearchRange


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
BANDPLANS_PATH = DATA_DIR / "bandplans.json"


def load_bandplans() -> list[SearchRange]:
    if not BANDPLANS_PATH.exists():
        return []
    data = json.loads(BANDPLANS_PATH.read_text(encoding="utf-8"))
    return [SearchRange.model_validate(item) for item in data.get("bandplans", [])]


def get_bandplan(range_id: str) -> SearchRange | None:
    return next((item for item in load_bandplans() if item.id == range_id), None)

