import sys
import os
import io
import wave
import numpy as np
from fastapi.testclient import TestClient

# Add backend to sys.path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

try:
    from backend.app import app
except ImportError:
    try:
        from app import app
    except ImportError:
        import app

client = TestClient(app)

channels = [
    {"label": "NOAA 162.550", "freq": 162550000, "mod": "nfm"},
    {"label": "NOAA 162.400", "freq": 162400000, "mod": "nfm"},
    {"label": "ABIA Tower", "freq": 120500000, "mod": "am"},
    {"label": "ABIA Ground", "freq": 121900000, "mod": "am"},
    {"label": "ABIA ATIS", "freq": 128800000, "mod": "am"},
]

voice_channels = []

def analyze_audio(data):
    if not data or len(data) < 100:
        return "error", 0, 0, 0, "unknown"
    
    try:
        with wave.open(io.BytesIO(data), 'rb') as wf:
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            n_frames = wf.getnframes()
            
            # Read ~2 seconds
            max_frames = framerate * 2
            frames = wf.readframes(min(n_frames, max_frames))
            
            if sampwidth == 2:
                samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
            else:
                return "unsupported_format", 0, 0, 0, "unknown"
            
            if n_channels > 1:
                samples = samples[::n_channels]
                
            if len(samples) == 0:
                return "empty", 0, 0, 0, "unknown"

            rms = np.sqrt(np.mean(samples**2))
            peak = np.max(np.abs(samples))
            
            # Zero Crossing Rate
            zcr = ((samples[:-1] * samples[1:]) < 0).sum() / len(samples)
            
            # Short-term RMS variance (50ms windows)
            win_size = int(framerate * 0.05)
            if len(samples) > win_size:
                st_rms = []
                for i in range(0, len(samples) - win_size, win_size):
                    win = samples[i:i+win_size]
                    st_rms.append(np.sqrt(np.mean(win**2)))
                variance = np.var(st_rms) if st_rms else 0
            else:
                variance = 0
            
            # Heuristic labeling
            classification = "unknown"
            if rms < 120:
                classification = "silence-like"
            elif zcr > 0.30 and variance < 2000:
                classification = "noise-like"
            elif 200 <= rms <= 9000 and 0.05 <= zcr <= 0.28 and variance >= 2000:
                classification = "possible voice-like"
            else:
                classification = "mixed/unknown"
                
            return "ok", rms, zcr, variance, classification
    except Exception as e:
        return f"error: {str(e)}", 0, 0, 0, "unknown"

print("label | status | rms | zcr | var | class")
for ch in channels:
    # Manual tune
    try:
        tune_resp = client.post("/api/scanner/manual_tune", json={"frequency": ch['freq'], "modulation": ch['mod']})
        # Get live audio
        audio_resp = client.get("/api/audio/live?squelch_db=-68&duration=2")
        
        status, rms, zcr, var, cls = analyze_audio(audio_resp.content if audio_resp.status_code == 200 else None)
        print(f"{ch['label']} | {audio_resp.status_code} | {rms:.1f} | {zcr:.3f} | {var:.1f} | {cls}")
        
        if cls == "possible voice-like":
            voice_channels.append(ch['label'])
    except Exception as e:
        print(f"{ch['label']} | error: {str(e)} | 0 | 0 | 0 | unknown")

print(f"VOICE_DETECTED={'yes' if voice_channels else 'no'}")
if voice_channels:
    print(f"Voice channels: {', '.join(voice_channels)}")
