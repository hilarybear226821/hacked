"""
SCPE LIVE FIRE SIMULATION
Runs the full SCPE Engine in a multi-target loop with simulated feedback.
Demonstrates:
1. Dynamic Power Allocation
2. Real-time Jitter Adaptation
3. Waveform Scheduling (TDM/Crossfade)
"""

import sys
import os
import time
import logging
import random
import threading
from unittest.mock import MagicMock

sys.path.append(os.getcwd())

from modules.scpe_engine import SCPEAttackController
from modules.sdr_controller import SDRController
from modules.auto_rolljam import AutoRollJam

# Setup Logging to Console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("LIVE_FIRE")

def run_simulation():
    print("="*60)
    print("SCPE ADVANCED MULTI-TARGET LIVE FIRE EXERCISE")
    print("="*60)
    
    # 1. Setup Stack
    logger.info("Initializing Stack...")
    
    # Mock SDR to avoid real RF, but print TX events
    mock_sdr = MagicMock(spec=SDRController)
    def mock_start_tx(*args, **kwargs):
        print(f"   [SDR] >>> TX START Freq={kwargs.get('frequency',0)/1e6}MHz Gain={kwargs.get('gain')} <<<")
        return True
    def mock_stop_tx(*args, **kwargs):
        print(f"   [SDR] >>> TX STOP <<<")
        return True
    
    mock_sdr.start_tx.side_effect = mock_start_tx
    mock_sdr.stop_tx.side_effect = mock_stop_tx
    
    # Init Engine
    engine = SCPEAttackController(mock_sdr, None)
    engine.start()
    
    # 2. Add Targets
    logger.info("Enrolling Targets...")
    engine.add_target("Target_Alpha_433", priority=2.0)
    engine.add_target("Target_Beta_315", priority=1.0)
    
    # Mock some captures for them
    engine.pop_mgr.get_or_create("Target_Alpha_433", 433.92e6)
    engine.pop_mgr.update_capture("Target_Alpha_433", {"bitstream": "11110000"*4, "freq": 433.92e6})
    
    engine.pop_mgr.get_or_create("Target_Beta_315", 315.00e6)
    engine.pop_mgr.update_capture("Target_Beta_315", {"bitstream": "10101010"*4, "freq": 315.00e6})
    
    # 3. Running Loop
    logger.info("Starting Attack Loop (Ctrl+C to stop)...")
    try:
        for i in range(1, 6): # Run 5 cycles
            print(f"\n--- Cycle {i} ---")
            
            # Run Cycle
            engine.run_attack_cycle()
            
            # Simulate Feedback (Random)
            # Alpha fails (High SNR), Beta succeeds
            logger.info("Simulating Feedback...")
            engine.update_feedback("Target_Alpha_433", {"snr": 35.0, "success": False})
            engine.update_feedback("Target_Beta_315", {"snr": 20.0, "success": True})
            
            # Print Logic State
            alpha_jit = engine.jitter_ctrl.get_jitter("Target_Alpha_433")
            beta_jit = engine.jitter_ctrl.get_jitter("Target_Beta_315")
            print(f"   [Logic] Alpha Jitter: {alpha_jit*100:.1f}% (Adapt: Increasing)")
            print(f"   [Logic] Beta  Jitter: {beta_jit*100:.1f}% (Adapt: Stable)")
            
            time.sleep(1.0)
            
    except KeyboardInterrupt:
        pass
    
    print("\n[!] Simulation Complete.")

if __name__ == "__main__":
    run_simulation()
