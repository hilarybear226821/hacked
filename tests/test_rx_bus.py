#!/usr/bin/env python3
"""
Test RX Bus Integration - Phase 1 Verification

Verifies that IQ samples flow from RX thread to RX Bus correctly.
"""

import sys
import os
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.rx_bus import rx_bus
from modules.sdr_controller import HackRFDevice, HackRFConfig

def test_rx_bus_integration():
    """Test that RX samples flow to bus"""
    print("=" * 60)
    print("RX Bus Integration Test - Phase 1")
    print("=" * 60 + "\n")
    
    sdr = HackRFDevice()
    
    try:
        # 1. Open and configure
        print("1. Opening device...")
        if not sdr.open():
            print("❌ FAIL: Could not open device (HackRF not connected?)")
            return False
        
        config = HackRFConfig(
            frequency_hz=433920000,
            sample_rate_hz=2000000,
            lna_gain_db=32,
            vga_gain_db=20,
            amp_enabled=True
        )
        sdr.configure(config)
        print("   ✅ Device configured")
        
        # 2. Start RX with dummy callback
        print("\n2. Starting RX...")
        samples_received = []
        
        def dummy_callback(samples):
            samples_received.append(len(samples))
        
        sdr.start_rx(dummy_callback, requester="test")
        print("   ✅ RX started")
        
        # 3. Pull from RX Bus
        print("\n3. Pulling from RX Bus...")
        bus_samples = []
        
        for i in range(5):
            iq_sample = rx_bus.pull(timeout=2.0)
            if iq_sample:
                bus_samples.append(iq_sample)
                print(f"   📡 Sample {i+1}: {len(iq_sample.samples)} IQ points, "
                      f"freq={iq_sample.center_freq/1e6:.3f} MHz, "
                      f"seq={iq_sample.sequence}")
            else:
                print(f"   ⚠️  Timeout on sample {i+1}")
        
        # 4. Check stats
        time.sleep(1)
        stats = rx_bus.get_stats()
        print(f"\n4. RX Bus Statistics:")
        print(f"   Samples pushed: {stats['samples_pushed']}")
        print(f"   Samples dropped: {stats['samples_dropped']}")
        print(f"   Drop rate: {stats['drop_rate']:.2%}")
        print(f"   Queue size: {stats['queue_size']}")
        
        # 5. Stop
        print("\n5. Stopping RX...")
        sdr.stop(requester="test")
        sdr.close()
        print("   ✅ Stopped cleanly")
        
        # 6. Verify
        print("\n6. Verification:")
        if len(bus_samples) >= 3:
            print(f"   ✅ Received {len(bus_samples)} samples from bus")
            print(f"   ✅ Callback received {len(samples_received)} batches")
            print(f"   ✅ RX Bus is working correctly!")
            return True
        else:
            print(f"   ❌ Only received {len(bus_samples)} samples (expected >= 3)")
            return False
            
    except Exception as e:
        print(f"\n❌ FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_rx_bus_integration()
    print("\n" + "=" * 60)
    if success:
        print("✅ PHASE 1 COMPLETE: RX Bus Integration Working")
    else:
        print("❌ PHASE 1 FAILED: Review errors above")
    print("=" * 60)
    
    sys.exit(0 if success else 1)
