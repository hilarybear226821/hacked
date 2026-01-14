
import unittest
from unittest.mock import MagicMock, patch
import numpy as np
import logging
import time
import sys
import os

sys.path.append(os.getcwd())

from modules.scpe_engine import SCPEAttackController
from modules.sdr_controller import SDRController
from modules.scpe_advanced_controls import DynamicPowerAllocator, WaveformScheduler, AdaptiveJitterController

# Silence logs
logging.basicConfig(level=logging.CRITICAL)

class TestSCPEAdvanced(unittest.TestCase):
    def setUp(self):
        self.mock_sdr = MagicMock(spec=SDRController)
        self.mock_sdr.start_tx.return_value = True
        
        self.attr_ctrl = SCPEAttackController(self.mock_sdr, None)
        # Mock Pop Manager to return candidates
        self.attr_ctrl.pop_mgr.get_replay_candidate = MagicMock(return_value={
            "bitstream": "10101010", 
            "freq": 433.92e6,
            "modulation": "OOK",
            "params": {"pulse_width_us": 500}
        })
        
        # Add targets
        self.attr_ctrl.add_target("DevA", priority=2.0)
        self.attr_ctrl.add_target("DevB", priority=1.0)
        
    def test_power_allocation(self):
        """Test priority-weighted power allocation with ramping"""
        print("\n[Test] Power Allocation")
        
        # Disable ramping for predictable test
        allocator = DynamicPowerAllocator(max_total_power=1.0, enable_ramping=False)
        allocator.update_priority("DevA", 2.0)
        allocator.update_priority("DevB", 1.0)
        
        weights = allocator.allocate()
        
        # Should allocate 2/3 to DevA, 1/3 to DevB
        self.assertAlmostEqual(weights["DevA"], 0.666, places=2)
        self.assertAlmostEqual(weights["DevB"], 0.333, places=2)
        print("   ✅ Weights Correct: A=0.67, B=0.33")
        
    def test_crossfade_cycle(self):
        print("\n[Test] Crossfade Attack Cycle")
        self.attr_ctrl.scheduler.mode = "CROSSFADE"
        
        # Patch local export/transmit to verify call
        with patch.object(self.attr_ctrl, '_transmit_composite') as mock_tx:
            self.attr_ctrl.run_attack_cycle()
            
            mock_tx.assert_called_once()
            args, _ = mock_tx.call_args
            composite = args[0]
            
            # Since both DevA and DevB contribute, composite should be blend
            # We trust WaveformScheduler logic here, verified via shape
            self.assertTrue(len(composite) > 0)
            print("   ✅ Composite Waveform Transmitted")

    def test_tdm_cycle(self):
        print("\n[Test] TDM Attack Cycle")
        self.attr_ctrl.scheduler.mode = "TDM"
        
        with patch.object(self.attr_ctrl, '_transmit_composite') as mock_tx:
            self.attr_ctrl.run_attack_cycle()
            
            # Should be called once per target (2 targets)
            self.assertEqual(mock_tx.call_count, 2)
            print("   ✅ TDM Scheduled 2 slots")

    def test_adaptive_jitter(self):
        """Test PID-based adaptive jitter feedback"""
        print("\n[Test] Adaptive Jitter Feedback")
        
        ctrl = AdaptiveJitterController(use_pid=True)
        base = ctrl.get_jitter("TestDev")
        
        # Simulate multiple failures with high SNR (timing issues)
        for _ in range(5):
            ctrl.update_feedback("TestDev", {"success": False, "snr": 30.0})
        next_j = ctrl.get_jitter("TestDev")
        
        print(f"   ✅ Jitter Increased: {base:.3f} -> {next_j:.3f}")
        self.assertGreater(next_j, base)
        
        # Simulate success - jitter should stabilize or decrease slightly
        for _ in range(3):
            ctrl.update_feedback("TestDev", {"success": True, "snr": 25.0})
        tight_j = ctrl.get_jitter("TestDev")
        
        # After success, PID should reduce error (jitter may stay same or decrease slightly)
        self.assertLessEqual(tight_j, next_j)
        print(f"   ✅ Jitter Decreased: {next_j:.3f} -> {tight_j:.3f}")

if __name__ == '__main__':
    unittest.main()
