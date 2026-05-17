"""Thin wrapper around pyrtlsdr for basic RTL-SDR tuning and power checks.

This is not a full demodulator yet. For the Phase 1 proof-of-concept, we tune
the dongle, read a small block of IQ samples, and estimate signal power. That is
enough to prove device access and scan/stop behavior in the TriCore UI.
"""

from __future__ import annotations

import math
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np


RTLSDR_DLL_DIRS = [
    Path(__file__).resolve().parents[1] / "tools" / "tricore-sdr" / "rtl-sdr",
    Path(__file__).resolve().parents[1] / "tools" / "tricore-sdr" / "dsdplus",
    Path(__file__).resolve().parents[3] / "sdrpp_windows_x64",
    Path(__file__).resolve().parents[3] / "sdrpp_windows_x64" / "sdrpp_windows_x64",
    Path(__file__).resolve().parents[3] / "sdrpp_windows_x64" / "DSDPlus",
    Path(r"C:\Program Files\PothosSDR\bin"),
    Path(r"C:\rtl-sdr"),
    Path(r"C:\Users\mimho\Downloads\SDRPlusPlus\sdrpp_windows_x64"),
    Path(r"C:\Program Files\rtl-sdr"),
    Path(r"C:\Program Files (x86)\rtl-sdr"),
]
_DLL_DIRECTORY_HANDLES: list[object] = []


def _enable_rtlsdr_dll_paths() -> None:
    """Make locally installed RTL-SDR DLLs visible before pyrtlsdr imports."""

    current_path = os.environ.get("PATH", "")
    path_parts = [part.lower() for part in current_path.split(os.pathsep) if part]

    for dll_dir in RTLSDR_DLL_DIRS:
        if not dll_dir.exists():
            continue

        dll_dir_text = str(dll_dir)
        if dll_dir_text.lower() not in path_parts:
            os.environ["PATH"] = f"{dll_dir_text}{os.pathsep}{os.environ.get('PATH', '')}"
            path_parts.insert(0, dll_dir_text.lower())

        if hasattr(os, "add_dll_directory"):
            try:
                _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(dll_dir_text))
            except OSError:
                pass


_enable_rtlsdr_dll_paths()

try:
    from rtlsdr.rtlsdr import LibUSBError
except Exception:
    LibUSBError = OSError


@dataclass
class SdrSettings:
    """Runtime SDR settings.

    gain_db:
        None means automatic gain. Try values like 0, 9, 19.7, 28, 36.4, or 49.6
        if signals are weak or the scanner never stops.
    """

    sample_rate: int = 1_024_000
    center_frequency_hz: int = 0
    gain_db: float | None = None
    sample_count: int = 16_384


class RtlSdrDevice:
    """Small RTL-SDR adapter used by ConventionalScanner."""

    def __init__(self, settings: SdrSettings | None = None) -> None:
        self.settings = settings or SdrSettings()
        self._sdr = None

    def open(self) -> None:
        """Open the first RTL-SDR dongle.

        Importing pyrtlsdr here lets the rest of the backend start even when the
        dependency or DLLs are missing. That gives the UI a useful error state.
        """

        _enable_rtlsdr_dll_paths()
        try:
            from rtlsdr import RtlSdr
        except ImportError as exc:
            raise RuntimeError(
                "RTL-SDR support could not load librtlsdr. Install PothosSDR or add "
                "rtlsdr.dll to PATH, then restart TriCore."
            ) from exc

        try:
            self._sdr = RtlSdr()
        except LibUSBError as exc:
            if "ACCESS" in str(exc).upper() or "-3" in str(exc):
                raise RuntimeError(
                    "RTL-SDR is busy or access is denied. Close SDRTrunk, SDR++, TriCore RTL mode, "
                    "or any other app using the dongle, then try again."
                ) from exc
            raise
        self._sdr.sample_rate = self.settings.sample_rate
        self.set_gain(self.settings.gain_db)

    def close(self) -> None:
        """Release the dongle if it is open."""

        if self._sdr is not None:
            self._sdr.close()
            self._sdr = None

    def set_gain(self, gain_db: float | None) -> None:
        """Set manual gain, or automatic gain when gain_db is None."""

        self.settings.gain_db = gain_db
        if self._sdr is None:
            return

        if gain_db is None:
            self._sdr.gain = "auto"
        else:
            self._sdr.gain = gain_db

    def tune(self, frequency_hz: int) -> None:
        """Tune the dongle to a center frequency in Hz."""

        if self._sdr is None:
            raise RuntimeError("RTL-SDR device is not open")

        self.settings.center_frequency_hz = frequency_hz
        self._sdr.center_freq = frequency_hz

    def read_power(self) -> float:
        """Read IQ samples and return a simple relative power level in dB."""

        if self._sdr is None:
            raise RuntimeError("RTL-SDR device is not open")

        samples = self._sdr.read_samples(self.settings.sample_count)
        mean_power = float(np.mean(np.abs(samples) ** 2))
        return 10.0 * math.log10(mean_power + 1e-12)


class SimulatedSdrDevice:
    """Receiver simulator for UI work when no RTL-SDR dongle is connected.

    It behaves like a real device from the scanner's point of view: open, tune,
    set gain, and read power. The power level rises on a repeating pattern so
    the dashboard shows realistic scan/receive movement during development.
    """

    def __init__(self, settings: SdrSettings | None = None) -> None:
        self.settings = settings or SdrSettings()
        self._opened = False
        self._scan_count = 0
        self._active_until = 0.0

    def open(self) -> None:
        """Start the simulated receiver."""

        self._opened = True

    def close(self) -> None:
        """Stop the simulated receiver."""

        self._opened = False

    def set_gain(self, gain_db: float | None) -> None:
        """Store gain so the UI can still show the selected value."""

        self.settings.gain_db = gain_db

    def tune(self, frequency_hz: int) -> None:
        """Tune to a pretend frequency."""

        if not self._opened:
            raise RuntimeError("Simulated SDR device is not open")

        self.settings.center_frequency_hz = frequency_hz
        self._scan_count += 1

        # Every few tuned channels, create a short pretend call.
        if self._scan_count % 5 == 0:
            self._active_until = time.monotonic() + random.uniform(2.0, 4.0)

    def read_power(self) -> float:
        """Return a fake relative power level in dB."""

        if not self._opened:
            raise RuntimeError("Simulated SDR device is not open")

        gain_boost = 0.0 if self.settings.gain_db is None else min(self.settings.gain_db / 20.0, 2.5)
        if time.monotonic() < self._active_until:
            return random.uniform(-26.0, -15.0) + gain_boost

        return random.uniform(-62.0, -43.0) + gain_boost
