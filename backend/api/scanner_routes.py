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
from .audio_routes import stop_live_audio_process
from .shared import scanner_core


router = APIRouter(prefix="/api/scanner", tags=["scanner"])


def _sync_transcriber_to_status(status):
    from ..transcriber import transcriber

    if not transcriber.running:
        return status

    transcriber.stop()
    scanner_core.restore_rtl_receiver_after_external_audio()

    channel = status.current_channel or status.active_channel
    if channel is None:
        return status

    modulation = str(channel.modulation or "nfm").lower()
    if modulation not in {"nfm", "am"}:
        return status

    stop_live_audio_process()
    scanner_core.release_rtl_receiver_for_external_audio()
    started = transcriber.start([channel])
    if not started.get("ok"):
        scanner_core.restore_rtl_receiver_after_external_audio()

    return status


def _prepare_tuner_change() -> None:
    stop_live_audio_process()
    current_channel = scanner_core.current_channel
    if current_channel is None or current_channel.modulation != "p25_placeholder":
        scanner_core.shutdown_managed_p25_runtime(clear_current=False)


@router.get("/status")
def scanner_status():
    return scanner_core.status()


@router.post("/start")
def start_scanner():
    _prepare_tuner_change()
    return scanner_core.start()


@router.post("/stop")
def stop_scanner():
    _prepare_tuner_change()
    return scanner_core.stop()


@router.post("/pause")
def pause_scanner():
    _prepare_tuner_change()
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
    _prepare_tuner_change()
    return scanner_core.skip()


@router.post("/next")
def next_channel():
    _prepare_tuner_change()
    return scanner_core.next_channel()


@router.post("/lockout")
def lockout_channel(payload: ChannelActionPayload = ChannelActionPayload()):
    return scanner_core.lockout(payload.channel_id)


@router.post("/priority")
def set_priority(payload: PriorityPayload = PriorityPayload()):
    return scanner_core.priority(payload.channel_id, payload.priority)


@router.post("/manual-tune")
def manual_tune(payload: ManualTunePayload):
    _prepare_tuner_change()
    status = scanner_core.manual_tune(
        frequency_hz=payload.frequency_hz,
        frequency_mhz=payload.frequency_mhz,
        modulation=payload.modulation,
        name=payload.name,
    )
    return _sync_transcriber_to_status(status)


@router.post("/tune")
def tune_channel(payload: ChannelActionPayload):
    _prepare_tuner_change()
    status = scanner_core.tune_channel(payload.channel_id or "")
    return _sync_transcriber_to_status(status)


@router.post("/search/start")
def start_search(payload: SearchStartPayload = SearchStartPayload()):
    _prepare_tuner_change()
    status = scanner_core.start_search(payload.range_id)
    return _sync_transcriber_to_status(status)


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
    stop_live_audio_process()
    return scanner_core.set_receiver_mode(payload.simulated)
