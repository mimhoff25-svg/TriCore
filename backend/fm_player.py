"""Live FM broadcast playback through rtl_fm and the system audio output."""

from __future__ import annotations

import math
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import sounddevice as sd

from windows_rtlsdr_tools import find_tool

AUDIO_RATE = 48_000
CHUNK_BYTES = 4_096
DEFAULT_WBFM_GAIN_DB = 28.0
DEFAULT_NFM_GAIN_DB = 36.4
NFM_STARTUP_TIMEOUT_SECONDS = 8.0


@dataclass
class FmPlayerStatus:
    playing: bool = False
    message: str = "FM player stopped"
    station: dict[str, Any] | None = None
    frequency_hz: int | None = None
    tuned_frequency_hz: int | None = None
    frequency_offset_hz: int = 0
    audio_device: int | None = None
    gain_used_db: float | None = None
    peak_db: float = -99.0
    last_db: float = -99.0
    chunks: int = 0
    noise_filter: str = "mono deemphasis + hiss filter"
    started_at: float | None = None


class FmNoiseFilter:
    """Lightweight mono post-filter for rtl_fm broadcast audio."""

    def __init__(self, gate_db: float | None = None) -> None:
        self._dc = 0.0
        self._lowpass = 0.0
        self._gate_db = gate_db
        self._gate_open = False
        # One-pole smoothing around the upper voice/music band to cut hiss.
        cutoff_hz = 11_000.0
        self._alpha = 1.0 - math.exp(-2.0 * math.pi * cutoff_hz / AUDIO_RATE)

    def process(self, raw: bytes) -> bytes:
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if samples.size == 0:
            return raw

        filtered = np.empty_like(samples)
        dc = self._dc
        lowpass = self._lowpass
        alpha = self._alpha
        for index, sample in enumerate(samples):
            dc = (0.999 * dc) + (0.001 * float(sample))
            highpassed = float(sample) - dc
            lowpass += alpha * (highpassed - lowpass)
            filtered[index] = lowpass

        self._dc = dc
        self._lowpass = lowpass

        db = _rms_db_from_samples(filtered)
        if self._gate_db is not None:
            open_db = self._gate_db
            close_db = self._gate_db - 5.0
            if db >= open_db:
                self._gate_open = True
            elif db <= close_db:
                self._gate_open = False
            if not self._gate_open:
                filtered *= 0.0
        elif db < -52.0:
            filtered *= 0.08
        elif db < -44.0:
            filtered *= 0.35

        filtered = np.clip(filtered * 1.15, -0.98, 0.98)
        return (filtered * 32767.0).astype(np.int16).tobytes()


