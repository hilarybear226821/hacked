"""
Timing Engine for Drift-Free Pulse Generation

Eliminates systematic quantization error when converting time to samples.
Critical for long frames and rolling codes.

Uses floor-based accumulation (not rounding) for deterministic edge placement.
"""

import numpy as np


class TimingAccumulator:
    """
    Fractional sample accumulator for drift-free timing
    
    Tracks fractional sample error across multiple duration conversions,
    eliminating systematic drift that would occur with naive int(duration * fs).
    
    Uses FLOOR (int()) not round() to ensure deterministic edge placement.
    
    Thread-unsafe: One instance per transmission stream.
    """
    
    def __init__(self, sample_rate: float):
        """
        Initialize timing accumulator
        
        Args:
            sample_rate: Sample rate in Hz
        """
        self.fs = sample_rate
        self.error = 0.0  # Fractional samples (bounded to [-1, 1])
    
    def samples(self, duration_sec: float) -> int:
        """
        Convert duration to sample count with error tracking
        
        Uses floor-based accumulation for deterministic timing.
        Jitter-free: same duration always produces same sample count.
        
        Args:
            duration_sec: Duration in seconds (must be > 0)
            
        Returns:
            Number of samples (floored, with error carried forward)
        """
        # Guard against invalid durations
        if duration_sec <= 0:
            return 0
        
        exact = duration_sec * self.fs
        total = exact + self.error
        n = int(total)  # Floor, not round - no jitter!
        self.error = total - n
        
        # Bound error to prevent FP precision drift over millions of pulses
        self.error = max(min(self.error, 1.0), -1.0)
        
        return n
    
    def reset(self):
        """
        Reset accumulated error
        
        Legal to call:
        - Between independent packets
        - Between capture/replay sessions
        - At start of new transmission stream
        
        MUST NOT call:
        - Mid-packet
        - Between ON/OFF edges of same symbol
        - During active pulse sequence
        """
        self.error = 0.0
