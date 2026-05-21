from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import threading
import time
from typing import Any, Iterable

from ..headless_p25_runtime import HeadlessP25Runtime
from ..radio.models import Channel, DecoderStatus
from .base_decoder import BaseDecoder


P25_LIVE_ACTIVITY_SECONDS = 12.0
P25_RECENT_RADIO_SECONDS = 600.0
MONITORED_TALKGROUP_REFRESH_SECONDS = 2.0


class ManagedP25Decoder(BaseDecoder):
    id = "p25-managed"
    label = "Managed P25 Runtime"
    modulation = "p25_placeholder"

    def __init__(self, control_channels_hz: Iterable[int] | None = None) -> None:
        self._control_channels_hz: tuple[int, ...] = ()
        self._runtime = HeadlessP25Runtime([])
        self._rf_gain_db: float | None = None
        self._selected_label: str | None = None
        self._selected_talkgroup_decimal: int | None = None
        self._monitored_talkgroups: tuple[tuple[int, str], ...] = ()
        self._known_talkgroups: tuple[tuple[int, str], ...] = ()
        self._locked_talkgroups: tuple[int, ...] = ()
        self._operation_lock = threading.RLock()
        self._last_monitored_apply_at = 0.0
        if control_channels_hz:
            self._set_control_channels(control_channels_hz)

    def _normalize_monitored_talkgroups(self, talkgroups: Iterable[tuple[int, str]]) -> tuple[tuple[int, str], ...]:
        normalized: list[tuple[int, str]] = []
        seen: set[int] = set()
        for decimal, alias in talkgroups:
            try:
                parsed_decimal = int(decimal)
            except (TypeError, ValueError):
                continue
            if parsed_decimal <= 0 or parsed_decimal in seen:
                continue
            seen.add(parsed_decimal)
            normalized.append((parsed_decimal, str(alias or f"TG {parsed_decimal}")))
        return tuple(normalized)

    def _monitored_talkgroup_decimals(self) -> set[int]:
        return {decimal for decimal, _alias in self._monitored_talkgroups}

    def _normalize_control_channels(self, control_channels_hz: Iterable[int]) -> tuple[int, ...]:
        ordered: list[int] = []
        seen: set[int] = set()
        for frequency_hz in control_channels_hz:
            try:
                parsed = int(frequency_hz)
            except (TypeError, ValueError):
                continue
            if parsed <= 0 or parsed in seen:
                continue
            seen.add(parsed)
            ordered.append(parsed)
        return tuple(ordered)

    def _set_control_channels(self, control_channels_hz: Iterable[int]) -> None:
        normalized = self._normalize_control_channels(control_channels_hz)
        if normalized == self._control_channels_hz:
            return
        if self._control_channels_hz:
            self._runtime.stop()
        self._runtime = HeadlessP25Runtime(list(normalized))
        self._runtime.set_rf_gain(self._rf_gain_db)
        self._runtime.set_known_talkgroups(list(self._known_talkgroups))
        self._runtime.set_locked_talkgroups(list(self._locked_talkgroups))
        self._control_channels_hz = normalized

    def _parse_int(self, value: object) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def _parse_text(self, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _format_frequency(self, frequency_hz: int | None) -> str:
        if frequency_hz is None or frequency_hz <= 0:
            return "--.----"
        return f"{frequency_hz / 1_000_000:.4f}"

    def _recent_radios(self, activity: dict[str, Any]) -> list[dict[str, Any]]:
        recent_radios = activity.get("recent_radios")
        if not isinstance(recent_radios, list):
            return []
        return [item for item in recent_radios if isinstance(item, dict)]

    def _activity_matches_selected_talkgroup(self, activity: dict[str, Any]) -> bool:
        activity_talkgroup = self._parse_int(activity.get("talkgroup_decimal"))
        monitored_decimals = self._monitored_talkgroup_decimals()
        if self._selected_talkgroup_decimal is not None:
            if monitored_decimals:
                return activity_talkgroup in monitored_decimals
            return activity_talkgroup == self._selected_talkgroup_decimal
        if not monitored_decimals:
            return True
        return activity_talkgroup in monitored_decimals

    def _radio_matches_selected_talkgroup(self, radio: dict[str, Any]) -> bool:
        radio_talkgroup = self._parse_int(radio.get("group"))
        monitored_decimals = self._monitored_talkgroup_decimals()
        if self._selected_talkgroup_decimal is not None:
            if monitored_decimals:
                return radio_talkgroup in monitored_decimals
            return radio_talkgroup == self._selected_talkgroup_decimal
        if not monitored_decimals:
            return True
        return radio_talkgroup in monitored_decimals

    def _parse_activity_timestamp(self, value: Any) -> datetime | None:
        text = self._parse_text(value)
        if not text:
            return None

        patterns = (
            r"(\d{4})/(\d{2})/(\d{2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?",
            r"(\d{4})\.(\d{2})\.(\d{2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            year, month, day, hour, minute, second = match.groups()
            try:
                return datetime(
                    int(year),
                    int(month),
                    int(day),
                    int(hour),
                    int(minute),
                    int(second or 0),
                )
            except ValueError:
                return None
        return None

    def _activity_age_seconds(self, value: Any) -> float | None:
        timestamp = self._parse_activity_timestamp(value)
        if timestamp is None:
            return None
        return (datetime.now() - timestamp).total_seconds()

    def _activity_duration_seconds(self, activity: dict[str, Any]) -> float:
        raw = self._parse_text(activity.get("raw"))
        if not raw:
            return 0.0
        match = re.search(r"\b(\d{1,3})s\b", raw)
        if not match:
            return 0.0
        return float(match.group(1))

    def _activity_is_fresh(self, activity: dict[str, Any]) -> bool:
        age = self._activity_age_seconds(activity.get("raw"))
        if age is None:
            return True
        return 0 <= age <= (P25_LIVE_ACTIVITY_SECONDS + self._activity_duration_seconds(activity))

    def _radio_is_recent(self, radio: dict[str, Any]) -> bool:
        age = self._activity_age_seconds(radio.get("timestamp"))
        if age is None:
            return False
        return 0 <= age <= P25_RECENT_RADIO_SECONDS

    def _selected_activity(self, activity: dict[str, Any]) -> dict[str, Any]:
        if not activity or (self._selected_talkgroup_decimal is None and not self._monitored_talkgroups):
            return dict(activity)

        recent_events = [item for item in activity.get("recent_events", []) if isinstance(item, dict)]
        selected_recent_events = [
            item for item in recent_events
            if self._activity_matches_selected_talkgroup(item)
        ]
        fresh_selected_events = [
            item for item in selected_recent_events
            if self._activity_is_fresh(item)
        ]
        selected_recent_radios = [
            item for item in self._recent_radios(activity)
            if self._radio_matches_selected_talkgroup(item) and self._radio_is_recent(item)
        ]

        candidate = (
            activity
            if self._activity_matches_selected_talkgroup(activity) and self._activity_is_fresh(activity)
            else None
        )
        if candidate is None:
            candidate = next(
                (item for item in fresh_selected_events if self._activity_matches_selected_talkgroup(item)),
                None,
            )

        filtered_activity = dict(activity)
        filtered_activity["recent_events"] = fresh_selected_events
        filtered_activity["recent_radios"] = selected_recent_radios

        if candidate is None:
            for key in (
                "raw",
                "voice_event",
                "voice_frequency_hz",
                "control_frequency_hz",
                "talkgroup_decimal",
                "source_radio_id",
                "target_radio_id",
                "nac",
                "phase",
                "encrypted",
            ):
                filtered_activity.pop(key, None)
            return filtered_activity

        for key, value in candidate.items():
            if key in {"recent_events", "recent_radios"}:
                continue
            filtered_activity[key] = value
        return filtered_activity

    def _status_from_snapshot(self, snapshot: dict[str, object]) -> DecoderStatus:
        engine = self._parse_text(snapshot.get("engine")) or "dsdplus"
        health = str(snapshot.get("health") or "stopped")
        message = str(snapshot.get("message") or "Managed P25 runtime idle.")
        running = bool(snapshot.get("running"))
        ready = bool(snapshot.get("installed", True)) and health not in {"missing_runtime", "no_tuner", "error", "driver_conflict"}
        active = running or health == "starting"
        raw_activity = snapshot.get("activity") if isinstance(snapshot.get("activity"), dict) else {}
        activity = self._selected_activity(raw_activity)
        voice_frequency_hz = self._parse_int(activity.get("voice_frequency_hz"))
        talkgroup_decimal = self._parse_int(activity.get("talkgroup_decimal")) or self._selected_talkgroup_decimal
        source_radio_id = self._parse_text(activity.get("source_radio_id"))
        target_radio_id = self._parse_text(activity.get("target_radio_id"))
        control_channels_hz = self._normalize_control_channels(snapshot.get("control_channels_hz") or self._control_channels_hz)
        control_channel_hz = self._parse_int(snapshot.get("control_channel_hz"))
        sync_state = (
            "voice_follow" if voice_frequency_hz is not None else
            "control_lock" if health == "ready" else
            "hunting" if health == "starting" else
            health
        )

        if voice_frequency_hz is not None:
            lock_message = f"Voice lock {self._format_frequency(voice_frequency_hz)} MHz"
            if talkgroup_decimal is not None:
                lock_message = f"{lock_message} TG {talkgroup_decimal}"
            if source_radio_id is not None:
                lock_message = f"{lock_message} RID {source_radio_id}"
            message = f"{lock_message}. {message}"
        elif engine == "sdrtrunk":
            message = (
                f"{message} SDRTrunk fallback is using the workspace GATRRS playlist; "
                "in-app P25 live audio and transcription are unavailable in fallback mode."
            )
        if self._selected_label:
            prefix = "Tracking" if running or health == "ready" else "Selected"
            message = f"{prefix} {self._selected_label}. {message}"

        runtime = {
            "engine": engine,
            "health": health,
            "control_channel_index": self._parse_int(snapshot.get("control_channel_index")) or 0,
            "p25data_records": self._parse_int(snapshot.get("p25data_records")) or 0,
            "failover_count": self._parse_int(snapshot.get("failover_count")) or 0,
        }
        last_failover_reason = self._parse_text(snapshot.get("last_failover_reason"))
        if last_failover_reason:
            runtime["last_failover_reason"] = last_failover_reason
        error_detail = self._parse_text(snapshot.get("error_detail"))
        if error_detail:
            runtime["error_detail"] = error_detail
        playlist_path = self._parse_text(snapshot.get("playlist_path"))
        if playlist_path:
            runtime["playlist_path"] = playlist_path
        audio_output_device = self._parse_int(snapshot.get("audio_output_device"))
        if audio_output_device is not None:
            runtime["audio_output_device"] = audio_output_device
        audio_output_name = self._parse_text(snapshot.get("audio_output_name"))
        if audio_output_name:
            runtime["audio_output_name"] = audio_output_name
        tuner_log = snapshot.get("tuner_log") if isinstance(snapshot.get("tuner_log"), dict) else None
        if tuner_log is not None:
            for key in ("device_count", "busy_device_numbers", "selected_device_number", "selected_serial", "failing_serial"):
                value = tuner_log.get(key)
                if value not in (None, [], ""):
                    runtime[key] = value

        return DecoderStatus(
            id=self.id,
            label=self.label,
            modulation=self.modulation,
            ready=ready,
            active=active,
            message=message,
            sync_state=sync_state,
            control_channel_hz=control_channel_hz,
            control_channels_hz=list(control_channels_hz),
            voice_frequency_hz=voice_frequency_hz,
            talkgroup_decimal=talkgroup_decimal,
            selected_talkgroup_decimal=self._selected_talkgroup_decimal,
            source_radio_id=source_radio_id,
            target_radio_id=target_radio_id,
            nac=self._parse_text(activity.get("nac")),
            phase=self._parse_text(activity.get("phase")),
            encrypted_call=bool(activity.get("encrypted")),
            recent_radios=self._recent_radios(activity),
            activity=dict(activity),
            runtime=runtime,
        )

    def status(self) -> DecoderStatus:
        with self._operation_lock:
            self._refresh_monitored_talkgroups_if_needed()
            return self._status_from_snapshot(self._runtime.status(force_probe=False))

    def _set_monitored_talkgroups(self, talkgroups: list[tuple[int, str]]) -> None:
        try:
            self._runtime.set_monitored_talkgroups(talkgroups)
            self._last_monitored_apply_at = time.monotonic()
        except OSError:
            pass

    def _refresh_monitored_talkgroups_if_needed(self) -> None:
        if not self._monitored_talkgroups or not self._runtime.is_running():
            return
        now = time.monotonic()
        if (now - self._last_monitored_apply_at) < MONITORED_TALKGROUP_REFRESH_SECONDS:
            return
        self._set_monitored_talkgroups(list(self._monitored_talkgroups))

    def set_known_talkgroups(self, talkgroups: Iterable[tuple[int, str]]) -> None:
        with self._operation_lock:
            self._known_talkgroups = self._normalize_monitored_talkgroups(talkgroups)
            try:
                self._runtime.set_known_talkgroups(list(self._known_talkgroups))
            except OSError:
                pass

    def set_locked_talkgroups(self, talkgroups: Iterable[int]) -> None:
        with self._operation_lock:
            locked: list[int] = []
            for decimal in talkgroups:
                parsed = self._parse_int(decimal)
                if parsed is not None and parsed > 0:
                    locked.append(parsed)
            self._locked_talkgroups = tuple(sorted(set(locked)))
            try:
                self._runtime.set_locked_talkgroups(list(self._locked_talkgroups))
            except OSError:
                pass

    def set_rf_gain(self, gain_db: float | None) -> None:
        with self._operation_lock:
            self._rf_gain_db = None if gain_db is None else float(gain_db)
            self._runtime.set_rf_gain(self._rf_gain_db)

    def _start_with_talkgroups(
        self,
        control_channels_hz: Iterable[int],
        talkgroups: Iterable[tuple[int, str]],
        label: str,
        selected_talkgroup_decimal: int | None,
    ) -> DecoderStatus:
        with self._operation_lock:
            normalized_control_channels = self._normalize_control_channels(control_channels_hz)
            can_reuse_running_runtime = (
                normalized_control_channels == self._control_channels_hz
                and self._runtime.is_running()
            )
            self._selected_label = label
            self._selected_talkgroup_decimal = selected_talkgroup_decimal
            self._monitored_talkgroups = self._normalize_monitored_talkgroups(talkgroups)
            self._set_control_channels(normalized_control_channels)
            self._set_monitored_talkgroups(list(self._monitored_talkgroups))
            if can_reuse_running_runtime:
                return self._status_from_snapshot(self._runtime.status(force_probe=False))
            snapshot = self._runtime.start(force_probe=False)
            self._set_monitored_talkgroups(list(self._monitored_talkgroups))
            return self._status_from_snapshot(snapshot)

    def hold_talkgroups(self, channel: Channel, talkgroups: Iterable[tuple[int, str]]) -> DecoderStatus:
        control_channels = channel.p25_control_channels_hz or [channel.frequency_hz]
        monitored_talkgroups = list(talkgroups)
        if not monitored_talkgroups and channel.p25_talkgroup_decimal is not None:
            monitored_talkgroups = [(channel.p25_talkgroup_decimal, channel.name)]
        return self._start_with_talkgroups(
            control_channels_hz=control_channels,
            talkgroups=monitored_talkgroups,
            label=channel.name,
            selected_talkgroup_decimal=channel.p25_talkgroup_decimal,
        )

    def tune(self, channel: Channel) -> DecoderStatus:
        control_channels = channel.p25_control_channels_hz or [channel.frequency_hz]
        monitored_talkgroups: list[tuple[int, str]] = []
        selected_talkgroup_decimal = None
        if channel.p25_talkgroup_decimal is not None:
            selected_talkgroup_decimal = channel.p25_talkgroup_decimal
            monitored_talkgroups = [(channel.p25_talkgroup_decimal, channel.name)]
        return self._start_with_talkgroups(
            control_channels_hz=control_channels,
            talkgroups=monitored_talkgroups,
            label=channel.name,
            selected_talkgroup_decimal=selected_talkgroup_decimal,
        )

    def scan_talkgroups(
        self,
        control_channels_hz: Iterable[int],
        talkgroups: Iterable[tuple[int, str]],
        label: str = "P25 Scan",
    ) -> DecoderStatus:
        return self._start_with_talkgroups(
            control_channels_hz=control_channels_hz,
            talkgroups=talkgroups,
            label=label,
            selected_talkgroup_decimal=None,
        )

    def stop(self) -> None:
        self._selected_label = None
        self._selected_talkgroup_decimal = None
        self._monitored_talkgroups = ()
        self._runtime.stop()

    def audio_wav_path(self) -> Path | None:
        snapshot = self._runtime.status(force_probe=False)
        if str(snapshot.get("engine") or "dsdplus").lower() != "dsdplus":
            return None
        return self._runtime.config_path() / "1R-DSDPlus.wav"
