"""FastAPI entry point for TriCore Scanner.

Run with:
    python -m uvicorn app:app --reload --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from scanner_controller import ScannerController
from windows_rtlsdr_tools import run_rtl_test


app = FastAPI(title="TriCore Scanner API", version="0.2.0")
controller = ScannerController()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5175",
        "http://localhost:5176",
        "http://127.0.0.1:5176",
        "null",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request bodies ───────────────────────────────────────────────────────────

class GainRequest(BaseModel):
    """Use gain_db=null for automatic gain."""
    gain_db: float | None = None


class ReceiverModeRequest(BaseModel):
    simulated: bool = True


class MuteRequest(BaseModel):
    muted: bool = False


class GroupFilterRequest(BaseModel):
    systems: list[str] | None = None  # None = all enabled


class ChannelFilterRequest(BaseModel):
    channel_ids: list[str] | None = None  # None = all enabled


class TuneRequest(BaseModel):
    channel_id: str


class FmPlayRequest(BaseModel):
    channel_id: str
    audio_device: int | None = None


class FmFineTuneRequest(BaseModel):
    channel_id: str
    offset_hz: int


class P25TalkgroupRequest(BaseModel):
    decimal: int


class AddChannelRequest(BaseModel):
    name: str
    system: str
    frequency_hz: int
    modulation: str = "nfm"
    service_type: str = "custom"
    category: str = "other"
    delay_seconds: float = 2.0
    priority: bool = False
    favorite: bool = False
    encrypted: bool = False


# ── Status ────────────────────────────────────────────────────────────────────

@app.get("/api/status")
def get_status():
    """Return the latest scanner state for the dashboard."""
    return controller.status()


# ── Scan lifecycle ────────────────────────────────────────────────────────────

@app.post("/api/scanner/start")
def start_scanner():
    """Start scanning. Clears hold and temporary skips."""
    return controller.start()


@app.post("/api/scanner/stop")
def stop_scanner():
    """Stop scanning. Clears temporary skips like a power cycle."""
    return controller.stop()


# ── Real-scanner button controls ──────────────────────────────────────────────

@app.post("/api/scanner/hold")
def hold_channel():
    """Stay Here — lock scanner to the current channel."""
    return controller.hold()


@app.post("/api/scanner/clear-hold")
def clear_hold():
    """Resume — release hold and return to normal scanning."""
    return controller.clear_hold()


@app.post("/api/scanner/skip")
def skip_channel():
    """Skip — temporarily avoid the current channel (Temporary Avoid)."""
    return controller.skip()


@app.post("/api/scanner/clear-skipped")
def clear_skipped():
    """Clear all temporary skips."""
    return controller.clear_skipped()


@app.post("/api/scanner/mute")
def set_mute(request: MuteRequest):
    """Mute or unmute audio output."""
    return controller.set_muted(request.muted)


# ── Device settings ───────────────────────────────────────────────────────────

@app.post("/api/scanner/gain")
def set_gain(request: GainRequest):
    """Set manual RTL-SDR gain, or auto gain when gain_db is null."""
    return controller.set_gain(request.gain_db)


@app.post("/api/scanner/receiver-mode")
def set_receiver_mode(request: ReceiverModeRequest):
    """Switch between demo mode (no dongle) and real RTL-SDR mode."""
    try:
        return controller.set_simulated(request.simulated)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


# ── Group filter / tune / call log ───────────────────────────────────────────

@app.post("/api/scanner/group-filter")
def set_group_filter(request: GroupFilterRequest):
    """Enable/disable specific systems. Pass systems=null to enable all."""
    return controller.set_group_filter(request.systems)


@app.post("/api/scanner/channel-filter")
def set_channel_filter(request: ChannelFilterRequest):
    """Enable a scanner playlist by channel IDs. Pass channel_ids=null to enable all."""
    return controller.set_channel_filter(request.channel_ids)


@app.post("/api/scanner/tune")
def tune_to_channel(request: TuneRequest):
    """Jump immediately to a specific channel and hold it."""
    found, status = controller.tune_to(request.channel_id)
    if not found:
        raise HTTPException(status_code=404, detail=f"Channel {request.channel_id!r} not found")
    return status


@app.get("/api/calls")
def get_calls():
    """Return recent call log, newest first (max 100 entries)."""
    return controller.get_calls()


# FM broadcast station ID metadata

@app.get("/api/fm/stations")
def get_fm_stations():
    """Return configured FM broadcast station identities."""
    return controller.fm_stations()


@app.get("/api/fm/active")
def get_active_fm_station():
    """Return station ID metadata for the active FM channel, when any."""
    return controller.active_fm_station() or {}


@app.post("/api/fm/play")
def play_fm_station(request: FmPlayRequest):
    """Tune and play a configured FM broadcast station through the audio output."""
    found, status = controller.play_fm(request.channel_id, audio_device=request.audio_device)
    if not found:
        raise HTTPException(status_code=404, detail=status["message"])
    return status


@app.post("/api/fm/stop")
def stop_fm_station():
    """Stop FM broadcast audio playback."""
    return controller.stop_fm()


@app.post("/api/fm/fine-tune")
def fine_tune_fm_station(request: FmFineTuneRequest):
    """Apply a small frequency offset and restart the current FM station."""
    found, status = controller.fine_tune_fm(request.channel_id, request.offset_hz)
    if not found:
        raise HTTPException(status_code=404, detail=status["message"])
    return status


@app.get("/api/fm/player/status")
def get_fm_player_status():
    """Return live FM playback status."""
    return controller.fm_player_status()


# Trunked P25 metadata / decoder status

@app.get("/api/trunked/systems")
def get_trunked_systems():
    """Return configured trunked radio systems and non-encrypted talkgroups."""
    return controller.trunked_systems()


@app.get("/api/trunked/talkgroups")
def get_trunked_talkgroups(include_encrypted: bool = False):
    """Return trunked talkgroups. Encrypted talkgroups are hidden by default."""
    return controller.trunked_talkgroups(include_encrypted=include_encrypted)


@app.get("/api/trunked/status")
def get_trunking_status():
    """Return P25 trunking + decoder status."""
    return controller.p25_status()


# ── Channel & system browser ──────────────────────────────────────────────────

@app.get("/api/p25/status")
def get_p25_status():
    """Return live TriCore P25/SDRTrunk integration status."""
    return controller.p25_status()


@app.post("/api/p25/start")
def start_p25_decoder():
    """Start SDRTrunk using the synced GATRRS playlist."""
    return controller.p25_start()


@app.post("/api/p25/stop")
def stop_p25_decoder():
    """Stop the SDRTrunk process launched by TriCore."""
    return controller.p25_stop()


@app.post("/api/p25/select-talkgroup")
def select_p25_talkgroup(request: P25TalkgroupRequest):
    """Select a P25 talkgroup to monitor and launch SDRTrunk for audio."""
    return controller.p25_select_talkgroup(request.decimal)


@app.post("/api/p25/sync-playlist")
def sync_p25_playlist():
    """Sync configured GATRRS talkgroups into the SDRTrunk playlist."""
    return controller.p25_sync_playlist()


@app.get("/api/sdr/runtime/status")
def get_sdr_runtime_status():
    """Return TriCore's copied SDR software runtime status."""
    return controller.sdr_runtime_status()


