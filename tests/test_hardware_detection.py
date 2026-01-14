import sys
import os
import time
import numpy as np

sys.path.append(os.getcwd())

from modules.sdr_controller import SDRController
from modules.auto_rolljam import SignalDetector

def test_hardware():
    print("=== Testing Hardware Signal Detection ===")
    
    detector = SignalDetector(sample_rate=2e6)
    sdr = SDRController()
    
    if not sdr.open():
        print("❌ Failed to open SDR")
        sys.exit(1)
        
    print("✅ SDR Opened")
    
    # Configure for 315Mhz (common for fobs) or 433
    freq = 433.92e6
    sdr.set_frequency(freq)
    print(f"✅ Tuned to {freq/1e6} MHz")
    
    # Test Streaming Capture
    print("Attempting to capture 500k samples via streaming...")
    try:
        samples = sdr.capture_samples(500000)
    except Exception as e:
        print(f"❌ Capture raised exception: {e}")
        samples = None

    if samples is None or len(samples) == 0:
        print("❌ Capture failed (No samples returned)")
        # This confirms if the buffer fix is working or not
    else:
        print(f"✅ Captured {len(samples)} samples")
        
        # Analyze
        freqs, psd = detector.calculate_psd(samples)
        noise = detector.estimate_noise_floor(psd)
        peak = np.max(psd)
        snr = peak - noise
        
        print(f"   Noise Floor: {noise:.1f} dBm")
        print(f"   Peak Power: {peak:.1f} dBm")
        print(f"   SNR: {snr:.1f} dB (Threshold: {detector.SNR_THRESHOLD_DB})")
        
        if snr > detector.SNR_THRESHOLD_DB:
            print("✅ Signal Detected (Above Threshold)")
        else:
            print("⚠️  No strong signal detected (Expected if no key pressed)")
            
    sdr.close()

if __name__ == "__main__":
    test_hardware()
