import sys
import os
import time
import numpy as np
import argparse
sys.path.append(os.getcwd())

from modules.sdr_controller import SDRController, HackRFConfig
from modules.auto_rolljam import SignalDetector

def tune_signal(target_freq_mhz=315.0, scan_width_mhz=2.0, duration=10):
    print(f"=== Signal Tuner: Finding peak near {target_freq_mhz} MHz ===")
    print(f"Scanning +/- {scan_width_mhz/2} MHz for {duration} seconds...")
    print("PRESS YOUR KEYFOB NOW continuously!")
    
    sdr = SDRController()
    if not sdr.open():
        print("❌ Failed to open SDR")
        return
    
    detector = SignalDetector(sample_rate=2e6)
    
    # Configure for wide capture
    sdr.set_frequency(target_freq_mhz * 1e6, sample_rate=2e6)
    sdr.device.set_gain(40) # Max LNA assumption, VGA will default
    
    peaks = []
    
    start_time = time.time()
    
    # We need a custom callback to capture live
    def callback(samples):
        # Calculate PSD
        freqs, psd = detector.calculate_psd(samples)
        
        # Find peak
        peak_idx = np.argmax(psd)
        peak_pwr = psd[peak_idx]
        peak_offset = freqs[peak_idx]
        
        noise = detector.estimate_noise_floor(psd)
        snr = peak_pwr - noise
        
        if snr > 5.0:
            actual_freq = (target_freq_mhz * 1e6) + peak_offset
            peaks.append({
                'freq': actual_freq,
                'pwr': peak_pwr,
                'snr': snr
            })
            print(f"  ⚡ Signal: {actual_freq/1e6:.3f} MHz (SNR: {snr:.1f} dB)")
            
    try:
        sdr.start_rx(callback, requester="tuner")
        
        while time.time() - start_time < duration:
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        pass
    finally:
        sdr.close()
        
    print("\n=== Tuning Results ===")
    if not peaks:
        print("❌ No signals detected. Try:")
        print("  1. Checking battery in fob")
        print("  2. Moving fob closer to antenna")
        print("  3. Verifying antenna connection")
        return
        
    # Analyze peaks
    # Group by frequency (100kHz bins)
    bins = {}
    for p in peaks:
        f_bin = round(p['freq'] / 1e5) * 1e5
        if f_bin not in bins:
            bins[f_bin] = []
        bins[f_bin].append(p)
        
    # Find best bin
    best_freq = 0
    max_count = 0
    
    for f, hits in bins.items():
        if len(hits) > max_count:
            max_count = len(hits)
            best_freq = f
            
    avg_snr = np.mean([p['snr'] for p in bins[best_freq]])
    
    print(f"✅ Strongest Signal: {best_freq/1e6:.3f} MHz")
    print(f"   Hits: {max_count}")
    print(f"   Avg SNR: {avg_snr:.1f} dB")
    print("\nAction: Update your 'Target Frequency' to this value.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--freq", type=float, default=315.0)
    args = parser.parse_args()
    
    tune_signal(args.freq)
