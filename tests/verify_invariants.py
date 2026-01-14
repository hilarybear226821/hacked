
import websocket
import threading
import time
import json
import requests
import sys

BASE_API = "http://localhost:5001/api"
WS_URL = "ws://localhost:5001/ws/events"

def on_message(ws, message):
    data = json.loads(message)
    # print(f"\n[WS] Event: {data['event']} | Seq: {data.get('sequence', '-')}")
    if data['event'] == 'fault':
        print(f"     [!] FAULT: {data['payload']['message']}")
    elif data['event'] == 'state_changed':
        print(f"     -> {data['payload']['from']} -> {data['payload']['to']}")
    elif data['event'] == 'operation_started':
        if 'id' in data:
             print(f"     -> Lifecycle Op Started: {data['name']} (ID: {data['id']})")
        else: 
             # Device level
             pass
    elif data['event'] == 'heartbeat':
         # Less spam, just once in a while or summary
         payload = data['payload']
         ops = payload['operations']
         op_str = f"Ops: {len(ops)}"
         if ops:
             op_str += f" ({ops[0]['name']}:{ops[0]['state']})"
         print(f"     -> HEARTBEAT [Up: {int(payload['backend_uptime_sec'])}s | {payload['sdr']['state']} | {op_str}]")

def on_error(ws, error):
    pass

def on_close(ws, close_status_code, close_msg):
    print("[WS] Closed")

def on_open(ws):
    print("[WS] Connected")
    threading.Thread(target=trigger_violations).start()

def trigger_violations():
    time.sleep(1)
    
    # Setup
    print("[API] Opening & Configuring...")
    requests.post(f"{BASE_API}/device/open")
    requests.post(f"{BASE_API}/device/configure", json={
        "frequency_hz": 433920000,
        "sample_rate_hz": 2000000,
        "lna_gain_db": 32, 
        "vga_gain_db": 20
    })
    time.sleep(1)

    # Test 1: Start RX then try TX
    print("\n[TEST] 1. Start RX, then try TX (Should Fail)")
    r = requests.post(f"{BASE_API}/rx/start", json={}) 
    if r.status_code == 200:
        op_id = r.json().get("operation_id")
        print(f"[API] RX Started with Operation ID: {op_id}")
    else:
        print(f"[API] RX Start Failed: {r.status_code}")

    time.sleep(2) 
    
    r = requests.post(f"{BASE_API}/tx/start", json={"mode": "tx_file"})
    print(f"[API] TX Start Response: {r.status_code}") 
    if r.status_code != 200:
        print(f"      -> Success: Blocked ({r.json().get('message', '')})")
    
    # Clean up (Stop RX)
    requests.post(f"{BASE_API}/rx/stop")
    time.sleep(1)
    
    # Test 2: Start TX then try RX
    print("\n[TEST] 2. Start TX (Jamming), then try RX (Should Fail)")
    r = requests.post(f"{BASE_API}/tx/start", json={"mode": "jam_noise"})
    if r.status_code == 200:
        op_id = r.json().get("operation_id")
        print(f"[API] TX Started with ID: {op_id}")
    
    time.sleep(1)
    
    r = requests.post(f"{BASE_API}/rx/start", json={})
    print(f"[API] RX Start Response: {r.status_code}")
    if r.status_code != 200:
        print(f"      -> Success: Blocked ({r.json().get('message', '')})")
    else:
        print(f"[!] FAILED: RX Started Unexpectedly!")
        
    requests.post(f"{BASE_API}/attack/stop", json={"operation": "jam_noise"})
    time.sleep(1)
    
    print("\n[TEST] Done. Closing.")
    ws.close()

if __name__ == "__main__":
    ws = websocket.WebSocketApp(WS_URL,
                              on_open=on_open,
                              on_message=on_message,
                              on_error=on_error, 
                              on_close=on_close)
    ws.run_forever()
