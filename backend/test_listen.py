"""TriCore Scanner — RTL-SDR audio listener and voice detection test.

Uses rtl_fm.exe (PothosSDR) for tuning and demodulation.
Uses sounddevice for real-time audio playback through M-Audio M-Track Solo (device 9).

Voice detection: uses amplitude VARIANCE (not just RMS level) to distinguish
real voice/data from the SDR noise floor. Pure noise has near-constant RMS;
voice and data have high chunk-to-chunk variation.

Usage:
    python test_listen.py --freq 162.550              # NOAA weather voice (NFM)
    python test_listen.py --freq 852.800 --trunked    # GATRRS P25 control channel
    python test_listen.py --freq 98.1 --mode wbfm     # FM radio
    python test_listen.py --scan                      # scan all channels
    python test_listen.py --scan --voice-only         # only report channels with voice/data
    python test_listen.py --devices                   # list audio devices
"""

import argparse
import math
import subprocess
import sys
import time

import numpy as np
import sounddevice as sd

# ── Hardware paths ────────────────────────────────────────────────────────────

from windows_rtlsdr_tools import find_tool as _find_tool
_rtl_fm = _find_tool("rtl_fm.exe")
RTL_FM = str(_rtl_fm) if _rtl_fm else r"C:\Program Files\PothosSDR\bin\rtl_fm.exe"

# ── Audio settings ────────────────────────────────────────────────────────────

AUDIO_RATE  = 48_000   # Hz
CHUNK_BYTES = 4_096    # 2048 int16 samples per chunk
M_AUDIO     = 9        # M-Audio M-Track Solo and Duo — default output device

# ── Test frequency list ───────────────────────────────────────────────────────

TEST_FREQS = [
    # --- Conventional analog (NFM) — voice directly audible ---
    {"name": "NOAA Weather Primary",    "freq_mhz": 162.550,  "mode": "fm",   "trunked": False, "group": "Weather"},
    {"name": "NOAA Weather Alt",        "freq_mhz": 162.400,  "mode": "fm",   "trunked": False, "group": "Weather"},
    {"name": "AFD Fire Dispatch",       "freq_mhz": 154.175,  "mode": "fm",   "trunked": False, "group": "Austin Fire & EMS"},
    {"name": "Austin EMS City",         "freq_mhz": 155.325,  "mode": "fm",   "trunked": False, "group": "Austin Fire & EMS"},
    {"name": "Austin EMS Dispatch",     "freq_mhz": 462.975,  "mode": "fm",   "trunked": False, "group": "Austin Fire & EMS"},
    {"name": "AFD Firecom West",        "freq_mhz": 453.775,  "mode": "fm",   "trunked": False, "group": "Austin Fire & EMS"},
    {"name": "AFD Firecom North",       "freq_mhz": 453.150,  "mode": "fm",   "trunked": False, "group": "Austin Fire & EMS"},
    {"name": "AFD Alarm Dispatch",      "freq_mhz": 453.900,  "mode": "fm",   "trunked": False, "group": "Austin Fire & EMS"},
    {"name": "TX Fire Mutual Aid",      "freq_mhz": 154.280,  "mode": "fm",   "trunked": False, "group": "Travis County"},
    {"name": "TX EMS Mutual Aid",       "freq_mhz": 155.340,  "mode": "fm",   "trunked": False, "group": "Travis County"},
    {"name": "VTAC 1 VHF Interop",     "freq_mhz": 155.7525, "mode": "fm",   "trunked": False, "group": "Travis County"},
    {"name": "UTAC 1 UHF Interop",     "freq_mhz": 453.2125, "mode": "fm",   "trunked": False, "group": "Travis County"},
    # --- GATRRS P25 Phase II trunked control channels ---
    # Tuning here gives P25 digital data bursts (proves reception).
    # Decoding voice requires SDRTrunk (Phase 6 goal).
    {"name": "GATRRS CC 852.800",       "freq_mhz": 852.800,  "mode": "fm",   "trunked": True,  "group": "GATRRS P25 Trunked"},
    {"name": "GATRRS CC 852.725",       "freq_mhz": 852.725,  "mode": "fm",   "trunked": True,  "group": "GATRRS P25 Trunked"},
    {"name": "GATRRS CC 851.1375",      "freq_mhz": 851.1375, "mode": "fm",   "trunked": True,  "group": "GATRRS P25 Trunked"},
    {"name": "GATRRS CC 769.2188",      "freq_mhz": 769.21875,"mode": "fm",   "trunked": True,  "group": "GATRRS P25 Trunked"},
    {"name": "GATRRS CC 769.4563",      "freq_mhz": 769.45625,"mode": "fm",   "trunked": True,  "group": "GATRRS P25 Trunked"},
    # --- FM broadcast (wideband FM) — always on, good baseline ---
    {"name": "KUT 90.5 NPR",            "freq_mhz": 90.5,     "mode": "wbfm", "trunked": False, "group": "Austin FM Radio"},
    {"name": "KLBJ 93.7 Classic Rock",  "freq_mhz": 93.7,     "mode": "wbfm", "trunked": False, "group": "Austin FM Radio"},
    {"name": "KVET 98.1 Country",       "freq_mhz": 98.1,     "mode": "wbfm", "trunked": False, "group": "Austin FM Radio"},
    {"name": "KUTX 98.9 UT Music",      "freq_mhz": 98.9,     "mode": "wbfm", "trunked": False, "group": "Austin FM Radio"},
    {"name": "KROX 101.5 Alt Rock",     "freq_mhz": 101.5,    "mode": "wbfm", "trunked": False, "group": "Austin FM Radio"},
]

