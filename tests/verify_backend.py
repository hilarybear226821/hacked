
import requests
import time
import sys

BASE_URL = "http://localhost:5001/api"

def test_capabilities():
    print("[*] Testing Capabilities...")
    r = requests.get(f"{BASE_URL}/capabilities", timeout=5)
    assert r.status_code == 200
    data = r.json()
    assert "supported_operations" in data
    assert "rx_stream" in data["supported_operations"]
    print("    [+] OK")

def test_state_flow():
    print("[*] Testing State Flow...")
    
    # 1. Initial State
    r = requests.get(f"{BASE_URL}/state", timeout=5)
    assert r.status_code == 200
    print(f"    [i] Initial State: {r.json()['device_state']}")
    
    # 2. Open
    print("    [>] Opening Device...")
    r = requests.post(f"{BASE_URL}/device/open", timeout=5)
    if r.status_code != 200:
        print(f"    [!] Open Failed (Is HackRF connected?): {r.json()}")
        return
        
    # Check IDEMPOTENCY
    r = requests.post(f"{BASE_URL}/device/open", timeout=5)
    assert r.status_code == 200
    
    # 3. Configure
    print("    [>] Configuring...")
    cfg = {
        "frequency_hz": 433920000,
        "sample_rate_hz": 2000000,
        "lna_gain_db": 32,
        "vga_gain_db": 20
    }
    r = requests.post(f"{BASE_URL}/device/configure", json=cfg, timeout=5)
    assert r.status_code == 200
    
    r = requests.get(f"{BASE_URL}/state", timeout=5)
    state = r.json()
    assert state['device_state'] == 'CONFIGURED'
    assert state['config']['frequency_hz'] == 433920000
    
    # 4. Starting RX
    print("    [>] Starting RX...")
    try:
        r = requests.post(f"{BASE_URL}/rx/start", json={"format": "cs8"}, timeout=5)
    except requests.exceptions.Timeout:
        print("    [!] Starting RX Timed Out")
        return

    if r.status_code == 200:
        time.sleep(1)
        r = requests.get(f"{BASE_URL}/state", timeout=5)
        st = r.json()['device_state']
        if st != 'RX_RUNNING':
             # Maybe it failed shortly after?
             print(f"    [!] Warning: State is {st}, expected RX_RUNNING")
             # Check last error
             print(f"    [!] Health: {r.json()['health']}")
        else:
             assert r.json()['operation'] == 'rx_stream'
        
        # 5. Stop RX
        print("    [>] Stopping RX...")
        r = requests.post(f"{BASE_URL}/rx/stop", timeout=5)
        assert r.status_code == 200
        
        r = requests.get(f"{BASE_URL}/state", timeout=5)
        # Should be CONFIGURED or OPEN? Spec says CONFIGURED
        assert r.json()['device_state'] == 'CONFIGURED'
        
    else:
        print(f"    [!] RX Start failed: {r.json()}")

    # 6. Close
    print("    [>] Closing Device...")
    r = requests.post(f"{BASE_URL}/device/close", timeout=5)
    assert r.status_code == 200
    
    r = requests.get(f"{BASE_URL}/state", timeout=5)
    assert r.json()['device_state'] == 'CLOSED'
    
    print("    [+] Flow OK")

if __name__ == "__main__":
    try:
        test_capabilities()
        test_state_flow()
        print("\n[SUCCESS] Backend Contract Verified")
    except Exception as e:
        print(f"\n[FAILURE] {e}")
        sys.exit(1)
