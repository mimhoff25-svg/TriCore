from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from .models import (
    ChannelCreate,
    FmFineTunePayload,
    FmPlayPayload,
    GainPayload,
    MutePayload,
    ScannerFilterPayload,
    ScannerGroupFilterPayload,
    TalkgroupSelectPayload,
    TunePayload,
)
from .scanner_controller import controller
from .transcriber import transcriber


app = FastAPI(title="TriCore Scanner Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def p25_payload():
    payload = controller.p25_status().model_dump()
    payload["selectedTalkgroup"] = controller.p25_status().selected_talkgroup.id if controller.p25_status().selected_talkgroup else None
    payload["activeCall"] = payload.get("active_call")
    payload["voiceScanActive"] = payload.get("voice_scan_active")
    payload["trackingLabel"] = payload.get("tracking_label")
    payload["trackedTalkgroupCount"] = payload.get("tracked_talkgroup_count")
    return payload


@app.get("/api/status")
def get_status():
    return controller.scanner_status()


@app.get("/api/calls")
def get_calls():
    return controller.get_calls()


@app.get("/api/channels")
def get_channels():
    return controller.get_channels()


@app.post("/api/channels/add")
def add_channel(payload: ChannelCreate):
    return controller.add_channel(payload)


@app.post("/api/scanner/channel-filter")
def set_channel_filter(payload: ScannerFilterPayload):
    controller.set_channel_filter(payload.channel_ids)
    return {"ok": True}


@app.post("/api/scanner/group-filter")
def set_group_filter(payload: ScannerGroupFilterPayload):
    controller.set_group_filter(payload.systems)
    return {"ok": True}


@app.post("/api/scanner/start")
def start_scanner():
    return controller.start_scanner()


@app.post("/api/scanner/stop")
def stop_scanner():
    return controller.stop_scanner()


@app.post("/api/scanner/tune")
def tune_channel(payload: TunePayload):
    return controller.tune_channel(payload.channel_id)


@app.post("/api/scanner/hold")
def hold_scanner():
    return controller.hold()


@app.post("/api/scanner/clear-hold")
def clear_hold():
    return controller.clear_hold()


@app.post("/api/scanner/skip")
def skip_channel():
    return controller.skip()


@app.post("/api/scanner/mute")
def mute_scanner(payload: MutePayload):
    return controller.set_mute(payload.muted)


@app.post("/api/scanner/gain")
def set_gain(payload: GainPayload):
    return controller.set_gain(payload.gain_db)


@app.get("/api/fm/stations")
def get_fm_stations():
    return controller.fm_stations()


@app.get("/api/fm/player/status")
def get_fm_player_status():
    return controller.fm_player_status()


@app.post("/api/fm/play")
def play_fm(payload: FmPlayPayload):
    return controller.play_fm(payload.channel_id)


@app.post("/api/fm/stop")
def stop_fm():
    return controller.stop_fm()


@app.post("/api/fm/fine-tune")
def fine_tune_fm(payload: FmFineTunePayload):
    return controller.fine_tune_fm(payload.channel_id, payload.offset_hz)


@app.get("/api/trunked/talkgroups")
def get_trunked_talkgroups(include_encrypted: bool = Query(default=False)):
    return controller.get_talkgroups(include_encrypted=include_encrypted)


@app.get("/api/p25/status")
def get_p25_status():
    return p25_payload()


@app.post("/api/p25/start")
def start_p25():
    controller.start_p25()
    return p25_payload()


@app.post("/api/p25/stop")
def stop_p25():
    controller.stop_p25()
    return p25_payload()


@app.post("/api/p25/select-talkgroup")
def select_talkgroup(payload: TalkgroupSelectPayload):
    controller.select_talkgroup(
        decimal=payload.decimal,
        talkgroup_id=payload.talkgroupId,
        talkgroup_payload=payload.talkgroup,
    )
    return p25_payload()


@app.post("/api/p25/sync-playlist")
def sync_p25_playlist():
    return controller.sync_p25_playlist()


@app.get("/api/sdr/runtime/status")
def get_runtime_status():
    return controller.runtime_status()


@app.get("/api/sdr/system")
def get_sdr_system():
    return controller.sdr_system_profile()


@app.post("/api/sdr/runtime/sync")
def sync_runtime_status():
    return controller.sync_runtime()


# ── Whisper transcription ──────────────────────────────────────────────

@app.get("/api/transcripts")
def get_transcripts():
    return transcriber.get_transcripts()


@app.get("/api/transcripts/status")
def get_transcripts_status():
    return transcriber.status()


@app.post("/api/transcripts/start")
def start_transcription():
    channels = controller.get_channels()
    return transcriber.start(channels)


@app.post("/api/transcripts/stop")
def stop_transcription():
    transcriber.stop()
    return {"ok": True}


@app.post("/api/transcripts/clear")
def clear_transcripts():
    transcriber.clear_transcripts()
    return {"ok": True}
