from enum import Enum, auto
import time

class DeviceState(Enum):
    DISCOVERY = auto() # First time seen
    ACTIVE = auto()    # Recently seen
    STALE = auto()     # Not seen for a while (Graceful Degradation)
    LOST = auto()      # Gone

class StateMachine:
    """
    Manages state transitions based on Time-To-Live (TTL)
    """
    def __init__(self, active_ttl=30.0, stale_ttl=300.0):
        self.active_ttl = active_ttl   # Time to go from ACTIVE -> STALE
        self.stale_ttl = stale_ttl     # Time to go from STALE -> LOST
        self.state = DeviceState.DISCOVERY
        self.last_seen = time.time()
        
    def update(self):
        """Called when device is seen again"""
        self.last_seen = time.time()
        self.state = DeviceState.ACTIVE
        
    def check_state(self):
        """Evaluate current state based on time elapsed"""
        now = time.time()
        elapsed = now - self.last_seen
        
        if self.state == DeviceState.DISCOVERY:
            # Immediate transition if confirming logic isn't complex
            self.state = DeviceState.ACTIVE
            
        if self.state == DeviceState.ACTIVE:
            if elapsed > self.active_ttl:
                self.state = DeviceState.STALE
                
        elif self.state == DeviceState.STALE:
            if elapsed > self.stale_ttl:
                self.state = DeviceState.LOST
                
        return self.state
