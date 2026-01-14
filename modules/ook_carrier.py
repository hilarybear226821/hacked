"""
OOK Carrier Generator

Generates phase-continuous gated complex carrier for OOK/ASK modulation.
No noise - uses constant complex tone that HackRF can properly upconvert.
"""

import numpy as np


class CarrierGenerator:
    """
    Phase-continuous complex carrier generator for OOK
    
    Generates A·e^(jφ) for carrier ON, zeros for carrier OFF.
    Maintains phase continuity across multiple generate() calls.
    """
    
    def __init__(self, sample_rate: float, amplitude: int = 10000, tone_offset_hz: float = None):
        """
        Initialize carrier generator
        
        Args:
            sample_rate: Sample rate in Hz (typically 2e6 for HackRF)
            amplitude: Signal amplitude (max 28000 for headroom with shaping)
            tone_offset_hz: Baseband tone offset (default: fs/200 for coherence)
        """
        self.fs = sample_rate
        
        # Amplitude validation (headroom for edge shaping)
        if amplitude > 28000:
            raise ValueError(f"Amplitude {amplitude} too high for CS16 with edge shaping (max 28000)")
        self.amp = amplitude
        
        # Coherent tone offset (integer divisor of sample rate)
        if tone_offset_hz is None:
            tone_offset_hz = sample_rate / 200  # 10 kHz @ 2 MHz
        self.tone_offset_hz = tone_offset_hz
        
        self.phase = 0.0
        self.omega = 2 * np.pi * tone_offset_hz / sample_rate
        
    def reset_phase(self, phase: float = 0.0):
        """
        Reset phase for deterministic reproducibility
        
        Args:
            phase: Initial phase in radians
        """
        self.phase = phase
        
    def generate_pulse(self, num_samples: int, shape_edges: bool = True) -> np.ndarray:
        """
        Generate carrier pulse with automatic edge shaping
        
        Args:
            num_samples: Number of IQ sample pairs
            shape_edges: Apply raised cosine edge shaping (default True)
            
        Returns:
            Interleaved int16 IQ array with shaped edges
        """
        iq = self._generate_carrier(num_samples)
        
        if shape_edges and num_samples >= 20:  # Only shape if long enough
            self._shape_edges_inplace(iq)
        
        return iq
    
    def _generate_carrier(self, num_samples: int) -> np.ndarray:
        """
        Generate raw carrier (internal use)
        
        Phase advances ONLY during carrier ON (this method).
        OFF periods must NOT call this method.
        
        Phase continuity: Receiver assumption is envelope-only detection.
        Phase is maintained for spectral coherence but not tracked by receiver.
        """
        # Guard against zero-length pulses
        if num_samples <= 0:
            return np.zeros(0, dtype=np.int16)
        
        n = np.arange(num_samples)
        phase = self.phase + self.omega * n
        
        # CRITICAL: Update phase by FULL num_samples (not num_samples-1)
        # Previous bug: phase[-1] was off-by-one, causing accumulation error
        self.phase = (self.phase + self.omega * num_samples) % (2 * np.pi)
        
        # Generate I and Q
        i = (self.amp * np.cos(phase)).astype(np.int16)
        q = (self.amp * np.sin(phase)).astype(np.int16)
        
        # Interleave I/Q for CS16 format
        iq = np.empty(num_samples * 2, dtype=np.int16)
        iq[0::2] = i
        iq[1::2] = q
        
        return iq
    
    def _shape_edges_inplace(self, iq: np.ndarray, ramp_len: int = 8):
        """
        Apply raised cosine ramp to reduce spectral splatter (INTERNAL)
        
        Uses raised cosine (Hann window) instead of linear for better spectral properties.
        
        Args:
            iq: Interleaved IQ samples (modified in-place)
            ramp_len: Ramp length in samples
        """
        if len(iq) < 4 * ramp_len:
            return  # Too short to shape
        
        # Raised cosine ramp (smoother than linear)
        ramp = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, ramp_len))
        
        # On-ramp (start of pulse)
        iq[:2*ramp_len:2] = (iq[:2*ramp_len:2] * ramp).astype(np.int16)  # I
        iq[1:2*ramp_len:2] = (iq[1:2*ramp_len:2] * ramp).astype(np.int16)  # Q
        
        # Off-ramp (end of pulse)
        iq[-2*ramp_len::2] = (iq[-2*ramp_len::2] * ramp[::-1]).astype(np.int16)  # I
        iq[-2*ramp_len+1::2] = (iq[-2*ramp_len+1::2] * ramp[::-1]).astype(np.int16)  # Q
