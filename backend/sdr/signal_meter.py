from __future__ import annotations

import math


def simulated_signal_level(frequency_hz: int, tick: int = 0) -> float:
    frequency_component = (frequency_hz // 25_000) % 17
    wave = math.sin((tick + frequency_component) / 3.0) * 8.0
    return round(-72.0 + frequency_component * 1.2 + wave, 1)


def squelch_open(signal_level: float, squelch_db: float) -> bool:
    return signal_level >= squelch_db

