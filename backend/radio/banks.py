from __future__ import annotations

import json
from pathlib import Path

from .models import Bank


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
BANKS_PATH = DATA_DIR / "default_banks.json"


def load_default_banks() -> list[Bank]:
    if not BANKS_PATH.exists():
        return []
    data = json.loads(BANKS_PATH.read_text(encoding="utf-8"))
    return [Bank.model_validate(item) for item in data.get("banks", [])]

