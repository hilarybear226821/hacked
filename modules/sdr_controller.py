
import time
import numpy as np
import logging
import subprocess
import os
import signal
import threading
import atexit
import fcntl
import select
from enum import Enum, auto
from typing import Optional, Callable, List, Set, Dict, Tuple, Any
from dataclasses import dataclass, field, asdict
from collections import deque
from pathlib import Path

from modules.events import event_bus
from modules.operations import operation_manager, OperationState
from core.system_state import system_state_manager, SystemState
from modules.rx_bus import rx_bus

logger = logging.getLogger("HackRF")

# ============================================================================
# 1. STATE MACHINE DEFINITION
# ============================================================================

class SDRState(Enum):
    """SDR State Enum - 9 State Strict Model"""
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    CONFIGURED = "CONFIGURED"
    RX_STARTING = "RX_STARTING"
    RX_RUNNING = "RX_RUNNING"
    TX_STARTING = "TX_STARTING"
    TX_RUNNING = "TX_RUNNING"
    STOPPING = "STOPPING"
    ERROR = "ERROR"

@dataclass
class RuntimeFlags:
    """Runtime tracking of ownership and processes"""
    rx_pid: Optional[int] = None
    tx_pid: Optional[int] = None
    last_error: Optional[Dict[str, Any]] = None
    lock_owner: Optional[str] = None
    current_operation: Optional[str] = None
    active_attacks: Set[str] = field(default_factory=set)
    active_attacks: Set[str] = field(default_factory=set)
    uptime_start: float = 0.0
    rx_bytes: int = 0
    rx_samples: int = 0

# ============================================================================
# 2. DATA MODELS
# ============================================================================

