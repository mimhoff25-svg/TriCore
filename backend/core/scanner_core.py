from __future__ import annotations

import time
from typing import Optional

from ..decoders.airband_decoder import AirbandDecoder
from ..decoders.analog_decoder import AnalogNfmDecoder
from ..decoders.base_decoder import BaseDecoder
from ..decoders.fm_broadcast_decoder import FmBroadcastDecoder
from ..decoders.p25_decoder import ManagedP25Decoder
from ..radio.frequency_manager import FrequencyManager
from ..radio.models import Channel, DecoderStatus, ReceiverStatus, ScannerSettings, ScannerStatus, SearchRange, SignalReading
from ..sdr.base_receiver import BaseReceiver
from ..sdr.demo_receiver import DemoReceiver
from ..sdr.rtl_sdr_receiver import RtlSdrReceiver
from .scanner_state import ScannerState


class ScannerCore:
    def __init__(self) -> None:
        self.frequency_manager = FrequencyManager()
        self.receiver: BaseReceiver = RtlSdrReceiver(device_index=0, open_device=False)

        self.settings = ScannerSettings(selected_bank_ids=self.frequency_manager.enabled_bank_ids())
        self.state = ScannerState.STOPPED
        self.current_channel: Optional[Channel] = None
        self.current_decoder: Optional[DecoderStatus] = None
        self.scan_index = 0
        self.search_index = 0
        self.search_range: Optional[SearchRange] = None
        self.session_skipped_channel_ids: set[str] = set()
        self.error_message: Optional[str] = None
        self._scan_hold_until = 0.0
        self._managed_p25_helpers_need_cleanup = True
        self.decoders: dict[str, BaseDecoder] = {
            "nfm": AnalogNfmDecoder(),
            "wfm": FmBroadcastDecoder(),
            "am": AirbandDecoder(),
            "p25_placeholder": ManagedP25Decoder(),
        }
        self.shutdown_managed_p25_runtime(clear_current=False)

    def status(self, advance: bool = True) -> ScannerStatus:
        signal_reading: Optional[SignalReading] = None
        scan_advanced = False
        if advance and self.state == ScannerState.SCANNING:
            signal_reading = self._read_current_signal()
            scan_advanced = self._advance_scan(signal_reading)
        elif advance and self.state == ScannerState.SEARCHING:
            self._advance_search()

        if self.current_channel and self.current_channel.modulation == "p25_placeholder":
            decoder = self.decoders.get(self.current_channel.modulation)
            if decoder is not None:
                self.current_decoder = decoder.status()

        active_channel = self._active_channel_for_status()
        receiver_status = self._receiver_status_for_current_channel(self.receiver.status(), active_channel)
        receiver_status = self._receiver_status_with_signal(receiver_status, signal_reading, active_channel, scan_advanced)
        selected_bank_ids = self.frequency_manager.enabled_bank_ids()
        return ScannerStatus(
            state=self.state.value,
            is_scanning=self.state == ScannerState.SCANNING,
            is_paused=self.state == ScannerState.PAUSED,
            is_holding=self.state == ScannerState.HOLDING,
            is_muted=self.settings.muted,
            current_channel=self.current_channel,
            active_channel=active_channel,
            current_frequency_hz=active_channel.frequency_hz if active_channel else receiver_status.tuned_frequency_hz,
            signal_level=receiver_status.signal_level,
            receiver_mode=receiver_status.label,
            simulated=receiver_status.simulated,
            squelch_db=self.settings.squelch_db,
            gain_db=self.settings.gain_db,
            selected_bank_ids=selected_bank_ids,
            message=self._message(receiver_status),
            error_message=self.error_message or receiver_status.error_message,
            search_range=self.search_range,
            decoder=self.current_decoder,
        )

    def receiver_status(self) -> ReceiverStatus:
        if self.current_channel and self.current_channel.modulation == "p25_placeholder":
            decoder = self.decoders.get(self.current_channel.modulation)
            if decoder is not None:
                self.current_decoder = decoder.status()
        status = self.receiver.status()
        status = self._receiver_status_for_current_channel(status, self._active_channel_for_status())
        if self.error_message and status.simulated:
            return status.model_copy(update={
                "error_message": self.error_message,
                "message": self.error_message,
                "last_rtl_error": self.error_message,
            })
        return status

    def release_rtl_receiver_for_external_audio(self) -> None:
        if isinstance(self.receiver, RtlSdrReceiver):
            self.receiver.close()

    def restore_rtl_receiver_after_external_audio(self) -> None:
        if not isinstance(self.receiver, RtlSdrReceiver):
            return
        if self.receiver.open_device:
            self.receiver.refresh()
        self.receiver.set_gain(self.settings.gain_db)
        self.receiver.set_squelch(self.settings.squelch_db)
        if self.current_channel:
            self.receiver.tune(self.current_channel.frequency_hz, self.current_channel.modulation)

    def shutdown_managed_p25_runtime(self, clear_current: bool = False) -> None:
        if not clear_current and not self._managed_p25_helpers_need_cleanup:
            return
        decoder = self.decoders.get("p25_placeholder")
        if decoder is not None:
            try:
                decoder.stop()
            except Exception:
                return
        self._managed_p25_helpers_need_cleanup = False
        if clear_current and self.current_channel and self.current_channel.modulation == "p25_placeholder":
            self.current_decoder = decoder.status() if decoder is not None else None
            self.state = ScannerState.STOPPED
            self.current_channel = None

    def start(self) -> ScannerStatus:
        self.state = ScannerState.SCANNING
        self._scan_hold_until = 0.0
        self.error_message = None
        self.session_skipped_channel_ids.clear()
        self._advance_scan()
        return self.status(advance=False)

    def stop(self) -> ScannerStatus:
        self._stop_active_decoder()
        self.state = ScannerState.STOPPED
        self.current_decoder = None
        self._scan_hold_until = 0.0
        self.error_message = None
        return self.status(advance=False)

    def pause(self) -> ScannerStatus:
        if self.state in {ScannerState.SCANNING, ScannerState.SEARCHING}:
            self.state = ScannerState.PAUSED
        return self.status(advance=False)

    def resume(self) -> ScannerStatus:
        self.state = ScannerState.SEARCHING if self.search_range else ScannerState.SCANNING
        if self.current_channel is None:
            self._advance_scan()
        return self.status(advance=False)

    def hold(self) -> ScannerStatus:
        if self.current_channel is None:
            self._advance_scan()
        self.state = ScannerState.HOLDING if self.current_channel else ScannerState.STOPPED
        return self.status(advance=False)

    def release(self) -> ScannerStatus:
        self.state = ScannerState.SCANNING if self.current_channel else ScannerState.STOPPED
        self._scan_hold_until = 0.0
        return self.status(advance=False)

    def skip(self) -> ScannerStatus:
        if self.current_channel is not None:
            self.session_skipped_channel_ids.add(self.current_channel.id)
        self.state = ScannerState.SCANNING
        self._scan_hold_until = 0.0
        self._advance_scan()
        return self.status(advance=False)

    def next_channel(self) -> ScannerStatus:
        previous_state = self.state
        self._advance_scan()
        if previous_state in {ScannerState.HOLDING, ScannerState.PAUSED, ScannerState.MANUAL_TUNE}:
            self.state = previous_state
        else:
            self.state = ScannerState.SCANNING
        return self.status(advance=False)

    def lockout(self, channel_id: str | None = None) -> ScannerStatus:
        target_id = channel_id or (self.current_channel.id if self.current_channel else None)
        if target_id is not None:
            self.frequency_manager.set_channel_lockout(target_id, True)
            if self.current_channel and self.current_channel.id == target_id:
                self.state = ScannerState.SCANNING
                self._advance_scan()
        return self.status(advance=False)

    def priority(self, channel_id: str | None = None, priority: bool = True) -> ScannerStatus:
        target_id = channel_id or (self.current_channel.id if self.current_channel else None)
        if target_id is not None:
            updated = self.frequency_manager.set_channel_priority(target_id, priority)
            if updated is not None and self.current_channel and self.current_channel.id == target_id:
                self.current_channel = updated
        return self.status(advance=False)

    def tune_channel(self, channel_id: str) -> ScannerStatus:
        channel = self.frequency_manager.get_channel(channel_id)
        if channel is None:
            self.state = ScannerState.ERROR
            self.error_message = "Channel not found."
            return self.status(advance=False)
        if channel.encrypted or channel.unavailable or channel.locked_out:
            self.state = ScannerState.SCANNING
            self.error_message = f"{channel.name} is Unavailable or hidden and was skipped."
            self._advance_scan()
            return self.status(advance=False)
        if not self._channel_supported_by_receiver(channel):
            self.error_message = f"{channel.name} is outside the RTL-SDR tuner range."
            return self.status(advance=False)
        self._tune_channel(channel)
        self.state = ScannerState.MANUAL_TUNE
        self.error_message = None
        return self.status(advance=False)

    def tune_p25_talkgroup(self, decimal: int) -> ScannerStatus:
        channel = self.frequency_manager.p25_talkgroup_channel(decimal)
        if channel is None:
            self.state = ScannerState.ERROR
            self.error_message = "GATRRS talkgroup not found."
            return self.status(advance=False)
        if channel.encrypted or channel.unavailable:
            self.state = ScannerState.ERROR
            self.error_message = f"{channel.name} is encrypted or unavailable."
            return self.status(advance=False)
        if not self._channel_supported_by_receiver(channel):
            self.error_message = f"{channel.name} is outside the RTL-SDR tuner range."
            return self.status(advance=False)

        self._tune_channel(channel)
        self.state = ScannerState.HOLDING
        self.error_message = None
        return self.status(advance=False)

    def stop_p25_decoder(self) -> ScannerStatus:
        self.shutdown_managed_p25_runtime(clear_current=True)
        return self.status(advance=False)

    def manual_tune(
        self,
        frequency_hz: int | None = None,
        frequency_mhz: float | None = None,
        modulation: str = "nfm",
        name: str | None = None,
    ) -> ScannerStatus:
        if frequency_hz is None and frequency_mhz is not None:
            frequency_hz = int(float(frequency_mhz) * 1_000_000)
        if frequency_hz is None or frequency_hz <= 0:
            self.state = ScannerState.ERROR
            self.error_message = "Manual tune needs a valid frequency."
            return self.status(advance=False)

        channel = self.frequency_manager.channel_for_manual_tune(frequency_hz, modulation, name)
        if not self._channel_supported_by_receiver(channel):
            self.error_message = f"{channel.name} is outside the RTL-SDR tuner range."
            return self.status(advance=False)
        self._tune_channel(channel)
        self.state = ScannerState.MANUAL_TUNE
        self.error_message = None
        return self.status(advance=False)

    def start_search(self, range_id: str | None = None) -> ScannerStatus:
        search_range = self.frequency_manager.first_bandplan(range_id)
        if search_range is None:
            self.state = ScannerState.ERROR
            self.error_message = "No search ranges are configured."
            return self.status(advance=False)
        self.search_range = search_range
        self.search_index = 0
        self.state = ScannerState.SEARCHING
        self._advance_search()
        return self.status(advance=False)

    def stop_search(self) -> ScannerStatus:
        self.search_range = None
        self._scan_hold_until = 0.0
        self.state = ScannerState.STOPPED
        return self.status(advance=False)

    def set_squelch(self, squelch_db: float) -> ScannerStatus:
        self.settings.squelch_db = float(squelch_db)
        self.receiver.set_squelch(self.settings.squelch_db)
        return self.status(advance=False)

    def set_gain(self, gain_db: Optional[float]) -> ScannerStatus:
        self.settings.gain_db = gain_db
        self.receiver.set_gain(gain_db)
        decoder = self.decoders.get("p25_placeholder")
        if isinstance(decoder, ManagedP25Decoder):
            decoder.set_rf_gain(gain_db)
        return self.status(advance=False)

    def set_mute(self, muted: bool) -> ScannerStatus:
        self.settings.muted = muted
        return self.status(advance=False)

    def set_receiver_mode(self, simulated: bool) -> ScannerStatus:
        self._stop_active_decoder()
        self.shutdown_managed_p25_runtime(clear_current=False)
        self.receiver.close()
        if simulated:
            self.receiver = DemoReceiver()
            self.receiver.set_gain(self.settings.gain_db)
            self.receiver.set_squelch(self.settings.squelch_db)
            self.error_message = None
        else:
            rtl = RtlSdrReceiver(open_device=False)
            rtl.set_gain(self.settings.gain_db)
            rtl.set_squelch(self.settings.squelch_db)
            self.receiver = rtl
            self.error_message = None

        if self.current_channel and self._channel_supported_by_receiver(self.current_channel):
            self.receiver.tune(self.current_channel.frequency_hz, self.current_channel.modulation)
        return self.status(advance=False)

    def set_bank_enabled(self, bank_id: str, enabled: bool) -> ScannerStatus:
        self.frequency_manager.set_bank_enabled(bank_id, enabled)
        self.settings.selected_bank_ids = self.frequency_manager.enabled_bank_ids()
        if self.current_channel and not self.frequency_manager.is_channel_scan_enabled(self.current_channel.id):
            self._scan_hold_until = 0.0
            self._advance_scan()
        return self.status(advance=False)

    def set_scan_selection(self, channel_ids: list[str], talkgroup_decimals: list[int], enabled: bool) -> ScannerStatus:
        self.frequency_manager.set_channel_scan_enabled_bulk(channel_ids, enabled)
        self.frequency_manager.set_talkgroup_scan_enabled_bulk(talkgroup_decimals, enabled)
        self.settings.selected_bank_ids = self.frequency_manager.enabled_bank_ids()
        if self.state == ScannerState.SCANNING and self.current_channel and not self.frequency_manager.is_channel_scan_enabled(self.current_channel.id):
            self._scan_hold_until = 0.0
            self._advance_scan()
        return self.status(advance=False)

    def channels(self) -> list[Channel]:
        return self.frequency_manager.list_channels()

    def banks(self):
        return self.frequency_manager.list_banks()

    def bandplans(self):
        return self.frequency_manager.list_bandplans()

    def _trunked_scan_has_voice_activity(self) -> bool:
        decoder = self.current_decoder
        if decoder is None:
            return False
        if decoder.active and decoder.voice_frequency_hz is not None:
            return True

        activity = decoder.activity if isinstance(decoder.activity, dict) else {}
        if decoder.voice_frequency_hz is not None and bool(activity.get("voice_event")):
            return True

        recent_events = activity.get("recent_events")
        if not isinstance(recent_events, list):
            return False

        for event in recent_events:
            if not isinstance(event, dict):
                continue
            if bool(event.get("voice_event")):
                return True
            try:
                if int(event.get("voice_frequency_hz") or 0) > 0:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    def _advance_scan(self, signal_reading: Optional[SignalReading] = None) -> bool:
        if self.current_channel and self._is_trunked_scan_channel(self.current_channel):
            now = time.monotonic()
            hold_seconds = max(float(getattr(self.current_channel, "delay_seconds", 2.5) or 2.5), 0.75)
            if self._trunked_scan_has_voice_activity():
                self._scan_hold_until = max(self._scan_hold_until, now + hold_seconds)
                return False
            if now < self._scan_hold_until:
                return False

        if self.current_channel and self.current_channel.modulation != "p25_placeholder":
            reading = signal_reading or self._read_current_signal()
            now = time.monotonic()
            if reading is not None and reading.squelch_open:
                hold_seconds = max(float(getattr(self.current_channel, "delay_seconds", 2.0) or 2.0), 0.75)
                self._scan_hold_until = max(self._scan_hold_until, now + hold_seconds)
                return False
            if now < self._scan_hold_until:
                return False

        self._scan_hold_until = 0.0
        candidates = [
            channel for channel in self.frequency_manager.scan_candidates()
            if channel.id not in self.session_skipped_channel_ids
            and self._channel_supported_by_receiver(channel)
        ]

        # Skip trunked-scan channels when the P25 runtime can't access a tuner —
        # avoids burning 2.5 s per scan cycle on a no-op DSDPlus attempt.
        if any(self._is_trunked_scan_channel(c) for c in candidates):
            p25_decoder = self.decoders.get("p25_placeholder")
            if p25_decoder is not None:
                try:
                    p25_health = str(p25_decoder.status().runtime.get("health") or "").lower()
                    if p25_health in {"no_tuner", "missing_runtime"}:
                        candidates = [c for c in candidates if not self._is_trunked_scan_channel(c)]
                except Exception:
                    pass

        if not candidates:
            self._stop_active_decoder()
            self.current_channel = None
            self.current_decoder = None
            self.state = ScannerState.ERROR
            self.error_message = "No available channels in enabled banks."
            return False

        if self.scan_index >= len(candidates):
            self.scan_index = 0
        channel = candidates[self.scan_index]
        self.scan_index = (self.scan_index + 1) % len(candidates)
        self._tune_channel(channel)
        if self._is_trunked_scan_channel(channel):
            hold_seconds = max(float(getattr(channel, "delay_seconds", 2.5) or 2.5), 0.75)
            self._scan_hold_until = time.monotonic() + hold_seconds
        self.error_message = None
        return True

    def _advance_search(self) -> None:
        if self.search_range is None:
            self.start_search(None)
            return
        channel = self.frequency_manager.search_channel(self.search_range, self.search_index)
        self.search_index += 1
        self._tune_channel(channel)
        self.error_message = None

    def _tune_channel(self, channel: Channel) -> None:
        if channel.encrypted or channel.unavailable:
            self.error_message = f"{channel.name} is Unavailable and was skipped."
            return
        if not self._channel_supported_by_receiver(channel):
            self.error_message = f"{channel.name} is outside the RTL-SDR tuner range and was skipped."
            return
        previous_channel = self.current_channel
        self._scan_hold_until = 0.0
        if previous_channel is not None:
            same_channel = (
                previous_channel.modulation == channel.modulation
                and previous_channel.frequency_hz == channel.frequency_hz
            )
            same_p25_control_runtime = False
            if same_channel and channel.modulation == "p25_placeholder":
                previous_controls = tuple(previous_channel.p25_control_channels_hz or [previous_channel.frequency_hz])
                next_controls = tuple(channel.p25_control_channels_hz or [channel.frequency_hz])
                same_p25_control_runtime = previous_controls == next_controls
                same_channel = (
                    previous_channel.id == channel.id
                    and previous_channel.p25_talkgroup_decimal == channel.p25_talkgroup_decimal
                    and previous_controls == next_controls
                )
            if not same_channel and not same_p25_control_runtime:
                previous_decoder = self.decoders.get(previous_channel.modulation)
                if previous_decoder is not None:
                    previous_decoder.stop()
                if previous_channel.modulation == "p25_placeholder":
                    self._managed_p25_helpers_need_cleanup = False
        self.current_channel = channel
        decoder = self.decoders.get(channel.modulation, self.decoders["nfm"])
        if channel.modulation == "p25_placeholder":
            if isinstance(decoder, ManagedP25Decoder):
                decoder.set_rf_gain(self.settings.gain_db)
                decoder.set_known_talkgroups(self.frequency_manager.known_trunked_talkgroup_targets())
                decoder.set_locked_talkgroups(self.frequency_manager.encrypted_trunked_talkgroup_decimals())
            self.release_rtl_receiver_for_external_audio()
            self._managed_p25_helpers_need_cleanup = True
        else:
            if self._managed_p25_helpers_need_cleanup:
                self.shutdown_managed_p25_runtime(clear_current=False)
            self.receiver.tune(channel.frequency_hz, channel.modulation)
        if self._is_trunked_scan_channel(channel) and isinstance(decoder, ManagedP25Decoder):
            self.current_decoder = decoder.scan_talkgroups(
                control_channels_hz=channel.p25_control_channels_hz or [channel.frequency_hz],
                talkgroups=self.frequency_manager.enabled_trunked_talkgroup_targets(),
                label=channel.name,
            )
        elif isinstance(decoder, ManagedP25Decoder) and channel.p25_talkgroup_decimal is not None:
            self.current_decoder = decoder.hold_talkgroups(
                channel,
                self.frequency_manager.hold_trunked_talkgroup_targets(channel.p25_talkgroup_decimal),
            )
        else:
            self.current_decoder = decoder.tune(channel)

    def _stop_active_decoder(self) -> None:
        if self.current_channel is None:
            return
        decoder = self.decoders.get(self.current_channel.modulation)
        if decoder is None:
            return
        decoder.stop()
        if self.current_channel.modulation == "p25_placeholder":
            self._managed_p25_helpers_need_cleanup = False

    def _active_channel_for_status(self) -> Optional[Channel]:
        if self.current_channel is None:
            return None
        if self.current_channel.modulation != "p25_placeholder" or self.current_decoder is None:
            return self.current_channel

        voice_frequency_hz = self.current_decoder.voice_frequency_hz
        if voice_frequency_hz is None or voice_frequency_hz <= 0 or voice_frequency_hz == self.current_channel.frequency_hz:
            return self.current_channel

        note = "Live voice frequency tracked from DSDPlus."
        if self.current_channel.notes:
            note = f"{self.current_channel.notes} {note}"
        return self.current_channel.model_copy(update={
            "frequency_hz": voice_frequency_hz,
            "notes": note,
        })

    def _channel_supported_by_receiver(self, channel: Channel) -> bool:
        if isinstance(self.receiver, RtlSdrReceiver):
            return RtlSdrReceiver.supports_frequency(channel.frequency_hz)
        return True

    def _p25_signal_level_for_status(self, receiver_status: ReceiverStatus) -> float:
        if self.current_decoder is None:
            return receiver_status.signal_level

        try:
            signal_level = float(receiver_status.signal_level)
        except (TypeError, ValueError):
            signal_level = -100.0

        sync_state = str(self.current_decoder.sync_state or "").lower()
        if sync_state == "voice_follow" or self.current_decoder.voice_frequency_hz is not None:
            return max(signal_level, float(self.settings.squelch_db) + 15.0)
        if sync_state == "control_lock":
            return max(signal_level, float(self.settings.squelch_db) + 7.0)
        return signal_level

    def _receiver_status_for_current_channel(
        self,
        receiver_status: ReceiverStatus,
        active_channel: Optional[Channel],
    ) -> ReceiverStatus:
        if self.current_channel is None or self.current_channel.modulation != "p25_placeholder" or self.current_decoder is None:
            return receiver_status

        runtime_health = str(self.current_decoder.runtime.get("health") or "").lower()
        if runtime_health in {"missing_runtime", "no_tuner", "error", "stopped"}:
            return receiver_status
        if not self.current_decoder.active and runtime_health not in {"ready", "starting"}:
            return receiver_status

        tuned_frequency_hz = active_channel.frequency_hz if active_channel is not None else self.current_channel.frequency_hz
        return receiver_status.model_copy(update={
            "label": self.current_decoder.label,
            "available": True,
            "rtl_sdr_available": True,
            "simulated": False,
            "tuned_frequency_hz": tuned_frequency_hz,
            "signal_level": self._p25_signal_level_for_status(receiver_status),
            "message": self.current_decoder.message,
            "error_message": None,
            "last_rtl_error": None,
        })

    def _receiver_status_with_signal(
        self,
        receiver_status: ReceiverStatus,
        signal_reading: Optional[SignalReading],
        active_channel: Optional[Channel],
        scan_advanced: bool,
    ) -> ReceiverStatus:
        if signal_reading is None or scan_advanced or active_channel is None or active_channel.modulation == "p25_placeholder":
            return receiver_status
        return receiver_status.model_copy(update={
            "tuned_frequency_hz": signal_reading.frequency_hz or active_channel.frequency_hz,
            "signal_level": signal_reading.level_db,
        })

    def _read_current_signal(self) -> Optional[SignalReading]:
        if self.current_channel is None or self.current_channel.modulation == "p25_placeholder":
            return None
        if not self.receiver.status().available:
            return None
        try:
            return self.receiver.read_signal()
        except Exception:
            return None

    def _is_trunked_scan_channel(self, channel: Channel | None) -> bool:
        return bool(
            channel is not None
            and channel.modulation == "p25_placeholder"
            and str(channel.id).startswith("trunked-scan-")
        )

    def _message(self, receiver_status: ReceiverStatus) -> str:
        if self.error_message:
            return self.error_message
        if self.state == ScannerState.STOPPED:
            return "Scanner stopped."
        if self.state == ScannerState.PAUSED:
            return "Scanner paused."
        if self.state == ScannerState.HOLDING:
            if self.current_channel and self.current_channel.modulation == "p25_placeholder" and self.current_decoder:
                return self.current_decoder.message
            return "Stay Here active."
        if self.state == ScannerState.SEARCHING and self.search_range:
            return f"Searching {self.search_range.name}."
        if self.state == ScannerState.MANUAL_TUNE:
            if self.current_channel and self.current_channel.modulation == "p25_placeholder" and self.current_decoder:
                return self.current_decoder.message
            return "Manual tune active."
        if self.current_channel:
            if self.current_channel.modulation == "p25_placeholder" and self.current_decoder:
                return self.current_decoder.message
            return f"Listening to {self.current_channel.name} with {receiver_status.label}."
        return "Scanner ready."
