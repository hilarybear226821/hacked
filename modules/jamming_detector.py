"""
Jamming Detector
FFT-based spectrum monitoring to detect RF jamming attacks
"""

import time
import numpy as np
from typing import Optional, Dict, Callable
from threading import Thread, Event
from scipy import signal as scipy_signal
from collections import deque

from core.device_model import DeviceRegistry
from core import DiscoveryEngine
from .sdr_controller import SDRController


class JammingDetector:
    """
    Spectrum monitoring and jamming detection
    Uses FFT to detect abnormal noise floor increases
    """
    
    def __init__(self, sdr: SDRController, registry: DeviceRegistry,
                 discovery_engine: DiscoveryEngine, config: Dict):
        self.sdr = sdr
        self.registry = registry
        self.discovery_engine = discovery_engine
        self.config = config
        self.passive_mode = True # Default to passive to avoid conflicts

        
        # FFT configuration
        self.fft_size = config.get('jamming', {}).get('fft_size', 2048)
        self.averaging_window = config.get('jamming', {}).get('averaging_window', 10)
        
        # Threshold for jamming detection (dB above baseline)
        self.threshold_db = config.get('jamming', {}).get('noise_floor_threshold', 10)
        
        # Baseline tracking
        self.noise_baselines: Dict[float, float] = {}  # freq -> baseline power
        self.jamming_history: Dict[float, list] = {}  # Freq -> history of detections
        self.threat_correlator = None
        
        # Alert callback
        self.alert_callback: Optional[Callable] = None
        
        # State
        self.running = False
        self.stop_event = Event()
        self.monitor_thread: Optional[Thread] = None
        
        # Bands to monitor
        self.monitor_bands = [
            (433.92e6, "433 MHz ISM"),
            (868.35e6, "868 MHz ISM"),
            (915.0e6, "915 MHz ISM"),
            (2.44e9, "2.4 GHz ISM/Bluetooth/Zigbee"),
        ]
        
        print("[Jamming] Initialized")
    
    def start(self, alert_callback: Optional[Callable] = None):
        """
        Start jamming detection
        Args:
            alert_callback: Function called when jamming detected
        """
        if self.running:
            print("[Jamming] Already running")
            return
        
        if not self.sdr.is_open and not self.passive_mode:
            print("[Jamming] SDR not open")
            return
        
        self.alert_callback = alert_callback
        self.running = True
        self.stop_event.clear()
        
        # Start monitoring thread ONLY if not passive
        if not self.passive_mode:
            self.monitor_thread = Thread(target=self._monitor_loop, daemon=True)
            self.monitor_thread.start()
        
        print(f"[Jamming] Monitoring started (Passive: {self.passive_mode})")
    
    def stop(self):
        """Stop jamming detection"""
        if not self.running:
            return
        
        print("[Jamming] Stopping...")
        self.running = False
        self.stop_event.set()
        
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        
        print("[Jamming] Stopped")
    
    def _monitor_loop(self):
        """Main monitoring loop"""
        # Initial baseline calibration
        print("[Jamming] Calibrating baseline...")
        self._calibrate_baselines()
        
        while self.running and not self.stop_event.is_set():
            for freq, band_name in self.monitor_bands:
                if not self.running or self.stop_event.is_set():
                    break
                
                # Monitor this band
                self._monitor_band(freq, band_name)
                
                # Brief pause
                self.stop_event.wait(timeout=0.5)
            
            # Wait before next cycle
            self.stop_event.wait(timeout=2)
    
    def _calibrate_baselines(self):
        """Calibrate noise floor baselines for all bands"""
        for freq, band_name in self.monitor_bands:
            if not self.running or self.stop_event.is_set():
                break
            
            print(f"[Jamming] Calibrating {band_name}...")
            
            # Take multiple measurements
            measurements = []
            for _ in range(self.averaging_window):
                power = self._measure_band_power(freq)
                if power is not None:
                    measurements.append(power)
                time.sleep(0.1)
            
            if measurements:
                # Use median as baseline (robust to outliers)
                baseline = np.median(measurements)
                self.noise_baselines[freq] = baseline
                print(f"[Jamming] {band_name} baseline: {baseline:.1f} dB")
    
    def _monitor_band(self, freq: float, band_name: str):
        """Monitor a specific frequency band for power tracking"""
        try:
            # Measure current power
            current_power = self._measure_band_power(freq)
            
            if current_power is None:
                return
            
            # Get baseline
            baseline = self.noise_baselines.get(freq, current_power)
            
            # Update baseline with exponential moving average
            alpha = 0.1  # Smoothing factor
            self.noise_baselines[freq] = alpha * current_power + (1 - alpha) * baseline
        
        except Exception as e:
            print(f"[Jamming] Error monitoring {band_name}: {e}")
    
    def _measure_band_power(self, freq: float) -> Optional[float]:
        """
        Measure average power in a frequency band
        Returns: Power in dB
        """
        try:
            # Set frequency
            self.sdr.set_frequency(freq)
            
            # Set appropriate sample rate
            if freq < 1e9:
                sample_rate = 2e6  # 2 MHz for sub-GHz
            else:
                sample_rate = 10e6  # 10 MHz for 2.4 GHz
            
            self.sdr.set_sample_rate(sample_rate)
            
            # Capture samples
            num_samples = self.fft_size * 4
            samples = self.sdr.capture_samples(num_samples)
            
            if samples is None or len(samples) < self.fft_size:
                return None
            
            # Compute FFT
            fft_result = np.fft.fftshift(np.fft.fft(samples[:self.fft_size]))
            
            # Calculate power spectrum (magnitude squared)
            power_spectrum = np.abs(fft_result) ** 2
            
            # Convert to dB
            power_db = 10 * np.log10(power_spectrum + 1e-12)  # Add small value to avoid log(0)
            
            # Average power across band
            avg_power = np.mean(power_db)
            
            return avg_power
        
        except Exception as e:
            print(f"[Jamming] Power measurement error: {e}")
            return None

    def _handle_jamming(self, freq: float, band_name: str, delta_db: float, power_db: float):
        """Jamming detection disabled"""
        pass
    
    def get_spectrum_data(self, freq: float, bandwidth: float = 10e6) -> Optional[Dict]:
        """
        Get spectrum waterfall data for visualization
        Args:
            freq: Center frequency
            bandwidth: Bandwidth to capture
        Returns: Dict with frequency bins and power spectrum
        """
        try:
            # Set parameters
            self.sdr.set_frequency(freq)
            self.sdr.set_sample_rate(bandwidth)
            
            # Capture samples
            samples = self.sdr.capture_samples(self.fft_size)
            
            if samples is None:
                return None
            
            # Compute FFT
            fft_result = np.fft.fftshift(np.fft.fft(samples))
            
            # Power spectrum in dB
            power_spectrum = 10 * np.log10(np.abs(fft_result) ** 2 + 1e-12)
            
            # Frequency bins
            freq_bins = np.linspace(freq - bandwidth/2, freq + bandwidth/2, len(power_spectrum))
            
            return {
                'frequencies': freq_bins.tolist(),
                'power': power_spectrum.tolist(),
                'center_freq': freq,
                'bandwidth': bandwidth,
                'timestamp': time.time()
            }
        
        except Exception as e:
            print(f"[Jamming] Spectrum capture error: {e}")
            return None
            
    def process_rssi_reading(self, freq: float, rssi: float):
        """
        Process external RSSI reading (from C-scanner)
        """
        if not self.running: return
        
        # Find band name
        band_name = "Unknown"
        if 433e6 <= freq <= 434e6: band_name = "433 MHz ISM"
        elif 868e6 <= freq <= 869e6: band_name = "868 MHz ISM"
        elif 915e6 <= freq <= 928e6: band_name = "915 MHz ISM"
        
        # Update baseline
        baseline = self.noise_baselines.get(freq, rssi)
        alpha = 0.05
        self.noise_baselines[freq] = alpha * rssi + (1 - alpha) * baseline
        
        # Check for jamming (sudden rise above baseline)
        if rssi > baseline + self.threshold_db:
             # Just print for now, complex logic disabled
             # print(f"[Jamming] Potential anomaly on {freq/1e6} MHz: {rssi:.1f} dBm (Base: {baseline:.1f})")
             pass