@dataclass
class HackRFConfig:
    frequency_hz: int
    sample_rate_hz: int
    lna_gain_db: int
    vga_gain_db: int
    vga_gain_db: int
    amp_enabled: bool = True
    max_tx_seconds: int = 30

    def validate(self):
        if not (1_000_000 <= self.frequency_hz <= 6_000_000_000):
            raise ValueError("Frequency out of range (1MHz - 6GHz)")
        if not (2_000_000 <= self.sample_rate_hz <= 20_000_000):
            raise ValueError("Sample rate out of range (2MSPS - 20MSPS)")
        
        valid_lna = [0, 8, 16, 24, 32, 40]
        if self.lna_gain_db not in valid_lna:
             self.lna_gain_db = min(valid_lna, key=lambda x: abs(x - self.lna_gain_db))

        self.vga_gain_db = max(0, min(62, (self.vga_gain_db // 2) * 2))

# ============================================================================
# 3. PROCESS MANAGER
# ============================================================================

class ProcessManager:
    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.lock = threading.Lock()
        
    def start(self, args: List[str], capture_stdout: bool = True) -> bool:
        with self.lock:
            if self.is_running():
                return False
                
            try:
                kwargs = {
                    'stderr': subprocess.PIPE, # Capture stderr for debugging
                    'bufsize': 0
                }
                
                if capture_stdout:
                    kwargs['stdout'] = subprocess.PIPE
                else:
                    kwargs['stdout'] = subprocess.DEVNULL
                
                logger.debug(f"Creating subprocess with args: {args}")
                self.process = subprocess.Popen(args, **kwargs)
                logger.debug(f"Process created: PID {self.process.pid}")
                
                if self.process.stdout:
                    fd = self.process.stdout.fileno()
                    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
                    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
                    logger.debug("Set stdout to non-blocking")
                
                time.sleep(0.05)
                poll_result = self.process.poll()
                logger.debug(f"Poll result after 50ms: {poll_result}")
                
                if poll_result is not None:
                     error_out = self.process.stderr.read().decode('utf-8', errors='replace') if self.process.stderr else "No stderr"
                     logger.error(f"Process failed immediately (exit code {poll_result}): {error_out}")
                     self.process = None
                     return False
                     
                logger.info(f"Process started successfully: PID {self.process.pid}")
                return True
            except FileNotFoundError:
                 logger.error(f"Binary not found: {args[0]}")
                 return False
            except Exception as e:
                logger.error(f"Process start error: {e}")
                import traceback
                traceback.print_exc()
                self.process = None
                return False

    def stop(self, timeout: float = 0.5):
        with self.lock:
            if not self.process: return
            
            pid = self.process.pid
            
            try:
                self.process.terminate()
            except ProcessLookupError:
                self.process = None
                return
                
            try:
                self.process.wait(timeout)
            except subprocess.TimeoutExpired:
                logger.warning(f"Process {pid} hung, using SIGKILL")
                try:
                    os.kill(pid, signal.SIGKILL)
                    self.process.wait(0.5)
                except:
                    pass
            finally:
                self.process = None

    def is_running(self) -> bool:
        with self.lock:
            return self.process is not None and self.process.poll() is None

    def read_stdout(self, size: int) -> Optional[bytes]:
        if not self.process or not self.process.stdout: return b''
        try:
            return os.read(self.process.stdout.fileno(), size)
        except BlockingIOError:
            return None
        except Exception:
            return b''

    def _drain_stderr(self) -> str:
        if not self.process or not self.process.stderr: return ""
        try:
             # Set to non-blocking just in case
             fd = self.process.stderr.fileno()
             fl = fcntl.fcntl(fd, fcntl.F_GETFL)
             fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
             
             return self.process.stderr.read().decode('utf-8', errors='replace')
        except:
             return ""

# ============================================================================
# 4. HACKRF DEVICE (Production Hardened)
# ============================================================================

class HackRFDevice:
    def __init__(self):
        self.state = SDRState.CLOSED
        self.flags = RuntimeFlags()
        self.config: Optional[HackRFConfig] = None
        
        self.lock = threading.RLock() 
        # event_bus is global singleton
        
        self.rx_manager = ProcessManager()
        self.tx_manager = ProcessManager()
        
        self.rx_thread: Optional[threading.Thread] = None
        self.stop_signal = threading.Event()
        self.sample_callback: Optional[Callable] = None
        
        self.op_started_event = threading.Event()
        
        atexit.register(self.close)

    def reset_device(self):
        """Hard reset of the HackRF hardware if possible"""
        with self.lock:
            logger.info("Attempting HackRF hardware reset...")
            self.stop_force()
            try:
                # Use hackrf_spiflash -R to trigger a reset
                subprocess.run(['hackrf_spiflash', '-R'], capture_output=True, timeout=2.0)
                time.sleep(1.0) # Wait for USB re-enumeration
                self.open()
            except Exception as e:
                logger.error(f"Hardware reset failed: {e}")

    def _canonical_table_check(self, from_state: SDRState, to_state: SDRState) -> bool:
        allowed = {
            SDRState.CLOSED:      {SDRState.OPEN},
            SDRState.OPEN:        {SDRState.CONFIGURED, SDRState.CLOSED},
            SDRState.CONFIGURED:  {SDRState.RX_STARTING, SDRState.TX_STARTING, SDRState.OPEN, SDRState.CLOSED},
            SDRState.RX_STARTING: {SDRState.RX_RUNNING, SDRState.ERROR, SDRState.STOPPING},
            SDRState.RX_RUNNING:  {SDRState.STOPPING, SDRState.ERROR},
            SDRState.TX_STARTING: {SDRState.TX_RUNNING, SDRState.ERROR, SDRState.STOPPING},
            SDRState.TX_RUNNING:  {SDRState.STOPPING, SDRState.ERROR},
            SDRState.STOPPING:    {SDRState.CONFIGURED, SDRState.ERROR, SDRState.OPEN}, # Added OPEN
            SDRState.ERROR:       {SDRState.OPEN, SDRState.CLOSED, SDRState.CONFIGURED}
        }
        return to_state in allowed.get(from_state, set())
        
    def _assert_invariants(self):
        """
        Enforce device invariants.
        Any violation is a HARD FAULT.
        """
        # RX + TX must never coexist
        if self.rx_manager.is_running() and self.tx_manager.is_running():
            raise RuntimeError("Invariant violation: RX and TX running simultaneously")

        # RX_RUNNING requires RX process
        if self.state == SDRState.RX_RUNNING:
            if not self.rx_manager.is_running():
                raise RuntimeError("RX_RUNNING but RX process not running")

        # TX_RUNNING requires TX process
        if self.state == SDRState.TX_RUNNING:
            if not self.tx_manager.is_running():
                raise RuntimeError("TX_RUNNING but TX process not running")

        # STOPPING must have no active processes starting
        if self.state == SDRState.STOPPING:
             pass

    def _atomic_transition(self, new_state: SDRState, requester: str = None, error: dict = None):
        with self.lock:
            if not self._canonical_table_check(self.state, new_state):
                 if new_state not in {SDRState.ERROR, SDRState.CLOSED}:
                    msg = f"Illegal Transition: {self.state.name} -> {new_state.name}"
                    logger.critical(msg)
                    raise RuntimeError(msg)

            old_state = self.state
            self.state = new_state
            
            if error:
                self.flags.last_error = error
                self.flags.last_error['timestamp'] = int(time.time())
            
            logger.info(f"TRANSITION [{self.state.name}] (Owner: {self.flags.lock_owner}, Op: {self.flags.current_operation})")
            
            if self.state == SDRState.CONFIGURED:
                 self.flags.current_operation = None
                 self.op_started_event.clear()
            elif self.state in {SDRState.RX_RUNNING, SDRState.TX_RUNNING}:
                 self.flags.uptime_start = time.time()
            
            # INVARIANT CHECK
            try:
                self._assert_invariants()
            except Exception as e:
                logger.critical(f"INVARIANT FAILURE: {e}")
                self.state = SDRState.ERROR # Force Error

                event_bus.emit(
                    "fault",
                    {
                        "type": "invariant_violation",
                        "message": str(e),
                        "from": old_state.name,
                        "to": "ERROR"
                    }
                )
                raise

            # Normal Event
            operation = None
            if new_state in {SDRState.RX_STARTING, SDRState.RX_RUNNING}:
                operation = "rx_stream"
            elif new_state in {SDRState.TX_STARTING, SDRState.TX_RUNNING}:
                operation = self.flags.current_operation or "tx_stream"
                
            event_bus.emit('state_changed', {
                "from": old_state.name,
                "to": new_state.name,
                "operation": operation
            })

    def get_snapshot(self) -> Dict[str, Any]:
        # Non-blocking snapshot to avoid stalling the web server during long operations
        locked = self.lock.acquire(blocking=False)
        try:
            if not locked:
                # If we can't acquire the lock, return a minimal snapshot indicating it's locked
                return {
                    "device_state": self.state.name,
                    "operation": self.flags.current_operation,
                    "config": asdict(self.config) if self.config else {},
                    "process": {"pid": None, "uptime_ms": 0},
                    "health": {
                        "rx_active": self.state == SDRState.RX_RUNNING,
                        "rx_bytes": self.flags.rx_bytes,
                        "rx_samples": self.flags.rx_samples,
                        "error_count": 0, # TODO: Track error count
                        "last_error": self.flags.last_error
                    },
                    "locked": True
                }

            cfg_dict = {}
            if self.config:
                cfg_dict = asdict(self.config)

            active = self.state in {SDRState.RX_RUNNING, SDRState.TX_RUNNING}
            uptime_ms = 0
            if active and hasattr(self.flags, 'uptime_start') and self.flags.uptime_start:
                uptime_ms = int((time.time() - self.flags.uptime_start) * 1000)
            
            process_data = {}
            if self.rx_manager.process:
                 process_data = {"pid": self.rx_manager.process.pid, "uptime_ms": uptime_ms}
            elif self.tx_manager.process:
                 process_data = {"pid": self.tx_manager.process.pid, "uptime_ms": uptime_ms}
            else:
                 process_data = {"pid": None, "uptime_ms": 0}
            
            op = None
            if self.state in {SDRState.RX_STARTING, SDRState.RX_RUNNING}: op = "rx_stream"
            elif self.state in {SDRState.TX_STARTING, SDRState.TX_RUNNING}: op = self.flags.current_operation

            return {
                "device_state": self.state.name,
                "operation": op,
                "config": cfg_dict,
                "process": process_data,
                "health": {
                    "rx_active": self.state == SDRState.RX_RUNNING,
                    "rx_bytes": self.flags.rx_bytes,
                    "rx_samples": self.flags.rx_samples,
                    "error_count": 0,
                    "last_error": self.flags.last_error
                },
                "locked": False
            }
        finally:
            if locked:
                self.lock.release()

    # --- Actions ---

    def open(self) -> bool:
        with self.lock:
            if self.state != SDRState.CLOSED: return True 
            
            try:
                check = subprocess.run(['hackrf_info'], capture_output=True, text=True)
                if "Found HackRF" not in check.stdout:
                    self._report_error("DEVICE_NOT_FOUND", "HackRF not found on USB")
                    return False
            except FileNotFoundError:
                 self._report_error("MISSING_BINARY", "hackrf_info not found in PATH")
                 return False
            except Exception as e:
                 self._report_error("UNKNOWN_ERROR", str(e))
                 return False
                
            self._atomic_transition(SDRState.OPEN)
            
            # Initialize system state to IDLE
            if system_state_manager.get_state() == SystemState.INIT:
                system_state_manager.transition(SystemState.IDLE, requester="system")
                
            return True

    def close(self):
        with self.lock:
            if self.state == SDRState.CLOSED:
                return

            try:
                # Stop any running operations first
                if self.state in {
                    SDRState.RX_RUNNING,
                    SDRState.TX_RUNNING,
                    SDRState.RX_STARTING,
                    SDRState.TX_STARTING,
                    SDRState.STOPPING,
                }:
                    self.stop()

                # Transition from CONFIGURED to OPEN
                if self.state == SDRState.CONFIGURED:
                    self._atomic_transition(SDRState.OPEN)

                # Transition from OPEN or ERROR to CLOSED
                if self.state in {SDRState.OPEN, SDRState.ERROR}:
                    self._atomic_transition(SDRState.CLOSED)

            finally:
                self.flags.lock_owner = None
                self.flags.current_operation = None

    def configure(self, config: HackRFConfig):
        with self.lock:
            if self.state not in {SDRState.OPEN, SDRState.CONFIGURED}:
                raise RuntimeError("Must be OPEN/CONFIGURED to configure")
            
            config.validate()
            self.config = config
            
            event_bus.emit('config_updated', asdict(self.config))
            
            if self.state == SDRState.OPEN:
                 self._atomic_transition(SDRState.CONFIGURED)

    def start_rx(self, callback: Callable, requester: str = "api") -> bool:
        with self.lock:
            # Idempotency check
            if self.state in [SDRState.RX_RUNNING, SDRState.RX_STARTING]:
                logger.debug(f"start_rx: already in {self.state.name}, returning True")
                return True
                
            # System-Level State Check
            try:
                if system_state_manager.state != SystemState.RX:
                    system_state_manager.assert_idle()
                    system_state_manager.transition(SystemState.RX, requester=requester)
            except RuntimeError as e:
                logger.error(f"System state violation: {e}")
                raise
            
            # Hard Block
            if self.tx_manager.is_running():
                system_state_manager.transition(SystemState.IDLE, requester=requester)
                raise RuntimeError("Cannot start RX while TX is active")
                
            if self.state != SDRState.CONFIGURED:
                 system_state_manager.transition(SystemState.IDLE, requester=requester)
                 raise RuntimeError(f"Cannot start RX from {self.state.name}")

            self.flags.lock_owner = requester
            self.flags.current_operation = "rx_stream"
            
            self._atomic_transition(SDRState.RX_STARTING)
            # Build command
            args = [
                '/usr/bin/hackrf_transfer',
                '-r', '-', # Receive to stdout
                '-f', str(self.config.frequency_hz),
                '-s', str(self.config.sample_rate_hz),
                '-l', str(self.config.lna_gain_db),
                '-g', str(self.config.vga_gain_db)
            ]
            if self.config.amp_enabled: args.extend(['-a', '1'])
            
            logger.info(f"Starting RX with direct subprocess: {args}")
            
            # USE ProcessManager
            try:
                if not self.rx_manager.start(args, capture_stdout=True):
                     stderr = self.rx_manager._drain_stderr()
                     logger.error(f"RX process failed to start: {stderr}")
                     self._atomic_transition(SDRState.ERROR, error={"code": "PROCESS_FAIL", "message": f"hackrf_transfer failed to start: {stderr}"})
                     system_state_manager.set_error("RX process failed to start")
                     return False
                     
                logger.info("RX process started successfully")
                
            except Exception as e:
                logger.error(f"Failed to start RX: {e}")
                import traceback
                traceback.print_exc()
                self._atomic_transition(SDRState.ERROR, error={"code": "START_ERROR", "message": str(e)})
                system_state_manager.set_error(f"RX start error: {e}")
                return False
                
            self.sample_callback = callback
            self.stop_signal.clear()
            self.op_started_event.clear() 
            
            # Configure RX Bus for decoder pipeline
            logger.info("DEBUG: Configuring rx_bus")
            rx_bus.configure(
                center_freq=self.config.frequency_hz,
                sample_rate=self.config.sample_rate_hz
            )
            logger.info("DEBUG: rx_bus configured")
            
            self.rx_thread = threading.Thread(target=self._rx_loop_select, daemon=True)
            self.rx_thread.start()
            logger.info("DEBUG: RX thread started")
            
            # RX start confirmation timeout
            if not self.op_started_event.wait(timeout=2.0):
                logger.error("RX start timeout: no samples received within 2s")
                self.stop_force()
                self._atomic_transition(
                    SDRState.ERROR,
                    error={"code": "RX_START_TIMEOUT", "message": "No RX data received"}
                )
                system_state_manager.set_error("RX start timeout")
                # Attempt auto-reset on timeout
                self.reset_device()
                return False

            self._atomic_transition(SDRState.RX_RUNNING)
            
            # Emit system state change event
            event_bus.emit("system_state_changed", {
                "from": "IDLE",
                "to": "RX",
                "operation": "rx_stream"
            })
            
            return True

    def capture_samples(self, count: int, requester: str = "internal", timeout: float = 2.0) -> Optional[np.ndarray]:
        """Synchronous capture of N samples"""
        captured = []
        capture_lock = threading.Lock()
        collection_done = threading.Event()
        
        def cb(samples):
            with capture_lock:
                if collection_done.is_set(): return
                captured.append(samples)
                total = sum(len(c) for c in captured)
                if total >= count:
                    collection_done.set()

        try:
            if not self.start_rx(cb, requester=requester):
                return None
            
            # Wait for data
            if not collection_done.wait(timeout):
                # Timeout
                pass
                
        except Exception as e:
            logger.error(f"Capture error: {e}")
        finally:
            self.stop(requester=requester)
            
        # Process samples
        if not captured: return None
        full = np.concatenate(captured)
        if len(full) > count:
            full = full[:count]
        return full

    def start_tx(self, filepath: Path, mode: str, repeat: bool, requester: str = "api") -> bool:
        with self.lock:
            # Idempotency check
            if self.state == SDRState.TX_RUNNING:
                return True
                
            # System-Level State Check
            try:
                if system_state_manager.state != SystemState.TX:
                    system_state_manager.assert_idle()
                    system_state_manager.transition(SystemState.TX, requester=requester)
            except RuntimeError as e:
                logger.error(f"System state violation: {e}")
                raise
             
            # Hard Block
            if self.rx_manager.is_running():
                system_state_manager.transition(SystemState.IDLE, requester=requester)
                raise RuntimeError("Cannot start TX while RX is active")
                
            if self.state != SDRState.CONFIGURED:
                system_state_manager.transition(SystemState.IDLE, requester=requester)
                raise RuntimeError(f"Cannot start TX from {self.state.name}")
                
            self.flags.lock_owner = requester
            self.flags.current_operation = mode
            
            self._atomic_transition(SDRState.TX_STARTING)

            args = [
                'hackrf_transfer', '-t', str(filepath),
                '-f', str(int(self.config.frequency_hz)),
                '-s', str(int(self.config.sample_rate_hz)),
                '-a', '1' if self.config.amp_enabled else '0',
                '-x', str(min(47, self.config.vga_gain_db)) # Safety Clamp
            ]
            if repeat: args.append('-R')
            
            if not self.tx_manager.start(args, capture_stdout=False):
                self._atomic_transition(SDRState.ERROR, error={"code": "PROCESS_FAIL", "message": "Failed to start hackrf_transfer (TX)"})
                system_state_manager.set_error("TX process failed to start")
                return False

            self._atomic_transition(SDRState.TX_RUNNING)
             
            # TX Watchdog
            threading.Timer(
                self.config.max_tx_seconds,
                lambda: self.stop_force() if self.state == SDRState.TX_RUNNING else None
            ).start()

            event_bus.emit('operation_started_device', { 
                "operation": mode,
                "pid": self.tx_manager.process.pid if self.tx_manager.process else None
            })
            
            # Emit system state change event
            event_bus.emit("system_state_changed", {
                "from": "IDLE",
                "to": "TX",
                "operation": mode
            })
            
            return True

    def stop(self, requester: str = None):
        with self.lock:
            # Idempotency - already stopped states
            if self.state in {SDRState.CLOSED, SDRState.OPEN, SDRState.CONFIGURED}:
                return

            # Permission check
            if requester and self.flags.lock_owner and self.flags.lock_owner != requester:
                 raise PermissionError(f"Stop denied: Owned by {self.flags.lock_owner}")

            # Only stop if in a running/starting state
            if self.state not in {
                SDRState.RX_RUNNING,
                SDRState.TX_RUNNING,
                SDRState.RX_STARTING,
                SDRState.TX_STARTING,
            }:
                return

            op_stopping = self.flags.current_operation

            if op_stopping:
             event_bus.emit("operation_stopped_device", {
                 "operation": op_stopping
             })
             
            # FSM-compliant transition
            self._atomic_transition(SDRState.STOPPING)
            self.stop_force()
            self._atomic_transition(SDRState.CONFIGURED)

            self.flags.lock_owner = None
            self.flags.current_operation = None
            
            # Transition system state back to IDLE
            try:
                if system_state_manager.get_state() in {SystemState.RX, SystemState.TX}:
                    system_state_manager.transition(SystemState.IDLE, requester=requester or "system")
                    event_bus.emit("system_state_changed", {
                        "from": system_state_manager.get_state().value,
                        "to": "IDLE",
                        "operation": op_stopping
                    })
            except Exception as e:
                logger.warning(f"SystemState transition error during stop: {e}")

    def stop_force(self):
        self.stop_signal.set()
        
        # Stop RX Bus
        rx_bus.stop()
        
        if self.rx_thread and self.rx_thread.is_alive():
             self.rx_thread.join(timeout=1.0)
        
        self.rx_manager.stop()
        self.tx_manager.stop()

    def record_signal(self, filepath: str, duration_sec: float, requester: str = "api") -> bool:
        """Timed capture to file (Device Layer)"""
        with self.lock:
             try:
                 system_state_manager.assert_idle()
                 system_state_manager.transition(SystemState.RX, requester=requester)
             except RuntimeError as e:
                 logger.error(f"System state violation for recording: {e}")
                 raise
             
             if self.tx_manager.is_running():
                 system_state_manager.transition(SystemState.IDLE, requester=requester)
                 raise RuntimeError("Cannot record while TX active")

             self.flags.lock_owner = requester
             self._atomic_transition(SDRState.RX_STARTING)
             
             num_samples = int(duration_sec * self.config.sample_rate_hz)
             args = [
                 'hackrf_transfer', '-r', str(filepath),
                 '-f', str(int(self.config.frequency_hz)),
                 '-s', str(int(self.config.sample_rate_hz)),
                 '-n', str(num_samples),
                 '-l', str(self.config.lna_gain_db),
                 '-g', str(self.config.vga_gain_db)
             ]
             if self.config.amp_enabled: args.extend(['-a', '1'])
             
             logger.info(f"[Device] Timed recording: {duration_sec}s to {filepath}")
             success = self.rx_manager.start(args, capture_stdout=False)
             if not success:
                  self._atomic_transition(SDRState.ERROR)
                  system_state_manager.set_error("Failed to start timed recording")
                  return False
             
             self._atomic_transition(SDRState.RX_RUNNING)
             
             # Wait for completion (blocking for recording)
             wait_start = time.time()
             while self.rx_manager.is_running():
                 if time.time() - wait_start > duration_sec + 5.0:
                     logger.error("Timed recording hung - killing")
                     self.rx_manager.stop()
                     break
                 time.sleep(0.1)
             
             self._atomic_transition(SDRState.CONFIGURED)
             system_state_manager.transition(SystemState.IDLE, requester=requester)
             return True

    def replay_signal(self, filepath: str, requester: str = "api") -> bool:
        """Timed replay (Device Layer)"""
        return self.start_tx(filepath, mode="replay", repeat=False, requester=requester)

    def _report_error(self, code: str, message: str):
        err = {
            "code": code,
            "severity": "fatal",
            "message": message,
            "timestamp": int(time.time()),
            "state": self.state.name
        } 
        self._atomic_transition(SDRState.ERROR, error=err)
        event_bus.emit('error', err)

    def _rx_loop_select(self):
        proc = self.rx_manager.process
        if not proc or not proc.stdout: return
        
        chunk_size = 262144 
        remainder = b''
        fd = proc.stdout.fileno()
        
        emitted_start = False
        
        try:
            while not self.stop_signal.is_set():
                if proc.poll() is not None:
                     # Zombie Detection
                     if not emitted_start:
                         event_bus.emit('fault', {
                             "type": "rx_process_died",
                             "pid": proc.pid
                         })
                         self._report_error("PROCESS_DIED", "RX Process died unexpectedly")
                     break

                r, _, _ = select.select([fd], [], [], 0.05)
                
                if fd in r:
                    try:
                        data = proc.stdout.read(chunk_size)
                    except BlockingIOError:
                        data = b''
                    
                    if not data: 
                        if data == b'': 
                             if proc.poll() is not None: break
                        continue
                        
                    if not emitted_start:
                        self.op_started_event.set()
                        emitted_start = True
                         
                    if remainder:
                         data = remainder + data
                         remainder = b''
                    
                    if len(data) % 2 != 0:
                         remainder = data[-1:]
                         data = data[:-1]
                    
                    if not data: continue
                    
                    floats = np.frombuffer(data, dtype=np.int8).astype(np.float32) / 128.0
                    c64 = floats[0::2] + 1j * floats[1::2]
                    
                    # Update Stats
                    self.flags.rx_bytes += len(data)
                    self.flags.rx_samples += len(c64)
                    
                    # Call user callback (legacy)
                    if self.sample_callback:
                        try:
                            self.sample_callback(c64)
                        except:
                            pass 
                    
                    # Push to RX Bus for decoder pipeline (non-blocking)
                    rx_bus.push(c64) 
                else: 
                     time.sleep(0.001)
                        
        except Exception as e:
            logger.error(f"RX Loop Error: {e}")
        finally:
            pass

# ============================================================================
# 5. CONTROLLER WRAPPER
# ============================================================================

class SDRController:
    """Singleton-like wrapper for the HackRFDevice"""
    def __init__(self):
        self.device = HackRFDevice()
        
    # --- PROXY METHODS ---
    def open(self) -> bool: return self.device.open()
    def close(self): self.device.close()
    
    @property 
    def is_open(self): 
        return self.device.state != SDRState.CLOSED

    @property
    def current_config(self):
        return self.device.config

    def set_frequency(self, freq_hz: float, sample_rate: float = 2e6) -> bool:
        if not self.device.open():
            logger.error("Failed to open device for frequency set")
            return False
        
        try:
            # User Requested MAX Power/Sensitivity
            # LNA: 40 (Max), VGA: 62 (Max)
            cfg = HackRFConfig(int(freq_hz), int(sample_rate), 40, 62)
            
            # Ensure we are in a configurable state
            if self.device.state not in {SDRState.OPEN, SDRState.CONFIGURED}:
                 # Try to force stop if stuck in running
                 if self.device.state in {SDRState.RX_RUNNING, SDRState.TX_RUNNING}:
                     self.device.stop()
                 else:
                     return False
                     
        except Exception as e:
            logger.error(f"Invalid frequency config: {e}")
            return False
            
        with self.device.lock:
             was_rx = self.device.state == SDRState.RX_RUNNING
             was_tx = self.device.state == SDRState.TX_RUNNING
             owner = self.device.flags.lock_owner
             cb = self.device.sample_callback
             
             try:
                 if was_rx or was_tx:
                     self.device.stop(owner)
                     
                 self.device.configure(cfg)
                 
                 if was_rx and owner:
                     self.device.start_rx(cb, owner)
                 return True
             except Exception as e:
                 logger.error(f"Failed to set frequency: {e}")
                 return False

    def set_sample_rate(self, hz: float) -> bool:
        freq = self.device.config.frequency_hz if self.device.config else 433.92e6
        return self.set_frequency(freq, sample_rate=hz)

    def set_gain(self, db: int) -> bool:
        """Update VGA gain (compatibility for AutoRollJam)"""
        if not self.device.config: return False
        with self.device.lock:
            # We recreate config to ensure all invariants are checked
            new_cfg = HackRFConfig(
                frequency_hz=self.device.config.frequency_hz,
                sample_rate_hz=self.device.config.sample_rate_hz,
                lna_gain_db=self.device.config.lna_gain_db,
                vga_gain_db=int(db),
                amp_enabled=self.device.config.amp_enabled
            )
            try:
                self.device.configure(new_cfg)
                return True
            except:
                return False

    def status(self) -> Dict[str, Any]:
        """Minimal status for heartbeat"""
        snapshot = self.device.get_snapshot()
        return {
            "present": snapshot['device_state'] != "CLOSED", 
            "busy": snapshot['device_state'] in {"RX_RUNNING", "TX_RUNNING", "RX_STARTING", "TX_STARTING"},
            "driver": "hackrf",
            "rx_active": snapshot['health']['rx_active'],
            "tx_active": snapshot['device_state'] == "TX_RUNNING",
            "state": snapshot['device_state']
        }

    def get_state_snapshot(self):
        return self.device.get_snapshot()

    def configure(self, params: dict):
        cfg = HackRFConfig(**params)
        self.device.configure(cfg)

    def start_rx(self, callback: Callable, requester: str = "api") -> Any:
        # If requester is internal logic expecting bool...
        if requester in ["rolljam", "internal"]:
             return self.device.start_rx(callback, requester)
             
        op = operation_manager.create("rx_stream")
        
        event_bus.emit("operation_started", {
            "id": op.id,
            "name": op.name,
            "timestamp": op.started_at
        })
        
        try:
            op.state = OperationState.STARTING
            success = self.device.start_rx(callback, requester)
            if not success:
                 raise RuntimeError("Device refused start_rx")
            
            op.state = OperationState.RUNNING
            return {"status": "started", "operation_id": op.id}

        except Exception as e:
            op.state = OperationState.FAILED
            op.error = str(e)
            event_bus.emit("operation_failed", {
                "id": op.id,
                "error": str(e)
            })
            operation_manager.remove(op.id)
            raise e

    def capture_samples(self, count: int, requester: str = "internal", timeout: float = 2.0) -> Optional[np.ndarray]:
        if self.device.state != SDRState.CONFIGURED:
            raise RuntimeError("SDR busy or not configured")
        return self.device.capture_samples(count, requester, timeout)
        
    def get_capabilities(self):
        """Report current capabilities based on hardware state"""
        ready = self.device.state in {SDRState.CONFIGURED, SDRState.OPEN}
        return {
            "rx": True,
            "tx": True,
            "jam": True,
            "record": True,
            "replay": True,
            "busy": not ready,
            "state": self.device.state.name
        }

    def stop_rx(self, requester: str = "api"):
        self.device.stop(requester)
        
        op = operation_manager.get_running_by_name("rx_stream")
        if op:
             op.state = OperationState.ABORTED
             event_bus.emit("operation_aborted", {
                 "id": op.id,
                 "reason": "user_stop"
             })
             operation_manager.remove(op.id)

    def start_tx(self, filepath: Path, repeat: bool, requester: str = "api", mode: str = "tx_file") -> Any:
        # Internal compatibility
        if requester in ["rolljam", "internal", "jamming"]:
             return self.device.start_tx(filepath, mode, repeat, requester)

        op = operation_manager.create(mode) # "tx_file" or "jam_noise"
        
        event_bus.emit("operation_started", {
            "id": op.id,
            "name": op.name,
            "timestamp": op.started_at
        })
        
        try:
            op.state = OperationState.STARTING
            success = self.device.start_tx(filepath, mode, repeat, requester)
            if not success:
                 raise RuntimeError("Device refused start_tx")

            op.state = OperationState.RUNNING
            return {"status": "started", "operation_id": op.id}
            
        except Exception as e:
            op.state = OperationState.FAILED
            op.error = str(e)
            event_bus.emit("operation_failed", {
                "id": op.id,
                "error": str(e)
            })
            operation_manager.remove(op.id)
            raise e

    def stop_tx(self, requester: str = "api"):
         self.device.stop(requester)
         # Cleanup
         op = operation_manager.get_running_by_name("tx_file") or operation_manager.get_running_by_name("jam_noise")
         if op:
             op.state = OperationState.ABORTED
             event_bus.emit("operation_aborted", {
                 "id": op.id,
                 "reason": "user_stop"
             })
             operation_manager.remove(op.id)

    def stop(self, requester: str = "api", operation_id: str = None):
         if operation_id:
             op = operation_manager.get(operation_id)
             if not op:
                 return
             
             op.state = OperationState.STOPPING
             self.device.stop(requester)
             
             op.state = OperationState.ABORTED
             event_bus.emit("operation_aborted", {
                 "id": op.id,
                 "reason": "user_stop"
             })
             operation_manager.remove(op.id)
         else:
             self.device.stop(requester)

    def start_jamming(self, freq_hz: float, requester: str = "jamming"):
        jam_file = Path("modules/jamming_noise.cs8") 
        if not jam_file.parent.exists(): jam_file.parent.mkdir(exist_ok=True)
        
        if not jam_file.exists():
             noise = (np.random.uniform(-1, 1, 200000) * 127).astype(np.int8)
             with open(jam_file, "wb") as f:
                 f.write(noise.tobytes())
        
        self.set_frequency(freq_hz) 
        
        return self.start_tx(jam_file, repeat=True, requester=requester, mode="jam_noise")

    def record_signal(self, filepath: str, duration: float, freq: float, sample_rate: float, requester: str = "api") -> bool:
        """High-level timed record"""
        self.configure({"frequency_hz": freq, "sample_rate_hz": sample_rate})
        return self.device.record_signal(filepath, duration, requester=requester)

    def replay_signal(self, filepath: str, freq: float, sample_rate: float, requester: str = "api") -> bool:
        """High-level replay"""
        self.configure({"frequency_hz": freq, "sample_rate_hz": sample_rate})
        return self.device.replay_signal(filepath, requester=requester)

    def transmit_file(self, filepath: str, freq: float, sample_rate: float, requester: str = "api") -> bool:
        """Alias for replay_signal to support BruteForce module"""
        return self.replay_signal(filepath, freq, sample_rate, requester=requester)

    def stop_jamming(self, requester: str = "jamming"):
        try:
             return self.device.stop_tx(requester) # Changed to proxy to device.stop_tx
        except:
             pass
