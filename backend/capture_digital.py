"""TriCore Scanner - P25 digital channel capture and data logger.

Tunes to a digital frequency (default: GATRRS 852.800 MHz P25 control channel),
records audio to WAV, and logs per-chunk signal statistics to CSV.

Usage:
    python capture_digital.py                          # GATRRS 852.800 MHz, 60s
    python capture_digital.py --freq 852.725 --dur 120 # different CC, 2 min
    python capture_digital.py --freq 162.550 --dur 30  # NOAA weather
    python capture_digital.py --no-audio               # log only, no playback
"""

import argparse
import csv
import json
import math
import socket
import struct
import subprocess
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import sounddevice as sd

from windows_rtlsdr_tools import find_tool as _find_tool
_rtl_fm_path = _find_tool("rtl_fm.exe")
RTL_FM = str(_rtl_fm_path) if _rtl_fm_path else r"C:\Program Files\PothosSDR\bin\rtl_fm.exe"
AUDIO_RATE = 48_000
CHUNK_BYTES = 4_096   # 2048 int16 samples
M_AUDIO     = 9

DATA_DIR = Path(__file__).parent.parent / "data" / "captures"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Known frequency to system metadata map
FREQ_META = {
    852.800:  {"system": "GATRRS", "type": "P25 Phase II", "role": "control_channel", "site": "Austin TX", "wacn": "BEE09", "system_id": "13E"},
    852.725:  {"system": "GATRRS", "type": "P25 Phase II", "role": "control_channel", "site": "Austin TX", "wacn": "BEE09", "system_id": "13E"},
    851.1375: {"system": "GATRRS", "type": "P25 Phase II", "role": "control_channel", "site": "Austin TX", "wacn": "BEE09", "system_id": "13E"},
    769.21875:{"system": "GATRRS", "type": "P25 Phase II", "role": "control_channel", "site": "Austin TX", "wacn": "BEE09", "system_id": "13E"},
    769.45625:{"system": "GATRRS", "type": "P25 Phase II", "role": "control_channel", "site": "Austin TX", "wacn": "BEE09", "system_id": "13E"},
    162.550:  {"system": "NOAA Weather Radio", "type": "NFM conventional", "role": "primary", "site": "Austin TX", "wacn": None, "system_id": None},
    162.400:  {"system": "NOAA Weather Radio", "type": "NFM conventional", "role": "alternate", "site": "Austin TX", "wacn": None, "system_id": None},
    154.175:  {"system": "Austin Fire & EMS",  "type": "NFM conventional", "role": "fire_dispatch", "site": "Austin TX", "wacn": None, "system_id": None},
}


def rms_db(raw: bytes) -> float:
    s = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return 20.0 * math.log10(float(np.sqrt(np.mean(s**2))) + 1e-12)


def cv_linear(rms_list: list) -> float:
    arr = np.array(rms_list)
    linear = 10.0 ** (arr / 20.0)
    return float(linear.std() / (linear.mean() + 1e-9))


def classify_p25(mean_db: float, cv: float) -> str:
    if mean_db > -13 and cv > 0.12:
        return "P25-BURST"
    if mean_db > -13:
        return "CARRIER"
    if cv > 0.08 and mean_db > -30:
        return "DATA"
    if mean_db > -30:
        return "QUIET-CARRIER"
    return "NOISE"


