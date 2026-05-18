from __future__ import annotations

from typing import Optional

from ..radio.models import ReceiverStatus, SignalReading
from .base_receiver import BaseReceiver
from .signal_meter import simulated_signal_level, squelch_open


class DemoReceiver(BaseReceiver):
    def __init__(self) -> None:
        self.frequency_hz: Optional[int] = None
        self.modulation = "nfm"
        self.gain_db: Optional[float] = None
        self.squelch_db = -65.0
        self._tick = 0

    def tune(self, frequency_hz: int, modulation: str = "nfm") -> ReceiverStatus:
        self.frequency_hz = int(frequency_hz)
        self.modulation = modulation
        return self.status()

    def set_gain(self, gain_db: Optional[float]) -> ReceiverStatus:
        self.gain_db = gain_db
        return self.status()

    def set_squelch(self, squelch_db: float) -> ReceiverStatus:
        self.squelch_db = float(squelch_db)
        return self.status()

    def read_signal(self) -> SignalReading:
        self._tick += 1
        frequency = int(self.frequency_hz or 0)
        level = simulated_signal_level(frequency, self._tick) if frequency else -100.0
        return SignalReading(
            frequency_hz=frequency,
            level_db=level,
            squelch_open=squelch_open(level, self.squelch_db),
            simulated=True,
        )

    def status(self) -> ReceiverStatus:
        signal = self.read_signal()
        return ReceiverStatus(
            mode="demo",
            label="Demo",
            simulated=True,
            available=True,
            tuned_frequency_hz=self.frequency_hz,
            gain_db=self.gain_db,
            squelch_db=self.squelch_db,
            signal_level=signal.level_db,
            message="Demo receiver ready. No RTL-SDR hardware required.",
        )

