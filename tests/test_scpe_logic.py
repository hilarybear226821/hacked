
import sys
import os
import time
import numpy as np
sys.path.append(os.getcwd())

from modules.scpe_engine import SCPEAttackController, SignalDetection
from modules.sdr_controller import SDRController

def test_scpe_engine():
    print("=== Testing SCPE Engine Logic ===")
    
    # Mock Physical Layer
    sdr = SDRController() # Mock or real, doesn't matter for logic test
    rolljam = None # Mock
    
    engine = SCPEAttackController(sdr, rolljam)
    engine.start()
    
    # Simulate Ingestion
    print("1. Simulating Signal Ingestion...")
    detection = SignalDetection(
        frequency=315e6,
        power_dbm=-40,
        snr_db=15.0,
        bandwidth_hz=50e3,
        timestamp=time.time(),
        confidence=0.9
    )
    
    engine.ingest_signal(detection, np.zeros(10))
    
    # Verify State
    dev_id = "Dev_315MHz"
    if dev_id in engine.pop_mgr.devices:
        dev = engine.pop_mgr.devices[dev_id]
        print(f"✅ Device Registered: {dev.device_id}")
        print(f"   Capture Queue: {len(dev.capture_queue)}")
    else:
        print("❌ Device registration failed")
        
    # Simulate Replay
    print("2. Simulating Replay Trigger...")
    result = engine.trigger_replay(dev_id, mode="SCPE_THICK")
    
    if result:
        print("✅ Replay Triggered Successfully")
        print(f"   Queue after replay: {len(dev.capture_queue)}")
    else:
        print("❌ Replay failed")
        
    print("=== Test Complete ===")

if __name__ == "__main__":
    test_scpe_engine()
