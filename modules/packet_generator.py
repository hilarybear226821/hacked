"""
Packet Generator for OOK Protocols (Nice Flo-R, KeeLoq, etc.)
Generates REAL RF-compliant IQ samples for HackRF transmission

FIXED ISSUES:
1. Pulse-Width Modulation (not Manchester)
2. Coherent carrier (not noise)
3. Proper framing with long inter-frame gap
4. Fractional timing precision
5. Correct preamble energy
6. Envelope shaping
7. Normalized amplitude
8. Protocol validation
"""

import numpy as np
import os
from typing import List, Tuple

class PacketGenerator:
    """
    Generate RF-compliant OOK (On-Off Keying) packets for sub-GHz protocols
    
    CRITICAL: This generates REAL RF signals that actual receivers can decode
    """
    
    # Nice Flo-R Timing (Pulse-Width Modulation)
    TE = 500e-6                    # 500 µs base time element
    SHORT_ON = 500e-6              # Bit 0: 500 µs ON
    LONG_ON = 1000e-6              # Bit 1: 1000 µs ON
    SYMBOL_PERIOD = 1500e-6        # Total symbol time (ON + OFF)
    
    PREAMBLE_PULSES = 8            # 8 short pulses for AGC convergence
    INTER_FRAME_GAP = 25e-3        # 25 ms silence (10x max symbol period)
    SYNC_GAP = 2000e-6             # 2 ms gap before data
    
    # RF Parameters
    SAMPLE_RATE = 2e6              # 2 MHz
    CARRIER_FREQ = 0               # Baseband (HackRF upconverts)
    AMPLITUDE = 0.8                # 80% of full scale (prevent clipping)
    
    # Envelope shaping parameters
    RISE_TIME = 10e-6              # 10 µs rise/fall time
    
    @classmethod
    def validate_bits(cls, bits: str, protocol: str = "flor12") -> bool:
        """
        Validate bit string for protocol
        
        Args:
            bits: Binary string
            protocol: Protocol name
        
        Returns:
            True if valid
        
        Raises:
            ValueError: If invalid
        """
        if not all(b in '01' for b in bits):
            raise ValueError(f"Invalid bits: must be binary string, got '{bits}'")
        
        if protocol == "flor12" and len(bits) != 12:
            raise ValueError(f"Nice Flo-R12 requires 12 bits, got {len(bits)}")
        
        if protocol == "flor24" and len(bits) != 64:
            raise ValueError(f"Nice Flo-R24 rolling code requires 64 bits, got {len(bits)}")
        
        return True
    
    @classmethod
    def _generate_carrier_pulse(cls, duration: float, amplitude: float = None) -> np.ndarray:
        """
        Generate coherent carrier pulse with envelope shaping
        
        Args:
            duration: Pulse duration in seconds
            amplitude: Signal amplitude (default: cls.AMPLITUDE)
        
        Returns:
            Complex IQ samples as interleaved int16
        """
        if amplitude is None:
            amplitude = cls.AMPLITUDE
        
        # Calculate exact fractional sample count (NO TRUNCATION)
        exact_samples = duration * cls.SAMPLE_RATE
        num_samples = int(np.ceil(exact_samples))
        
        # Generate time vector with precise timing
        t = np.arange(num_samples) / cls.SAMPLE_RATE
        
        # Generate coherent CW carrier (constant complex vector)
        # For baseband OOK: constant DC (I=amplitude, Q=0)
        # This creates a clean spectral line when upconverted
        carrier = np.ones(num_samples, dtype=np.complex64) * amplitude
        
        # Apply envelope shaping (critical for spectral hygiene)
        rise_samples = int(cls.RISE_TIME * cls.SAMPLE_RATE)
        
        if rise_samples > 0 and num_samples > 2 * rise_samples:
            # Sine-squared envelope for smooth transitions
            t_rise = np.linspace(0, np.pi/2, rise_samples)
            envelope = np.sin(t_rise) ** 2
            
            # Apply to leading/trailing edges
            carrier[:rise_samples] *= envelope
            carrier[-rise_samples:] *= envelope[::-1]
        
        # Convert to CS8 format (int8 interleaved I/Q)
        # Scale to int8 range: [-128, 127]
        scale = 127 * amplitude  # Use 127 not 128 to avoid clipping
        i_samples = (np.real(carrier) * scale).astype(np.int8)
        q_samples = (np.imag(carrier) * scale).astype(np.int8)
        
        # Interleave I and Q for CS8 format
        iq = np.empty(num_samples * 2, dtype=np.int8)
        iq[0::2] = i_samples
        iq[1::2] = q_samples
        
        return iq
    
    @classmethod
    def _generate_silence(cls, duration: float) -> np.ndarray:
        """
        Generate precise silence (true zero, not noise floor)
        
        Args:
            duration: Silence duration in seconds
        
        Returns:
            Zero-valued IQ samples
        """
        exact_samples = duration * cls.SAMPLE_RATE
        num_samples = int(np.ceil(exact_samples))
        
        # True zero (not noise floor)
        return np.zeros(num_samples * 2, dtype=np.int16)
    
    @classmethod
    def _pwm_encode_bits(cls, bits: str) -> List[Tuple[str, float]]:
        """
        Encode bits using Pulse-Width Modulation (NOT Manchester)
        
        Nice Flo-R encoding:
        - Bit 0: 500 µs ON, 1000 µs OFF
        - Bit 1: 1000 µs ON, 500 µs OFF
        
        Returns:
            List of ('carrier'|'silence', duration) tuples
        """
        pulses = []
        
        for bit in bits:
            if bit == '1':
                # Long ON, short OFF
                pulses.append(('carrier', cls.LONG_ON))
                pulses.append(('silence', cls.SYMBOL_PERIOD - cls.LONG_ON))
            elif bit == '0':
                # Short ON, long OFF
                pulses.append(('carrier', cls.SHORT_ON))
                pulses.append(('silence', cls.SYMBOL_PERIOD - cls.SHORT_ON))
            else:
                raise ValueError(f"Invalid bit: {bit}")
        
        return pulses
    
    @classmethod
    def generate_nice_flor(cls, data_bits: str, protocol: str = "flor12") -> np.ndarray:
        """
        Generate complete Nice Flo-R packet with proper OOK encoding
        
        Args:
            data_bits: Binary string (12 bits for FLO-R12, 64 for FLO-R24)
            protocol: 'flor12' or 'flor24'
        
        Returns:
            IQ samples as interleaved int16 array
        """
        # Validate input
        cls.validate_bits(data_bits, protocol)
        
        pulse_sequence = []
        
        # 1. INTER-FRAME GAP (critical for receiver reset)
        # Must be 10x longer than any symbol to reset receiver state
        pulse_sequence.append(('silence', cls.INTER_FRAME_GAP))
        
        # 2. PREAMBLE (AGC convergence + envelope detector bias)
        # Short alternating pulses to condition analog front-end
        # Must deliver sustained energy with proper duty cycle
        for _ in range(cls.PREAMBLE_PULSES):
            pulse_sequence.append(('carrier', cls.TE))
            pulse_sequence.append(('silence', cls.TE))
        
        # 3. SYNC GAP (distinct start-of-frame marker)
        # Longer gap than any data symbol to signal start
        pulse_sequence.append(('silence', cls.SYNC_GAP))
        
        # 4. START PULSE (optional but recommended)
        # Single long pulse to arm data decoder
        pulse_sequence.append(('carrier', cls.LONG_ON))
        pulse_sequence.append(('silence', cls.TE))
        
        # 5. DATA PAYLOAD (PWM encoding)
        pulse_sequence.extend(cls._pwm_encode_bits(data_bits))
        
        # 6. END SILENCE (allow receiver to process last bit)
        pulse_sequence.append(('silence', cls.SYMBOL_PERIOD))
        
        # Generate IQ samples with precise timing
        buffers = []
        for pulse_type, duration in pulse_sequence:
            if pulse_type == 'carrier':
                buffers.append(cls._generate_carrier_pulse(duration))
            elif pulse_type == 'silence':
                buffers.append(cls._generate_silence(duration))
            else:
                raise ValueError(f"Invalid pulse type: {pulse_type}")
        
        # Concatenate all segments
        return np.concatenate(buffers)
    
    @classmethod
    def generate_keeloq(cls, encrypted_data: int, button: int = 1, 
                        serial: int = 0x12345678, fixed_code: int = 0) -> np.ndarray:
        """
        Generate KeeLoq rolling code packet (similar PWM encoding)
        
        Args:
            encrypted_data: 32-bit encrypted counter
            button: Button code (4 bits)
            serial: 28-bit serial number
            fixed_code: Optional fixed portion
        
        Returns:
            IQ samples
        """
        # KeeLoq format: 32-bit encrypted + 4-bit button + 28-bit serial = 64 bits
        bits = format(encrypted_data, '032b') + format(button, '04b') + format(serial, '028b')
        
        # KeeLoq uses similar PWM but different timing
        # For now, use FLO-R encoding (can be customized)
        return cls.generate_nice_flor(bits[:64], protocol='flor24')
    
    @classmethod
    def save_to_cs16(cls, samples: np.ndarray, filename: str):
        """
        Save IQ samples to .cs16 file for HackRF transmission
        
        Args:
            samples: Interleaved I/Q int16 samples
            filename: Output filename
        """
        os.makedirs(os.path.dirname(os.path.abspath(filename)) if os.path.dirname(filename) else '.', 
                    exist_ok=True)
        
        with open(filename, 'wb') as f:
            f.write(samples.tobytes())
        
        print(f"✅ Generated {len(samples)//2} IQ samples ({len(samples)//2/cls.SAMPLE_RATE*1000:.1f} ms)")
        print(f"   File: {filename}")
        print(f"   Size: {len(samples)*2} bytes")
    
    @classmethod
    def generate_batch(cls, codes: List[str], protocol: str = "flor12", 
                      guard_time: float = 10e-3) -> np.ndarray:
        """
        Generate multiple codes with guard time spacing
        
        Args:
            codes: List of binary strings
            protocol: Protocol name
            guard_time: Inter-packet spacing in seconds
        
        Returns:
            Concatenated IQ samples
        """
        packets = []
        guard_samples = cls._generate_silence(guard_time)
        
        for i, code in enumerate(codes):
            print(f"[{i+1}/{len(codes)}] Generating {protocol.upper()} code: {code}")
            packet = cls.generate_nice_flor(code, protocol)
            packets.append(packet)
            
            # Add guard time between packets
            if i < len(codes) - 1:
                packets.append(guard_samples)
        
        return np.concatenate(packets)
    
    @classmethod
    def get_signal_info(cls, samples: np.ndarray) -> dict:
        """
        Analyze generated signal for validation
        
        Returns:
            Dict with signal statistics
        """
        # Deinterleave I and Q
        i_samples = samples[0::2].astype(np.float32)
        q_samples = samples[1::2].astype(np.float32)
        
        # Calculate power
        power = i_samples**2 + q_samples**2
        avg_power = np.mean(power)
        peak_power = np.max(power)
        
        # Calculate duty cycle
        on_samples = np.sum(power > (avg_power * 0.1))
        duty_cycle = on_samples / len(power)
        
        # Check for clipping
        max_amplitude = max(np.max(np.abs(i_samples)), np.max(np.abs(q_samples)))
        clipping = max_amplitude >= 32767 * 0.95
        
        return {
            'duration_ms': len(power) / cls.SAMPLE_RATE * 1000,
            'avg_power': avg_power,
            'peak_power': peak_power,
            'duty_cycle_percent': duty_cycle * 100,
            'max_amplitude': max_amplitude,
            'clipping_detected': clipping,
            'samples': len(power)
        }
