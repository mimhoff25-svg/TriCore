from __future__ import annotations

from fastapi import APIRouter

from ..transcriber import transcriber
from .audio_routes import stop_live_audio_process
from .shared import scanner_core


router = APIRouter(prefix="/api/transcriber", tags=["transcriber"])


def _p25_transcript_metadata(channel) -> dict:
    metadata = {
        "system_name": getattr(channel, "system_name", None),
        "category": getattr(channel, "category", None),
        "selected_talkgroup_decimal": getattr(channel, "p25_talkgroup_decimal", None),
    }
    decoder = scanner_core.decoders.get("p25_placeholder")
    if decoder is None:
        return metadata
    try:
        decoder_status = decoder.status()
    except Exception:
        return metadata

    metadata.update({
        "talkgroup_decimal": decoder_status.talkgroup_decimal or decoder_status.selected_talkgroup_decimal,
        "selected_talkgroup_decimal": decoder_status.selected_talkgroup_decimal or metadata["selected_talkgroup_decimal"],
        "source_radio_id": decoder_status.source_radio_id,
        "target_radio_id": decoder_status.target_radio_id,
        "voice_frequency_hz": decoder_status.voice_frequency_hz,
    })

    if not metadata.get("source_radio_id"):
        for radio in decoder_status.recent_radios or []:
            if not isinstance(radio, dict):
                continue
            metadata["source_radio_id"] = str(radio.get("radio")) if radio.get("radio") is not None else None
            metadata["radio_label"] = radio.get("alias")
            metadata["talkgroup_decimal"] = radio.get("group") or metadata.get("talkgroup_decimal")
            break

    if metadata.get("source_radio_id"):
        metadata["radio_id"] = str(metadata["source_radio_id"])
    elif metadata.get("target_radio_id"):
        metadata["radio_id"] = str(metadata["target_radio_id"])
    return metadata


def _transcriber_status_payload() -> dict:
    status = transcriber.status()
    is_p25 = str(status.get("current_modulation") or "").lower() == "p25_placeholder"
    channel = scanner_core.current_channel
    if is_p25 and channel is not None:
        metadata = _p25_transcript_metadata(channel)
        status.update({
            "current_radio_id": metadata.get("radio_id") or status.get("current_radio_id"),
            "current_source_radio_id": metadata.get("source_radio_id") or status.get("current_source_radio_id"),
            "current_target_radio_id": metadata.get("target_radio_id") or status.get("current_target_radio_id"),
            "current_talkgroup_decimal": metadata.get("talkgroup_decimal") or status.get("current_talkgroup_decimal"),
            "current_voice_frequency_hz": metadata.get("voice_frequency_hz") or status.get("current_voice_frequency_hz"),
        })
    return status


@router.get("/status")
async def transcriber_status():
    return {
        **_transcriber_status_payload(),
        "transcripts": transcriber.get_transcripts(),
    }


@router.post("/start")
async def start_transcriber():
    status = _transcriber_status_payload()
    if status.get("running"):
        return {
            **status,
            "ok": False,
            "error": "Transcriber already running.",
            "transcripts": transcriber.get_transcripts(),
        }

    active_channel = scanner_core.current_channel
    if active_channel is None:
        status = scanner_core.status()
        active_channel = status.current_channel or status.active_channel

    is_p25_channel = bool(
        active_channel is not None and str(active_channel.modulation or "").lower() == "p25_placeholder"
    )
    p25_audio_path = None

    if not is_p25_channel:
        scanner_core.shutdown_managed_p25_runtime(clear_current=False)
        receiver_status = scanner_core.receiver_status()
        if not receiver_status.available:
            message = receiver_status.error_message or receiver_status.message or "RTL-SDR receiver unavailable."
            return {
                **status,
                "ok": False,
                "error": message,
                "transcripts": transcriber.get_transcripts(),
            }

    stop_live_audio_process()
    if not is_p25_channel:
        scanner_core.release_rtl_receiver_for_external_audio()

    channels = [active_channel] if active_channel is not None else scanner_core.channels()

    if is_p25_channel:
        decoder = scanner_core.decoders.get("p25_placeholder")
        decoder_status = None
        if decoder is not None:
            try:
                decoder_status = decoder.status()
            except Exception:
                decoder_status = None
        audio_path_factory = getattr(decoder, "audio_wav_path", None)
        if callable(audio_path_factory):
            p25_audio_path = audio_path_factory()
        if p25_audio_path is None:
            runtime_engine = str((decoder_status.runtime or {}).get("engine") or "").lower() if decoder_status is not None else ""
            if runtime_engine == "sdrtrunk":
                error = "SDRTrunk fallback is handling P25 audio from the workspace playlist. In-app live audio and transcription are unavailable in fallback mode."
            else:
                error = "Managed P25 audio is not available."
            return {
                **status,
                "ok": False,
                "error": error,
                "transcripts": transcriber.get_transcripts(),
            }

    started = (
        transcriber.start(channels, p25_audio_path=p25_audio_path, metadata_provider=_p25_transcript_metadata)
        if p25_audio_path is not None
        else transcriber.start(channels)
    )
    if not started.get("ok") and not is_p25_channel:
        scanner_core.restore_rtl_receiver_after_external_audio()
    status = _transcriber_status_payload()
    return {
        **status,
        **started,
        "error": started.get("error") or status.get("error"),
        "transcripts": transcriber.get_transcripts(),
    }


@router.post("/stop")
async def stop_transcriber():
    was_p25 = str(transcriber.status().get("current_modulation") or "").lower() == "p25_placeholder"
    transcriber.stop()
    if not was_p25:
        scanner_core.restore_rtl_receiver_after_external_audio()
    return {
        **_transcriber_status_payload(),
        "transcripts": transcriber.get_transcripts(),
    }


@router.post("/clear")
async def clear_transcripts():
    transcriber.clear_transcripts()
    return {
        **_transcriber_status_payload(),
        "transcripts": [],
    }