class FmAudioPlayer:
    """Owns one rtl_fm process and one audio output stream."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._proc: subprocess.Popen | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._status = FmPlayerStatus()

    def status(self) -> dict[str, Any]:
        with self._lock:
            data = self._status.__dict__.copy()
        if data["started_at"]:
            data["elapsed_seconds"] = round(time.monotonic() - data["started_at"], 1)
        else:
            data["elapsed_seconds"] = 0.0
        return data

    def play(self, station: dict[str, Any], gain_db: float | None = None, audio_device: int | None = None) -> dict[str, Any]:
        return self.play_channel(
            station,
            mode="wbfm",
            gain_db=gain_db,
            audio_device=audio_device,
            label=f"{station['callsign']} {station['frequency_mhz']:.1f} MHz",
            noise_filter="mono deemphasis + hiss filter",
        )

    def play_channel(
        self,
        channel: dict[str, Any],
        mode: str = "nfm",
        gain_db: float | None = None,
        audio_device: int | None = None,
        label: str | None = None,
        noise_filter: str = "mono narrow FM filter",
    ) -> dict[str, Any]:
        self.stop()

        rtl_fm = find_tool("rtl_fm.exe")
        if rtl_fm is None:
            with self._lock:
                self._status = FmPlayerStatus(
                    playing=False,
                    message="rtl_fm.exe was not found. Install PothosSDR or RTL-SDR tools.",
                    station=channel,
                    frequency_hz=channel["frequency_hz"],
                    audio_device=audio_device,
                )
            return self.status()

        self._stop.clear()
        with self._lock:
            self._status = FmPlayerStatus(
                playing=True,
                message=f"Playing {label or channel.get('name') or channel['frequency_hz']}",
                station=channel,
                frequency_hz=channel["frequency_hz"],
                tuned_frequency_hz=int(channel["frequency_hz"]) + int(channel.get("frequency_offset_hz") or 0),
                frequency_offset_hz=int(channel.get("frequency_offset_hz") or 0),
                audio_device=audio_device,
                gain_used_db=gain_db if gain_db is not None else (DEFAULT_WBFM_GAIN_DB if mode == "wbfm" else DEFAULT_NFM_GAIN_DB),
                noise_filter=noise_filter,
                started_at=time.monotonic(),
            )

        self._thread = threading.Thread(
            target=self._run,
            args=(str(rtl_fm), channel, mode, gain_db, audio_device),
            daemon=True,
        )
        self._thread.start()
        return self.status()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._stop_external_rtl_fm()

        with self._lock:
            previous = self._status
            self._status = FmPlayerStatus(
                playing=False,
                message="FM player stopped",
                station=previous.station,
                frequency_hz=previous.frequency_hz,
                tuned_frequency_hz=previous.tuned_frequency_hz,
                frequency_offset_hz=previous.frequency_offset_hz,
                audio_device=previous.audio_device,
                gain_used_db=previous.gain_used_db,
                peak_db=previous.peak_db,
                last_db=previous.last_db,
                chunks=previous.chunks,
                noise_filter=previous.noise_filter,
            )
        self._proc = None
        return self.status()

    def _stop_external_rtl_fm(self) -> None:
        try:
            subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-Command",
                    "Get-Process rtl_fm -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=6,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

    def _run(
        self,
        rtl_fm: str,
        station: dict[str, Any],
        mode: str,
        gain_db: float | None,
        audio_device: int | None,
    ) -> None:
        offset_hz = int(station.get("frequency_offset_hz") or 0)
        freq_hz = int(station["frequency_hz"]) + offset_hz
        rtl_mode = "wbfm" if mode == "wbfm" else "fm"
        sample_rate = "240000" if mode == "wbfm" else "240000"
        effective_gain = gain_db if gain_db is not None else (DEFAULT_WBFM_GAIN_DB if mode == "wbfm" else DEFAULT_NFM_GAIN_DB)
        cmd = [
            rtl_fm,
            "-f", str(freq_hz),
            "-M", rtl_mode,
            "-s", sample_rate,
            "-r", str(AUDIO_RATE),
        ]
        if mode == "wbfm":
            cmd.extend(["-E", "deemp"])
        else:
            cmd.extend(["-E", "dc", "-l", "120"])
        if effective_gain is not None:
            cmd.extend(["-g", str(effective_gain)])
        cmd.append("-")
        stderr_lines: list[str] = []

        def _drain_stderr(pipe: Any) -> None:
            for line in pipe:
                if len(stderr_lines) > 40:
                    stderr_lines.pop(0)
                stderr_lines.append(line.decode(errors="replace"))

        def _startup_watchdog(proc: subprocess.Popen) -> None:
            time.sleep(NFM_STARTUP_TIMEOUT_SECONDS)
            with self._lock:
                chunks = self._status.chunks
            if mode == "wbfm" or self._stop.is_set() or chunks > 0 or proc.poll() is not None:
                return
            with self._lock:
                self._status.playing = False
                self._status.message = (
                    "Railroad audio did not open. The RTL-SDR is busy, the channel is silent, "
                    "or rtl_fm is blocked before audio output."
                )
            try:
                proc.terminate()
            except OSError:
                pass

        try:
            env = None
            try:
                import os
                tool_dir = str(Path(rtl_fm).parent)
                env = os.environ.copy()
                env["PATH"] = tool_dir + os.pathsep + env.get("PATH", "")
            except OSError:
                env = None
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(Path(rtl_fm).parent),
                env=env,
            )
            stderr_thread = threading.Thread(target=_drain_stderr, args=(self._proc.stderr,), daemon=True)
            stderr_thread.start()
            if mode != "wbfm":
                threading.Thread(target=_startup_watchdog, args=(self._proc,), daemon=True).start()
            noise_filter = FmNoiseFilter(gate_db=-28.0 if mode != "wbfm" else None)

            sd.query_devices(audio_device, "output")
            with sd.RawOutputStream(
                samplerate=AUDIO_RATE,
                channels=1,
                dtype="int16",
                device=audio_device,
                blocksize=CHUNK_BYTES // 2,
            ) as stream:
                while not self._stop.is_set():
                    if self._proc.stdout is None:
                        break
                    raw = self._proc.stdout.read(CHUNK_BYTES)
                    if not raw:
                        break

                    filtered = noise_filter.process(raw)
                    stream.write(filtered)
                    db = _rms_db(filtered)
                    with self._lock:
                        self._status.last_db = db
                        self._status.peak_db = max(self._status.peak_db, db)
                        self._status.chunks += 1

            stderr_thread.join(timeout=1.0)
            stderr = "".join(stderr_lines).strip()

            if not self._stop.is_set():
                with self._lock:
                    self._status.playing = False
                    if mode != "wbfm" and self._status.chunks == 0:
                        self._status.message = (
                            "Railroad audio did not open. The channel may be silent or the RTL-SDR may be busy."
                        )
                    else:
                        self._status.message = stderr or "FM playback ended"
        except Exception as exc:
            with self._lock:
                self._status.playing = False
                self._status.message = f"FM playback failed: {exc}"
        finally:
            proc = self._proc
            if proc and proc.poll() is None:
                proc.terminate()
            self._proc = None


def _rms_db(raw: bytes) -> float:
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return _rms_db_from_samples(samples)


def _rms_db_from_samples(samples: np.ndarray) -> float:
    if samples.size == 0:
        return -99.0
    return round(20.0 * math.log10(float(np.sqrt(np.mean(samples**2))) + 1e-12), 1)
