from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .conventional_scanner import is_channel_available, next_scannable_channel_index
from .database import load_channels, load_talkgroups, save_user_channel
from .headless_p25_runtime import HeadlessP25Runtime
from .models import (
    CallEntry,
    Channel,
    ChannelCreate,
    FmPlayerStatus,
    FmStation,
    P25ActiveCall,
    P25Status,
    RuntimeStatus,
    ScannerStatus,
    SdrSystemProfile,
    Talkgroup,
)
from .sdr_system import build_sdr_system_profile
from .sdr_device import SdrDevice
from .windows_rtlsdr_tools import detect_runtime_tools, runtime_root


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ScannerController:
    def __init__(self) -> None:
        self.device = SdrDevice()
        self.channels = load_channels()
        self.talkgroups, self.trunked_catalog = load_talkgroups()
        self.decoder = HeadlessP25Runtime(self._control_channels())
        self.calls: deque[CallEntry] = deque(maxlen=80)
        self.status = ScannerStatus(message=self.device.status_message(), simulated=self.device.simulated)
        self.fm_player = FmPlayerStatus()
        decoder_snapshot = self._phase1_decoder_snapshot()
        self.p25 = P25Status(
            state=self._p25_state_for_health(str(decoder_snapshot.get("health") or "stopped")),
            preferred_control_channel_hz=self._preferred_control_channel(),
            message=str(decoder_snapshot.get("message") or "Headless P25 runtime idle."),
            external_decoder=decoder_snapshot,
            voice_scan_error=None,
            voice_sweep_stats={"sweeps": 0, "last_sweep_ms": 0, "channels": self._voice_channel_count()},
        )
        self.channel_filter: Optional[list[str]] = None
        self.system_filter: Optional[list[str]] = None
        self.skipped_channel_ids: set[str] = set()
        self.scan_index = 0
        self.is_paused = False
        self.error_message: Optional[str] = None
        self._refresh_runtime()

    def _phase1_decoder_snapshot(self) -> dict[str, object]:
        return {
            "running": False,
            "health": "stopped",
            "message": "P25/trunking decoder idle. Phase 1 conventional scanner mode is active.",
            "headless": True,
            "managed": True,
            "activity": {},
            "control_channel_hz": None,
        }

    def _runtime_ready(self, tools: dict[str, bool]) -> bool:
        required = ("fmp24", "dsdplus")
        return all(tools.get(name, False) for name in required)

    def _p25_state_for_health(self, health: str, talkgroup_selected: bool = False) -> str:
        if health == "ready":
            return "WAITING_FOR_TRAFFIC" if talkgroup_selected else "WAITING_FOR_TALKGROUP"
        if health == "starting":
            return "STARTING_DECODER"
        if health == "waiting_for_channel_start":
            return "WAITING_FOR_CHANNEL_START"
        if health == "no_tuner":
            return "NO_SIGNAL"
        if health == "missing_runtime":
            return "NO_RUNTIME"
        if health == "error":
            return "ERROR"
        return "WAITING_FOR_TALKGROUP"

    def _talkgroup_message(self, health: str, talkgroup: Optional[Talkgroup], decoder_snapshot: dict[str, object]) -> str:
        decoder_message = str(decoder_snapshot.get("message") or "Decoder state unavailable.")
        if talkgroup is None:
            if health == "ready":
                return "Headless P25 runtime running. Select a talkgroup."
            return decoder_message
        tracking_label = self._tracking_label_for(talkgroup)
        if health == "ready":
            return f"Tracking {tracking_label} with the headless P25 runtime."
        if health == "starting":
            return f"Tracking {tracking_label}. Headless P25 runtime is starting."
        if health == "no_tuner":
            return f"Selected {talkgroup.alpha_tag}, but the tuner is not available. {decoder_message}"
        if health == "missing_runtime":
            return f"Selected {talkgroup.alpha_tag}, but the headless P25 runtime is missing required tools."
        return f"Selected {talkgroup.alpha_tag}, but the headless decoder failed to start. {decoder_message}"

    def _sync_p25_runtime(self) -> None:
        decoder_snapshot = self.decoder.status(force_probe=False)
        talkgroup = self.p25.selected_talkgroup
        health = str(decoder_snapshot.get("health") or "stopped")
        message = self._talkgroup_message(health, talkgroup, decoder_snapshot)
        p25_state = self._p25_state_for_health(health, talkgroup_selected=talkgroup is not None)
        active_call, runtime_event, active_voice_channels = self._decoder_activity(decoder_snapshot, talkgroup)

        tuned_frequency_hz = (
            active_call.voice_frequency_hz if active_call is not None and active_call.voice_frequency_hz is not None
            else self.decoder.control_channel_hz() or self._preferred_control_channel()
        )
        status_state = "RECEIVING_CALL" if active_call is not None else p25_state
        p25_active_channel = None
        if talkgroup is not None:
            p25_active_channel = Channel(
                id=talkgroup.id,
                name=talkgroup.alpha_tag,
                system="GATRRS",
                category="trunked",
                frequency_hz=int(tuned_frequency_hz or 0),
                modulation="p25",
                encrypted=bool(talkgroup.encrypted),
                favorite=False,
                priority=True,
                service_type=talkgroup.service_type or "custom",
                delay_seconds=0.0,
                department=talkgroup.tag or talkgroup.description,
                primary_radio_id=active_call.source_radio_id if active_call is not None else None,
                target_radio_id=active_call.target_radio_id if active_call is not None else None,
            )

        self.p25 = self.p25.model_copy(update={
            "running": bool(decoder_snapshot.get("running")),
            "state": p25_state,
            "message": message,
            "tracking_label": self._tracking_label_for(talkgroup),
            "tracked_talkgroup_count": len(self._priority_talkgroups_for(talkgroup)) if talkgroup is not None else 0,
            "external_decoder": decoder_snapshot,
            "voice_scan_active": health == "ready",
            "voice_scan_error": None if health == "ready" else message,
            "active_call": active_call,
            "last_event": runtime_event or self.p25.last_event,
            "active_voice_channels": active_voice_channels,
        })
        self.status = self.status.model_copy(update={
            "state": status_state,
            "message": message,
            "active_channel": p25_active_channel,
            "signal_power": -99.0 if health != "ready" else self.status.signal_power,
            "simulated": self.device.simulated,
        })

    def _refresh_runtime(self, force_probe: bool = False) -> None:
        self.device.refresh(force=force_probe)
        tools = detect_runtime_tools()
        if force_probe or self.p25.running or self.p25.selected_talkgroup:
            decoder_snapshot = self.decoder.status(force_probe=force_probe)
        else:
            decoder_snapshot = self._phase1_decoder_snapshot()
        self.runtime = RuntimeStatus(
            ready=self._runtime_ready(tools),
            runtime_root=runtime_root(),
            message=str(decoder_snapshot.get("message") or "Runtime catalog loaded."),
            tools=tools,
            diagnostics=decoder_snapshot,
        )
        self.system_profile = build_sdr_system_profile(self.channels, self.trunked_catalog, tools, decoder_snapshot)

    def _preferred_control_channel(self) -> Optional[int]:
        sites = self.trunked_catalog.get("sites", [])
        if not sites:
            return None
        channels = sites[0].get("control_channels_hz", [])
        return int(channels[0]) if channels else None

    def _control_channels(self) -> list[int]:
        sites = self.trunked_catalog.get("sites", [])
        if not sites:
            return []
        return [int(channel) for channel in sites[0].get("control_channels_hz", [])]

    def _voice_channel_count(self) -> int:
        sites = self.trunked_catalog.get("sites", [])
        if not sites:
            return 0
        return len(sites[0].get("voice_channels_hz", []))

    def _talkgroup_for_decimal(self, decimal: Optional[int]) -> Optional[Talkgroup]:
        if decimal is None:
            return None
        return next((item for item in self.talkgroups if item.decimal == int(decimal)), None)

    def _is_tcso_talkgroup(self, talkgroup: Talkgroup) -> bool:
        text = f"{talkgroup.alpha_tag} {talkgroup.description}".upper()
        return "TCSO" in text or "TC TRANS" in text

    def _tracking_label_for(self, talkgroup: Optional[Talkgroup]) -> Optional[str]:
        if talkgroup is None:
            return None
        if self._is_tcso_talkgroup(talkgroup):
            return "TCSO talkgroups"
        return talkgroup.alpha_tag

    def _priority_talkgroups_for(self, talkgroup: Talkgroup) -> list[Talkgroup]:
        if self._is_tcso_talkgroup(talkgroup):
            return [
                item
                for item in self.talkgroups
                if self._is_tcso_talkgroup(item) and not item.encrypted
            ]
        return [talkgroup]

    def _selected_talkgroup_allows_activity(self, selected_talkgroup: Optional[Talkgroup], talkgroup: Optional[Talkgroup], talkgroup_decimal: Optional[int]) -> bool:
        if selected_talkgroup is None:
            return True
        if self._is_tcso_talkgroup(selected_talkgroup):
            if talkgroup is not None:
                return self._is_tcso_talkgroup(talkgroup)
            if talkgroup_decimal is None:
                return False
            return any(
                item.decimal == int(talkgroup_decimal) and self._is_tcso_talkgroup(item) and not item.encrypted
                for item in self.talkgroups
            )
        return talkgroup_decimal == selected_talkgroup.decimal

    def _prioritize_decoder_talkgroups(self, talkgroups: list[Talkgroup]) -> None:
        for item in talkgroups:
            try:
                self.decoder.prioritize_talkgroup(item.decimal, item.alpha_tag)
            except OSError:
                pass

    def _decoder_activity(self, decoder_snapshot: dict[str, object], selected_talkgroup: Optional[Talkgroup]) -> tuple[Optional[P25ActiveCall], Optional[dict[str, object]], list[dict[str, object]]]:
        activity = decoder_snapshot.get("activity")
        if not isinstance(activity, dict):
            return None, None, []
        if selected_talkgroup is not None:
            recent_events = activity.get("recent_events")
            if isinstance(recent_events, list):
                for event in recent_events:
                    if not isinstance(event, dict):
                        continue
                    event_talkgroup_decimal = event.get("talkgroup_decimal")
                    if event_talkgroup_decimal is not None:
                        try:
                            event_talkgroup_decimal = int(event_talkgroup_decimal)
                        except (TypeError, ValueError):
                            event_talkgroup_decimal = None
                    event_talkgroup = self._talkgroup_for_decimal(event_talkgroup_decimal)
                    if self._selected_talkgroup_allows_activity(selected_talkgroup, event_talkgroup, event_talkgroup_decimal):
                        activity = event
                        break

        talkgroup_decimal = activity.get("talkgroup_decimal")
        if talkgroup_decimal is not None:
            try:
                talkgroup_decimal = int(talkgroup_decimal)
            except (TypeError, ValueError):
                talkgroup_decimal = None

        talkgroup = self._talkgroup_for_decimal(talkgroup_decimal)

        voice_frequency_hz = activity.get("voice_frequency_hz")
        if voice_frequency_hz is not None:
            try:
                voice_frequency_hz = int(voice_frequency_hz)
            except (TypeError, ValueError):
                voice_frequency_hz = None

        source_radio_id = activity.get("source_radio_id")
        target_radio_id = activity.get("target_radio_id")
        source_alias = activity.get("source_alias")
        raw = activity.get("raw") or decoder_snapshot.get("p25data_last_line")
        is_voice_event = bool(activity.get("voice_event"))

        activity_allowed = self._selected_talkgroup_allows_activity(selected_talkgroup, talkgroup, talkgroup_decimal)

        has_runtime_activity = (
            activity_allowed
            and
            is_voice_event
            and (
                talkgroup_decimal is not None
                or voice_frequency_hz is not None
                or source_radio_id is not None
                or target_radio_id is not None
            )
        )

        active_call: Optional[P25ActiveCall] = None
        if has_runtime_activity:
            active_call = P25ActiveCall(
                talkgroup=talkgroup,
                talkgroup_decimal=talkgroup_decimal,
                voice_frequency_hz=voice_frequency_hz,
                source_radio_id=str(source_radio_id) if source_radio_id is not None else (str(source_alias) if source_alias is not None else None),
                target_radio_id=str(target_radio_id) if target_radio_id is not None else None,
            )

        last_event: Optional[dict[str, object]] = None
        if activity_allowed and (raw or active_call is not None):
            last_event = {
                "raw": str(raw or "Runtime activity detected."),
                "talkgroup_decimal": active_call.talkgroup_decimal if active_call is not None else talkgroup_decimal,
                "source_radio_id": str(source_radio_id) if source_radio_id is not None else None,
                "target_radio_id": str(target_radio_id) if target_radio_id is not None else None,
                "phase": activity.get("phase"),
            }
            if talkgroup is not None:
                last_event["talkgroup"] = talkgroup.model_dump()
            elif selected_talkgroup is not None:
                last_event["selected_talkgroup"] = selected_talkgroup.model_dump()
            if source_alias is not None:
                last_event["source_alias"] = str(source_alias)

        active_voice_channels: list[dict[str, object]] = []
        if activity_allowed and voice_frequency_hz is not None:
            active_voice_channels.append({
                "frequency_hz": voice_frequency_hz,
                "label": talkgroup.alpha_tag if talkgroup is not None else f"TG {talkgroup_decimal or 'Active'}",
            })

        return active_call, last_event, active_voice_channels

    def _record_call(self, name: str, frequency_hz: int, service_type: str) -> None:
        entry = CallEntry(
            id=f"call-{int(datetime.now(tz=timezone.utc).timestamp() * 1000)}",
            name=name,
            frequency_hz=frequency_hz,
            service_type=service_type,
            time=datetime.now(tz=timezone.utc).isoformat(),
        )
        self.calls.appendleft(entry)

    def get_channels(self) -> list[Channel]:
        return self.channels

    def add_channel(self, payload: ChannelCreate) -> ScannerStatus:
        channel = save_user_channel(payload)
        self.channels = load_channels()
        self.status.message = f"Added {channel.name}."
        return self.status

    def get_talkgroups(self, include_encrypted: bool = False) -> list[Talkgroup]:
        if include_encrypted:
            return self.talkgroups
        return [talkgroup for talkgroup in self.talkgroups if not talkgroup.encrypted]

    def get_calls(self) -> list[CallEntry]:
        return list(self.calls)

    def runtime_status(self) -> RuntimeStatus:
        self._refresh_runtime()
        return self.runtime

    def sdr_system_profile(self) -> SdrSystemProfile:
        self._refresh_runtime()
        return self.system_profile

    def sync_runtime(self) -> RuntimeStatus:
        self._refresh_runtime(force_probe=True)
        self.runtime.message = str(self.runtime.diagnostics.get("message") or "Runtime sync completed.")
        return self.runtime

    def sync_p25_playlist(self) -> dict:
        config_path = self.decoder.config_path()
        if self._preferred_control_channel() is not None:
            return {
                "updated": True,
                "message": f"Headless P25 runtime is using {config_path} with the workspace GATRRS control-channel list.",
            }
        return {"updated": False, "message": "No GATRRS control channels are configured for the headless runtime."}

    def _filtered_channels(self) -> list[Channel]:
        channels = self.channels
        if self.channel_filter:
            allowed = set(self.channel_filter)
            channels = [channel for channel in channels if channel.id in allowed]
        if self.system_filter:
            allowed_systems = set(self.system_filter)
            channels = [channel for channel in channels if channel.system in allowed_systems]
        return channels

    def _available_channel_count(self, channels: list[Channel]) -> int:
        return sum(1 for channel in channels if is_channel_available(channel, self.skipped_channel_ids))

    def _public_channel(self, channel: Optional[Channel]) -> Optional[dict[str, object]]:
        if channel is None:
            return None
        payload = channel.model_dump()
        unavailable = bool(channel.encrypted)
        payload["unavailable"] = unavailable
        payload["availability"] = "Unavailable" if unavailable else "Available"
        payload["channel_id"] = channel.id
        return payload

    def _scanner_state_label(self) -> str:
        if self.is_paused:
            return "Paused"
        if self.status.held:
            return "Holding"
        if self.status.state in {"SCANNING", "RECEIVING_CALL"}:
            return "Scanning"
        return "Stopped"

    def _status_payload(self) -> dict[str, object]:
        channel = self.status.active_channel
        public_channel = self._public_channel(channel)
        state = "PAUSED" if self.is_paused else self.status.state
        is_scanning = state in {"SCANNING", "RECEIVING_CALL"} and not self.status.held
        return {
            "is_scanning": is_scanning,
            "is_paused": self.is_paused,
            "is_muted": self.status.muted,
            "is_holding": self.status.held,
            "current_channel": public_channel,
            "current_frequency_hz": channel.frequency_hz if channel else None,
            "signal_level": self.status.signal_power,
            "receiver_mode": self.device.receiver_label,
            "simulated": self.device.simulated,
            "error_message": self.error_message or self.device.error_message,
            "scanner_state": self._scanner_state_label(),
            "state": state,
            "message": self.status.message,
            "held": self.status.held,
            "muted": self.status.muted,
            "active_channel": public_channel,
            "signal_power": self.status.signal_power,
            "signal_threshold": self.status.signal_threshold,
            "gain_db": self.status.gain_db,
            "channels_scanned": self.status.channels_scanned,
            "in_delay": self.status.in_delay,
            "delay_remaining": self.status.delay_remaining,
        }

    def scanner_status(self) -> dict[str, object]:
        if self.fm_player.playing:
            self.status = self.status.model_copy(update={"simulated": self.device.simulated})
            return self._status_payload()
        if self.p25.selected_talkgroup or self.p25.running:
            self._sync_p25_runtime()
        self.status = self.status.model_copy(update={"simulated": self.device.simulated})
        return self._status_payload()

    def _set_no_available_status(self) -> dict[str, object]:
        self.status = self.status.model_copy(update={
            "state": "NO_SIGNAL",
            "message": "No available non-encrypted channels to scan.",
            "active_channel": None,
            "channels_scanned": 0,
            "held": False,
            "in_delay": False,
            "delay_remaining": 0.0,
            "simulated": self.device.simulated,
        })
        self.is_paused = False
        return self.scanner_status()

    def _select_next_available(self, state: str, message: str, held: bool = False) -> dict[str, object]:
        channels = self._filtered_channels()
        selected = next_scannable_channel_index(channels, self.scan_index, self.skipped_channel_ids)
        if selected is None:
            return self._set_no_available_status()

        selected_index, channel = selected
        self.scan_index = (selected_index + 1) % max(len(channels), 1)
        self.error_message = None
        self.status = self.status.model_copy(update={
            "state": state,
            "message": message,
            "active_channel": channel,
            "channels_scanned": self._available_channel_count(channels),
            "held": held,
            "in_delay": False,
            "delay_remaining": 0.0,
            "signal_power": -64.0 + ((selected_index % 5) * 2.5),
            "simulated": self.device.simulated,
        })
        return self.scanner_status()

    def start_scanner(self) -> dict[str, object]:
        self.skipped_channel_ids.clear()
        self.is_paused = False
        channels = self._filtered_channels()
        available_count = self._available_channel_count(channels)
        return self._select_next_available("SCANNING", f"Scanning {available_count} available channels.")

    def stop_scanner(self) -> dict[str, object]:
        self.is_paused = False
        self.status = self.status.model_copy(update={
            "state": "READY",
            "message": "Scanner stopped.",
            "held": False,
            "in_delay": False,
            "delay_remaining": 0.0,
            "simulated": self.device.simulated,
        })
        return self.scanner_status()

    def pause_scanner(self) -> dict[str, object]:
        self.is_paused = True
        self.status = self.status.model_copy(update={
            "state": "PAUSED",
            "message": "Scanner paused.",
            "held": False,
            "in_delay": False,
            "delay_remaining": 0.0,
            "simulated": self.device.simulated,
        })
        return self.scanner_status()

    def resume_scanner(self) -> dict[str, object]:
        self.is_paused = False
        if self.status.active_channel is None:
            return self.start_scanner()
        self.status = self.status.model_copy(update={
            "state": "SCANNING",
            "message": "Scanner resumed.",
            "held": False,
            "in_delay": False,
            "delay_remaining": 0.0,
            "simulated": self.device.simulated,
        })
        return self.scanner_status()

    def next_channel(self) -> dict[str, object]:
        held = self.status.held
        paused = self.is_paused
        active = self.status.state in {"SCANNING", "RECEIVING_CALL"}
        state = "HOLDING_CHANNEL" if held else ("PAUSED" if paused else ("SCANNING" if active else "READY"))
        return self._select_next_available(state, "Moved to next available channel.", held=held)

    def tune_channel(self, channel_id: str) -> dict[str, object]:
        channel = next((item for item in self.channels if item.id == channel_id), None)
        if channel is None:
            self.error_message = "Channel not found."
            self.status = self.status.model_copy(update={"state": "ERROR", "message": "Channel not found."})
            return self.scanner_status()

        if channel.encrypted:
            self.skipped_channel_ids.add(channel.id)
            self.error_message = f"{channel.name} is Unavailable because it is encrypted."
            if self.status.active_channel and not self.status.active_channel.encrypted:
                self.status = self.status.model_copy(update={"message": self.error_message})
                return self.scanner_status()
            return self._select_next_available("SCANNING", self.error_message)

        self.is_paused = False
        self.error_message = None
        self.status = self.status.model_copy(update={
            "state": "RECEIVING_CALL",
            "message": f"Tuned {channel.name}.",
            "active_channel": channel,
            "held": False,
            "in_delay": False,
            "delay_remaining": 0.0,
            "signal_power": -53.0,
            "simulated": self.device.simulated,
        })
        return self.scanner_status()

    def hold(self) -> dict[str, object]:
        if self.status.active_channel is None:
            self._select_next_available("HOLDING_CHANNEL", "Stay Here active.", held=True)
        self.is_paused = False
        state = "HOLDING_CHANNEL" if self.status.active_channel else self.status.state
        self.status = self.status.model_copy(update={
            "state": state,
            "held": True if self.status.active_channel else False,
            "message": "Stay Here active." if self.status.active_channel else "No channel available to hold.",
            "simulated": self.device.simulated,
        })
        return self.scanner_status()

    def release_hold(self) -> dict[str, object]:
        self.is_paused = False
        state = "SCANNING" if self.status.active_channel else "READY"
        self.status = self.status.model_copy(update={
            "state": state,
            "held": False,
            "message": "Stay Here released.",
            "simulated": self.device.simulated,
        })
        return self.scanner_status()

    def clear_hold(self) -> dict[str, object]:
        return self.release_hold()

    def skip(self) -> dict[str, object]:
        current = self.status.active_channel
        if current is not None:
            self.skipped_channel_ids.add(current.id)
        self.is_paused = False
        return self._select_next_available("SCANNING", "Current channel hidden for this session.", held=False)

    def set_mute(self, muted: bool) -> dict[str, object]:
        self.status = self.status.model_copy(update={
            "muted": muted,
            "message": "Audio muted." if muted else "Audio unmuted.",
            "simulated": self.device.simulated,
        })
        return self.scanner_status()

    def set_gain(self, gain_db: Optional[float]) -> dict[str, object]:
        self.status = self.status.model_copy(update={
            "gain_db": gain_db,
            "message": f"Gain set to {'auto' if gain_db is None else f'{gain_db:.1f} dB'}.",
            "simulated": self.device.simulated,
        })
        return self.scanner_status()

    def set_receiver_mode(self, simulated: bool) -> dict[str, object]:
        self.device.set_simulated(simulated)
        self.error_message = self.device.error_message
        message = self.error_message or ("Demo receiver mode active." if simulated else "RTL-SDR receiver mode active.")
        self.status = self.status.model_copy(update={
            "message": message,
            "simulated": self.device.simulated,
        })
        return self.scanner_status()

    def set_channel_filter(self, channel_ids: Optional[list[str]]) -> None:
        self.channel_filter = channel_ids
        self.skipped_channel_ids.clear()
        self.scan_index = 0

    def set_group_filter(self, systems: Optional[list[str]]) -> None:
        self.system_filter = systems
        self.skipped_channel_ids.clear()
        self.scan_index = 0

    def fm_stations(self) -> list[FmStation]:
        stations: list[FmStation] = []
        for channel in self.channels:
            if channel.service_type != "fm_radio":
                continue
            stations.append(FmStation(
                id=channel.id,
                callsign=channel.name.split()[0].upper(),
                name=channel.name,
                frequency_hz=channel.frequency_hz,
                frequency_mhz=round(channel.frequency_hz / 1_000_000, 1),
                artist="Austin Playlist",
                song_title=channel.name,
                now_playing=f"{channel.name} live audio path ready",
                program_name=channel.system,
                metadata_raw=f"{channel.name} on {channel.system}",
            ))
        return stations

    def fm_player_status(self) -> FmPlayerStatus:
        return self.fm_player

    def play_fm(self, channel_id: str) -> FmPlayerStatus:
        station = next((item for item in self.fm_stations() if item.id == channel_id), None)
        if station is None:
            return self.fm_player

        self.stop_p25()

        self.status = self.status.model_copy(update={
            "state": "RECEIVING_CALL",
            "message": f"Playing FM station {station.callsign}.",
            "active_channel": next((channel for channel in self.channels if channel.id == channel_id), None),
            "signal_power": -49.0,
            "simulated": self.device.simulated,
        })
        self.fm_player = FmPlayerStatus(
            playing=True,
            chunks=32,
            station=station,
            frequency_hz=station.frequency_hz,
            tuned_frequency_hz=station.frequency_hz,
            frequency_offset_hz=0,
            gain_used_db=self.status.gain_db,
            last_db=-48.5,
            peak_db=-41.2,
        )
        self._record_call(station.name, station.frequency_hz, station.service_type)
        return self.fm_player

    def fine_tune_fm(self, channel_id: str, offset_hz: int) -> FmPlayerStatus:
        if not self.fm_player.playing:
            return self.play_fm(channel_id)
        self.fm_player = self.fm_player.model_copy(update={
            "frequency_offset_hz": offset_hz,
            "tuned_frequency_hz": (self.fm_player.frequency_hz or 0) + offset_hz,
        })
        return self.fm_player

    def stop_fm(self) -> FmPlayerStatus:
        self.fm_player = FmPlayerStatus()
        return self.fm_player

    def p25_status(self) -> P25Status:
        if self.p25.selected_talkgroup or self.p25.running or self.p25.external_decoder.get("running"):
            self._sync_p25_runtime()
        else:
            self.p25 = self.p25.model_copy(update={"external_decoder": self.decoder.status(force_probe=False)})
        return self.p25

    def start_p25(self) -> P25Status:
        self.stop_fm()
        self.device.refresh(force=True)
        self._refresh_runtime(force_probe=True)
        decoder_snapshot = self.decoder.start(force_probe=True)
        decoder_health = str(decoder_snapshot.get("health") or "error")
        decoder_message = str(decoder_snapshot.get("message") or "P25 decoder failed to start.")
        decoder_running = bool(decoder_snapshot.get("running"))
        active_call, runtime_event, active_voice_channels = self._decoder_activity(decoder_snapshot, None)

        self.status = self.status.model_copy(update={
            "state": self._p25_state_for_health(decoder_health),
            "message": decoder_message,
            "active_channel": None,
            "held": False,
            "signal_power": -99.0 if decoder_health != "ready" else self.status.signal_power,
            "simulated": self.device.simulated,
        })
        self.p25 = self.p25.model_copy(update={
            "running": decoder_running,
            "state": self._p25_state_for_health(decoder_health),
            "message": "Headless P25 runtime running. Select a talkgroup." if decoder_health == "ready" else decoder_message,
            "selected_talkgroup": None,
            "tracking_label": None,
            "tracked_talkgroup_count": 0,
            "active_call": active_call,
            "last_event": runtime_event,
            "external_decoder": decoder_snapshot,
            "voice_scan_active": decoder_health == "ready",
            "voice_scan_error": None if decoder_health == "ready" else decoder_message,
            "voice_sweep_stats": {
                "sweeps": (self.p25.voice_sweep_stats or {}).get("sweeps", 0) + 1,
                "last_sweep_ms": 180 if decoder_health == "ready" else 0,
                "channels": self._voice_channel_count(),
            },
            "active_voice_channels": active_voice_channels,
        })
        return self.p25

    def stop_p25(self) -> P25Status:
        decoder_snapshot = self.decoder.stop()
        self.p25 = self.p25.model_copy(update={
            "running": False,
            "state": "WAITING_FOR_TALKGROUP",
            "message": "P25 decoder stopped.",
            "selected_talkgroup": None,
            "tracking_label": None,
            "tracked_talkgroup_count": 0,
            "active_call": None,
            "last_event": None,
            "voice_scan_active": False,
            "voice_scan_error": None,
            "active_voice_channels": [],
            "external_decoder": decoder_snapshot,
        })
        self.status = self.status.model_copy(update={
            "held": False,
            "message": "P25 decoder stopped.",
        })
        return self.p25

    def select_talkgroup(self, decimal: Optional[int] = None, talkgroup_id: Optional[str] = None, talkgroup_payload: Optional[dict] = None) -> P25Status:
        talkgroup: Optional[Talkgroup] = None
        if decimal is not None:
            talkgroup = next((item for item in self.talkgroups if item.decimal == decimal), None)
        if talkgroup is None and talkgroup_id:
            talkgroup = next((item for item in self.talkgroups if item.id == talkgroup_id), None)
        if talkgroup is None and talkgroup_payload:
            if "decimal" in talkgroup_payload:
                talkgroup = next((item for item in self.talkgroups if item.decimal == int(talkgroup_payload["decimal"])), None)
            else:
                talkgroup = Talkgroup.model_validate(talkgroup_payload)
        if talkgroup is None:
            self.p25 = self.p25.model_copy(update={"message": "Talkgroup not found."})
            return self.p25

        priority_talkgroups = self._priority_talkgroups_for(talkgroup)
        self._prioritize_decoder_talkgroups(priority_talkgroups)
        self.start_p25()
        self._prioritize_decoder_talkgroups(priority_talkgroups)
        decoder_snapshot = self.decoder.status(force_probe=False)
        decoder_health = str(decoder_snapshot.get("health") or "error")
        message = self._talkgroup_message(decoder_health, talkgroup, decoder_snapshot)

        self.p25 = self.p25.model_copy(update={
            "running": bool(decoder_snapshot.get("running")),
            "state": self._p25_state_for_health(decoder_health, talkgroup_selected=True),
            "message": message,
            "selected_talkgroup": talkgroup,
            "tracking_label": self._tracking_label_for(talkgroup),
            "tracked_talkgroup_count": len(priority_talkgroups),
            "active_call": None,
            "last_event": {
                "raw": f"Selected TG {talkgroup.decimal} {talkgroup.alpha_tag}",
                "talkgroup": talkgroup.model_dump(),
            },
            "voice_scan_active": decoder_health == "ready",
            "voice_scan_error": None if decoder_health == "ready" else message,
            "active_voice_channels": [],
            "external_decoder": decoder_snapshot,
        })
        self.status = self.status.model_copy(update={
            "state": self._p25_state_for_health(decoder_health, talkgroup_selected=True),
            "message": message,
            "held": True,
            "signal_power": -99.0 if decoder_health != "ready" else self.status.signal_power,
            "simulated": self.device.simulated,
        })
        return self.p25


controller = ScannerController()
