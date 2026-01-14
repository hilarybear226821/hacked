
import time
import threading
from typing import Set, Dict
from core.device_model import DeviceRegistry

class AutoSubGhzEngine:
    """
    Autonomous Sub-GHz Active Scanner.
    cycles between key frequencies (315, 433.92) and records signals exceeding threshold.
    Bypasses passive scanner for reliability.
    """
    def __init__(self, scanner, registry=None, config=None, recorder=None, arbiter=None):
        # Handle Scanner vs SDR (GUI vs WebServer)
        if hasattr(scanner, 'sdr'): 
            self.subghz_scanner = scanner
            self.sdr = scanner.sdr 
        else: 
            self.subghz_scanner = None
            self.sdr = scanner
            
        self.registry = registry
        self.config = config or {}
        self.recorder = recorder
        self.arbiter = arbiter
        self.running = False
        self.lock = threading.Lock()
        
        # Targets for Active Scan
        self.scan_targets = [315.0e6, 433.92e6]
        
    def start(self):
        """Start the autonomous Sub-GHz active scanner"""
        if self.running: return
        self.running = True
        
        # Ensure passive scanner is OFF so we can control SDR
        if self.subghz_scanner and hasattr(self.subghz_scanner, 'scanning_active') and self.subghz_scanner.scanning_active:
            print("[Auto] Stopping passive scanner for Active Engine...")
            self.subghz_scanner.stop()
        
        t = threading.Thread(target=self._active_scan_loop, daemon=True)
        t.start()
        print("[Auto-SubGhz] Active Engine Started (Cycling 315/433 MHz)")

    def _active_scan_loop(self):
        """Cycle frequencies and capture if signal detected"""
        import numpy as np
        
        # Give time for cleanup
        time.sleep(1.0)
        
        while self.running:
            for freq in self.scan_targets:
                if not self.running: break
                
                try:
                    # 1. Tune
                    if not self.sdr.set_frequency(freq):
                         print(f"[Auto] Failed to set freq {freq}")
                         continue
                         
                    # 2. Measure RSSI (Quick Listen)
                    samples = self.sdr.capture_samples(80000) # 40ms sample
                    
                    if samples is None or len(samples) == 0:
                        continue
                        
                    # Calculate RSSI with balanced validation
                    magnitudes = np.abs(samples)
                    peak = np.max(magnitudes)
                    mean_power = np.mean(magnitudes)
                    rssi = 20 * np.log10(peak + 1e-6)
                    # SCANNER LOGIC: Trigger on OOK bursts (car fobs, doorbells)
                    # -70 dBm = Reasonable range (10-15 meters)
                    # 6x ratio = Clear burst pattern
                    power_ratio = peak / (mean_power + 1e-6)
                    
                    above_threshold = magnitudes > (mean_power * 2.5)
                    burst_samples = np.sum(above_threshold)
                    burst_ratio = burst_samples / len(magnitudes)
                    
                    # TRIGGER CONDITION
                    if rssi > -70 and power_ratio > 6.0 and 0.05 < burst_ratio < 0.6:
                        print(f"🚨 [DETECTION] Possible Key Fob at {freq/1e6} MHz")
                        print(f"   ↳ RSSI: {rssi:.1f} dBm, SNR: {power_ratio:.1f}x, Burst: {burst_ratio*100:.0f}%")
                        
                        # Bridge to arbiter for real-time app update
                        if self.arbiter:
                            self.arbiter.submit({
                                "decoder": "auto_engine",
                                "protocol": "OOK_Burst",
                                "confidence": 0.9,
                                "frame_id": f"autorf_{int(time.time()*1000)}",
                                "timestamp": time.time(),
                                "features": {"rssi": rssi, "snr": power_ratio, "freq": freq/1e6}
                            })
                            self.arbiter.finalize(f"autorf_{int(time.time()*1000)}")

                        self._trigger_capture(freq)
                        # Avoid double-triggering
                        time.sleep(2.0)
                    elif rssi > -75:  # Log near-misses if debug enabled
                        pass
                        
                except Exception as e:
                    print(f"⚠️ [Auto] Scan Error: {e}")
                    time.sleep(0.5)
                    
                time.sleep(0.2) # Fast cycle
                
    def _trigger_capture(self, freq):
        """Record the detected signal with validation"""
        try:
            import numpy as np
            
            name = f"Auto_{int(freq/1e6)}MHz_{int(time.time())}"
            print(f"[Auto] Validating signal on {freq/1e6} MHz...")
            
            # Pre-capture validation: ensure signal is still present
            samples = self.sdr.capture_samples(50000)  # 25ms check
            if samples is None or len(samples) == 0:
                print(f"[Auto] ❌ No data received, skipping")
                return
            
            # Validate signal quality
            magnitudes = np.abs(samples)
            peak = np.max(magnitudes)
            mean_power = np.mean(magnitudes)
            std_power = np.std(magnitudes)
            
            # Signal must have clear variation (not flat noise)
            signal_to_noise = peak / (mean_power + 1e-6)
            variation_ratio = std_power / (mean_power + 1e-6)
            
            # Require strong signal AND variation (indicating actual transmission)
            if signal_to_noise < 3.0 or variation_ratio < 0.3:
                print(f"[Auto] ❌ Invalid signal quality (SNR: {signal_to_noise:.1f}, Var: {variation_ratio:.2f})")
                return
            
            print(f"[Auto] ✓ Signal validated (SNR: {signal_to_noise:.1f}, Var: {variation_ratio:.2f})")
            print(f"[Auto] Recording '{name}'...")
            
            # Now record the full signal
            success = self.recorder.record(
                 name=name,
                 freq_mhz=freq/1e6, 
                 duration_sec=2.0
            )
            
            if success:
                 print(f"[Auto] ✅ Capture Saved. Ready for Replay.")
                 # Get last entry ID for confirmation
                 last = self.recorder.db[-1]
                 if last['name'] == name:
                     print(f"✅ [Auto] ID: {last['id']}")
                 
        except Exception as e:
            print(f"[Auto] Capture Failed: {e}")
            
    def stop(self):
        """Stop autonomous operations"""
        self.running = False
        # Explicitly stop SDR to release it immediately
        try:
            if hasattr(self.sdr, 'stop_rx'):
                self.sdr.stop_rx()
            elif hasattr(self.sdr, 'stop_streaming'):
                self.sdr.stop_streaming()
        except:
            pass
        print("[Auto-SubGhz] Stopped.")
