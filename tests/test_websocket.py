#!/usr/bin/env python3
"""Quick WebSocket connection test"""

import asyncio
import websockets
import json

async def test_websocket():
    uri = "ws://localhost:5001/ws/events"
    
    try:
        async with websockets.connect(uri) as websocket:
            print("✅ WebSocket connected successfully!")
            
            # Receive initial snapshot
            message = await websocket.recv()
            data = json.loads(message)
            
            print(f"\n📡 Received event: {data['event']}")
            print(f"   Sequence: {data['sequence']}")
            print(f"   Timestamp: {data['timestamp']}")
            
            if data['event'] == 'state_snapshot':
                print(f"\n📊 SDR State: {data['payload'].get('device_state', 'unknown')}")
                print(f"   Config: {data['payload'].get('config', {})}")
            
            print("\n✅ WebSocket is working correctly!")
            
    except Exception as e:
        print(f"❌ WebSocket error: {e}")

if __name__ == "__main__":
    asyncio.run(test_websocket())
