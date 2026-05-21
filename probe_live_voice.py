from __future__ import annotations
import io
import math
import struct
import wave

from fastapi.testclient import TestClient

from backend.app import app
from backend.api.shared import scanner_core

client = TestClient(app)

targets = [
    ("NOAA 162.550", 162550000, "nfm"),
    ("NOAA 162.400", 162400000, "nfm"),
    ("ABIA Tower", 120500000, "am"),
    ("ABIA Ground", 121900000, "am"),
    ("ABIA ATIS", 128800000, "am"),
]

def analyze_wav(data: bytes):
    with wave.open(io.BytesIO(data), "rb") as wf:
        rate = wf.getframerate()
        frames = wf.readframes(min(wf.getnframes(), rate * 2))
    if len(frames) < 4:
        return 0.0, 0.0, 0.0
    samples = struct.unpack("<" + "h" * (len(frames)//2), frames)
    n = len(samples)
    rms = math.sqrt(sum(s*s for s in samples) / n)
    zc = sum(1 for i in range(1, n) if (samples[i-1] <= 0 < samples[i]) or (samples[i-1] >= 0 > samples[i]))
    zcr = zc / max(1, n - 1)

    win = max(1, int(rate * 0.05))
    w_rms = []
    for i in range(0, n, win):
        seg = samples[i:i+win]
        if not seg:
            continue
        w = math.sqrt(sum(v*v for v in seg) / len(seg))
        w_rms.append(w)
    if len(w_rms) > 1:
        mean = sum(w_rms) / len(w_rms)
        var = sum((v - mean) ** 2 for v in w_rms) / (len(w_rms) - 1)
    else:
        var = 0.0
    return rms, zcr, var

def classify(rms, zcr, var):
    if rms < 120:
        return "silence-like"
    if zcr > 0.30 and var < 2000:
        return "noise-like"
    if 200 <= rms <= 9000 and 0.05 <= zcr <= 0.28 and var >= 2000:
        return "possible voice-like"
    return "mixed/unknown"

voice_hits = []
print("label | status | rms | zcr | var | class")
for label, freq, mod in targets:
    scanner_core.manual_tune(frequency_hz=freq, modulation=mod, name=label)
    resp = client.get("/api/audio/live", params={"frequency_hz": freq, "modulation": mod, "squelch_db": -68})
    if resp.status_code != 200:
        detail = ""
        try:
            detail = str(resp.json().get("detail", ""))
        except Exception:
            detail = resp.text
        print(f"{label} | {resp.status_code} | - | - | - | {detail[:120]}")
        continue

    rms, zcr, var = analyze_wav(resp.content)
    klass = classify(rms, zcr, var)
    if klass == "possible voice-like":
        voice_hits.append(label)
    print(f"{label} | 200 | {rms:.1f} | {zcr:.3f} | {var:.1f} | {klass}")

if voice_hits:
    print("VOICE_DETECTED=yes; channels=" + ", ".join(voice_hits))
else:
    print("VOICE_DETECTED=no; channels=none")
