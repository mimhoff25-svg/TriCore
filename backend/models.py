"""Shared scanner states and data models for TriCore Scanner.

Modeled on Uniden BCD536HP / SDS100 operational behavior.
"""

from enum import Enum
from pydantic import BaseModel


class ScannerState(str, Enum):
    SCANNING = "SCANNING"
    RECEIVING_CALL = "RECEIVING_CALL"
    HOLDING_CHANNEL = "HOLDING_CHANNEL"
    MUTED = "MUTED"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"
    NO_SIGNAL = "NO_SIGNAL"
    DEVICE_NOT_FOUND = "DEVICE_NOT_FOUND"


class Channel(BaseModel):
    """A conventional channel loaded from configs/frequencies/*.json.

    Fields mirror Uniden BCD536HP per-channel settings.
    """

    id: str
    name: str
    system: str
    frequency_hz: int
    modulation: str = "nfm"         # nfm, fm, am, wfm
    encrypted: bool = False         # true → mark Unavailable and skip
    favorite: bool = False
    priority: bool = False          # checked every N channels like real scanners
    service_type: str = "custom"    # police/fire/ems/weather/public_works/utility
                                    # transportation/interop/fm_radio/am_radio/custom
    category: str = "other"         # broad group: public_safety/weather/interop
                                    # fm_radio/am_radio/infrastructure/other
    delay_seconds: float = 2.0      # post-signal delay; Uniden default = 2s
    number_tag: int | None = None   # quick-access number 0–999
    volume_offset: int = 0          # per-channel volume trim (future audio)


class TrunkedSite(BaseModel):
    """A P25 trunked RF site with control and voice frequencies."""

    id: str
    name: str
    rfss: int | None = None
    site: int | None = None
    county: str = ""
    control_channels_hz: list[int] = []
    voice_channels_hz: list[int] = []


class Talkgroup(BaseModel):
    """A trunked talkgroup carried by a P25 system."""

    id: str
    decimal: int
    hex: str
    mode: str = "D"
    alpha_tag: str
    description: str = ""
    service_type: str = "custom"
    tag: str = ""
    encrypted: bool = False


class TrunkedSystem(BaseModel):
    """Scanner metadata for a trunked radio system."""

    id: str
    name: str
    short_name: str
    location: str
    system_type: str
    system_voice: str
    wacn: str | None = None
    system_id: str | None = None
    source: dict = {}
    sites: list[TrunkedSite] = []
    talkgroups: list[Talkgroup] = []


class TrunkingStatus(BaseModel):
    """Current P25 trunking/decode status shown in the UI."""

    enabled: bool = False
    decoder: str = "not_configured"
    state: str = "NOT_READY"
    message: str = "P25 trunking decoder is not configured"
    active_system: str | None = None
    active_site: str | None = None
    control_channel_hz: int | None = None
    active_talkgroup: Talkgroup | None = None
    voice_frequency_hz: int | None = None
    source_radio_id: int | None = None
    target_radio_id: int | None = None
    encrypted: bool = False
    last_event_utc: str | None = None


class ScannerStatus(BaseModel):
    """Current status broadcast to the UI on every poll."""

    state: ScannerState
    message: str
    active_channel: Channel | None = None
    signal_power: float = 0.0
    signal_threshold: float = 0.0
    gain_db: float | None = None
    simulated: bool = False
    held: bool = False              # scanner is locked to one channel (Stay Here)
    in_delay: bool = False          # signal dropped; delay timer is counting
    delay_remaining: float = 0.0    # seconds left in delay countdown
    skipped_count: int = 0          # number of temporarily skipped channels
    channels_scanned: int = 0       # total channels checked this session
