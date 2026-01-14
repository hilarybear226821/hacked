
import time
import threading
import json
import logging

logger = logging.getLogger("EventBus")

class EventBus:
    def __init__(self):
        self.clients = set()
        self.sequence = 0
        self.lock = threading.Lock()

    def register(self, ws):
        with self.lock:
            self.clients.add(ws)
            logger.info(f"Client registered. Total: {len(self.clients)}")

    def unregister(self, ws):
        with self.lock:
            self.clients.discard(ws)
            logger.info(f"Client unregistered. Total: {len(self.clients)}")

    def emit(self, event: str, payload: dict):
        # Atomic Sequence & Snapshot
        with self.lock:
            self.sequence += 1
            seq = self.sequence
            timestamp = time.time()
            # Snapshot clients while holding lock
            current_clients = list(self.clients)
            
        message = {
            "event": event,
            "timestamp": timestamp,
            "sequence": seq,
            "payload": payload
        }
        msg_json = json.dumps(message)

        dead = []
        for ws in current_clients:
            try:
                ws.send(msg_json)
            except Exception as e:
                # logger.warning(f"WS Send fail: {e}")
                dead.append(ws)

        if dead:
            with self.lock:
                for ws in dead:
                    self.clients.discard(ws)

# SINGLETON
event_bus = EventBus()