@app.post("/api/sdr/runtime/sync")
def sync_sdr_runtime():
    """Copy local SDR tools into TriCore's managed SDR runtime folder."""
    return controller.sdr_runtime_sync()


@app.get("/api/channels")
def get_channels():
    """Return all loaded channels (the full frequency list)."""
    return controller.scanner.channels


@app.get("/api/systems")
def get_systems():
    """Return a summary of every radio system in the frequency list."""
    systems: dict[str, dict] = {}
    for ch in controller.scanner.channels:
        if ch.system not in systems:
            systems[ch.system] = {
                "name": ch.system,
                "category": ch.category,
                "channel_count": 0,
                "service_types": set(),
                "has_priority": False,
                "has_favorite": False,
            }
        s = systems[ch.system]
        s["channel_count"] += 1
        s["service_types"].add(ch.service_type)
        if ch.priority:
            s["has_priority"] = True
        if ch.favorite:
            s["has_favorite"] = True

    result = []
    for s in systems.values():
        result.append({
            "name": s["name"],
            "category": s["category"],
            "channel_count": s["channel_count"],
            "service_types": sorted(s["service_types"]),
            "has_priority": s["has_priority"],
            "has_favorite": s["has_favorite"],
        })
    return result


@app.post("/api/channels/add")
def add_channel(request: AddChannelRequest):
    """Add a new conventional channel to the scan list at runtime."""
    return controller.add_channel(request.model_dump())


@app.delete("/api/channels/{channel_id}")
def remove_channel(channel_id: str):
    """Remove a channel from the scan list by ID."""
    found, status = controller.remove_channel(channel_id)
    if not found:
        raise HTTPException(status_code=404, detail=f"Channel {channel_id!r} not found")
    return status


# ── Diagnostics ───────────────────────────────────────────────────────────────

@app.get("/api/rtl-test")
def rtl_test():
    """Run rtl_test.exe briefly for Windows driver diagnostics."""
    success, output = run_rtl_test()
    return {"success": success, "output": output}
