from __future__ import annotations

from enum import StrEnum


class ScannerState(StrEnum):
    STOPPED = "stopped"
    SCANNING = "scanning"
    PAUSED = "paused"
    HOLDING = "holding"
    SEARCHING = "searching"
    MANUAL_TUNE = "manual_tune"
    ERROR = "error"

