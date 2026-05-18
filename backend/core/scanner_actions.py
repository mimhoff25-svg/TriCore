from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class ChannelActionPayload(BaseModel):
    channel_id: Optional[str] = None


class PriorityPayload(BaseModel):
    channel_id: Optional[str] = None
    priority: bool = True


class ManualTunePayload(BaseModel):
    frequency_hz: Optional[int] = None
    frequency_mhz: Optional[float] = None
    modulation: str = "nfm"
    name: Optional[str] = None


class SearchStartPayload(BaseModel):
    range_id: Optional[str] = None


class SquelchPayload(BaseModel):
    squelch_db: float


class GainPayload(BaseModel):
    gain_db: Optional[float] = None


class ReceiverModePayload(BaseModel):
    simulated: bool = True

