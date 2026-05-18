from __future__ import annotations

from fastapi import APIRouter

from ..core.scanner_actions import (
    ChannelActionPayload,
    GainPayload,
    ManualTunePayload,
    PriorityPayload,
    ReceiverModePayload,
    SearchStartPayload,
    SquelchPayload,
)
from .shared import scanner_core


router = APIRouter(prefix="/api/scanner", tags=["scanner"])


@router.get("/status")
def scanner_status():
    return scanner_core.status()


@router.post("/start")
def start_scanner():
    return scanner_core.start()


@router.post("/stop")
def stop_scanner():
    return scanner_core.stop()


@router.post("/pause")
def pause_scanner():
    return scanner_core.pause()


@router.post("/resume")
def resume_scanner():
    return scanner_core.resume()


@router.post("/hold")
def hold_scanner():
    return scanner_core.hold()


@router.post("/release")
def release_scanner():
    return scanner_core.release()


@router.post("/release-hold")
def release_hold_scanner():
    return scanner_core.release()


@router.post("/clear-hold")
def clear_hold_scanner():
    return scanner_core.release()


@router.post("/skip")
def skip_channel():
    return scanner_core.skip()


@router.post("/next")
def next_channel():
    return scanner_core.next_channel()


@router.post("/lockout")
def lockout_channel(payload: ChannelActionPayload = ChannelActionPayload()):
    return scanner_core.lockout(payload.channel_id)


@router.post("/priority")
def set_priority(payload: PriorityPayload = PriorityPayload()):
    return scanner_core.priority(payload.channel_id, payload.priority)


@router.post("/manual-tune")
def manual_tune(payload: ManualTunePayload):
    return scanner_core.manual_tune(
        frequency_hz=payload.frequency_hz,
        frequency_mhz=payload.frequency_mhz,
        modulation=payload.modulation,
        name=payload.name,
    )


@router.post("/tune")
def tune_channel(payload: ChannelActionPayload):
    return scanner_core.tune_channel(payload.channel_id or "")


@router.post("/search/start")
def start_search(payload: SearchStartPayload = SearchStartPayload()):
    return scanner_core.start_search(payload.range_id)


@router.post("/search/stop")
def stop_search():
    return scanner_core.stop_search()


@router.post("/squelch")
def set_squelch(payload: SquelchPayload):
    return scanner_core.set_squelch(payload.squelch_db)


@router.post("/gain")
def set_gain(payload: GainPayload):
    return scanner_core.set_gain(payload.gain_db)


@router.post("/mute")
def set_mute(payload: dict):
    return scanner_core.set_mute(bool(payload.get("muted")))


@router.post("/receiver-mode")
def legacy_receiver_mode(payload: ReceiverModePayload):
    return scanner_core.set_receiver_mode(payload.simulated)
