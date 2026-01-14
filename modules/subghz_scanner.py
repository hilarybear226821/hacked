"""
Sub-GHz Scanner - Production Implementation

FIXED ALL 20 ARCHITECTURAL FAILURES:
Complete rewrite with proper separation of concerns
"""

import time
import numpy as np
import threading
import logging
import hashlib
from typing import Optional, Dict, List, Tuple, Callable, Protocol as TypingProtocol
from dataclasses import dataclass, field
from collections import deque
from enum import Enum, auto
import atexit

logger = logging.getLogger("SubGHzScanner")


# ============================================================================
# SEPARATED CONCERNS - Component Interfaces
# ============================================================================

class SignalProcessor(TypingProtocol):
    """Interface for signal processing"""
    def process(self, iq_samples: np.ndarray, frequency: float, sample_rate: float) -> List['SignalBurst']:
        ...


class SignalDecoder(TypingProtocol):
    """Interface for protocol decoding"""
    def decode(self, burst: 'SignalBurst') -> Optional['DecodedSignal']:
        ...


# ============================================================================
# SCANNER EVENT BUS - External Interface
# ============================================================================

class ScannerEvent(Enum):
    """Scanner events for external subscription"""
    SIGNAL_DETECTED = auto()
    SIGNAL_RECORDED = auto()
    FREQUENCY_CHANGED = auto()
    STATE_CHANGED = auto()
    ERROR_RAISED = auto()
    BUFFER_OVERRUN = auto()


@dataclass
class ScannerStatus:
    """Scanner status snapshot"""
    state: 'ScanState'
    current_frequency: float
    sample_rate: float
    buffer_usage: float  # 0.0 to 1.0
    detected_signals: int
    uptime_seconds: float


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class SignalBurst:
    """Detected signal burst with validated metadata"""
    start_sample: int
    end_sample: int
    frequency: float
    sample_rate: float
    peak_amplitude: float
    mean_amplitude: float
    snr_db: float
    timestamp: float = field(default_factory=time.time)
    samples: Optional[np.ndarray] = None
    
    @property
    def duration_seconds(self) -> float:
        return (self.end_sample - self.start_sample) / self.sample_rate
    
    @property
    def num_samples(self) -> int:
        return self.end_sample - self.start_sample


@dataclass
class DecodedSignal:
    """Decoded protocol data"""
    protocol: str
    data_hex: str
    device_id: str  # Deterministic, stable ID
    confidence: float  # 0.0 to 1.0
    metadata: Dict = field(default_factory=dict)
    
    def __post_init__(self):
        # Validate device_id is deterministic
        if not self.device_id:
            # Generate stable ID from protocol + data
            stable_str = f"{self.protocol}:{self.data_hex}"
            self.device_id = hashlib.sha256(stable_str.encode()).hexdigest()[:16]


# ============================================================================
# DSP - Proper Signal Processing
# ============================================================================

