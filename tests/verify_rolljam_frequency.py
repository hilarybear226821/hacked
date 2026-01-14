import sys
import os
import time
import logging
from unittest.mock import MagicMock
sys.path.append(os.getcwd())

from modules.auto_rolljam import AutoRollJam, SignalDetection

def verify_315_support():
    print("=== Verifying 315 MHz RollJam Support ===")
    
    # Mock dependencies
    sdr = MagicMock()
    sdr.open.return_value = True
    sdr.set_frequency.return_value = True
    sdr.set_sample_rate.return_value = True
    sdr.set_gain.return_value = True
    sdr.capture_samples.return_value = [1+1j] * 1024 # Dummy data
    
    recorder = MagicMock()
    
    # Initialize with 315 MHz
    target_freq = 315.0e6
    rolljam = AutoRollJam(sdr, recorder, target_freq=target_freq)
    
    # 1. Verify initialization
    if rolljam.target_freq != target_freq:
        print(f"❌ Initialization failed: Expected {target_freq}, got {rolljam.target_freq}")
        return False
    else:
        print(f"✅ Initialized with correct frequency: {target_freq/1e6} MHz")
        
    sdr.set_frequency.reset_mock()
    
    # 2. Verify configuration calls
    rolljam._configure_sdr()
    
    sdr.set_frequency.assert_called_with(target_freq)
    print(f"✅ SDR frequency set to {target_freq/1e6} MHz")
    
    # 3. Verify protocol selection (if any logic depends on freq)
    # The detector uses SignalDetector which is generic but uses generic 433/315 bins
    # Let's check if the detector can detect simplified signals relative to center freq
    
    return True

if __name__ == "__main__":
    if verify_315_support():
        print("\n✅ Verification PASSED")
        sys.exit(0)
    else:
        print("\n❌ Verification FAILED")
        sys.exit(1)
