import sys
import os
import time
import numpy as np
import logging
sys.path.append(os.getcwd())

from modules.auto_rolljam import SignalDetector, SignalDetection

def generate_test_signal(sample_rate=2e6, freq_offset=0, snr_db=10, duration_sec=0.1):
    """Generate synthetic IQ signal with noise"""
    t = np.arange(int(duration_sec * sample_rate)) / sample_rate
    
    # Carrier
    signal = np.exp(1j * 2 * np.pi * freq_offset * t)
    
    # Pulse modulation (OOK-like)
    # 50% duty cycle 1kHz square wave
    envelope = (np.sign(np.sin(2 * np.pi * 1000 * t)) + 1) / 2
    signal = signal * envelope
    
    # Add noise
    noise_power = 10**(-snr_db/10)
    noise = (np.random.randn(len(t)) + 1j * np.random.randn(len(t))) * np.sqrt(noise_power/2)
    
    return (signal + noise).astype(np.complex64)

def verify_315_detection():
    print("=== Verifying 315 MHz Signal Detection Logic ===")
    
    detector = SignalDetector(sample_rate=2e6)
    target_freq = 315.0e6
    
    # Test 1: Silence (Noise only)
    print("\n[Test 1] Testing Noise Floor (Silence)...")
    noise = (np.random.randn(2048*10) + 1j * np.random.randn(2048*10)) * 0.01
    detection = detector.detect_signal(noise, target_freq)
    
    if detection:
        print(f"❌ False Positive detected in noise! Conf: {detection.confidence}")
        return False
    else:
        print("✅ Correctly ignored noise.")
        
    # Test 2: Strong 315 MHz Signal
    print("\n[Test 2] Testing Strong 315 MHz Signal (SNR 20dB)...")
    # Signal exactly at center frequency (0 offset in baseband)
    sig_strong = generate_test_signal(freq_offset=0, snr_db=20)
    
    detection = detector.detect_signal(sig_strong, target_freq)
    
    if detection:
        print(f"✅ Detection Successful!")
        print(f"   Freq: {detection.frequency/1e6:.3f} MHz")
        print(f"   SNR: {detection.snr_db:.1f} dB")
        print(f"   Conf: {detection.confidence:.2f}")
        
        if abs(detection.frequency - target_freq) > 100e3:
            print("❌ Frequency detection inaccurate")
            return False
    else:
        print("❌ Failed to detect strong signal")
        return False

    # Test 3: Weak 315 MHz Signal (Boundary condition)
    print("\n[Test 3] Testing Weak 315 MHz Signal (SNR 8dB)...")
    # Signal slightly offset by 50kHz
    sig_weak = generate_test_signal(freq_offset=50e3, snr_db=8)
    
    detection = detector.detect_signal(sig_weak, target_freq)
    
    if detection:
         print(f"✅ Weak Signal Detected")
         print(f"   Freq: {detection.frequency/1e6:.3f} MHz")
         print(f"   SNR: {detection.snr_db:.1f} dB")
    else:
         print("❌ Failed to detect weak signal (should detect > 7dB)")
         return False
         
    return True

if __name__ == "__main__":
    if verify_315_detection():
        print("\n✅ 315 MHz Detection Verification PASSED")
        sys.exit(0)
    else:
        print("\n❌ 315 MHz Detection Verification FAILED")
        sys.exit(1)
