
"""
FSM Lifecycle Test - Mandatory Production Test

Tests the critical RX → CLOSE path that was causing crashes.
"""

import time
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.sdr_controller import HackRFDevice, HackRFConfig, SDRState

def test_rx_close_path():
    """
    Test that close() correctly handles RX_RUNNING state.
    
    This was the crash path:
    - RX_RUNNING → close() → CLOSED (illegal jump)
    
    Should be:
    - RX_RUNNING → STOPPING → CONFIGURED → OPEN → CLOSED
    """
    print("=== Test: RX → CLOSE Path ===\n")
    
    sdr = HackRFDevice()
    
    try:
        # 1. Open device
        print("1. Opening device...")
        if not sdr.open():
            print("❌ FAIL: Could not open device (HackRF not connected?)")
            return False
        assert sdr.state == SDRState.OPEN, f"Expected OPEN, got {sdr.state}"
        print(f"   State: {sdr.state.name} ✓")
        
        # 2. Configure
        print("\n2. Configuring...")
        config = HackRFConfig(
            frequency_hz=433920000,
            sample_rate_hz=2000000,
            lna_gain_db=32,
            vga_gain_db=20,
            amp_enabled=True
        )
        sdr.configure(config)
        assert sdr.state == SDRState.CONFIGURED, f"Expected CONFIGURED, got {sdr.state}"
        print(f"   State: {sdr.state.name} ✓")
        
        # 3. Start RX
        print("\n3. Starting RX...")
        def dummy_callback(samples):
            pass
        
        success = sdr.start_rx(dummy_callback, requester="test")
        assert success, "start_rx failed"
        assert sdr.state == SDRState.RX_RUNNING, f"Expected RX_RUNNING, got {sdr.state}"
        print(f"   State: {sdr.state.name} ✓")
        
        time.sleep(0.5)  # Let RX run briefly
        
        # 4. Close (critical test)
        print("\n4. Closing device (while RX active)...")
        print("   This should: RX_RUNNING → STOPPING → CONFIGURED → OPEN → CLOSED")
        sdr.close()
        
        assert sdr.state == SDRState.CLOSED, f"Expected CLOSED, got {sdr.state}"
        print(f"   State: {sdr.state.name} ✓")
        
        print("\n✅ PASS: RX → CLOSE path is FSM-compliant")
        return True
        
    except Exception as e:
        print(f"\n❌ FAIL: {e}")
        print(f"   Final state: {sdr.state.name}")
        import traceback
        traceback.print_exc()
        return False

def test_tx_close_path():
    """Test that close() correctly handles TX_RUNNING state."""
    print("\n=== Test: TX → CLOSE Path ===\n")
    
    sdr = HackRFDevice()
    
    try:
        # Open and configure
        sdr.open()
        config = HackRFConfig(433920000, 2000000, 32, 20)
        sdr.configure(config)
        
        # Create dummy TX file
        import tempfile
        import numpy as np
        with tempfile.NamedTemporaryFile(suffix=".cs8", delete=False) as f:
            tx_file = f.name
            noise = (np.random.uniform(-1, 1, 10000) * 127).astype(np.int8)
            f.write(noise.tobytes())
        
        # Start TX
        from pathlib import Path
        sdr.start_tx(Path(tx_file), mode="test_tx", repeat=False, requester="test")
        assert sdr.state == SDRState.TX_RUNNING
        
        time.sleep(0.1)
        
        # Close
        sdr.close()
        assert sdr.state == SDRState.CLOSED
        
        # Cleanup
        os.remove(tx_file)
        
        print("✅ PASS: TX → CLOSE path is FSM-compliant")
        return True
        
    except Exception as e:
        print(f"❌ FAIL: {e}")
        return False

def test_stop_idempotency():
    """Test that stop() is idempotent and safe to call multiple times."""
    print("\n=== Test: Stop Idempotency ===\n")
    
    sdr = HackRFDevice()
    
    try:
        sdr.open()
        config = HackRFConfig(433920000, 2000000, 32, 20)
        sdr.configure(config)
        sdr.start_rx(lambda x: None, requester="test")
        
        # Call stop multiple times
        sdr.stop(requester="test")
        assert sdr.state == SDRState.CONFIGURED
        
        sdr.stop(requester="test")  # Should be no-op
        assert sdr.state == SDRState.CONFIGURED
        
        sdr.stop(requester="test")  # Should be no-op
        assert sdr.state == SDRState.CONFIGURED
        
        sdr.close()
        
        print("✅ PASS: Stop is idempotent")
        return True
        
    except Exception as e:
        print(f"❌ FAIL: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("FSM Lifecycle Tests - Production Hardening")
    print("=" * 60 + "\n")
    
    results = []
    results.append(("RX → CLOSE Path", test_rx_close_path()))
    results.append(("TX → CLOSE Path", test_tx_close_path()))
    results.append(("Stop Idempotency", test_stop_idempotency()))
    
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")
    
    all_passed = all(r[1] for r in results)
    print("\n" + ("="*60))
    if all_passed:
        print("ALL TESTS PASSED - FSM is production-ready")
    else:
        print("SOME TESTS FAILED - Review FSM implementation")
    print("=" * 60)
    
    sys.exit(0 if all_passed else 1)
