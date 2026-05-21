from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .audio_routes import stop_live_audio_process
from .shared import scanner_core


router = APIRouter(prefix="/api/p25", tags=["p25"])


class P25TalkgroupPayload(BaseModel):
    decimal: Optional[int] = None
    talkgroup_decimal: Optional[int] = None
    talkgroupId: Optional[str] = None
    talkgroup: Optional[dict] = None


def _stop_analog_audio_for_p25() -> None:
    stop_live_audio_process()
    try:
        from ..transcriber import transcriber

        if transcriber.running:
            transcriber.stop()
    except Exception:
        pass
    scanner_core.release_rtl_receiver_for_external_audio()


def _managed_p25_decoder_status():
    decoder = scanner_core.decoders.get("p25_placeholder")
    if decoder is None:
        return None
    try:
        return decoder.status()
    except Exception:
        return None


def _selected_talkgroup_payload(channel, decoder):
    talkgroup_decimal = None
    if channel is not None and channel.p25_talkgroup_decimal is not None:
        talkgroup_decimal = channel.p25_talkgroup_decimal
    elif decoder is not None and decoder.selected_talkgroup_decimal is not None:
        talkgroup_decimal = decoder.selected_talkgroup_decimal

    if talkgroup_decimal is None:
        return None

    talkgroup_channel = scanner_core.frequency_manager.p25_talkgroup_channel(int(talkgroup_decimal))
    if talkgroup_channel is not None:
        return {
            "decimal": talkgroup_channel.p25_talkgroup_decimal,
            "alpha_tag": talkgroup_channel.name,
            "description": talkgroup_channel.notes,
            "service_type": talkgroup_channel.service_type,
            "encrypted": talkgroup_channel.encrypted,
        }

    return {
        "decimal": int(talkgroup_decimal),
        "alpha_tag": f"TG {int(talkgroup_decimal)}",
        "description": None,
        "service_type": None,
        "encrypted": False,
    }


def _status_payload():
    status = scanner_core.status(advance=False)
    channel = status.current_channel or status.active_channel
    if channel is not None and channel.modulation != "p25_placeholder":
        channel = None
    decoder = status.decoder if channel is not None else _managed_p25_decoder_status()
    selected_talkgroup = _selected_talkgroup_payload(channel, decoder)
    return {
        "running": bool(decoder.active) if decoder is not None else False,
        "state": status.state,
        "message": decoder.message if decoder is not None else status.message,
        "selected_talkgroup": selected_talkgroup,
        "tracking_label": selected_talkgroup["alpha_tag"] if selected_talkgroup is not None else None,
        "preferred_control_channel_hz": (
            decoder.control_channel_hz if decoder is not None and decoder.control_channel_hz is not None else
            (channel.p25_control_channels_hz[0] if channel is not None and channel.p25_control_channels_hz else (channel.frequency_hz if channel is not None else None))
        ),
        "current_frequency_hz": status.current_frequency_hz,
        "voice_frequency_hz": decoder.voice_frequency_hz if decoder is not None else None,
        "talkgroup_decimal": decoder.talkgroup_decimal if decoder is not None else None,
        "source_radio_id": decoder.source_radio_id if decoder is not None else None,
        "target_radio_id": decoder.target_radio_id if decoder is not None else None,
        "nac": decoder.nac if decoder is not None else None,
        "phase": decoder.phase if decoder is not None else None,
        "sync_state": decoder.sync_state if decoder is not None else None,
        "recent_radios": decoder.recent_radios if decoder is not None else [],
        "activity": decoder.activity if decoder is not None else {},
        "decoder": decoder,
        "active_channel": channel,
    }


def _decimal_from_payload(payload: P25TalkgroupPayload) -> int | None:
    if payload.decimal is not None:
        return int(payload.decimal)
    if payload.talkgroup_decimal is not None:
        return int(payload.talkgroup_decimal)
    if payload.talkgroup and payload.talkgroup.get("decimal") is not None:
        return int(payload.talkgroup["decimal"])
    if payload.talkgroupId:
        for item in scanner_core.frequency_manager.trunked_talkgroups(include_encrypted=True):
            if item.get("id") == payload.talkgroupId:
                try:
                    return int(item.get("decimal"))
                except (TypeError, ValueError):
                    return None
    return None


@router.get("/status")
def get_p25_status():
    return _status_payload()


@router.post("/start")
def start_p25_decoder():
    catalog = scanner_core.frequency_manager.trunked_catalog()
    sites = catalog.get("sites") or []
    control_channels = []
    if sites and isinstance(sites[0], dict):
        control_channels = sites[0].get("control_channels_hz") or []
    if not control_channels:
        raise HTTPException(status_code=404, detail="No GATRRS control channels are configured.")

    _stop_analog_audio_for_p25()
    scanner_core.manual_tune(
        frequency_hz=int(control_channels[0]),
        modulation="p25",
        name="GATRRS Control",
    )
    return _status_payload()


@router.post("/stop")
def stop_p25_decoder():
    return scanner_core.stop_p25_decoder()


@router.post("/select-talkgroup")
def select_p25_talkgroup(payload: P25TalkgroupPayload):
    decimal = _decimal_from_payload(payload)
    if decimal is None:
        raise HTTPException(status_code=400, detail="A talkgroup decimal or talkgroup id is required.")

    channel = scanner_core.frequency_manager.p25_talkgroup_channel(decimal)
    if channel is None:
        raise HTTPException(status_code=404, detail="GATRRS talkgroup not found.")
    if channel.encrypted or channel.unavailable:
        raise HTTPException(status_code=409, detail=f"{channel.name} is encrypted or unavailable.")

    _stop_analog_audio_for_p25()
    scanner_core.tune_p25_talkgroup(decimal)
    return _status_payload()
