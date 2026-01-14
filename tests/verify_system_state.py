
import requests
import time
import sys

BASE_URL = "http://localhost:5001/api"

def test_system_state_enforcement():
    """Test that SystemState prevents simultaneous RX/TX"""
    print("\n=== Testing System State Enforcement ===")
    
    try:
        # 1. Configure SDR
        r = requests.post(f"{BASE_URL}/device/configure", json={
            "frequency_hz": 433920000,
            "sample_rate_hz": 2000000,
            "lna_gain_db": 32,
            "vga_gain_db": 20,
            "amp_enabled": True
        })
        print(f"Configure: {r.status_code}")
        
        # 2. Start RX
        r_rx = requests.post(f"{BASE_URL}/rx/start", json={})
        print(f"RX Start: {r_rx.status_code} - {r_rx.text[:100]}")
        
        if r_rx.status_code == 200:
            rx_data = r_rx.json()
            rx_op_id = rx_data.get("operation_id")
            
            time.sleep(1)
            
            # 3. Try to start TX (should fail due to SystemState)
            r_tx = requests.post(f"{BASE_URL}/tx/start", json={
                "mode": "jam_noise",
                "filepath": "/tmp/test.cs8",
                "repeat": False
            })
            print(f"TX Start (should fail): {r_tx.status_code} - {r_tx.text[:100]}")
            
            if r_tx.status_code != 200:
                print("✅ PASS: SystemState correctly blocked TX while RX active")
                result = True
            else:
                print("❌ FAIL: SystemState allowed TX while RX active")
                result = False
            
            # 4. Stop RX
            requests.post(f"{BASE_URL}/rx/stop")
            time.sleep(1)
            
            return result
        else:
            print("❌ FAIL: Could not start RX")
            return False
            
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_attack_integration():
    """Test integrated attacks"""
    print("\n=== Testing Attack Integration ===")
    
    results = []
    
    # Test RollJam
    try:
        r = requests.post(f"{BASE_URL}/attack/rolljam/start", json={
            "frequency_hz": 433920000
        })
        print(f"RollJam Start: {r.status_code}")
        results.append(("RollJam", r.status_code == 200 or r.status_code == 409))
        if r.status_code == 200:
            time.sleep(1)
            requests.post(f"{BASE_URL}/attack/rolljam/stop")
    except Exception as e:
        print(f"RollJam Error: {e}")
        results.append(("RollJam", False))
    
    time.sleep(2)
    
    # Test Camera Jammer
    try:
        r = requests.post(f"{BASE_URL}/attack/camera_jammer/start", json={
            "band": "2.4GHz",
            "timeout": 5
        })
        print(f"Camera Jammer Start: {r.status_code}")
        results.append(("Camera Jammer", r.status_code == 200 or r.status_code == 409))
        if r.status_code == 200:
            time.sleep(1)
            requests.post(f"{BASE_URL}/attack/camera_jammer/stop")
    except Exception as e:
        print(f"Camera Jammer Error: {e}")
        results.append(("Camera Jammer", False))
    
    time.sleep(2)
    
    # Test Brute Force
    try:
        r = requests.post(f"{BASE_URL}/attack/bruteforce/start", json={
            "start_code": 0,
            "end_code": 5
        })
        print(f"Brute Force Start: {r.status_code}")
        results.append(("Brute Force", r.status_code == 200 or r.status_code == 409))
        if r.status_code == 200:
            time.sleep(1)
            requests.post(f"{BASE_URL}/attack/bruteforce/stop")
    except Exception as e:
        print(f"Brute Force Error: {e}")
        results.append(("Brute Force", False))
    
    return all(r[1] for r in results)

if __name__ == "__main__":
    print("=== Backend Integration Verification ===\n")
    
    results = []
    results.append(("System State Enforcement", test_system_state_enforcement()))
    results.append(("Attack Integration", test_attack_integration()))
    
    print("\n=== Final Results ===")
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")
    
    all_passed = all(r[1] for r in results)
    sys.exit(0 if all_passed else 1)
