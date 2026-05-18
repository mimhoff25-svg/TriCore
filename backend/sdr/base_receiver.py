from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..radio.models import ReceiverStatus, SignalReading


class BaseReceiver(ABC):
    @abstractmethod
    def tune(self, frequency_hz: int, modulation: str = "nfm") -> ReceiverStatus:
        raise NotImplementedError

    @abstractmethod
    def set_gain(self, gain_db: Optional[float]) -> ReceiverStatus:
        raise NotImplementedError

    @abstractmethod
    def set_squelch(self, squelch_db: float) -> ReceiverStatus:
        raise NotImplementedError

    @abstractmethod
    def read_signal(self) -> SignalReading:
        raise NotImplementedError

    @abstractmethod
    def status(self) -> ReceiverStatus:
        raise NotImplementedError

    def close(self) -> None:
        return None
