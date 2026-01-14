
import requests
import time
import sys

BASE_URL = "http://localhost:5001/api"

def test_capabilities():
    print("Testing Capabilities Endpoint...")
    try:
        r = requests.get(f"{BASE_URL}/capabilities")
        print(f"Status: {r.status_code}")
        
        if r.status_code == 200:
            data = r.json()
            print(f"Supported Operations: {data.get('supported_operations')}")
            print(f"Available Attacks: {list(data.get('attacks', {}).keys())}")
            return True
        else:
            print("FAILURE: Capabilities endpoint error")
            return False
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_camera_jammer():
    print("\nTesting Camera Jammer...")
    try:
        # Start jamming
        r = requests.post(f"{BASE_URL}/attack/camera_jammer/start", json={
            "band": "2.4GHz",
            "sweep": False,
            "timeout": 10
        })
        print(f"Start Status: {r.status_code}")
        print(f"Start Response: {r.text}")
        
        if r.status_code == 200:
            data = r.json()
            op_id = data.get("operation_id")
            print(f"SUCCESS: Camera jammer started (op_id: {op_id})")
            
            time.sleep(2)
            
            # Stop jamming
            r_stop = requests.post(f"{BASE_URL}/attack/camera_jammer/stop")
            print(f"Stop Status: {r_stop.status_code}")
            print(f"Stop Response: {r_stop.text}")
            return True
        else:
            print("FAILURE: Camera jammer start failed")
            return False
            
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_bruteforce():
    print("\nTesting Brute Force...")
    try:
        # Start brute force with small range
        r = requests.post(f"{BASE_URL}/attack/bruteforce/start", json={
            "start_code": 0,
            "end_code": 10  # Small range for testing
        })
        print(f"Start Status: {r.status_code}")
        print(f"Start Response: {r.text}")
        
        if r.status_code == 200:
            data = r.json()
            op_id = data.get("operation_id")
            print(f"SUCCESS: Brute force started (op_id: {op_id})")
            
            time.sleep(2)
            
            # Stop brute force
            r_stop = requests.post(f"{BASE_URL}/attack/bruteforce/stop")
            print(f"Stop Status: {r_stop.status_code}")
            print(f"Stop Response: {r_stop.text}")
            return True
        else:
            print("FAILURE: Brute force start failed")
            return False
            
    except Exception as e:
        print(f"Error: {e}")
        return False

if __name__ == "__main__":
    print("=== Attack Integration Verification ===\n")
    
    results = []
    results.append(("Capabilities", test_capabilities()))
    results.append(("Camera Jammer", test_camera_jammer()))
    results.append(("Brute Force", test_bruteforce()))
    
    print("\n=== Results ===")
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")
    
    all_passed = all(r[1] for r in results)
    sys.exit(0 if all_passed else 1)
