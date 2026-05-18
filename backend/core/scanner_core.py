from __future__ import annotations

from typing import Optional

from ..decoders.airband_decoder import AirbandDecoder
from ..decoders.analog_decoder import AnalogNfmDecoder
from ..decoders.base_decoder import BaseDecoder
from ..decoders.fm_broadcast_decoder import FmBroadcastDecoder
from ..decoders.p25_decoder import P25DecoderPlaceholder
from ..radio.frequency_manager import FrequencyManager
from ..radio.models import Channel, DecoderStatus, ReceiverStatus, ScannerSettings, ScannerStatus, SearchRange
from ..sdr.base_receiver import BaseReceiver
from ..sdr.demo_receiver import DemoReceiver
from ..sdr.rtl_sdr_receiver import RtlSdrReceiver
from .scanner_state import ScannerState


class ScannerCore:
    def __init__(self) -> None:
        self.frequency_manager = FrequencyManager()
        self.receiver: BaseReceiver = DemoReceiver()
        self.settings = ScannerSettings(selected_bank_ids=self.frequency_manager.enabled_bank_ids())
        self.state = ScannerState.STOPPED
        self.current_channel: Optional[Channel] = None
        self.current_decoder: Optional[DecoderStatus] = None
        self.scan_index = 0
        self.search_index = 0
        self.search_range: Optional[SearchRange] = None
        self.session_skipped_channel_ids: set[str] = set()
        self.error_message: Optional[str] = None
        self.decoders: dict[str, BaseDecoder] = {
            "nfm": AnalogNfmDecoder(),
            "wfm": FmBroadcastDecoder(),
            "am": AirbandDecoder(),
            "p25_placeholder": P25DecoderPlaceholder(),
        }

    def status(self, advance: bool = True) -> ScannerStatus:
        if advance and self.state == ScannerState.SCANNING:
            self._advance_scan()
        elif advance and self.state == ScannerState.SEARCHING:
            self._advance_search()

        receiver_status = self.receiver.status()
        signal = self.receiver.read_signal()
        selected_bank_ids = self.frequency_manager.enabled_bank_ids()
        return ScannerStatus(
            state=self.state.value,
            is_scanning=self.state == ScannerState.SCANNING,
            is_paused=self.state == ScannerState.PAUSED,
            is_holding=self.state == ScannerState.HOLDING,
            is_muted=self.settings.muted,
            current_channel=self.current_channel,
            active_channel=self.current_channel,
            current_frequency_hz=self.current_channel.frequency_hz if self.current_channel else receiver_status.tuned_frequency_hz,
            signal_level=signal.level_db,
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
        status = self.receiver.status()
        if self.error_message and status.simulated:
            return status.model_copy(update={"error_message": self.error_message, "message": self.error_message})
        return status

    def start(self) -> ScannerStatus:
        self.state = ScannerState.SCANNING
        self.error_message = None
        self.session_skipped_channel_ids.clear()
        self._advance_scan()
        return self.status(advance=False)

    def stop(self) -> ScannerStatus:
        self.state = ScannerState.STOPPED
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
        return self.status(advance=False)

    def skip(self) -> ScannerStatus:
        if self.current_channel is not None:
            self.session_skipped_channel_ids.add(self.current_channel.id)
        self.state = ScannerState.SCANNING
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
        self._tune_channel(channel)
        self.state = ScannerState.MANUAL_TUNE
        self.error_message = None
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
        self.state = ScannerState.STOPPED
        return self.status(advance=False)

    def set_squelch(self, squelch_db: float) -> ScannerStatus:
        self.settings.squelch_db = float(squelch_db)
        self.receiver.set_squelch(self.settings.squelch_db)
        return self.status(advance=False)

    def set_gain(self, gain_db: Optional[float]) -> ScannerStatus:
        self.settings.gain_db = gain_db
        self.receiver.set_gain(gain_db)
        return self.status(advance=False)

    def set_mute(self, muted: bool) -> ScannerStatus:
        self.settings.muted = muted
        return self.status(advance=False)

    def set_receiver_mode(self, simulated: bool) -> ScannerStatus:
        self.receiver.close()
        if simulated:
            self.receiver = DemoReceiver()
            self.receiver.set_gain(self.settings.gain_db)
            self.receiver.set_squelch(self.settings.squelch_db)
            self.error_message = None
        else:
            rtl = RtlSdrReceiver()
            rtl.set_gain(self.settings.gain_db)
            rtl.set_squelch(self.settings.squelch_db)
            if rtl.available:
                self.receiver = rtl
                self.error_message = None
            else:
                rtl_error = rtl.status().message
                rtl.close()
                self.receiver = DemoReceiver()
                self.receiver.set_gain(self.settings.gain_db)
                self.receiver.set_squelch(self.settings.squelch_db)
                self.error_message = f"RTL-SDR mode is unavailable. {rtl_error} Staying in Demo mode."

        if self.current_channel:
            self.receiver.tune(self.current_channel.frequency_hz, self.current_channel.modulation)
        return self.status(advance=False)

    def set_bank_enabled(self, bank_id: str, enabled: bool) -> ScannerStatus:
        self.frequency_manager.set_bank_enabled(bank_id, enabled)
        self.settings.selected_bank_ids = self.frequency_manager.enabled_bank_ids()
        if self.current_channel and self.current_channel.bank_id not in set(self.settings.selected_bank_ids):
            self._advance_scan()
        return self.status(advance=False)

    def channels(self) -> list[Channel]:
        return self.frequency_manager.list_channels()

    def banks(self):
        return self.frequency_manager.list_banks()

    def bandplans(self):
        return self.frequency_manager.list_bandplans()

    def _advance_scan(self) -> None:
        candidates = [
            channel for channel in self.frequency_manager.scan_candidates()
            if channel.id not in self.session_skipped_channel_ids
        ]
        if not candidates:
            self.current_channel = None
            self.current_decoder = None
            self.state = ScannerState.ERROR
            self.error_message = "No available channels in enabled banks."
            return

        if self.scan_index >= len(candidates):
            self.scan_index = 0
        channel = candidates[self.scan_index]
        self.scan_index = (self.scan_index + 1) % len(candidates)
        self._tune_channel(channel)
        self.error_message = None

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
        self.current_channel = channel
        self.receiver.tune(channel.frequency_hz, channel.modulation)
        decoder = self.decoders.get(channel.modulation, self.decoders["nfm"])
        self.current_decoder = decoder.tune(channel)

    def _message(self, receiver_status: ReceiverStatus) -> str:
        if self.error_message:
            return self.error_message
        if self.state == ScannerState.STOPPED:
            return "Scanner stopped."
        if self.state == ScannerState.PAUSED:
            return "Scanner paused."
        if self.state == ScannerState.HOLDING:
            return "Stay Here active."
        if self.state == ScannerState.SEARCHING and self.search_range:
            return f"Searching {self.search_range.name}."
        if self.state == ScannerState.MANUAL_TUNE:
            return "Manual tune active."
        if self.current_channel:
            return f"Listening to {self.current_channel.name} with {receiver_status.label}."
        return "Scanner ready."
