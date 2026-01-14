
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
    print(f"\n[WS] Event: {data['event']} | Seq: {data['sequence']}")
    if data['event'] == 'state_changed':
        print(f"     -> {data['payload']['from']} -> {data['payload']['to']}")
    elif data['event'] == 'state_snapshot':
        print(f"     -> Snapshot State: {data['payload']['device_state']}")
    elif data['event'] == 'operation_started':
        print(f"     -> Started: {data['payload']['operation']}")

def on_error(ws, error):
    print(f"[WS] Error: {error}")

def on_close(ws, close_status_code, close_msg):
    print("[WS] Closed")

def on_open(ws):
    print("[WS] Connected")
    
    # Trigger actions in a separate thread after a delay
    threading.Thread(target=trigger_actions).start()

def trigger_actions():
    time.sleep(1)
    
    # 1. Open
    print("[API] Opening Device...")
    requests.post(f"{BASE_API}/device/open")
    time.sleep(0.5)
    
    # 2. Configure
    print("[API] Configuring...")
    cfg = {
        "frequency_hz": 433920000,
        "sample_rate_hz": 2000000,
        "lna_gain_db": 32,
        "vga_gain_db": 20
    }
    requests.post(f"{BASE_API}/device/configure", json=cfg)
    time.sleep(0.5)
    
    # 3. Start RX
    print("[API] Starting RX...")
    requests.post(f"{BASE_API}/rx/start", json={"format": "cs8"})
    
    # Wait for RX Running & Operation Started
    time.sleep(2)
    
    # 4. Stop
    print("[API] Stopping RX...")
    requests.post(f"{BASE_API}/rx/stop")
    time.sleep(0.5)
    
    print("[API] Closing...")
    requests.post(f"{BASE_API}/device/close")
    time.sleep(0.5)
    
    print("[TEST] Done. Closing WS.")
    ws.close()

if __name__ == "__main__":
    # websocket.enableTrace(True)
    ws = websocket.WebSocketApp(WS_URL,
                              on_open=on_open,
                              on_message=on_message,
                              on_error=on_error,
                              on_close=on_close)

    ws.run_forever()