# ── Signal analysis ───────────────────────────────────────────────────────────

def rms_db(raw: bytes) -> float:
    s = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return 20.0 * math.log10(float(np.sqrt(np.mean(s**2))) + 1e-12)


def power_bar(db: float, width: int = 22) -> str:
    pct = max(0.0, min(1.0, (db + 60.0) / 60.0))
    n = int(pct * width)
    return f"[{'#'*n}{'.'*(width-n)}] {db:+.1f}dB"


def classify(rms_list: list[float], trunked: bool) -> tuple[str, float]:
    """Return (label, confidence%) based on amplitude variance over a dwell window.

    Voice/data: chunk-to-chunk RMS varies a lot (speech has loud/quiet parts).
    Pure noise: RMS is nearly constant regardless of absolute level.
    P25 trunked control channel: rhythmic bursting, moderate variance.
    """
    if len(rms_list) < 4:
        return "unknown", 0.0

    arr = np.array(rms_list)
    mean_db = float(arr.mean())
    std_db  = float(arr.std())

    # Coefficient of variation in linear power (not dB) — more stable metric
    linear = 10.0 ** (arr / 20.0)
    cv = float(linear.std() / (linear.mean() + 1e-9))

    if trunked:
        # P25 control channel: rhythmic bursts give moderate CV + high mean
        if mean_db > -30 and cv > 0.08:
            return "P25 DATA", min(99, int(cv * 300))
        if mean_db > -30:
            return "carrier", 50
        return "quiet", 0

    # Conventional NFM
    if cv > 0.35 and mean_db > -35:
        return "VOICE", min(99, int(cv * 150))
    if cv > 0.15 and mean_db > -35:
        return "data/tone", min(99, int(cv * 200))
    if mean_db > -30:
        return "carrier", 40
    return "quiet", 0


# ── Core listen function ──────────────────────────────────────────────────────

