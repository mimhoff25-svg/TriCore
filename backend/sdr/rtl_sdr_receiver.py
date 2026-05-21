from __future__ import annotations

import math
import os
import time
from typing import Any, Optional

from ..decoder_runtime import probe_rtl_sdr_device
from ..radio.models import ReceiverStatus, SignalReading
from ..windows_rtlsdr_tools import rtl_sdr_library_dirs
from .base_receiver import BaseReceiver
from .signal_meter import squelch_open


DEFAULT_SAMPLE_RATE_HZ = 1_024_000
DEFAULT_READ_SIZE = 16_384
OPEN_RETRY_COOLDOWN_SECONDS = 5.0
ACCESS_DENIED_RETRY_COOLDOWN_SECONDS = 15.0
MIN_TUNABLE_FREQUENCY_HZ = 24_000_000
MAX_TUNABLE_FREQUENCY_HZ = 1_766_000_000


class RtlSdrReceiver(BaseReceiver):
    def __init__(self, device_index: int = 0, open_device: bool = True) -> None:
        self.device_index = device_index
        self.open_device = open_device
        self.frequency_hz: Optional[int] = None
        self.modulation = "nfm"
        self.gain_db: Optional[float] = None
        self.squelch_db = -65.0
        self.sample_rate_hz = DEFAULT_SAMPLE_RATE_HZ
        self._snapshot = probe_rtl_sdr_device(force=True)
        self._device: Any = None
        self._last_signal_db = -100.0
        self._last_error: Optional[str] = None
        self._library_error: Optional[str] = None
        self._dll_handles: list[Any] = []
        self._searched_library_dirs: list[str] = []
        self._next_open_retry_at = 0.0
        self._prepare_rtl_environment()
        self._rtl_class = self._load_rtl_class() if open_device else None
        if open_device:
            self._open_device()

    @property
    def available(self) -> bool:
        if not self.open_device:
            return bool(self._snapshot.get("available")) and self._last_error is None
        return self._device is not None and self._last_error is None

    @staticmethod
    def supports_frequency(frequency_hz: int) -> bool:
        return MIN_TUNABLE_FREQUENCY_HZ <= int(frequency_hz) <= MAX_TUNABLE_FREQUENCY_HZ

    def tune(self, frequency_hz: int, modulation: str = "nfm") -> ReceiverStatus:
        self.frequency_hz = int(frequency_hz)
        self.modulation = modulation
        if not self.supports_frequency(self.frequency_hz):
            self._last_error = (
                f"RTL-SDR frequency {self.frequency_hz / 1_000_000:.6f} MHz is outside "
                f"the supported tuner range of {MIN_TUNABLE_FREQUENCY_HZ / 1_000_000:.1f}-"
                f"{MAX_TUNABLE_FREQUENCY_HZ / 1_000_000:.0f} MHz."
            )
            return self.status()

        if not self.open_device:
            self._last_error = None
            return self.status()

        if not self._ensure_open():
            return self.status()

        try:
            self._device.center_freq = self.frequency_hz
            self._device.sample_rate = self.sample_rate_hz
            self._apply_gain()
            self._last_error = None
        except Exception as exc:
            self._mark_unavailable(f"RTL-SDR tune failed: {exc}")
        return self.status()

    def set_gain(self, gain_db: Optional[float]) -> ReceiverStatus:
        self.gain_db = gain_db
        if self._device is not None and self._last_error is None:
            self._apply_gain()
        return self.status()

    def set_squelch(self, squelch_db: float) -> ReceiverStatus:
        self.squelch_db = float(squelch_db)
        return self.status()

    def read_signal(self) -> SignalReading:
        if self._device is None or self._last_error is not None:
            return SignalReading(
                frequency_hz=int(self.frequency_hz or 0),
                level_db=-100.0,
                squelch_open=False,
                simulated=False,
            )

        try:
            samples = self._device.read_samples(DEFAULT_READ_SIZE)
            level = self._estimate_rssi_db(samples)
            self._last_signal_db = level
            self._last_error = None
        except Exception as exc:
            self._mark_unavailable(f"RTL-SDR sample read failed: {exc}")
            level = -100.0

        return SignalReading(
            frequency_hz=int(self.frequency_hz or 0),
            level_db=level,
            squelch_open=squelch_open(level, self.squelch_db),
            simulated=False,
        )

    def refresh(self) -> ReceiverStatus:
        self._snapshot = probe_rtl_sdr_device(force=True)
        self._next_open_retry_at = 0.0
        if self.open_device and self._device is None:
            self._open_device()
        return self.status()

    def status(self) -> ReceiverStatus:
        if not self.available:
            message = self._friendly_error()
            return ReceiverStatus(
                mode="rtl_sdr",
                label="RTL-SDR",
                simulated=False,
                available=False,
                demo_available=True,
                rtl_sdr_available=False,
                tuned_frequency_hz=self.frequency_hz,
                gain_db=self.gain_db,
                squelch_db=self.squelch_db,
                signal_level=-100.0,
                message=message,
                error_message=message,
                last_rtl_error=message,
            )

        message = "RTL-SDR receiver connected." if self.open_device else "RTL-SDR tuner detected. External audio tools are available."
        return ReceiverStatus(
            mode="rtl_sdr",
            label="RTL-SDR",
            simulated=False,
            available=True,
            demo_available=True,
            rtl_sdr_available=True,
            tuned_frequency_hz=self.frequency_hz,
            gain_db=self.gain_db,
            squelch_db=self.squelch_db,
            signal_level=self._last_signal_db,
            message=message,
        )

    def close(self) -> None:
        if self._device is None:
            return
        try:
            self._device.close()
        except Exception:
            pass
        finally:
            self._device = None

    def _load_rtl_class(self):
        try:
            from rtlsdr import RtlSdr

            return RtlSdr
        except Exception as exc:
            detail = f"pyrtlsdr is not available or cannot load librtlsdr: {exc}"
            if self._searched_library_dirs:
                searched = ", ".join(self._searched_library_dirs)
                detail = f"{detail}. Searched RTL-SDR library paths: {searched}"
            self._library_error = detail
            return None

    def _prepare_rtl_environment(self) -> None:
        directories = [str(path) for path in rtl_sdr_library_dirs()]
        self._searched_library_dirs = directories
        if not directories:
            return

        existing_path = [item for item in os.environ.get("PATH", "").split(os.pathsep) if item]
        seen = {item.lower() for item in existing_path}
        prepend = [item for item in directories if item.lower() not in seen]
        if prepend:
            os.environ["PATH"] = os.pathsep.join([*prepend, *existing_path])

        if os.name != "nt" or not hasattr(os, "add_dll_directory"):
            return

        for directory in directories:
            try:
                self._dll_handles.append(os.add_dll_directory(directory))
            except (FileNotFoundError, OSError):
                continue

    def _open_device(self) -> bool:
        if self._rtl_class is None:
            self._mark_unavailable(self._library_error or "pyrtlsdr is not available.")
            return False

        try:
            self._device = self._rtl_class(device_index=self.device_index)
            self._device.sample_rate = self.sample_rate_hz
            if self.frequency_hz:
                self._device.center_freq = self.frequency_hz
            self._apply_gain()
            self._last_error = None
            self._next_open_retry_at = 0.0
            return True
        except Exception as exc:
            self._device = None
            probe_message = str(self._snapshot.get("message") or "No RTL-SDR tuner could be opened.")
            failure_message = f"RTL-SDR open failed: {exc}. {probe_message}"
            self._mark_unavailable(failure_message)
            retry_delay = ACCESS_DENIED_RETRY_COOLDOWN_SECONDS if "access denied" in failure_message.lower() else OPEN_RETRY_COOLDOWN_SECONDS
            self._next_open_retry_at = time.monotonic() + retry_delay
            return False

    def _ensure_open(self) -> bool:
        if self._device is not None and self._last_error is None:
            return True
        if time.monotonic() < self._next_open_retry_at:
            return False
        return self._open_device()

    def _apply_gain(self) -> None:
        if self._device is None:
            return
        try:
            if self.gain_db is None:
                manual_gain_toggle = getattr(self._device, "set_manual_gain_enabled", None)
                if callable(manual_gain_toggle):
                    manual_gain_toggle(False)
                self._device.gain = "auto"
            else:
                manual_gain_toggle = getattr(self._device, "set_manual_gain_enabled", None)
                if callable(manual_gain_toggle):
                    manual_gain_toggle(True)
                self._device.gain = float(self.gain_db)
        except Exception as exc:
            self._mark_unavailable(f"RTL-SDR gain failed: {exc}")

    def _estimate_rssi_db(self, samples: Any) -> float:
        try:
            count = len(samples)
        except TypeError:
            return -100.0
        if count == 0:
            return -100.0

        try:
            power = sum(float(abs(sample) ** 2) for sample in samples) / count
        except Exception:
            return -100.0
        if power <= 0:
            return -100.0

        dbfs = 10.0 * math.log10(power)
        # PyRTLSDR returns normalized IQ samples. This is a relative meter, not calibrated dBm.
        return round(max(-100.0, min(0.0, dbfs)), 1)

    def _mark_unavailable(self, message: str) -> None:
        self._last_error = message
        if self._device is not None:
            try:
                self._device.close()
            except Exception:
                pass
            self._device = None

    def _friendly_error(self) -> str:
        if self._last_error:
            return f"RTL-SDR unavailable. {self._last_error}"
        if self._library_error:
            return f"RTL-SDR unavailable. {self._library_error}"
        probe_message = str(self._snapshot.get("message") or "No RTL-SDR tuner detected.")
        return f"RTL-SDR unavailable. {probe_message}"
