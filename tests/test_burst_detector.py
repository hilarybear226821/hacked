
import numpy as np
import logging
import sys
import os

# Mock the modules
sys.path.append(os.getcwd())

from modules.subghz_scanner import BurstDetector, SignalBurst

def test_burst_detector_gap_filling():
    detector = BurstDetector(min_snr_db=3.0, min_duration_samples=10)
    
    # Create an envelope with 2 bursts separated by a small gap
    # Burst 1: 10-20
    # Burst 2: 25-35
    # Gap: 5 samples (less than 100)
    envelope = np.zeros(100)
    envelope[10:20] = 1.0
    envelope[25:35] = 1.0
    
    noise_floor = 0.01
    
    # Should merge them into one burst 10-35
    bursts = detector.detect_bursts(envelope, noise_floor, 315e6, 2e6)
    print(f"Detected {len(bursts)} bursts")
    for b in bursts:
        print(f"Burst: {b.start_sample} -> {b.end_sample}")

def test_index_error_case():
    # Case where starts and ends have different lengths or tricky boundaries
    detector = BurstDetector(min_snr_db=3.0, min_duration_samples=2)
    
    # Signal starts at the very end
    envelope = np.zeros(10)
    envelope[9] = 1.0
    # transitions will be [0,0,0,0,0,0,0,0,1]
    # starts = [9]
    # ends = []
    
    bursts = detector.detect_bursts(envelope, 0.01, 315e6, 2e6)
    print(f"Boundary case (start at end): {len(bursts)} bursts")

    # Signal ends at the very beginning
    envelope = np.zeros(10)
    envelope[0] = 1.0
    # transitions will be [-1, 0, ...]
    # starts = []
    # ends = [1]
    
    bursts = detector.detect_bursts(envelope, 0.01, 315e6, 2e6)
    print(f"Boundary case (end at start): {len(bursts)} bursts")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        test_burst_detector_gap_filling()
        test_index_error_case()
        print("Tests completed successfully")
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
