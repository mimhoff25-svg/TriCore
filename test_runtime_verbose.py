import time
import sys
import os
import logging

# Configure logging to stdout
logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)

sys.path.append(os.getcwd())

try:
    print("Importing SdrTrunkRuntime...")
    from backend.decoder_runtime import SdrTrunkRuntime
    print("Successfully imported SdrTrunkRuntime")
    
    runtime = SdrTrunkRuntime()
    print("Getting initial status (no probe)...")
    status = runtime.get_status()
    print(f"Status before start: {status}")
    
    print("Starting runtime (force_probe=True)...")
    # Using a shorter timeout for the subprocess call inside start/status if possible, 
    # but the method doesn't take one. We'll just run it.
    runtime.start(force_probe=True)
    
    print("Waiting 10 seconds for tuner and logs...")
    for i in range(10):
        time.sleep(1)
        print(f"Tick {i+1}...")
    
    print("Getting status after 10s...")
    status_after = runtime.get_status()
    print(f"Status after 10s: {status_after}")
    
    print("Stopping runtime...")
    runtime.stop()
    print("Final status:")
    print(runtime.get_status())
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
