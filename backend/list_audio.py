import sounddevice as sd
for i, d in enumerate(sd.query_devices()):
    if d["max_output_channels"] > 0:
        print(f"  [{i}] {d['name']}  out={d['max_output_channels']}ch")
print(f"\nDefault output: {sd.default.device[1]}")
