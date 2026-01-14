
"""
System-Level State Machine (Authoritative)

This module defines the top-level system state that governs all RF operations.
It enforces mutual exclusion between RX and TX, and ensures that the system
cannot enter illegal states.

State Hierarchy:
    SystemState (top-level) -> SDRState (hardware) -> OperationState (tasks)
"""

from enum import Enum
from typing import Set, Dict
import threading
import logging

logger = logging.getLogger("SystemState")

class SystemState(Enum):
    """Top-level system state - authoritative truth"""
    INIT = "init"
    IDLE = "idle"
    RX = "rx"
    TX = "tx"
    ERROR = "error"

# Formal Transition Table
ALLOWED_TRANSITIONS: Dict[SystemState, Set[SystemState]] = {
    SystemState.INIT: {SystemState.IDLE},
    SystemState.IDLE: {SystemState.RX, SystemState.TX, SystemState.ERROR},
    SystemState.RX: {SystemState.IDLE, SystemState.ERROR},
    SystemState.TX: {SystemState.IDLE, SystemState.ERROR},
    SystemState.ERROR: {SystemState.IDLE}
}

class SystemStateManager:
    """
    Singleton manager for system-level state.
    
    This is the authoritative source of truth for the entire system.
    All RF operations must check and update this state.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(SystemStateManager, cls).__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        self.state = SystemState.INIT
        self.lock = threading.RLock()
        self.error_message: str = ""

    def get_state(self) -> SystemState:
        with self.lock:
            return self.state

    def can_transition(self, new_state: SystemState) -> bool:
        """Check if transition is legal"""
        with self.lock:
            return new_state in ALLOWED_TRANSITIONS.get(self.state, set())

    def transition(self, new_state: SystemState, requester: str = "system") -> bool:
        """
        Attempt state transition with validation.
        
        Returns:
            True if transition succeeded, False otherwise
            
        Raises:
            RuntimeError if transition is illegal
        """
        with self.lock:
            if not self.can_transition(new_state):
                msg = f"Illegal system state transition: {self.state.value} -> {new_state.value}"
                logger.critical(msg)
                raise RuntimeError(msg)
            
            old_state = self.state
            self.state = new_state
            
            # Clear error message if leaving ERROR state
            if old_state == SystemState.ERROR and new_state != SystemState.ERROR:
                self.error_message = ""
            
            logger.info(f"System State: {old_state.value} -> {new_state.value} (by {requester})")
            return True

    def set_error(self, message: str):
        """Force transition to ERROR state"""
        with self.lock:
            old_state = self.state
            self.state = SystemState.ERROR
            self.error_message = message
            logger.error(f"System ERROR from {old_state.value}: {message}")

    def reset(self):
        """Reset from ERROR to IDLE"""
        with self.lock:
            if self.state == SystemState.ERROR:
                self.transition(SystemState.IDLE, requester="reset")
            else:
                raise RuntimeError("Can only reset from ERROR state")

    def assert_idle(self):
        """Assert that system is IDLE (for operations requiring exclusive access)"""
        with self.lock:
            if self.state != SystemState.IDLE:
                raise RuntimeError(f"System not IDLE (current: {self.state.value})")

    def assert_not_error(self):
        """Assert that system is not in ERROR state"""
        with self.lock:
            if self.state == SystemState.ERROR:
                raise RuntimeError(f"System in ERROR state: {self.error_message}")

# Global singleton
system_state_manager = SystemStateManager()