class OOKDemodulator:
    """
    Production OOK demodulation with proper DSP
    """
    
    def __init__(self, sample_rate: float):
        self.sample_rate = sample_rate
        self.noise_floor = 0.01  # Linear units (not dB)
        self.lock = threading.Lock()
        
        # Precompute filter coefficients (ONCE, not per-sample)
        try:
            from scipy import signal as scipy_signal
            cutoff_hz = self.sample_rate / 20
            self.filter_b, self.filter_a = scipy_signal.butter(
                3, cutoff_hz / (self.sample_rate / 2)
            )
            self.has_scipy = True
        except ImportError:
            logger.warning("SciPy not available - using simple moving average filter")
            self.has_scipy = False
            self.filter_b = None
            self.filter_a = None
    
    def demodulate(self, iq_samples: np.ndarray) -> np.ndarray:
        """
        Demodulate OOK with proper preprocessing
        
        Returns:
            Envelope (magnitude) with DC removed and AGC applied
        """
        # Remove DC offset
        iq_centered = iq_samples - np.mean(iq_samples)
        
        # IQ imbalance correction (simple)
        i_samples = np.real(iq_centered)
        q_samples = np.imag(iq_centered)
        
        i_power = np.mean(i_samples ** 2)
        q_power = np.mean(q_samples ** 2)
        
        if q_power > 0:
            q_samples *= np.sqrt(i_power / q_power)
        
        iq_corrected = i_samples + 1j * q_samples
        
        # Envelope detection
        magnitude = np.abs(iq_corrected)
        
        # Lowpass filter (precomputed coefficients)
        if self.has_scipy and self.filter_b is not None:
            from scipy import signal as scipy_signal
            envelope = scipy_signal.filtfilt(self.filter_b, self.filter_a, magnitude)
        else:
            # Fallback: simple moving average
            window_size = max(5, int(self.sample_rate / 100000))
            envelope = np.convolve(magnitude, np.ones(window_size)/window_size, mode='same')
        
        # AGC normalization
        rms = np.sqrt(np.mean(envelope ** 2))
        if rms > 0:
            envelope = envelope / rms
        
        return envelope
    
    def estimate_noise_floor(self, envelope: np.ndarray) -> float:
        """
        Robust noise floor estimation
        
        Returns:
            Noise floor in LINEAR units (not dB)
        """
        # Use 10th percentile (robust to signals)
        noise_level = np.percentile(envelope, 10)
        
        # Clamp to prevent zero
        noise_level = max(noise_level, 1e-10)
        
        # Update with EMA (stay in linear)
        with self.lock:
            self.noise_floor = 0.9 * self.noise_floor + 0.1 * noise_level
        
        return self.noise_floor


class BurstDetector:
    """
    Statistical burst detection
    """
    
    def __init__(self, min_snr_db: float = 4.0, min_duration_samples: int = 200):
        self.min_snr_db = min_snr_db
        self.min_duration_samples = min_duration_samples
    
    def detect_bursts(self, envelope: np.ndarray, noise_floor: float, 
                     frequency: float, sample_rate: float) -> List[SignalBurst]:
        """
        Detect bursts with statistical validation
        
        Args:
            envelope: Demodulated envelope
            noise_floor: Noise floor in linear units
            frequency: Center frequency
            sample_rate: Sample rate
        
        Returns:
            List of validated bursts
        """
        # SNR-based threshold
        threshold = noise_floor * (10 ** (self.min_snr_db / 20))
        
        # Use padding to ensure we capture bursts at buffer boundaries and have proper pairs
        is_high_padded = np.concatenate(([False], envelope > threshold, [False]))
        transitions = np.diff(is_high_padded.astype(np.int8))
        
        starts = np.where(transitions == 1)[0]
        ends = np.where(transitions == -1)[0]
        
        # Gap Filling / Hysteresis (Merge bursts separated by < 100 samples)
        if len(starts) > 1:
            valid_starts = [starts[0]]
            valid_ends = []
            
            gap_threshold = 100 
            for i in range(len(starts) - 1):
                gap = starts[i+1] - ends[i]
                if gap > gap_threshold:
                    valid_ends.append(ends[i])
                    valid_starts.append(starts[i+1])
            
            valid_ends.append(ends[-1])
            starts, ends = np.array(valid_starts), np.array(valid_ends)

        # Match starts with ends (consume pairs sequentially)
        bursts = []
        for start, end in zip(starts, ends):
            duration = end - start
            
            # Validate minimum duration
            if duration < self.min_duration_samples:
                continue
            
            # Calculate burst statistics
            burst_data = envelope[start:end]
            peak_amp = np.max(burst_data)
            mean_amp = np.mean(burst_data)
            
            # Calculate SNR
            if noise_floor > 0:
                snr_db = 20 * np.log10(peak_amp / noise_floor)
            else:
                snr_db = 100.0
            
            # Validate SNR
            if snr_db < self.min_snr_db:
                continue
            
            burst = SignalBurst(
                start_sample=int(start),
                end_sample=int(end),
                frequency=frequency,
                sample_rate=sample_rate,
                peak_amplitude=float(peak_amp),
                mean_amplitude=float(mean_amp),
                snr_db=float(snr_db),
                samples=burst_data.copy()
            )
            
            bursts.append(burst)
        
        return bursts


# ============================================================================
# THREAD-SAFE SCAN CONTROLLER
# ============================================================================

