import websocket
import threading
import time
import json
import sys

def on_message(ws, message):
    print(f"Received: {message[:100]}...")
    ws.close()

def on_error(ws, error):
    print(f"Error: {error}")

def on_open(ws):
    print("Connection opened")

def test_endpoint(url):
    print(f"Testing {url}...")
    ws = websocket.WebSocketApp(url,
                              on_message=on_message,
                              on_error=on_error,
                              on_open=on_open)
    ws.run_forever()

if __name__ == "__main__":
    # Test Logs
    print("--- Testing Log Stream ---")
    try:
        ws = websocket.create_connection("ws://127.0.0.1:5001/ws/logs")
        result = ws.recv()
        print(f"✅ Log Stream Working. Received: {result[:50]}")
        ws.close()
    except Exception as e:
        print(f"❌ Log Stream Failed: {e}")

    # Test Spectrum
    print("\n--- Testing Spectrum Stream ---")
    try:
        ws = websocket.create_connection("ws://127.0.0.1:5001/ws/spectrum")
        # We might need to wait for a broadcast
        print("Waiting for spectrum data...")
        ws.settimeout(2.0)
        try:
            result = ws.recv()
            data = json.loads(result)
            if data.get('type') == 'spectrum':
                 print(f"✅ Spectrum Stream Working. Data: {str(data)[:50]}...")
            else:
                 print(f"⚠️ Received non-spectrum data: {result[:50]}")
        except Exception as e:
            print(f"⚠️ No spectrum data received (expected if no signal): {e}")
            print("✅ Connection established though.")
        ws.close()
    except Exception as e:
        print(f"❌ Spectrum Stream Connection Failed: {e}")
