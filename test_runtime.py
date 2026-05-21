import time
import sys
import os

# Add the current directory to sys.path so it can find backend
sys.path.append(os.getcwd())

try:
    from backend.decoder_runtime import SdrTrunkRuntime
    print("Successfully imported SdrTrunkRuntime")
    
    runtime = SdrTrunkRuntime()
    print(f"Status before start: {runtime.get_status()}")
    
    print("Starting runtime with force_probe=True...")
    runtime.start(force_probe=True)
    
    print("Waiting 10 seconds...")
    time.sleep(10)
    
    print(f"Status after 10s: {runtime.get_status()}")
    
    print("Stopping runtime...")
    runtime.stop()
    print(f"Final status: {runtime.get_status()}")
    
except Exception as e:
    print(f"Error during execution: {e}")
    import traceback
    traceback.print_exc()