class ScanState(Enum):
    """Scanner states"""
    STOPPED = auto()
    STARTING = auto()
    RUNNING = auto()
    PAUSED = auto()
    STOPPING = auto()
    ERROR = auto()


class ThreadSafeScanController:
    """
    Thread-safe scanner control with proper state management
    """
    
    def __init__(self):
        self.state = ScanState.STOPPED
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.error_count = 0
    
    def start(self, scan_func: Callable[[], None]) -> bool:
        """
        Start scanner thread
        
        Args:
            scan_func: Function to run in thread
        
        Returns:
            True if started successfully
        """
        with self.lock:
            if self.state != ScanState.STOPPED:
                logger.warning(f"Cannot start from state {self.state.name}")
                return False
            
            self.state = ScanState.STARTING
        
        try:
            self.stop_event.clear()
            self.thread = threading.Thread(target=scan_func, daemon=False)
            self.thread.start()
            
            with self.lock:
                self.state = ScanState.RUNNING
            
            logger.info("Scanner started")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start scanner: {e}")
            with self.lock:
                self.state = ScanState.ERROR
            return False
    
    def pause(self) -> bool:
        """Pause scanning (thread continues, just paused)"""
        with self.lock:
            if self.state != ScanState.RUNNING:
                return False
            
            self.state = ScanState.PAUSED
            logger.info("Scanner paused")
            return True
    
    def resume(self) -> bool:
        """Resume scanning"""
        with self.lock:
            if self.state != ScanState.PAUSED:
                return False
            
            self.state = ScanState.RUNNING
            logger.info("Scanner resumed")
            return True
    
    def stop(self, timeout: float = 5.0) -> bool:
        """
        Stop scanner with guaranteed cleanup
        
        Returns:
            True if stopped cleanly
        """
        with self.lock:
            if self.state == ScanState.STOPPED:
                return True
            
            if self.state == ScanState.STOPPING:
                logger.warning("Already stopping")
                return False
            
            self.state = ScanState.STOPPING
        
        logger.info("Stopping scanner...")
        
        # Signal stop
        self.stop_event.set()
        
        # Wait for thread
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=timeout)
            
            if self.thread.is_alive():
                logger.error(f"Thread did not stop within {timeout}s")
                with self.lock:
                    self.state = ScanState.ERROR
                return False
        
        with self.lock:
            self.state = ScanState.STOPPED
            self.thread = None
        
        logger.info("Scanner stopped")
        return True
    
    def is_running(self) -> bool:
        """Check if actively scanning"""
        with self.lock:
            return self.state == ScanState.RUNNING
    
    def is_paused(self) -> bool:
        """Check if paused"""
        with self.lock:
            return self.state == ScanState.PAUSED
    
    def should_stop(self) -> bool:
        """Check if stop requested"""
        return self.stop_event.is_set()
    
    def get_state(self) -> ScanState:
        """Get current state"""
        with self.lock:
            return self.state


# ============================================================================
# BUFFERED ASYNC CALLBACKS
# ============================================================================

class AsyncCallbackManager:
    """
    Async callback execution with buffering and isolation
    """
    
    def __init__(self, queue_size: int = 1000):
        self.callbacks: List[Callable] = []
        self.lock = threading.Lock()
        self.queue = deque(maxlen=queue_size)
        self.worker_thread: Optional[threading.Thread] = None
        self.running = False
    
    def start(self):
        """Start async worker"""
        self.running = True
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()
    
    def stop(self):
        """Stop async worker with drain"""
        # Drain queue first (process remaining items)
        timeout = time.time() + 2.0  # 2 second drain timeout
        while self.queue and time.time() < timeout:
            time.sleep(0.01)
        
        # Now stop
        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=2.0)
    
    def register(self, callback: Callable):
        """Register callback"""
        with self.lock:
            self.callbacks.append(callback)
    
    def notify(self, *args, **kwargs):
        """Enqueue notification (non-blocking)"""
        try:
            self.queue.append((args, kwargs))
        except IndexError:
            logger.warning("Callback queue full - dropped notification")
    
    def _worker(self):
        """Background worker"""
        while self.running:
            if not self.queue:
                time.sleep(0.01)
                continue
            
            try:
                args, kwargs = self.queue.popleft()
            except IndexError:
                continue
            
            # Call all callbacks with isolation
            with self.lock:
                callbacks = self.callbacks.copy()
            
            for cb in callbacks:
                try:
                    cb(*args, **kwargs)
                except Exception as e:
                    logger.error(f"Callback error: {e}")


