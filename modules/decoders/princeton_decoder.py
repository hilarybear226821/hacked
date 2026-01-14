"""
Production-Grade Princeton (PT2262/EV1527) Decoder

Improvements over prototype:
- Adaptive TE estimation (not fixed threshold)
- Sync-based frame locking
- Strict pulse grammar enforcement
- Raw duration preservation
- Structured results with confidence

This module exposes two layers:
- `PrincetonDecoder`: protocol-level decoder operating on (level, duration) pulses
- `PrincetonSubGhzDecoder`: adapter implementing the generic
  `SubGhzProtocolDecoder` interface used by `SubGhzDecoderManager`.
"""

import numpy as np
from typing import Optional, Dict, List, Tuple

from ..subghz_decoder import SubGhzProtocolDecoder


class PrincetonDecoder:
    """
    Princeton/PT2262/EV1527 decoder with production-grade robustness
    
    Protocol:
    - Encoding: Pulse-width (short=1TE, long=3TE)
    - Frame: [SYNC] + 12 bits (HIGH, LOW) pairs
    - Sync: Long LOW gap (~31 TE)
    - Idle: LOW
    """
    
    def __init__(self, tolerance: float = 0.4):
        """
        Initialize decoder
        
        Args:
            tolerance: Pulse duration tolerance (±40% typical for real captures)
        """
        self.tolerance = tolerance
        self.pulses: List[Tuple[int, float]] = []  # (level, duration_us)
        
    def feed(self, level: int, duration_us: float):
        """
        Feed pulse to decoder (preserves raw duration)
        
        Args:
            level: 1 for HIGH, 0 for LOW
            duration_us: Pulse duration in microseconds
        """
        self.pulses.append((level, duration_us))
    
    def _estimate_te(self, high_durations: List[float]) -> Optional[float]:
        """
        Estimate TE from HIGH pulse durations using ratio-based clustering
        
        Args:
            high_durations: List of HIGH pulse durations
            
        Returns:
            Estimated TE in microseconds, or None if insufficient data
        """
        if len(high_durations) < 4:
            return None
        
        # Use ratio-based clustering (not index slicing)
        durs = np.array(high_durations)
        med = np.median(durs)
        # Short pulses < 1.8× median
        shorts = durs[durs < med * 1.8]
        
        if len(shorts) == 0:
            return None
        
        return np.median(shorts)
    
    def _find_sync(self, pulses: List[Tuple[int, float]], te: float) -> Optional[int]:
        """
        Find sync gap with context checks (long LOW between HIGH pulses)
        
        Args:
            pulses: List of (level, duration) tuples
            te: Estimated TE
            
        Returns:
            Index after sync, or None if not found
        """
        sync_min = te * 28  # More strict (nominal 31 TE)
        sync_max = te * 45  # Prevent false lock on noise
        
        for i in range(1, len(pulses) - 1):
            level, duration = pulses[i]
            
            # Sync must be: preceded by HIGH, LOW itself, followed by HIGH
            if (level == 0 and
                pulses[i-1][0] == 1 and
                pulses[i+1][0] == 1 and
                sync_min <= duration <= sync_max):
                return i + 1  # Start after sync
        
        return None
    
    def _classify_duration(self, duration: float, te: float, is_off: bool = False) -> Optional[str]:
        """
        Classify pulse duration as SHORT or LONG
        
        Args:
            duration: Pulse duration in microseconds
            te: Estimated TE
            is_off: True if this is an OFF pulse (more lenient for last bit)
            
        Returns:
            'short' (1×TE) or 'long' (3×TE), or None if ambiguous
        """
        short_target = te * 1.0
        long_target = te * 3.0
        
        # Check if within tolerance
        if abs(duration - short_target) / short_target <= self.tolerance:
            return 'short'
        elif abs(duration - long_target) / long_target <= self.tolerance:
            return 'long'
        elif is_off and duration >= long_target * 0.6:  # OFF >= 1.8×TE counts as LONG
            # This handles last bit's OFF merging with interframe gap
            return 'long'
        else:
            return None  # Ambiguous
    
    def deserialize(self) -> Optional[Dict]:
        """
        Decode Princeton frame with strict validation
        
        Returns:
            Dictionary with decoded data and metadata, or None if decode fails
        """
        if len(self.pulses) < 24:  # Minimum: sync + 12 bits × 2 edges
            return None
        
        # Step 1: Estimate TE from HIGH pulses
        high_durations = [dur for level, dur in self.pulses if level == 1]
        te = self._estimate_te(high_durations)
        
        if te is None:
            return None
        
        # Step 2: Find sync and start frame decoding after it
        sync_idx = self._find_sync(self.pulses, te)
        
        if sync_idx is None:
            return None
        
        # Step 3: Enforce idle-LOW / frame starts with HIGH
        if sync_idx >= len(self.pulses) or self.pulses[sync_idx][0] != 1:
            return None  # Frame must start with HIGH
        
        # Step 4: Decode bits with strict grammar (HIGH → LOW only)
        bits = []
        classification_errors = []
        i = sync_idx
        
        while i < len(self.pulses) - 1 and len(bits) < 12:  # STOP at 12 bits
            level1, dur1 = self.pulses[i]
            level2, dur2 = self.pulses[i + 1]
            
            # Enforce HIGH → LOW strictly (reject noise)
            if level1 != 1 or level2 != 0:
                break  # Invalid sequence
            
            # Classify durations
            class1 = self._classify_duration(dur1, te, is_off=False)  # HIGH pulse
            class2 = self._classify_duration(dur2, te, is_off=True)   # LOW pulse
            
            if class1 is None or class2 is None:
                break  # Ambiguous timing
            
            # Decode bit (Princeton: short HIGH + long LOW = 0, long HIGH + short LOW = 1)
            if class1 == 'short' and class2 == 'long':
                bits.append('0')
                target1, target2 = te, te * 3
            elif class1 == 'long' and class2 == 'short':
                bits.append('1')
                target1, target2 = te * 3, te
            else:
                break  # Invalid pattern
            
            # Track classification error for confidence
            classification_errors.append(abs(dur1 - target1) / target1)
            classification_errors.append(abs(dur2 - target2) / target2)
            
            i += 2
        
        # Step 5: Validate exact bit length (PT2262 is exactly 12 bits)
        if len(bits) != 12:
            return None
        
        # Step 6: Convert and compute confidence
        bits_str = ''.join(bits)
        value = int(bits_str, 2)
        hex_str = f"{value:03X}"
        
        # Better confidence metric: classification margin
        confidence = max(0.0, 1.0 - np.mean(classification_errors)) if classification_errors else 0.5
        
        return {
            'protocol': 'princeton',
            'bits': bits_str,
            'hex': hex_str,
            'value': value,
            'te_us': te,
            'confidence': confidence,
            'bit_count': len(bits)
        }
    
    def reset(self):
        """Clear pulse buffer"""
        self.pulses.clear()


class PrincetonSubGhzDecoder(SubGhzProtocolDecoder):
    """
    Adapter exposing Princeton decoding via the generic SubGhzProtocolDecoder API.
    
    The higher-level `SubGhzDecoderManager` expects decoders to:
    - accept pulses via `feed(level, duration_us)`
    - return a hex payload string from `deserialize()`
    - expose a human-readable protocol name via `get_string()`
    """

    def __init__(self, tolerance: float = 0.4):
        self._decoder = PrincetonDecoder(tolerance=tolerance)

    def alloc(self) -> None:
        """Allocate/reset underlying protocol decoder state."""
        self._decoder.reset()

    def feed(self, level: int, duration: int) -> None:
        """Forward raw pulse to underlying decoder."""
        self._decoder.feed(level, float(duration))

    def deserialize(self) -> str:
        """
        Convert pulses into a hex payload string.

        Returns:
            Hex string (e.g. '0ABC') if a valid frame is decoded.

        Raises:
            ValueError if no valid frame is available.
        """
        result = self._decoder.deserialize()
        if not result:
            raise ValueError("No valid Princeton frame decoded")
        return result["hex"]

    def get_string(self) -> str:
        """Human-readable protocol name."""
        return "Princeton/PT2262"
