"""Conventional frequency scanner modeled on Uniden BCD536HP / SDS100 behavior.

Real-scanner behaviors implemented here:
  - 2-second post-signal delay (per-channel, configurable)
  - Signal returns during delay → delay resets (scanner stays on channel)
  - Priority channel interrupt every N channels scanned
  - Temporary skip/avoid (cleared when scanning stops, like a power cycle)
  - Stay Here / Hold — scanner locks to one channel and keeps monitoring it
  - Timeout timer — force resume after N seconds even if signal is still up
  - Encrypted channels → UNAVAILABLE, never decoded
"""

from __future__ import annotations

import json
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from models import Channel, ScannerState, ScannerStatus
from sdr_device import RtlSdrDevice, SdrSettings, SimulatedSdrDevice

StatusCallback = Callable[[ScannerStatus], None]

# How fast the scanner polls power during active receive (seconds)
_POLL_INTERVAL = 0.12


class ConventionalScanner:
    """Scan/stop controller with real-scanner timing and hold/skip behavior."""

    def __init__(
        self,
        frequency_file: Path,
        gain_db: float | None = None,
        signal_threshold: float = -35.0,
        dwell_seconds: float = 0.12,          # ~100–120 ms per channel while scanning
        priority_check_interval: int = 3,     # check priority every N channels
        timeout_seconds: float = 30.0,        # force resume after 30 s on one call
        simulated: bool = True,
    ) -> None:
        self.frequency_file = frequency_file
        self.signal_threshold = signal_threshold
        self.dwell_seconds = dwell_seconds
        self.priority_check_interval = priority_check_interval
        self.timeout_seconds = timeout_seconds
        self.simulated = simulated

        self.channels: list[Channel] = self._load_channels(frequency_file)
        self._temporarily_skipped: set[str] = set()
        self._held_channel_id: str | None = None
        self._channels_scanned: int = 0
        self._group_filter: set[str] | None = None   # None = all systems enabled
        self._channel_filter: set[str] | None = None  # None = all channels enabled
        self._call_log: deque[dict] = deque(maxlen=100)

        self.running = False
        self.muted = False
        self.device = self._make_device(gain_db)

        self.status = ScannerStatus(
            state=ScannerState.NO_SIGNAL,
            message="Scanner is idle",
            signal_threshold=signal_threshold,
            gain_db=gain_db,
            simulated=simulated,
        )

    # ── Device helpers ──────────────────────────────────────────────────────

    def _make_device(self, gain_db: float | None):
        settings = SdrSettings(gain_db=gain_db)
        return SimulatedSdrDevice(settings) if self.simulated else RtlSdrDevice(settings)

    def _load_channels(self, path: Path) -> list[Channel]:
        data = json.loads(path.read_text(encoding="utf-8"))
        channels = [Channel(**item) for item in data.get("channels", [])]
        if not channels:
            raise ValueError(f"No channels found in {path}")
        return channels

    # ── Public control API ──────────────────────────────────────────────────

    def set_group_filter(self, systems: list[str] | None) -> None:
        """Restrict scanning to specific systems. None = all systems enabled."""
        self._group_filter = set(systems) if systems is not None else None
        self._channel_filter = None

    def set_channel_filter(self, channel_ids: list[str] | None) -> None:
        """Restrict scanning to a playlist of channel IDs. None = all channels enabled."""
        self._channel_filter = set(channel_ids) if channel_ids is not None else None
        self._group_filter = None

    def tune_to(self, channel_id: str) -> bool:
        """Jump immediately to a specific channel (hold it). Returns False if not found."""
        channel = next((c for c in self.channels if c.id == channel_id), None)
        if channel:
            self._held_channel_id = channel_id
            self.status.held = True
            self.status.state = ScannerState.HOLDING_CHANNEL
            self.status.active_channel = channel
            self.status.message = "Tuned - holding channel"
        return channel is not None

    def add_channel(self, ch: Channel) -> None:
        """Add a new channel to the scan list at runtime."""
        self.channels.append(ch)

    def remove_channel(self, channel_id: str) -> bool:
        """Remove a channel by ID. Returns False if not found."""
        before = len(self.channels)
        self.channels = [c for c in self.channels if c.id != channel_id]
        if self._held_channel_id == channel_id:
            self._held_channel_id = None
            self.status.held = False
        return len(self.channels) < before

    def get_calls(self) -> list[dict]:
        """Return recent call log, newest first."""
        return list(reversed(self._call_log))

    def set_gain(self, gain_db: float | None) -> None:
        self.device.set_gain(gain_db)
        self.status.gain_db = gain_db

    def set_simulated(self, simulated: bool) -> None:
        if self.running:
            raise RuntimeError("Stop scanning before changing receiver mode.")
        gain = self.status.gain_db
        self.simulated = simulated
        self.device = self._make_device(gain)
        self.status.simulated = simulated
        self.status.message = "Demo receiver ready" if simulated else "RTL-SDR receiver selected"

    def stop(self) -> None:
        """Signal the scan loop to exit. Also clears temporary skips."""
        self.running = False
        self._temporarily_skipped.clear()
        self._held_channel_id = None
        self.status = ScannerStatus(
            state=ScannerState.NO_SIGNAL,
            message="Scanner is idle",
            active_channel=self.status.active_channel,
            signal_power=self.status.signal_power,
            signal_threshold=self.signal_threshold,
            gain_db=self.status.gain_db,
            simulated=self.simulated,
            held=False,
            skipped_count=0,
            channels_scanned=self._channels_scanned,
        )

    def hold_channel(self, channel_id: str | None) -> None:
        """Lock scanner to one channel (Stay Here). Pass None to resume scanning."""
        self._held_channel_id = channel_id
        self.status.held = channel_id is not None
        if channel_id:
            self.status.state = ScannerState.HOLDING_CHANNEL
            self.status.message = "Holding - press Scan to resume"
        else:
            if self.status.state == ScannerState.HOLDING_CHANNEL:
                self.status.state = ScannerState.SCANNING if self.running else ScannerState.NO_SIGNAL
            self.status.message = "Resuming scan"

    def skip_current(self) -> str | None:
        """Temporarily avoid the current channel and resume scanning.

        Mirrors Uniden 'Temporary Avoid' — clears on the next stop() call.
        """
        ch = self.status.active_channel
        if ch:
            self._temporarily_skipped.add(ch.id)
            if self._held_channel_id == ch.id:
                self._held_channel_id = None
                self.status.held = False
            self.status.skipped_count = len(self._temporarily_skipped)
            return ch.id
        return None

    def clear_skipped(self) -> None:
        """Clear all temporary avoids — like power-cycling a real scanner."""
        self._temporarily_skipped.clear()
        self.status.skipped_count = 0

    # ── Scan loop ───────────────────────────────────────────────────────────

    def scan_forever(self, callback: StatusCallback | None = None) -> None:
        """Main scan loop. Runs until stop() is called."""
        self.running = True
        self._channels_scanned = 0

        try:
            self.device.open()
        except Exception as exc:
            self.running = False
            self._publish(ScannerStatus(
                state=ScannerState.DEVICE_NOT_FOUND,
                message=f"RTL-SDR device could not be opened: {exc}",
                signal_threshold=self.signal_threshold,
                gain_db=self.status.gain_db,
                simulated=self.simulated,
            ), callback)
            return

        try:
            while self.running:
                active_channels = self._active_scan_list()
                if not active_channels:
                    self._publish(ScannerStatus(
                        state=ScannerState.NO_SIGNAL,
                        message="No enabled channels to scan",
                        signal_threshold=self.signal_threshold,
                        gain_db=self.status.gain_db,
                        simulated=self.simulated,
                        held=False,
                        skipped_count=len(self._temporarily_skipped),
                        channels_scanned=self._channels_scanned,
                    ), callback)
                    time.sleep(0.25)
                    continue

                for channel in active_channels:
                    if not self.running:
                        break

                    # Priority interrupt: every N channels, quick-check priority channels
                    if (self._channels_scanned > 0
                            and self._channels_scanned % self.priority_check_interval == 0
                            and not self._held_channel_id):
                        self._priority_pass(callback)

                    if not self.running:
                        break

                    if channel.encrypted:
                        self._publish_unavailable(channel, callback)
                        continue

                    if channel.id in self._temporarily_skipped:
                        continue

                    self._check_channel(channel, callback)
                    self._channels_scanned += 1
        finally:
            self.device.close()

    def _active_scan_list(self) -> list[Channel]:
        """Return [held_channel] when held, otherwise filtered non-skipped list."""
        if self._held_channel_id:
            held = [c for c in self.channels if c.id == self._held_channel_id]
            return held or self.channels
        return [
            c for c in self.channels
            if c.id not in self._temporarily_skipped
            and (self._group_filter is None or c.system in self._group_filter)
            and (self._channel_filter is None or c.id in self._channel_filter)
        ]

    def _priority_pass(self, callback: StatusCallback | None) -> None:
        """Quick-check all priority channels. If active, receive with full delay loop."""
        priority = [
            c for c in self.channels
            if c.priority and not c.encrypted and c.id not in self._temporarily_skipped
            and (self._group_filter is None or c.system in self._group_filter)
            and (self._channel_filter is None or c.id in self._channel_filter)
        ]
        for ch in priority:
            if not self.running:
                return
            self.device.tune(ch.frequency_hz)
            time.sleep(self.dwell_seconds)
            power = self.device.read_power()
            if power >= self.signal_threshold:
                self._receive_loop(ch, power, callback)

    def _check_channel(self, channel: Channel, callback: StatusCallback | None) -> None:
        """Tune, dwell, read power, then either log quiet or enter receive loop."""
        self.device.tune(channel.frequency_hz)
        time.sleep(self.dwell_seconds)
        power = self.device.read_power()

        if power < self.signal_threshold:
            # Quiet channel — publish state and move on
            state = ScannerState.HOLDING_CHANNEL if self._held_channel_id else ScannerState.SCANNING
            message = "Monitoring channel" if self._held_channel_id else "Scanning"
            self._publish(ScannerStatus(
                state=state,
                message=message,
                active_channel=channel,
                signal_power=power,
                signal_threshold=self.signal_threshold,
                gain_db=self.status.gain_db,
                simulated=self.simulated,
                held=bool(self._held_channel_id),
                channels_scanned=self._channels_scanned,
                skipped_count=len(self._temporarily_skipped),
            ), callback)
            self._log(state, channel, power)
            return

        # Signal detected — enter the receive + delay loop
        self._receive_loop(channel, power, callback)

    def _receive_loop(self, channel: Channel, initial_power: float, callback: StatusCallback | None) -> None:
        """Hold on an active channel with proper Uniden-style delay timer.

        Uniden BCD536HP behavior:
          - While signal is present: show RECEIVING_CALL
          - When signal drops: start delay countdown (default 2 s)
          - Signal returns before delay expires: reset countdown, back to RECEIVING_CALL
          - Delay expires or timeout hit: move to next channel
        """
        power = initial_power
        signal_start = time.monotonic()
        delay_start: float | None = None
        delay_seconds = max(0.0, channel.delay_seconds)
        call_logged = False

        while self.running:
            # Check if user skipped this channel mid-receive
            if channel.id in self._temporarily_skipped:
                break

            if power >= self.signal_threshold:
                # Log the call once at start
                if not call_logged:
                    self._call_log.append({
                        "id": str(uuid.uuid4())[:8],
                        "channel_id": channel.id,
                        "name": channel.name,
                        "system": channel.system,
                        "service_type": channel.service_type,
                        "frequency_hz": channel.frequency_hz,
                        "peak_power": round(power, 1),
                        "time": datetime.now(timezone.utc).isoformat(),
                    })
                    call_logged = True

                # Signal is present — cancel any delay countdown
                delay_start = None
                state = ScannerState.MUTED if self.muted else ScannerState.RECEIVING_CALL
                message = "Receiving" if not self.muted else "Muted"
                self._publish(ScannerStatus(
                    state=state,
                    message=message,
                    active_channel=channel,
                    signal_power=power,
                    signal_threshold=self.signal_threshold,
                    gain_db=self.status.gain_db,
                    simulated=self.simulated,
                    held=bool(self._held_channel_id),
                    channels_scanned=self._channels_scanned,
                    skipped_count=len(self._temporarily_skipped),
                ), callback)
                self._log(state, channel, power)

                # Timeout: force resume even if signal is still up (prevents lockup)
                if self.timeout_seconds > 0 and (time.monotonic() - signal_start) > self.timeout_seconds:
                    break

            else:
                # Signal dropped
                if delay_start is None:
                    delay_start = time.monotonic()
                    if delay_seconds <= 0:
                        break  # 0-second delay = leave immediately

                elapsed = time.monotonic() - delay_start
                if elapsed >= delay_seconds:
                    break  # delay expired, move to next channel

                # Still in delay window — show countdown
                remaining = delay_seconds - elapsed
                self._publish(ScannerStatus(
                    state=ScannerState.SCANNING,
                    message=f"Signal ended — resuming in {remaining:.0f}s",
                    active_channel=channel,
                    signal_power=power,
                    signal_threshold=self.signal_threshold,
                    gain_db=self.status.gain_db,
                    simulated=self.simulated,
                    held=bool(self._held_channel_id),
                    in_delay=True,
                    delay_remaining=remaining,
                    channels_scanned=self._channels_scanned,
                    skipped_count=len(self._temporarily_skipped),
                ), callback)

            time.sleep(_POLL_INTERVAL)
            power = self.device.read_power()

    def _publish_unavailable(self, channel: Channel, callback: StatusCallback | None) -> None:
        self._publish(ScannerStatus(
            state=ScannerState.UNAVAILABLE,
            message=f"{channel.name} — encrypted, skipping",
            active_channel=channel,
            signal_threshold=self.signal_threshold,
            gain_db=self.status.gain_db,
            simulated=self.simulated,
            held=bool(self._held_channel_id),
            skipped_count=len(self._temporarily_skipped),
        ), callback)

    def _publish(self, status: ScannerStatus, callback: StatusCallback | None) -> None:
        self.status = status
        if callback:
            callback(status)

    def _log(self, state: ScannerState, channel: Channel, power: float) -> None:
        print(
            f"[TriCore] {state.value:18} "
            f"{channel.name:30} "
            f"{channel.frequency_hz / 1_000_000:.5f} MHz  "
            f"power={power:+.1f} dB  "
            f"gain={'auto' if self.status.gain_db is None else self.status.gain_db}"
        )