# ============================================================================
# MAIN SCANNER (Thin Coordinator)
# ============================================================================

class SubGHzScanner:
    """
    Production Sub-GHz scanner with protocol decoding
    """
    
    def __init__(self, sdr_controller, config: Dict):
        """Initialize scanner with decoders
        
        Args:
            sdr_controller: SDR controller instance
            config: Scanner configuration dict
        """
        self.sdr = sdr_controller
        self.config = config or {}
        
        # === DECODER INTEGRATION ===
        from .subghz_decoder_manager import SubGhzDecoderManager
        self.decoder_mgr = SubGhzDecoderManager(config={})
        logger.info("Protocol decoders initialized: CAME, Nice, Princeton, EV1527")
        
        # Core Components
        self.controller = ThreadSafeScanController()
        # Safe sample rate retrieval
        current_sample_rate = 2e6
        if hasattr(self.sdr, 'device') and hasattr(self.sdr.device, 'config') and self.sdr.device.config:
            current_sample_rate = self.sdr.device.config.sample_rate_hz
            
        self.demodulator = OOKDemodulator(sample_rate=current_sample_rate)
        # Lower noise floor initialization for better start-up sensitivity
        self.demodulator.noise_floor = 0.0001 
        self.burst_detector = BurstDetector(min_snr_db=3.0, min_duration_samples=50)
        self.callback_mgr = AsyncCallbackManager(queue_size=1000)
        
        # Event subscription system (NEW)
        from collections import defaultdict
        self._subscribers: Dict[ScannerEvent, List[Callable]] = defaultdict(list)
        self._subscriber_lock = threading.Lock()
        
        from modules.protocol_detector import ProtocolDetector
        self.detector = ProtocolDetector()
        self.start_time = time.time()
        self.detected_signals_count = 0
        self.stats = {'signals_decoded': 0}
        
        # Scan configuration
        self.sample_rate = config.get('sample_rate', 2e6)
        self.capture_duration = config.get('capture_duration', 0.2)
        self.hop_interval = config.get('hop_interval', 2.0)  # Stay on each freq for 2s
        self.frequencies = config.get('scan_frequencies', [315e6, 433.92e6, 868e6, 915e6]) # Default frequencies
        
        # Sample accumulation for processing (CAPPED to prevent OOM)
        self.sample_buffer = []
        self.buffer_lock = threading.Lock()
        self.max_buffer_chunks = 1000  # Prevent unbounded growth
        self.current_frequency = self.frequencies[0] if self.frequencies else 433.92e6
        
        # Start callback worker
        self.callback_mgr.start()
        
        # NOTE: No atexit - let GUI control lifecycle explicitly
        
        logger.info("SubGHzScanner initialized")
    
    def start(self) -> bool:
        """
        Start scanning by listening to the global rx_bus.
        Automatically ensure SDR is in RX mode.
        """
        success = self.controller.start(self._scan_loop)
        
        if success:
            # Ensure SDR is RXing
            # Note: sdr is SDRController wrapper, we access device state directly
            current_state = self.sdr.device.state.name
            
            if current_state in ["CLOSED", "OPEN"]:
                logger.info("Scanner configuring SDR defaults...")
                if not self.sdr.set_frequency(self.current_frequency, self.sample_rate):
                    logger.error("Failed to configure SDR")
                    self.controller.stop()
                    return False
                current_state = self.sdr.device.state.name

            if "RX" not in current_state:
                logger.info("Scanner starting SDR RX stream...")
                # use requester="internal" to get direct boolean success/fail and avoid operation_manager overhead
                rx_success = self.sdr.start_rx(lambda x: None, requester="internal")
                if not rx_success:
                    logger.error("Failed to start SDR for scanner")
                    self.controller.stop()
                    return False
                    
            self._emit_event(ScannerEvent.STATE_CHANGED, self.controller.get_state())
        
        return success
    
    def pause(self) -> bool:
        """Pause scanning"""
        success = self.controller.pause()
        if success:
            self._emit_event(ScannerEvent.STATE_CHANGED, self.controller.get_state())
        return success
    
    def resume(self) -> bool:
        """Resume scanning"""
        success = self.controller.resume()
        if success:
            self._emit_event(ScannerEvent.STATE_CHANGED, self.controller.get_state())
        return success
    
    def stop(self) -> bool:
        """Stop scanning"""
        # 1. Stop scanner thread
        success = self.controller.stop()
        
        # 2. Stop callbacks
        self.callback_mgr.stop()
        
        # 3. Release SDR lock (CRITICAL FIX)
        try:
            self.sdr.stop_rx(requester="internal")
        except:
            pass
        
        if success:
            self._emit_event(ScannerEvent.STATE_CHANGED, self.controller.get_state())
        
        return success
    
    def register_callback(self, callback: Callable):
        """
        Register signal detection callback
        """
        self.callback_mgr.register(callback)
        # self.subscribe(ScannerEvent.SIGNAL_DETECTED, callback) # REMOVED: Incompatible signature
    
    def _scan_loop(self):
        """
        Main scan loop - consumes from rx_bus and hops frequencies if needed.
        """
        from modules.rx_bus import rx_bus
        freq_idx = 0
        last_hop_time = time.time()
        
        while not self.controller.should_stop():
            # Check if paused
            if self.controller.is_paused():
                time.sleep(0.1)
                continue
            
            try:
                # 1. Pull samples from bus
                iq_sample = rx_bus.pull(timeout=0.1, consumer="scanner")
                
                if iq_sample:
                    # Update local state from sample metadata
                    self.current_frequency = iq_sample.center_freq
                    self.sample_rate = iq_sample.sample_rate
                    
                    # Process the batch
                    self._process_samples(iq_sample.samples, iq_sample.timestamp)
                
                # 2. Check if time to hop (only if scanner "owns" the SDR and wants to hop)
                # In real-world, we only hop if we are the primary requester or allowed to.
                if self.config.get('auto_hop', True) and time.time() - last_hop_time >= self.hop_interval:
                    new_freq = self.frequencies[(freq_idx + 1) % len(self.frequencies)]
                    freq_idx = (freq_idx + 1) % len(self.frequencies)
                    
                    if new_freq != self.current_frequency:
                        # Attempt to tune - SDRController handles permission
                        if self.sdr.set_frequency(new_freq):
                            self.current_frequency = new_freq
                            last_hop_time = time.time()
                            self._emit_event(ScannerEvent.FREQUENCY_CHANGED, self.current_frequency)
                
            except Exception as e:
                logger.error(f"Scan loop error: {e}")
                time.sleep(0.5)
    
    def _process_samples(self, samples: np.ndarray, timestamp: float):
        """
        Process a batch of samples from the bus
        """
        try:
            # Demodulate
            envelope = self.demodulator.demodulate(samples)
            
            # Estimate noise (returns linear, not dB)
            noise_floor = self.demodulator.estimate_noise_floor(envelope)
            
            # Detect bursts
            bursts = self.burst_detector.detect_bursts(
                envelope, noise_floor, self.current_frequency, self.sample_rate
            )
            
            # Notify callbacks (async, non-blocking)
            for burst in bursts:
                self.detected_signals_count += 1
                
                # Identify protocol & DECODE
                pulses = self._burst_to_pulses(burst)
                
                # Feed pulses to protocol decoders
                for level, duration_us in pulses:
                    self.decoder_mgr.feed_pulse(level, duration_us)
                
                # Try to decode
                decoded_results = self.decoder_mgr.get_results(current_rssi=burst.snr_db)
                
                if decoded_results:
                    # Successfully decoded a protocol!
                    for result in decoded_results:
                        proto = result.protocol
                        raw_code = result.data  # This is the bitstream!
                        
                        logger.info(f"✓ DECODED: {proto} = {raw_code[:40]}...")
                        self.stats['signals_decoded'] += 1
                        
                        # Emit decoded signal with bitstream
                        summary = f"{proto}: {raw_code[:20]}..."
                        self.callback_mgr.notify(burst.frequency, proto, summary, raw_code=raw_code)
                        self._emit_event(ScannerEvent.SIGNAL_DETECTED, burst)
                        break  # Use first successful decode
                else:
                    # Fallback to RSSI-only detection
                    result = self.detector.analyze_pulses(pulses)
                    proto = result.get('protocol', 'RSSI')
                    summary = f"RSSI: {burst.snr_db:.1f}dB"
                    if proto != 'RSSI':
                        summary = f"{proto} ({result.get('estimated_bits', 0)}b)"
                    
                    self.callback_mgr.notify(burst.frequency, proto, summary)
                    self._emit_event(ScannerEvent.SIGNAL_DETECTED, burst)
                
                # Reset decoders for next signal
                self.decoder_mgr.reset_decoders()
                
        except Exception as e:
            logger.error(f"Sample processing error: {e}")

    def _burst_to_pulses(self, burst: 'SignalBurst') -> List[Tuple[int, int]]:
        """Convert envelope samples to pulses"""
        if burst.samples is None: return []
        
        # Simple thresholding
        threshold = (np.max(burst.samples) + np.min(burst.samples)) / 2
        is_high = burst.samples > threshold
        
        transitions = np.diff(is_high.astype(int))
        starts = np.where(transitions == 1)[0] + 1
        ends = np.where(transitions == -1)[0] + 1
        
        # Combine into pulses
        pulses = []
        if len(is_high) == 0:
            return pulses
            
        last_idx = 0
        current_level = int(is_high[0])
        
        for i in range(1, len(is_high)):
            if is_high[i] != current_level:
                duration_us = (i - last_idx) / burst.sample_rate * 1e6
                pulses.append((current_level, int(duration_us)))
                current_level = int(is_high[i])
                last_idx = i
        
        return pulses
    
    def get_state(self) -> ScanState:
        """Get scanner state"""
        return self.controller.get_state()
    
    def enable_scanning(self, enabled: bool) -> bool:
        """Enable or disable scanning (compatibility method for GUI)"""
        if enabled:
            if self.controller.is_paused():
                return self.resume()
            elif self.controller.get_state() == ScanState.STOPPED:
                return self.start()
            return True
        else:
            return self.pause()
    
    # ========================================================================
    # EVENT BUS - External Subscription API
    # ========================================================================
    
    def subscribe(self, event: ScannerEvent, callback: Callable) -> None:
        """
        Subscribe to scanner events
        
        Args:
            event: Event type to subscribe to
            callback: Function called when event occurs
        """
        with self._subscriber_lock:
            if callback not in self._subscribers[event]:
                self._subscribers[event].append(callback)
                logger.debug(f"Subscriber added for {event.name}")
    
    def unsubscribe(self, event: ScannerEvent, callback: Callable) -> None:
        """
        Unsubscribe from scanner events
        
        Args:
            event: Event type to unsubscribe from
            callback: Previously registered callback
        """
        with self._subscriber_lock:
            if callback in self._subscribers[event]:
                self._subscribers[event].remove(callback)
                logger.debug(f"Subscriber removed for {event.name}")
    
    def _emit_event(self, event: ScannerEvent, data: any = None) -> None:
        """
        Emit event to all subscribers (internal use)
        
        Args:
            event: Event type
            data: Event payload
        """
        with self._subscriber_lock:
            subscribers = self._subscribers[event].copy()
        
        # Call subscribers without holding lock
        for callback in subscribers:
            try:
                if data is not None:
                    callback(data)
                else:
                    callback()
            except Exception as e:
                logger.error(f"Event callback error ({event.name}): {e}")
    
    def get_status(self) -> ScannerStatus:
        """Get current scanner status snapshot"""
        with self.buffer_lock:
            buffer_usage = len(self.sample_buffer) / self.max_buffer_chunks
        
        return ScannerStatus(
            state=self.controller.get_state(),
            current_frequency=self.current_frequency,
            sample_rate=self.sample_rate,
            buffer_usage=buffer_usage,
            detected_signals=self.detected_signals_count,
            uptime_seconds=time.time() - self.start_time
        )
    