def listen(freq_mhz: float, mode: str = "fm", gain: float = 40.2,
           duration: float | None = None, device: int = M_AUDIO,
           trunked: bool = False, quiet: bool = False) -> dict:

    freq_hz = int(freq_mhz * 1_000_000)
    sr = "250000" if mode == "wbfm" else "200000"

    cmd = [RTL_FM, "-f", str(freq_hz), "-M", mode,
           "-s", sr, "-r", str(AUDIO_RATE), "-g", str(gain), "-"]

    if not quiet:
        tag = "[TRUNKED]" if trunked else "[CONV]   "
        dur_label = f"{duration:.0f}s" if duration else "Ctrl+C"
        print(f"\n  {tag} {freq_mhz:.4f} MHz  mode={mode}  gain={gain}dB  [{dur_label}]")
        if trunked:
            print("           Trunked CC: expect P25 data bursts, not voice audio.")
            print("           Voice decode requires SDRTrunk (Phase 6).")

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    start = time.monotonic()
    rms_history: list[float] = []
    peak_db = -99.0

    try:
        with sd.RawOutputStream(samplerate=AUDIO_RATE, channels=1,
                                dtype="int16", device=device,
                                blocksize=CHUNK_BYTES // 2) as stream:
            while True:
                if duration and (time.monotonic() - start) >= duration:
                    break
                raw = proc.stdout.read(CHUNK_BYTES)
                if not raw:
                    break
                stream.write(raw)

                db = rms_db(raw)
                peak_db = max(peak_db, db)
                rms_history.append(db)

                if not quiet and len(rms_history) % 4 == 0:
                    label, conf = classify(rms_history[-20:], trunked)
                    elapsed = time.monotonic() - start
                    bar = power_bar(db)
                    pct_str = f"  [{label} {conf}%]" if conf > 0 else f"  [{label}]"
                    sfx = f"  {elapsed:.0f}s" if duration else ""
                    print(f"\r  {bar}{pct_str}{sfx}           ", end="", flush=True)

    except KeyboardInterrupt:
        if not quiet:
            print("\n  Stopped.")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()

    if not quiet:
        print()

    label, conf = classify(rms_history, trunked)
    return {
        "freq_mhz": freq_mhz,
        "mode":     mode,
        "trunked":  trunked,
        "peak_db":  round(peak_db, 1),
        "label":    label,
        "conf":     conf,
        "active":   label not in ("quiet", "unknown"),
    }


# ── Scan mode ─────────────────────────────────────────────────────────────────

def scan_all(dwell: float, gain: float, device: int, voice_only: bool) -> None:
    print(f"\n{'='*68}")
    print(f"  TriCore Scanner — voice & data scan")
    print(f"  Gain {gain}dB  |  Dwell {dwell}s  |  Device {device} (M-Audio)")
    print(f"  Voice detection: amplitude variance method")
    print(f"{'='*68}")

    last_group = None
    results = []

    for entry in TEST_FREQS:
        g = entry["group"]
        if g != last_group:
            print(f"\n  ── {g} ──")
            last_group = g

        name_col = f"{entry['freq_mhz']:.4f} MHz  {entry['name']:<32}"
        tag = "[T]" if entry["trunked"] else "   "
        print(f"  {tag} {name_col}", end="", flush=True)

        try:
            r = listen(entry["freq_mhz"], entry["mode"], gain=gain,
                       duration=dwell, device=device,
                       trunked=entry["trunked"], quiet=True)
            stars = ">>>" if r["active"] else "   "
            print(f"  {stars} {r['label']:<12} peak {r['peak_db']:+.1f}dB  conf {r['conf']}%")
            results.append({**entry, **r})
        except Exception as exc:
            print(f"  ERROR: {exc}")

    # Summary
    active = [r for r in results if r["active"]]
    voice  = [r for r in active if "VOICE" in r["label"]]
    p25    = [r for r in active if "P25" in r["label"]]

    print(f"\n{'='*68}")
    print(f"  Scan complete  |  {len(active)}/{len(results)} active")
    if voice:
        print(f"\n  VOICE detected on:")
        for r in voice:
            print(f"    {r['freq_mhz']:.4f} MHz  {r['name']}  (peak {r['peak_db']:+.1f}dB)")
    if p25:
        print(f"\n  P25 data detected on:")
        for r in p25:
            print(f"    {r['freq_mhz']:.4f} MHz  {r['name']}")
    carriers = [r for r in active if r["label"] in ("carrier", "data/tone")]
    if carriers:
        print(f"\n  Carrier/data on:")
        for r in carriers:
            print(f"    {r['freq_mhz']:.4f} MHz  {r['name']}  ({r['label']})")
    print(f"{'='*68}\n")

    # Auto-tune to voice channels
    if voice:
        print("  Auto-tuning to first voice channel...")
        v = voice[0]
        listen(v["freq_mhz"], v["mode"], gain=gain, device=device,
               trunked=v["trunked"])


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(prog="test_listen",
        description="TriCore Scanner — RTL-SDR voice detection test")
    ap.add_argument("--freq",       type=float,           help="Frequency in MHz")
    ap.add_argument("--mode",       default="fm",         help="fm or wbfm [default: fm]")
    ap.add_argument("--gain",       type=float, default=40.2)
    ap.add_argument("--dwell",      type=float, default=8.0, help="Seconds per channel in scan [default: 8]")
    ap.add_argument("--device",     type=int,   default=M_AUDIO)
    ap.add_argument("--trunked",    action="store_true",  help="Mark as trunked control channel")
    ap.add_argument("--scan",       action="store_true",  help="Scan all test frequencies")
    ap.add_argument("--voice-only", action="store_true",  help="Only report voice/data channels after scan")
    ap.add_argument("--devices",    action="store_true",  help="List audio output devices")
    args = ap.parse_args()

    if args.devices:
        print("\nAudio output devices:")
        for i, d in enumerate(sd.query_devices()):
            if d["max_output_channels"] > 0:
                m = " *" if i == sd.default.device[1] else "  "
                print(f"{m} [{i:2d}] {d['name']}")
        return

    print(f"\n  TriCore Scanner — RTL-SDR Audio Test")
    print(f"  rtl_fm : {RTL_FM}")
    print(f"  Device : {args.device}")

    if args.scan:
        scan_all(dwell=args.dwell, gain=args.gain,
                 device=args.device, voice_only=args.voice_only)
    elif args.freq:
        listen(args.freq, mode=args.mode, gain=args.gain,
               device=args.device, trunked=args.trunked)
    else:
        ap.print_help()
        print("""
  Quick start:
    python test_listen.py --scan                       # scan + auto-tune to voice
    python test_listen.py --freq 162.550               # NOAA weather
    python test_listen.py --freq 154.175               # AFD Fire Dispatch
    python test_listen.py --freq 852.800 --trunked     # GATRRS P25 control
    python test_listen.py --freq 98.1 --mode wbfm      # KVET FM Country
""")


if __name__ == "__main__":
    main()
