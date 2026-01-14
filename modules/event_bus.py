
import time
import threading
import json
import logging
from typing import Set, Dict, Any

logger = logging.getLogger("EventBus")

class EventBus:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(EventBus, cls).__new__(cls)
                cls._instance._init()
            return cls._instance
            
    def _init(self):
        self.clients: Set[Any] = set()
        self.sequence_map: Dict[Any, int] = {} # Per-client sequence
        # Spec says "Monotonic counter (per connection)"
        self.lock = threading.Lock()
        
    def register(self, ws):
        with self.lock:
            self.clients.add(ws)
            self.sequence_map[ws] = 0
            logger.info(f"Client connected. Total: {len(self.clients)}")
            
    def unregister(self, ws):
        with self.lock:
            if ws in self.clients:
                self.clients.remove(ws)
                if ws in self.sequence_map:
                    del self.sequence_map[ws]
                logger.info(f"Client disconnected. Total: {len(self.clients)}")
                
    def emit(self, event: str, payload: dict):
        """Emit event to all connected clients with per-client sequence"""
        # Snapshot payload to avoid mutation during iteration
        # Note: We must generate the msg INSIDE the loop or PER client because sequence differs
        
        timestamp = time.time()
        
        with self.lock:
            # We copy list to allow safe removal during iteration if send fails
            for ws in list(self.clients):
                try:
                    self.sequence_map[ws] += 1
                    seq = self.sequence_map[ws]
                    
                    msg = {
                        "event": event,
                        "timestamp": timestamp,
                        "sequence": seq,
                        "payload": payload
                    }
                    
                    ws.send(json.dumps(msg))
                    
                except Exception as e:
                    # logger.error(f"WS Send Error: {e}")
                    # Assume disconnected
                    try:
                        self.clients.remove(ws)
                        del self.sequence_map[ws]
                    except:
                        pass
