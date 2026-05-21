import asyncio
import json
from backend.headless_p25_runtime import HeadlessP25Runtime

async def main():
    try:
        control_channels = [851137500, 851287500, 851312500, 851387500]
        rt = HeadlessP25Runtime(control_channels_hz=control_channels)
        
        # Access internal _sdrtrunk_runtime
        sdr_rt = rt._sdrtrunk_runtime
        print(f"SDRTrunk profile_root: {sdr_rt.profile_root}")
        print(f"SDRTrunk playlist_path: {sdr_rt.playlist_path}")
        
        # start() is not async, it returns a dict
        snapshot_dict = rt.start(force_probe=False)
        
        # Since it returns a dict, we'll map necessary fields
        # Note: The original request asked for engine, health, message, profile_root, playlist_path, and processes
        # We need to see if these are in the dict or if they are properties of the runtime
        
        print("Snapshot Details:")
        # Print the relevant keys from the dictionary
        keys_to_print = ["engine", "health", "message", "profile_root", "playlist_path", "processes"]
        filtered_snapshot = {k: snapshot_dict.get(k) for k in keys_to_print}
        print(json.dumps(filtered_snapshot, indent=2))
        
        # stop() might also not be async, checking signature
        # But for now, we try calling it.
        rt.stop()
        
    except Exception as e:
        print(f"Error during execution: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    asyncio.run(main())
