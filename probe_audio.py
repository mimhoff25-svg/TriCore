import sys
import os
import struct
import math
import subprocess

def check_rtl():
    print("Checking RTL-SDR availability...")
    try:
        # Check if rtl_test can see the device
        result = subprocess.run(["rtl_test", "-t"], capture_output=True, text=True, timeout=10)
        print(f"rtl_test output: {result.stderr}")
        if "No supported devices found" in result.stderr:
            print("Verdict: RTL-SDR NOT FOUND.")
            return False
        print("Verdict: RTL-SDR FOUND.")
        return True
    except FileNotFoundError:
        print("Verdict: rtl_test not found in PATH.")
        return False
    except Exception as e:
        print(f"Exception checking RTL: {e}")
        return False

# Ensure backend is in path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

try:
    from fastapi.testclient import TestClient
    from backend.app import app
except ImportError:
    try:
        from app import app
    except ImportError as e:
        print(f"Import Error: {e}")
        sys.exit(1)

check_rtl()

frequencies = [
    (162550000, "nfm", "NOAA 162.55"),
    (162400000, "nfm", "NOAA 162.40"),
    (120500000, "am", "ABIA Tower"),
    (121900000, "am", "ABIA Ground"),
    (128800000, "am", "ABIA ATIS"),
    (124400000, "am", "Approach"),
]

client = TestClient(app)

def analyze_audio(data, sample_rate):
    if not data:
        return "silence-like", 0, 0, 0, 0
    
    samples = []
    for i in range(0, len(data) - 1, 2):
        val = struct.unpack('<h', data[i:i+2])[0]
        samples.append(val)
    
    if not samples:
        return "silence-like", 0, 0, 0, 0

    count = len(samples)
    sum_sq = sum(float(s)*s for s in samples)
    rms = math.sqrt(sum_sq / count)
    peak = max(abs(s) for s in samples)
    
    zcr = 0
    for i in range(1, count):
        if (samples[i] >= 0 and samples[i-1] < 0) or (samples[i] < 0 and samples[i-1] >= 0):
            zcr += 1
    zcr_rate = zcr / count
    
    near_zero = sum(1 for s in samples if abs(s) < 100)
    nz_pct = (near_zero / count) * 100
    
    if rms < 150:
        label = "silence-like"
    elif zcr_rate > 0.4 and rms > 500:
        label = "noise-like"
    elif rms > 200 and 0.05 < zcr_rate < 0.4:
        label = "possible voice-like"
    else:
        label = "noise-like"
        
    return label, rms, peak, zcr_rate, nz_pct

print(f"{'Label':<20} | {'Freq':<10} | {'RMS':<8} | {'Peak':<8} | {'ZCR':<8} | {'NZ%':<5} | {'Classification'}")
print("-" * 88)

any_voice = False
for freq, mod, label in frequencies:
    try:
        with client.stream("GET", "/api/audio/live", params={
            "frequency_hz": freq,
            "modulation": mod,
            "squelch_db": -68
        }) as response:
            if response.status_code != 200:
                print(f"{label:<20} | {freq:<10} | ERR: {response.status_code} - {response.text}")
                continue
            
            header = response.read(44)
            if len(header) < 44:
                 print(f"{label:<20} | {freq:<10} | ERR: Short Header")
                 continue
            
            sr = struct.unpack('<I', header[24:28])[0]
            bytes_to_read = sr * 2 * 2 
            audio_data = response.read(bytes_to_read)
            
            classification, rms, peak, zcr, nz = analyze_audio(audio_data, sr)
            if classification == "possible voice-like":
                any_voice = True
                
            print(f"{label:<20} | {freq:<10} | {rms:8.1f} | {peak:8.0f} | {zcr:8.3f} | {nz:5.1f} | {classification}")
            
    except Exception as e:
        print(f"{label:<20} | {freq:<10} | EXCEPTION: {e}")

print("-" * 88)
print(f"FINAL VERDICT: {'Voice-like activity detected!' if any_voice else 'No voice-like activity detected.'}")
