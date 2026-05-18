from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class Channel(BaseModel):
    id: str
    name: str
    system: str
    category: str = "other"
    frequency_hz: int
    modulation: str = "nfm"
    encrypted: bool = False
    favorite: bool = False
    priority: bool = False
    service_type: str = "custom"
    delay_seconds: float = 2.0
    number_tag: Optional[int] = None
    department: Optional[str] = None
    primary_radio_id: Optional[str] = None
    target_radio_id: Optional[str] = None


class ChannelCreate(BaseModel):
    name: str
    system: str
    category: str = "other"
    frequency_hz: int
    modulation: str = "nfm"
    encrypted: bool = False
    favorite: bool = False
    priority: bool = False
    service_type: str = "custom"
    delay_seconds: float = 2.0


class CallEntry(BaseModel):
    id: str
    name: str
    frequency_hz: int
    service_type: str = "custom"
    time: str


class ScannerStatus(BaseModel):
    state: str = "NO_SIGNAL"
    message: str = "Ready"
    simulated: bool = True
    held: bool = False
    in_delay: bool = False
    delay_remaining: float = 0.0
    signal_power: float = -72.0
    signal_threshold: float = -35.0
    gain_db: Optional[float] = None
    channels_scanned: int = 0
    muted: bool = False
    active_channel: Optional[Channel] = None


class ScannerFilterPayload(BaseModel):
    channel_ids: Optional[list[str]] = None


class ScannerGroupFilterPayload(BaseModel):
    systems: Optional[list[str]] = None


class TunePayload(BaseModel):
    channel_id: str


class MutePayload(BaseModel):
    muted: bool


class GainPayload(BaseModel):
    gain_db: Optional[float] = None


class Talkgroup(BaseModel):
    id: str
    decimal: int
    hex: Optional[str] = None
    mode: Optional[str] = None
    alpha_tag: str
    description: Optional[str] = None
    service_type: str = "custom"
    tag: Optional[str] = None
    encrypted: bool = False


class TalkgroupSelectPayload(BaseModel):
    decimal: Optional[int] = None
    talkgroupId: Optional[str] = None
    talkgroup: Optional[dict[str, Any]] = None


class P25ActiveCall(BaseModel):
    talkgroup: Optional[Talkgroup] = None
    talkgroup_decimal: Optional[int] = None
    voice_frequency_hz: Optional[int] = None
    source_radio_id: Optional[str] = None
    target_radio_id: Optional[str] = None


class P25Status(BaseModel):
    running: bool = False
    state: str = "WAITING_FOR_TALKGROUP"
    message: str = "Built-in decoder idle"
    selected_talkgroup: Optional[Talkgroup] = None
    tracking_label: Optional[str] = None
    tracked_talkgroup_count: int = 0
    active_call: Optional[P25ActiveCall] = None
    last_event: Optional[dict[str, Any]] = None
    preferred_control_channel_hz: Optional[int] = None
    external_decoder: dict[str, Any] = Field(default_factory=lambda: {"installed": False, "headless": True, "managed": True, "engine": "dsdplus"})
    voice_scan_active: bool = False
    voice_scan_error: Optional[str] = None
    voice_sweep_stats: Optional[dict[str, Any]] = None
    active_voice_channels: list[dict[str, Any]] = Field(default_factory=list)


class FmStation(BaseModel):
    id: str
    callsign: str
    name: str
    frequency_hz: int
    frequency_mhz: float
    service_type: str = "fm_radio"
    artist: Optional[str] = None
    song_title: Optional[str] = None
    now_playing: Optional[str] = None
    program_name: Optional[str] = None
    program_host: Optional[str] = None
    album: Optional[str] = None
    metadata_status: str = "ok"
    metadata_source: str = "local catalog"
    metadata_raw: Optional[str] = None


class FmPlayPayload(BaseModel):
    channel_id: str


class FmFineTunePayload(BaseModel):
    channel_id: str
    offset_hz: int = 0


class FmPlayerStatus(BaseModel):
    playing: bool = False
    chunks: int = 0
    station: Optional[FmStation] = None
    frequency_hz: Optional[int] = None
    tuned_frequency_hz: Optional[int] = None
    frequency_offset_hz: int = 0
    gain_used_db: Optional[float] = None
    last_db: float = -72.0
    peak_db: float = -58.0


class RuntimeStatus(BaseModel):
    ready: bool = False
    runtime_root: str
    message: str = "Runtime not synced"
    tools: dict[str, bool] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class SdrBand(BaseModel):
    name: str
    band_type: str = "other"
    start_hz: int
    end_hz: int


class SdrBandplan(BaseModel):
    id: str
    name: str
    country_code: Optional[str] = None
    source_path: str
    band_count: int = 0
    featured_bands: list[SdrBand] = Field(default_factory=list)


class SdrTunerProfile(BaseModel):
    id: str
    name: str
    tuner_type: str
    source_path: str
    unique_id: Optional[str] = None
    sample_rate_hz: Optional[int] = None
    frequency_correction_ppm: Optional[float] = None
    minimum_frequency_hz: Optional[int] = None
    maximum_frequency_hz: Optional[int] = None
    gain_profile: dict[str, Any] = Field(default_factory=dict)


class SdrDecoderEngine(BaseModel):
    id: str
    name: str
    managed: bool = True
    headless: bool = False
    source_path: Optional[str] = None
    protocols: list[str] = Field(default_factory=list)
    health: Optional[str] = None
    running: bool = False
    message: Optional[str] = None


class SdrSystemNode(BaseModel):
    id: str
    name: str
    system_type: str
    source_path: Optional[str] = None
    location: Optional[str] = None
    control_channels_hz: list[int] = Field(default_factory=list)
    active_control_channel_hz: Optional[int] = None
    voice_channel_count: int = 0
    talkgroup_count: int = 0
    preferred_tuner_profile_id: Optional[str] = None
    preferred_decoder_engine_id: Optional[str] = None


class SdrSystemProfile(BaseModel):
    id: str
    name: str
    location: Optional[str] = None
    focus: Optional[str] = None
    capabilities: list[str] = Field(default_factory=list)
    bandplan: Optional[SdrBandplan] = None
    tuner_profiles: list[SdrTunerProfile] = Field(default_factory=list)
    decoder_engines: list[SdrDecoderEngine] = Field(default_factory=list)
    systems: list[SdrSystemNode] = Field(default_factory=list)


class PlaylistSyncStatus(BaseModel):
    updated: bool = False
    message: str = "Playlist already in sync"
