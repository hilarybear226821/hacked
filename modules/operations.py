
from enum import Enum
from dataclasses import dataclass
import time
import uuid
import threading
from typing import Dict, Optional, List

class OperationState(Enum):
    INIT = "init"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    COMPLETED = "completed"
    ABORTED = "aborted"
    FAILED = "failed"

@dataclass
class Operation:
    id: str
    name: str                # "monitor", "record", "replay", "rolljam"
    state: OperationState
    started_at: float
    owner: Optional[str] = None
    progress: float = 0.0    # 0.0 -> 1.0
    message: str = ""
    error: Optional[str] = None

class OperationManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(OperationManager, cls).__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        self._active: Dict[str, Operation] = {}
        self.lock = threading.Lock()

    @property
    def active(self) -> Dict[str, Operation]:
        # Expose direct dict for backward compatibility but protected by lock when used properly
        return self._active

    def create(self, name: str, owner: str = "system") -> Operation:
        with self.lock:
            op = Operation(
                id=str(uuid.uuid4()),
                name=name,
                state=OperationState.INIT,
                started_at=time.time(),
                owner=owner
            )
            self._active[op.id] = op
            return op

    def get(self, op_id: str) -> Optional[Operation]:
        with self.lock:
            return self._active.get(op_id)
            
    def get_running_by_name(self, name: str) -> Optional[Operation]:
        with self.lock:
            for op in self._active.values():
                if op.name == name and op.state in {OperationState.STARTING, OperationState.RUNNING}:
                    return op
            return None

    def remove(self, op_id: str):
        with self.lock:
            self._active.pop(op_id, None)

    def abort_all(self, reason: str):
        with self.lock:
            for op in self._active.values():
                op.state = OperationState.ABORTED
                op.error = reason
            # We don't remove them here, allow heartbeat to report them as aborted, 
            # then cleanup or let clients discover. 
            # Actually, standard behavior is remove? 
            # For now, keep them so Heartbeat can see "ABORTED".

# GLOBAL SINGLETON
operation_manager = OperationManager()
