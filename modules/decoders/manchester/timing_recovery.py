"""
Timing Recovery for Nice Flo-R Manchester Decoder

Responsibilities:
- Collect raw pulse durations
- Cluster durations into ~1×TE, ~2×TE, ~4×TE (sync)
- Continuously refine TE estimate
- Reject frames if TE variance > tolerance
"""

import numpy as np
from typing import List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum, auto


class PulseClass(Enum):
    """Pulse classification relative to TE"""
    SHORT = auto()   # ~1×TE (half-bit)
    HALF = auto()    # Alias for SHORT
    LONG = auto()    # ~2×TE (full bit)
    SYNC = auto()    # ~4×TE (sync gap)
    INVALID = auto() # Outside tolerance


@dataclass
class TEStats:
    """TE estimation statistics"""
    te: float           # Base TE in microseconds
    variance: float     # TE variance (0-1)
    confidence: float   # Estimation confidence (0-1)
    sample_count: int   # Number of pulses used
    
    @property
    def half_bit(self) -> float:
        """Half-bit duration (1×TE)"""
        return self.te
    
    @property
    def full_bit(self) -> float:
        """Full bit duration (2×TE)"""
        return self.te * 2.0
    
    @property
    def sync_threshold(self) -> float:
        """Sync detection threshold (≥3.5×TE)"""
        return self.te * 3.5


class TimingRecovery:
    """
    Adaptive TE estimation and pulse classification
    
    Uses rolling buffer of pulse durations to continuously refine
    TE estimate and classify incoming pulses.
    """
    
    def __init__(self, tolerance: float = 0.35, buffer_size: int = 40):
        """
        Initialize timing recovery
        
        Args:
            tolerance: TE variance tolerance (default 35%)
            buffer_size: Rolling buffer size for TE estimation
        """
        self.tolerance = tolerance
        self.buffer_size = buffer_size
        self.pulse_buffer: List[float] = []
    
    def feed(self, duration_us: float):
        """
        Feed pulse duration to timing recovery
        
        Args:
            duration_us: Pulse duration in microseconds
        """
        self.pulse_buffer.append(duration_us)
        
        # Maintain rolling buffer
        if len(self.pulse_buffer) > self.buffer_size:
            self.pulse_buffer.pop(0)
    
    def estimate_te(self) -> Optional[TEStats]:
        """
        Estimate TE from collected pulses
        
        Algorithm:
        1. Use median of shortest quartile (preamble pulses ~1×TE)
        2. Calculate variance
        3. Reject if variance > tolerance
        
        Returns:
            TEStats or None if insufficient data or high variance
        """
        if len(self.pulse_buffer) < 10:
            return None
        
        # Convert to numpy for efficiency
        durations = np.array(self.pulse_buffer)
        
        # Shortest quartile represents ~1×TE pulses (preamble)
        sorted_durs = np.sort(durations)
        quartile_size = len(sorted_durs) // 4
        shortest_quartile = sorted_durs[:quartile_size] if quartile_size > 0 else sorted_durs[:1]
        
        # Estimate TE as median of shortest quartile
        te_estimate = np.median(shortest_quartile)
        
        # Calculate variance relative to TE
        deviations = np.abs(shortest_quartile - te_estimate) / te_estimate
        variance = np.mean(deviations)
        
        # Reject if variance too high
        if variance > self.tolerance:
            return None
        
        # Confidence based on sample count and low variance
        confidence = min(1.0, len(self.pulse_buffer) / self.buffer_size) * (1.0 - variance)
        
        return TEStats(
            te=te_estimate,
            variance=variance,
            confidence=confidence,
            sample_count=len(self.pulse_buffer)
        )
    
    def classify(self, duration_us: float, te_stats: TEStats) -> PulseClass:
        """
        Classify pulse duration relative to TE
        
        Args:
            duration_us: Pulse duration in microseconds
            te_stats: Current TE statistics
            
        Returns:
            PulseClass (SHORT/LONG/SYNC/INVALID)
        """
        te = te_stats.te
        tol = self.tolerance
        
        # Check each category with tolerance
        short_target = te * 1.0
        long_target = te * 2.0
        sync_min = te * 3.5
        sync_max = te * 6.0
        
        if abs(duration_us - short_target) / short_target <= tol:
            return PulseClass.SHORT
        elif abs(duration_us - long_target) / long_target <= tol:
            return PulseClass.LONG
        elif sync_min <= duration_us <= sync_max:
            return PulseClass.SYNC
        else:
            return PulseClass.INVALID
    
    def reset(self):
        """Clear pulse buffer"""
        self.pulse_buffer.clear()
