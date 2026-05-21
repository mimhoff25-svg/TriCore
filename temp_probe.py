import sys
import os
import wave
import io
import numpy as np
from fastapi.testclient import TestClient

# Adjust path to import backend
sys.path.append(os.getcwd())

from backend.app import app
from backend.api.shared import scanner_core

client = TestClient(app)

channels = [
    ("NOAA", 162550000, "nfm"),
    ("NOAA", 162400000, "nfm"),
    ("ABIA Tower", 120500000, "am"),
    ("ABIA Ground", 121900000, "am"),
]

voice_channels = []

for label, freq, mod in channels:
    try:
        # Some setup might be needed if manual_tune isn't enough to initialize the device, 
        # but let's follow the instructions.
        scanner_core.manual_tune(frequency_hz=freq, modulation=mod, name=label)
        
        response = client.get("/api/audio/live", params={
            "frequency_hz": freq,
            "modulation": mod,
            "squelch_db": -68
        })
        
        if response.status_code != 200:
            detail = response.json().get("detail", "No detail") if response.headers.get("content-type") == "application/json" else response.text[:50]
            print(f"{label} | {response.status_code} | {detail}")
            continue
            
        # Parse WAV
        try:
            with wave.open(io.BytesIO(response.content), "rb") as wav:
                params = wav.getparams()
                frames = wav.readframes(params.nframes)
                audio_data = np.frombuffer(frames, dtype=np.int16)
                
            if len(audio_data) == 0:
                print(f"{label} | 200 | rms=0 | zcr=0 | class=silence-like")
                continue

            # Compute RMS
            rms = np.sqrt(np.mean(audio_data.astype(np.float64)**2))
            
            # Compute Zero Crossing Rate
            zero_crossings = np.where(np.diff(np.signbit(audio_data)))[0]
            zcr = len(zero_crossings) / len(audio_data)
            
            classification = "possible voice-like"
            if rms < 120:
                classification = "silence-like"
            elif zcr > 0.30:
                classification = "noise-like"
            else:
                voice_channels.append(label)
                
            print(f"{label} | 200 | rms={rms:.2f} | zcr={zcr:.4f} | class={classification}")
            
        except Exception as e:
            print(f"{label} | 200 | error parsing wav: {e}")

    except Exception as e:
        print(f"{label} | error | {e}")

voice_detected = "yes" if voice_channels else "no"
print(f"VOICE_DETECTED={voice_detected}")
if voice_channels:
    print(f"Channels: {', '.join(voice_channels)}")