def capture(freq_mhz: float, duration: float, gain: float,
            device: int, play_audio: bool) -> dict:

    freq_hz = int(freq_mhz * 1_000_000)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    utc_start = datetime.now(timezone.utc).isoformat()
    freq_tag = f"{freq_mhz:.4f}".replace(".", "_")

    wav_path  = DATA_DIR / f"{ts}_{freq_tag}MHz.wav"
    csv_path  = DATA_DIR / f"{ts}_{freq_tag}MHz_stats.csv"
    meta_path = DATA_DIR / f"{ts}_{freq_tag}MHz_meta.json"

    cmd = [RTL_FM, "-f", str(freq_hz), "-M", "fm",
           "-s", "200000", "-r", str(AUDIO_RATE), "-g", str(gain), "-"]

    print(f"\n  GATRRS P25 Capture")
    print(f"  Frequency : {freq_mhz:.4f} MHz")
    print(f"  Duration  : {duration:.0f}s")
    print(f"  WAV file  : {wav_path.name}")
    print(f"  CSV file  : {csv_path.name}")
    print(f"  Audio out : {'Device ' + str(device) if play_audio else 'disabled'}")
    print(f"  {'-'*52}")

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    start = time.monotonic()
    rms_history: list = []
    peak_db = -99.0
    burst_count = 0
    chunk_index = 0

    wav_file = wave.open(str(wav_path), "wb")
    wav_file.setnchannels(1)
    wav_file.setsampwidth(2)
    wav_file.setframerate(AUDIO_RATE)

    csv_file = open(csv_path, "w", newline="")
    writer = csv.writer(csv_file)
    writer.writerow(["time_s", "chunk", "rms_db", "peak_db_so_far",
                     "cv_last20", "label", "burst_count"])

    try:
        stream_ctx = sd.RawOutputStream(
            samplerate=AUDIO_RATE, channels=1, dtype="int16",
            device=device, blocksize=CHUNK_BYTES // 2
        ) if play_audio else None

        def run():
            nonlocal peak_db, burst_count, chunk_index
            while True:
                elapsed = time.monotonic() - start
                if elapsed >= duration:
                    break
                raw = proc.stdout.read(CHUNK_BYTES)
                if not raw:
                    break

                if play_audio and stream_ctx:
                    stream_ctx.write(raw)

                wav_file.writeframes(raw)

                db = rms_db(raw)
                peak_db = max(peak_db, db)
                rms_history.append(db)
                chunk_index += 1

                cv = cv_linear(rms_history[-20:]) if len(rms_history) >= 4 else 0.0
                mean_db = float(np.mean(rms_history[-20:])) if rms_history else db
                label = classify_p25(mean_db, cv)

                if label == "P25-BURST":
                    burst_count += 1

                writer.writerow([
                    f"{elapsed:.3f}", chunk_index,
                    f"{db:.2f}", f"{peak_db:.2f}",
                    f"{cv:.4f}", label, burst_count
                ])

                if chunk_index % 8 == 0:
                    bar_pct = max(0, min(100, int((db + 30) * 2.5)))
                    bar = "#" * (bar_pct // 4) + "." * (25 - bar_pct // 4)
                    print(f"\r  [{bar}] {db:+.1f}dB  {label:<14}  bursts:{burst_count:4d}  {elapsed:.0f}/{duration:.0f}s  ",
                          end="", flush=True)

        if play_audio and stream_ctx:
            with stream_ctx:
                run()
        else:
            run()

    except KeyboardInterrupt:
        print("\n  Stopped by user.")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
        wav_file.close()
        csv_file.close()

    elapsed_total = time.monotonic() - start
    cv_overall = cv_linear(rms_history) if len(rms_history) >= 4 else 0.0
    mean_overall = float(np.mean(rms_history)) if rms_history else -99.0

    print(f"\n\n  {'-'*52}")
    print(f"  Capture complete  ({elapsed_total:.1f}s  |  {chunk_index} chunks)")
    print(f"  Peak dB    : {peak_db:+.1f}")
    print(f"  Mean dB    : {mean_overall:+.1f}")
    print(f"  CV overall : {cv_overall:.4f}")
    print(f"  P25 bursts : {burst_count}")
    print(f"  WAV saved  : {wav_path}")
    print(f"  CSV saved  : {csv_path}")

    sys_meta = FREQ_META.get(freq_mhz, {})
    audio_dev = sd.query_devices(device)

    metadata = {
        "capture": {
            "timestamp_utc":  utc_start,
            "timestamp_local": ts,
            "host":            socket.gethostname(),
            "duration_s":      round(elapsed_total, 3),
            "chunks_recorded": chunk_index,
        },
        "frequency": {
            "freq_mhz":    freq_mhz,
            "freq_hz":     freq_hz,
            "modulation":  "fm",
            "sample_rate": 200000,
            "audio_rate":  AUDIO_RATE,
            "gain_db":     gain,
        },
        "system": {
            "name":       sys_meta.get("system", "Unknown"),
            "type":       sys_meta.get("type", "unknown"),
            "role":       sys_meta.get("role", "unknown"),
            "site":       sys_meta.get("site", ""),
            "wacn":       sys_meta.get("wacn"),
            "system_id":  sys_meta.get("system_id"),
        },
        "hardware": {
            "dongle":    "Realtek RTL2838UHIDIR",
            "tuner":     "Rafael Micro R820T/2",
            "rtl_fm":    RTL_FM,
            "audio_device_index": device,
            "audio_device_name":  audio_dev["name"],
        },
        "signal": {
            "peak_db":     round(peak_db, 1),
            "mean_db":     round(mean_overall, 1),
            "cv_overall":  round(cv_overall, 4),
            "burst_count": burst_count,
            "audio_played": play_audio,
        },
        "files": {
            "wav":  wav_path.name,
            "csv":  csv_path.name,
            "meta": meta_path.name,
        },
    }

    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"  JSON meta  : {meta_path}")

    return {
        "freq_mhz":    freq_mhz,
        "duration_s":  elapsed_total,
        "chunks":      chunk_index,
        "peak_db":     round(peak_db, 1),
        "mean_db":     round(mean_overall, 1),
        "cv":          round(cv_overall, 4),
        "burst_count": burst_count,
        "wav_path":    str(wav_path),
        "csv_path":    str(csv_path),
        "meta_path":   str(meta_path),
    }


def main():
    ap = argparse.ArgumentParser(description="TriCore - P25 digital capture + data logger")
    ap.add_argument("--freq",     type=float, default=852.800, help="Frequency MHz [default: 852.800]")
    ap.add_argument("--dur",      type=float, default=60.0,    help="Capture duration seconds [default: 60]")
    ap.add_argument("--gain",     type=float, default=40.2)
    ap.add_argument("--device",   type=int,   default=M_AUDIO)
    ap.add_argument("--no-audio", action="store_true",         help="Disable audio playback (log only)")
    args = ap.parse_args()

    capture(
        freq_mhz=args.freq,
        duration=args.dur,
        gain=args.gain,
        device=args.device,
        play_audio=not args.no_audio,
    )


if __name__ == "__main__":
    main()
