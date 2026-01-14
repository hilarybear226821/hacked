import logging
import unittest
import sys
import os
import time
import numpy as np
from unittest.mock import patch, MagicMock

sys.path.append(os.getcwd())

# Import our stack
from modules.sdr_controller import SDRController
from modules.auto_rolljam import SignalDetection, AutoRollJam
from modules.scpe_engine import SCPEAttackController
from modules.scpe_waveform import SCPEWaveformGenerator

# Configure logging
logging.basicConfig(level=logging.ERROR)

class TestSCPEFullSuite(unittest.TestCase):
    
    def setUp(self):
        """Setup mock environment for full stack test"""
        print("\n[Setup] Initializing SCPE Stack...")
        self.sdr = MagicMock(spec=SDRController) # Mock SDR
        self.sdr.start_tx.return_value = True # Mock success
        
        self.waveform_gen = SCPEWaveformGenerator(sample_rate=2e6)
        
        # We need a mock AutoRollJam that doesn't actually touch hardware
        # but allows us to feed it signals
        self.rolljam = None 
        
        self.engine = SCPEAttackController(self.sdr, self.rolljam)
        self.engine.start()
        
    def test_01_waveform_generation(self):
        """Verify Thickened Waveform Generation"""
        print("[Test 01] Generating Thickened Waveform...")
        bitstream = "10101010"
        
        # Standard
        standard_iq = self.waveform_gen.generate_ook_thickened(bitstream, pulse_width_us=500, jitter_percent=0.0)
        
        # Thickened
        thick_iq = self.waveform_gen.generate_ook_thickened(bitstream, pulse_width_us=500, jitter_percent=0.10)
        
        self.assertTrue(len(thick_iq) > 0)
        self.assertNotEqual(len(standard_iq), len(thick_iq), "Jitter should affect total length statistically")
        print(f"   ✅ Standard Len: {len(standard_iq)}, Thick Len: {len(thick_iq)}")

    def test_02_population_state_management(self):
        """Verify Population Manager R_P logic"""
        print("[Test 02] Managing Population State...")
        
        # Ingest signal
        det = SignalDetection(
            frequency=315e6, power_dbm=-50, snr_db=20, 
            bandwidth_hz=10e3, timestamp=time.time(), confidence=1.0
        )
        self.engine.ingest_signal(det, np.zeros(100))
        
        dev_id = "Dev_315MHz"
        self.assertIn(dev_id, self.engine.pop_mgr.devices)
        
        dev = self.engine.pop_mgr.devices[dev_id]
        self.assertEqual(len(dev.capture_queue), 1)
        print(f"   ✅ Device {dev_id} tracked with {len(dev.capture_queue)} captures")

    def test_03_replay_orchestration(self):
        """Verify Attack Controller Decision Logic"""
        print("[Test 03] Orchestrating Ghost Replay...")
        
        dev_id = "Dev_315MHz"
        
        # Ensure we have state (from prev test or new)
        det = SignalDetection(315e6, -50, 20, 10e3, time.time(), 1.0)
        self.engine.ingest_signal(det, np.zeros(100))
        
        # Trigger
        success = self.engine.trigger_replay(dev_id, mode="SCPE_THICK")
        self.assertTrue(success)
        
        # Verify call to SDR
        self.sdr.start_tx.assert_called()
        self.sdr.stop_tx.assert_called()
        
        # Verify queue consumed (FIFO)
        dev = self.engine.pop_mgr.devices[dev_id]
        self.assertEqual(len(dev.capture_queue), 0, "Queue should be empty after replay")
        print("   ✅ Replay triggered and queue consumed")

    def test_04_live_simulation(self):
        """Simulate a full Rolling Code attack cycle"""
        print("[Test 04] Full Attack Cycle Simulation...")
        
        # 1. JAM & CAPTURE
        print("   -> Phase 1: Jam & Capture")
        for i in range(3):
            det = SignalDetection(433.92e6, -40, 25, 50e3, time.time(), 1.0)
            self.engine.ingest_signal(det, np.zeros(1000))
            
        dev_id = "Dev_433MHz"
        dev = self.engine.pop_mgr.devices[dev_id]
        self.assertEqual(len(dev.capture_queue), 3)
        print(f"   ✅ Captured 3 codes for {dev_id}")
        
        # 2. REPLAY (SCPE)
        print("   -> Phase 2: Ghost Replay execution")
        self.engine.trigger_replay(dev_id, mode="SCPE_THICK")
        
        self.assertEqual(len(dev.capture_queue), 2)
        print("   ✅ Replay successful, 2 codes remaining")

if __name__ == "__main__":
    unittest.main()
