from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, computed_field


SERVICE_TYPES = {
    "public_safety",
    "police",
    "fire_ems",
    "public_works",
    "railroad",
    "airband",
    "marine",
    "noaa_weather",
    "fm_broadcast",
    "ham",
    "business",
    "custom",
}

MODULATIONS = {"nfm", "wfm", "am", "p25_placeholder"}
SCANNER_STATES = {"stopped", "scanning", "paused", "holding", "searching", "manual_tune", "error"}


class Channel(BaseModel):
    id: str
    name: str
    frequency_hz: int
    modulation: str = "nfm"
    service_type: str = "custom"
    bank_id: str = "custom"
    system_name: str = "Local"
    category: str = "other"
    p25_talkgroup_decimal: Optional[int] = None
    p25_control_channels_hz: list[int] = Field(default_factory=list)
    encrypted: bool = False
    unavailable: bool = False
    favorite: bool = False
    priority: bool = False
    scan_enabled: bool = True
    locked_out: bool = False
    delay_seconds: float = 2.0
    number_tag: Optional[int] = None
    notes: Optional[str] = None
    signal_level: float = -100.0
    stream_url: Optional[str] = None

    @computed_field
    @property
    def frequency_mhz(self) -> float:
        return round(self.frequency_hz / 1_000_000, 6)


class Bank(BaseModel):
    id: str
    name: str
    service_type: str
    enabled: bool = True
    priority: int = 100
    description: str = ""


class ServiceType(BaseModel):
    id: str
    label: str
    description: str = ""


class RadioSystem(BaseModel):
    id: str
    name: str
    system_type: str = "conventional"
    description: str = ""


class ReceiverStatus(BaseModel):
    mode: str = "demo"
    label: str = "Demo"
    simulated: bool = True
    available: bool = True
    demo_available: bool = True
    rtl_sdr_available: bool = False
    tuned_frequency_hz: Optional[int] = None
    gain_db: Optional[float] = None
    squelch_db: float = -65.0
    signal_level: float = -100.0
    message: str = "Demo receiver ready."
    error_message: Optional[str] = None
    last_rtl_error: Optional[str] = None


class ScannerSettings(BaseModel):
    selected_bank_ids: list[str] = Field(default_factory=list)
    squelch_db: float = -65.0
    gain_db: Optional[float] = None
    muted: bool = False


class SignalReading(BaseModel):
    frequency_hz: int
    level_db: float
    squelch_open: bool
    simulated: bool = True


class DecoderStatus(BaseModel):
    id: str
    label: str
    modulation: str
    ready: bool = True
    active: bool = False
    message: str = "Decoder idle."
    sync_state: Optional[str] = None
    control_channel_hz: Optional[int] = None
    control_channels_hz: list[int] = Field(default_factory=list)
    voice_frequency_hz: Optional[int] = None
    talkgroup_decimal: Optional[int] = None
    selected_talkgroup_decimal: Optional[int] = None
    source_radio_id: Optional[str] = None
    target_radio_id: Optional[str] = None
    nac: Optional[str] = None
    phase: Optional[str] = None
    encrypted_call: bool = False
    recent_radios: list[dict[str, Any]] = Field(default_factory=list)
    activity: dict[str, Any] = Field(default_factory=dict)
    runtime: dict[str, Any] = Field(default_factory=dict)


class SearchRange(BaseModel):
    id: str
    name: str
    service_type: str
    start_hz: int
    end_hz: int
    step_hz: int
    modulation: str = "nfm"
    description: str = ""

    @computed_field
    @property
    def start_mhz(self) -> float:
        return round(self.start_hz / 1_000_000, 6)

    @computed_field
    @property
    def end_mhz(self) -> float:
        return round(self.end_hz / 1_000_000, 6)


class ScannerStatus(BaseModel):
    state: str = "stopped"
    is_scanning: bool = False
    is_paused: bool = False
    is_holding: bool = False
    is_muted: bool = False
    current_channel: Optional[Channel] = None
    active_channel: Optional[Channel] = None
    current_frequency_hz: Optional[int] = None
    signal_level: float = -100.0
    receiver_mode: str = "Demo"
    simulated: bool = True
    squelch_db: float = -65.0
    gain_db: Optional[float] = None
    selected_bank_ids: list[str] = Field(default_factory=list)
    message: str = "Scanner stopped."
    error_message: Optional[str] = None
    search_range: Optional[SearchRange] = None
    decoder: Optional[DecoderStatus] = None

    @computed_field
    @property
    def scanner_state(self) -> str:
        return {
            "stopped": "Stopped",
            "scanning": "Scanning",
            "paused": "Paused",
            "holding": "Holding",
            "searching": "Searching",
            "manual_tune": "Manual Tune",
            "error": "Error",
        }.get(self.state, self.state.title())
