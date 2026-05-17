"""Application-level controller used by FastAPI.

Owns the background scan thread and exposes simple methods the web UI calls.
"""

from __future__ import annotations

import threading
from pathlib import Path

from conventional_scanner import ConventionalScanner
from fm_player import FmAudioPlayer
from fm_radio import fetch_now_playing, load_fm_stations
from models import ScannerStatus
from p25_service import P25DecoderService
from sdr_runtime import SdrRuntime


class ScannerController:
    """Start/stop wrapper for the conventional scanner."""

    def __init__(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.sdr_runtime = SdrRuntime(root)
        self.sdr_runtime.ensure()
        frequency_file = root / "configs" / "frequencies" / "sample_frequencies.json"
        self.frequency_file = frequency_file
        self.scanner = ConventionalScanner(
            frequency_file=frequency_file,
            gain_db=None,
            simulated=False,
        )
        self.p25 = P25DecoderService(
            config_dir=root / "configs" / "trunked",
            project_root=root,
        )
        self.fm_player = FmAudioPlayer()
        self._fm_offsets_hz: dict[str, int] = {}
        self._thread: threading.Thread | None = None

    # ── Lifecycle ───────────────────────────────────────────────────────────

    def start(self) -> ScannerStatus:
        """Start scanning. Stops other receiver engines so the RTL-SDR is free."""
        self.p25.stop()
        self.fm_player.stop()
        if self._thread and self._thread.is_alive():
            if self.scanner.running:
                return self.scanner.status
            self._thread.join(timeout=1.0)
            if self._thread.is_alive():
                return self.scanner.status
        self.scanner.hold_channel(None)
        self.scanner.clear_skipped()
        self._thread = threading.Thread(target=self.scanner.scan_forever, daemon=True)
        self._thread.start()
        return self.scanner.status

    def stop(self) -> ScannerStatus:
        """Stop scanning. Clears temporary skips like power-cycling a real scanner."""
        self.scanner.stop()
        self.fm_player.stop()
        return self.scanner.status

    # ── Device settings ─────────────────────────────────────────────────────

    def set_gain(self, gain_db: float | None) -> ScannerStatus:
        self.scanner.set_gain(gain_db)
        return self.scanner.status

    def set_simulated(self, simulated: bool) -> ScannerStatus:
        self.scanner.set_simulated(simulated)
        return self.scanner.status

    # ── Scanner controls (mirror real scanner buttons) ───────────────────────

    def hold(self) -> ScannerStatus:
        """Stay Here — lock scanner to the current channel."""
        ch = self.scanner.status.active_channel
        if ch:
            self.scanner.hold_channel(ch.id)
        return self.scanner.status

    def clear_hold(self) -> ScannerStatus:
        """Resume — release hold and return to normal scanning."""
        self.scanner.hold_channel(None)
        return self.scanner.status

    def skip(self) -> ScannerStatus:
        """Skip — temporarily avoid the current channel (Temporary Avoid)."""
        self.scanner.skip_current()
        return self.scanner.status

    def clear_skipped(self) -> ScannerStatus:
        """Clear all temporary skips."""
        self.scanner.clear_skipped()
        return self.scanner.status

    def set_muted(self, muted: bool) -> ScannerStatus:
        self.scanner.muted = muted
        return self.scanner.status

    def set_group_filter(self, systems: list[str] | None) -> ScannerStatus:
        self.p25.stop()
        self.fm_player.stop()
        self.scanner.set_group_filter(systems)
        return self.scanner.status

    def set_channel_filter(self, channel_ids: list[str] | None) -> ScannerStatus:
        self.p25.stop()
        self.fm_player.stop()
        self.scanner.set_channel_filter(channel_ids)
        return self.scanner.status

    def tune_to(self, channel_id: str) -> tuple[bool, ScannerStatus]:
        self.p25.stop()
        found = self.scanner.tune_to(channel_id)
        active = self.scanner.status.active_channel
        if found and active and active.service_type == "railroad":
            self.scanner.stop()
            channel = active.model_dump()
            self.fm_player.play_channel(
                channel,
                mode="nfm",
                gain_db=self.scanner.status.gain_db,
                label=f"{active.name} {active.frequency_hz / 1_000_000:.5f} MHz",
                noise_filter="mono narrow FM railroad filter",
            )
            self.scanner.tune_to(channel_id)
        elif found and active and active.service_type != "fm_radio":
            self.fm_player.stop()
        return found, self.scanner.status

    def add_channel(self, data: dict) -> ScannerStatus:
        from models import Channel
        import uuid as _uuid
        if not data.get("id"):
            data["id"] = str(_uuid.uuid4())[:8]
        ch = Channel(**data)
        self.scanner.add_channel(ch)
        return self.scanner.status

    def remove_channel(self, channel_id: str) -> tuple[bool, ScannerStatus]:
        found = self.scanner.remove_channel(channel_id)
        return found, self.scanner.status

    def get_calls(self) -> list[dict]:
        return self.scanner.get_calls()

    def trunked_systems(self):
        return self.p25.list_systems()

    def trunked_talkgroups(self, include_encrypted: bool = False) -> list[dict]:
        return self.p25.list_talkgroups(include_encrypted=include_encrypted)

    def p25_status(self) -> dict:
        return self.p25.status()

    def p25_start(self) -> dict:
        self.stop()
        return self.p25.scan_all()

    def p25_stop(self) -> dict:
        return self.p25.stop()

    def p25_select_talkgroup(self, decimal: int) -> dict:
        self.stop()
        return self.p25.select_talkgroup(decimal)

    def p25_sync_playlist(self) -> dict:
        return self.p25.sync_sdrtrunk_playlist()

    def sdr_runtime_status(self) -> dict:
        return self.sdr_runtime.status()

    def sdr_runtime_sync(self) -> dict:
        return self.sdr_runtime.ensure()

    def fm_stations(self) -> list[dict]:
        stations = load_fm_stations(self.frequency_file)
        for station in stations:
            station["frequency_offset_hz"] = self._fm_offsets_hz.get(station["id"], 0)
        return stations

    def active_fm_station(self) -> dict | None:
        active = self.scanner.status.active_channel
        if not active or active.service_type != "fm_radio":
            return None

        for station in self.fm_stations():
            if station["id"] == active.id:
                return station
        return None

    def play_fm(self, channel_id: str, audio_device: int | None = None) -> tuple[bool, dict]:
        self.p25.stop()
        self.scanner.stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        station = next((s for s in self.fm_stations() if s["id"] == channel_id), None)
        if station is None:
            return False, {"playing": False, "message": f"FM station {channel_id!r} not found"}

        found = self.scanner.tune_to(channel_id)
        if not found:
            return False, {"playing": False, "message": f"Channel {channel_id!r} not found"}

        return True, self.fm_player.play(station, gain_db=self.scanner.status.gain_db, audio_device=audio_device)

    def fine_tune_fm(self, channel_id: str, offset_hz: int) -> tuple[bool, dict]:
        offset_hz = max(-100_000, min(100_000, int(offset_hz)))
        if offset_hz == 0:
            self._fm_offsets_hz.pop(channel_id, None)
        else:
            self._fm_offsets_hz[channel_id] = offset_hz
        return self.play_fm(channel_id)

    def stop_fm(self) -> dict:
        return self.fm_player.stop()

    def fm_player_status(self) -> dict:
        status = self.fm_player.status()
        station = status.get("station")
        if station and station.get("service_type") == "fm_radio":
            station.update(fetch_now_playing(station))
            status["station"] = station
        return status

    # ── Status ──────────────────────────────────────────────────────────────

    def status(self) -> ScannerStatus:
        return self.scanner.status
