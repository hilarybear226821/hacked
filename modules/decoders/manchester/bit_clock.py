"""
Bit Clock Recovery for Manchester Decoding

Implements DPLL-like phase tracking for proper Manchester decoding.
Samples at mid-bit boundaries, not edges.
"""

import numpy as np
from typing import Optional, Callable
from dataclasses import dataclass
from enum import Enum, auto


class BitEvent(Enum):
    """Bit clock events"""
    BIT_ZERO = 0
    BIT_ONE = 1
    SYNC_EVENT = auto()
    INVALID = auto()


@dataclass
class BitSample:
    """Bit sampling result"""
    bit: int                    # 0 or 1
    confidence: float           # 0-1
    phase_error: float          # Phase tracking error
    manchester_violation: bool  # True if invalid Manchester pattern detected


class BitClock:
    """
    Digital clock recovery for Manchester decoding
    
    Maintains phase alignment and samples at mid-bit boundaries.
    Decodes based on transition direction at bit-cell center.
    """
    
    def __init__(self, te: float, tolerance: float = 0.2):
        """
        Initialize bit clock
        
        Args:
            te: Time element (half-bit duration) in microseconds
            tolerance: Phase tolerance for sampling
        """
        self.te = te
        self.bit_period = 2 * te  # Full Manchester bit = 2×TE
        self.tolerance = tolerance
        
        # Phase accumulator (DPLL state)
        self.phase = 0.0  # Current phase in bit period (0-1)
        self.last_level = -1
        
        # Bit event callback
        self.on_bit: Optional[Callable[[BitSample], None]] = None
    
    def reset_phase(self):
        """Reset phase accumulator (call after sync)"""
        self.phase = 0.0
        self.last_level = -1
    
    def feed(self, level: int, duration_us: float):
        """
        Feed pulse to bit clock
        
        Args:
            level: Signal level (0 or 1)
            duration_us: Pulse duration in microseconds
        """
        # Advance phase by pulse duration
        phase_delta = duration_us / self.bit_period
        
        # Track transitions
        if self.last_level != -1 and level != self.last_level:
            # Transition occurred - sample at mid-bit
            self._sample_bit(self.last_level, level)
        
        # Update phase accumulator
        self.phase += phase_delta
        
        # Wrap phase (keep in 0-1 range, counting bit periods)
        while self.phase >= 1.0:
            self.phase -= 1.0
        
        self.last_level = level
    
    def _sample_bit(self, prev_level: int, curr_level: int):
        """
        Sample bit at transition (mid-bit in Manchester)
        
        Manchester encoding:
        - HIGH→LOW at mid-bit = 0
        - LOW→HIGH at mid-bit = 1
        
        Args:
            prev_level: Previous signal level
            curr_level: Current signal level
        """
        manchester_violation = False
        
        # Decode Manchester transition
        if prev_level == 1 and curr_level == 0:
            bit = 0  # HIGH→LOW = 0
        elif prev_level == 0 and curr_level == 1:
            bit = 1  # LOW→HIGH = 1
        else:
            # Invalid (same level twice - Manchester violation)
            manchester_violation = True
            bit = 0  # Default to 0, will be flagged
        
        # Phase error: should transition near phase=0.5 (mid-bit)
        # If phase near 0 or 1, we're at bit boundaries (wrong)
        phase_error = abs(self.phase - 0.5)
        
        # Confidence based on phase alignment
        confidence = 1.0 - (phase_error * 2.0)  # Map [0, 0.5] to [1.0, 0.0]
        confidence = max(0.0, min(1.0, confidence))
        
        # Penalize confidence if Manchester violation
        if manchester_violation:
            confidence *= 0.1  # Heavily penalize
        
        # Emit bit event
        if self.on_bit:
            self.on_bit(BitSample(
                bit=bit,
                confidence=confidence,
                phase_error=phase_error,
                manchester_violation=manchester_violation
            ))
    
    def set_bit_callback(self, callback: Callable[[BitSample], None]):
        """
        Set callback for bit events
        
        Args:
            callback: Function to call on each decoded bit
        """
        self.on_bit = callback
