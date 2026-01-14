import sys
import os
import shutil
import json
from unittest.mock import MagicMock
sys.path.append(os.getcwd())

from modules.vehicle_clone import VehicleCloner

def verify_vehicle_clone():
    print("=== Verifying Vehicle Cloner Workflow ===")
    
    # Setup mocks
    sdr = MagicMock()
    sdr.record_signal.return_value = True
    sdr.replay_signal.return_value = True
    
    recorder = MagicMock()
    recorder.db = []
    
    detector = MagicMock()
    # Simulate partial detection (protocol known, decoding known)
    detector.detect_from_file.return_value = {
        "protocol": "KeeLoq",
        "confidence": 0.95,
        "decoder": "keeloq_decoder.KeeLoqDecoder"
    }
    
    # Create test directory for captures
    if os.path.exists("captures/subghz"):
        # Don't delete existing captures in real use, but for test we might want isolation
        pass
    else:
        os.makedirs("captures/subghz", exist_ok=True)
        
    # Use temporary DB file
    temp_db = "captures/test_clones.json"
    if os.path.exists(temp_db):
        os.remove(temp_db)
        
    # Initialize
    cloner = VehicleCloner(sdr, recorder, detector)
    cloner.db_file = temp_db
    cloner.clones = [] # Reset memory state
    
    # 1. Test Quick Clone
    print("\n[Test 1] Quick Clone...")
    result = cloner.quick_clone(freq_mhz=315.0, duration=1.0)
    
    if result["success"]:
        print("✅ Quick Clone Successful")
        clone = result["clone"]
        print(f"   ID: {clone['id']}")
        print(f"   Protocol: {clone['protocol']}")
        print(f"   Freq: {clone['frequency_mhz']} MHz")
        
        if clone['protocol'] != "KeeLoq":
            print("❌ Protocol mismatch")
            return False
            
        # Verify DB save
        if not os.path.exists(temp_db):
            print("❌ DB file not saved")
            return False
    else:
        print(f"❌ Quick Clone Failed: {result.get('error')}")
        return False
        
    # 2. Test Replay
    print("\n[Test 2] Replay Clone...")
    clone_id = result["clone"]["id"]
    success = cloner.replay_clone(clone_id)
    
    if success:
        print("✅ Replay Successful")
        sdr.replay_signal.assert_called()
    else:
        print("❌ Replay Failed")
        return False
        
    # 3. Test Deletion
    print("\n[Test 3] Deletion...")
    success = cloner.delete_clone(clone_id)
    
    if success:
        print("✅ Deletion Successful")
        if cloner.get_clone(clone_id):
            print("❌ Clone still in memory")
            return False
    else:
        print("❌ Deletion Failed")
        return False
        
    return True

if __name__ == "__main__":
    try:
        if verify_vehicle_clone():
            print("\n✅ Vehicle Cloner Verification PASSED")
            sys.exit(0)
        else:
            print("\n❌ Vehicle Cloner Verification FAILED")
            sys.exit(1)
    finally:
        # Cleanup
        if os.path.exists("captures/test_clones.json"):
            os.remove("captures/test_clones.json")
