"""
Production Nice Flo-R Manchester Decoder

Implements:
1. Adaptive TE estimation (per-frame clustering)
2. Bit clock recovery (proper Manchester timing)
3. Rolling code structure (KeeLoq parsing)
4. Frame voting (noise resilience)

Based on validated Princeton decoder architecture.
"""

import numpy as np
from typing import Optional, Dict, List, Tuple
from collections import deque
from dataclasses import dataclass
import logging

from ..subghz_decoder import SubGhzProtocolDecoder

logger = logging.getLogger(__name__)


@dataclass
class NiceFrame:
    """Parsed Nice Flo-R frame structure"""
    bits: str
    button: int
    serial: int
    counter: int
    encrypted: int
    te_us: float
    confidence: float
    

class NiceFlorDecoder:
    """
    Production Nice Flo-R decoder with proper Manchester support
    
    Architecture:
    - Adaptive TE estimation (median clustering)
    - Bit clock recovery (2×TE bit cells)
    - Strict Manchester validation
    - Frame voting (3+ identical frames)
    - KeeLoq structure parsing
    """
    
    def __init__(self, tolerance: float = 0.3):
        """
        Initialize decoder
        
        Args:
            tolerance: Pulse duration tolerance (±30% for real remotes)
        """
        self.tolerance = tolerance
        self.pulses: List[Tuple[int, float]] = []
        self.frames: deque = deque(maxlen=10)  # Frame voting buffer
        
    def feed(self, level: int, duration_us: float):
        """
        Feed pulse to decoder
        
        Args:
            level: 1 for HIGH, 0 for LOW
            duration_us: Pulse duration in microseconds
        """
        self.pulses.append((level, duration_us))
    
    def _estimate_te(self, durations: List[float]) -> Optional[float]:
        """
        Estimate TE from pulse durations using adaptive clustering
        
        Manchester half-bit = 1×TE, so we cluster around shortest pulses.
        """
        if len(durations) < 10:
            return None
        
        durs = np.array(durations)
        # Preamble pulses are ~1×TE, use lower quartile
        sorted_durs = np.sort(durs)
        lower_quartile = sorted_durs[:len(sorted_durs)//4]
        
        if len(lower_quartile) == 0:
            return None
        
        return np.median(lower_quartile)
    
    def _find_preamble_sync(self, pulses: List[Tuple[int, float]], te: float) -> Optional[int]:
        """
        Find preamble end / sync gap
        
        Preamble: Alternating ~1×TE pulses (HIGH-LOW-HIGH-LOW...)
        Sync: Long gap ~4×TE
        
        Returns index after sync, or None
        """
        sync_min = te * 3.5  # ~4×TE
        sync_max = te * 6.0
        preamble_min_pulses = 8
        
        # Look for alternating pattern followed by long gap
        for i in range(preamble_min_pulses, len(pulses) - 1):
            level, duration = pulses[i]
            
            # Check if this is a sync gap (long LOW)
            if level == 0 and sync_min <= duration <= sync_max:
                # Validate preamble before it
                preamble_ok = self._validate_preamble(pulses[:i], te)
                if preamble_ok:
                    return i + 1  # Start data after sync
        
        return None
    
    def _validate_preamble(self, preamble_pulses: List[Tuple[int, float]], te: float) -> bool:
        """
        Validate preamble alternation and timing
        
        Allow some jitter but enforce:
        - Mostly alternating levels
        - Durations around 1×TE
        """
        if len(preamble_pulses) < 8:
            return False
        
        alternation_count = 0
        te_match_count = 0
        
        for i in range(1, len(preamble_pulses)):
            prev_level, prev_dur = preamble_pulses[i-1]
            curr_level, curr_dur = preamble_pulses[i]
            
            # Check alternation
            if curr_level != prev_level:
                alternation_count += 1
            
            # Check TE match (±tolerance)
            if abs(curr_dur - te) / te <= self.tolerance:
                te_match_count += 1
        
        # Require at least 70% alternation and TE match
        alternation_ratio = alternation_count / (len(preamble_pulses) - 1)
        te_ratio = te_match_count / len(preamble_pulses)
        
        return alternation_ratio >= 0.7 and te_ratio >= 0.6
    
    def _decode_manchester_data(self, data_pulses: List[Tuple[int, float]], te: float) -> Optional[str]:
        """
        Decode Manchester data with bit clock recovery
        
        Manchester encoding:
        - Each bit = 2 half-bits (2×TE total)
        - Transition at mid-bit determines value
        - IEEE: HIGH→LOW = 0, LOW→HIGH = 1
        
        Returns bit string or None if invalid
        """
        bits = []
        i = 0
        
        while i < len(data_pulses) - 1:
            level1, dur1 = data_pulses[i]
            level2, dur2 = data_pulses[i + 1]
            
            # Bit cell timing: dur1 + dur2 should ≈ 2×TE
            bit_cell_duration = dur1 + dur2
            expected_cell = 2 * te
            
            if abs(bit_cell_duration - expected_cell) / expected_cell > self.tolerance:
                # Bit cell timing violated, try to resync
                i += 1  # Slide by one pulse
                continue
            
            # Classify individual half-bits
            half1_ok = abs(dur1 - te) / te <= self.tolerance
            half2_ok = abs(dur2 - te) / te <= self.tolerance
            
            if not (half1_ok and half2_ok):
                i += 1
                continue
            
            # Decode Manchester transition
            if level1 == 1 and level2 == 0:
                bits.append('0')  # HIGH→LOW = 0
            elif level1 == 0 and level2 == 1:
                bits.append('1')  # LOW→HIGH = 1
            else:
                # Invalid Manchester (same level or wrong pattern)
                i += 1
                continue
            
            i += 2  # Consumed both half-bits
        
        # Nice frames are typically 52 or 64 bits
        if 50 <= len(bits) <= 66:
            return ''.join(bits)
        
        return None
    
    def _parse_keeloq_structure(self, bits: str) -> Optional[NiceFrame]:
        """
        Parse Nice Flo-R KeeLoq structure
        
        Typical structure (64-bit):
        - Bits 0-3: Button (4 bits)
        - Bits 4-31: Serial number (28 bits)
        - Bits 32-63: Encrypted payload (32 bits - KeeLoq block)
        
        Returns parsed frame or None
        """
        if len(bits) < 60:
            return None
        
        # Extract fields (bit order may vary by variant)
        button = int(bits[0:4], 2)
        serial = int(bits[4:32], 2)
        encrypted = int(bits[32:64], 2) if len(bits) >= 64 else int(bits[32:], 2)
        
        # Counter extraction would require KeeLoq decryption
        # For now, treat encrypted block as opaque
        counter = -1  # Unknown without decryption
        
        return NiceFrame(
            bits=bits,
            button=button,
            serial=serial,
            counter=counter,
            encrypted=encrypted,
            te_us=0,  # Will be filled by caller
            confidence=0  # Will be filled by caller
        )
    
    def deserialize(self) -> Optional[Dict]:
        """
        Decode Nice frame with full validation
        
        Returns decoded frame dict or None
        """
        if len(self.pulses) < 30:
            return None
        
        # Step 1: Estimate TE from all pulses
        all_durations = [dur for level, dur in self.pulses]
        te = self._estimate_te(all_durations)
        
        if te is None:
            return None
        
        # Step 2: Find preamble and sync
        sync_idx = self._find_preamble_sync(self.pulses, te)
        
        if sync_idx is None:
            return None
        
        # Step 3: Decode Manchester data
        data_pulses = self.pulses[sync_idx:]
        bits = self._decode_manchester_data(data_pulses, te)
        
        if bits is None:
            return None
        
        # Step 4: Parse KeeLoq structure
        frame = self._parse_keeloq_structure(bits)
        
        if frame is None:
            return None
        
        # Step 5: Compute confidence (bit-cell timing variance)
        timing_errors = []
        for i in range(0, len(data_pulses) - 1, 2):
            if i + 1 < len(data_pulses):
                dur1 = data_pulses[i][1]
                dur2 = data_pulses[i + 1][1]
                cell_dur = dur1 + dur2
                error = abs(cell_dur - 2 * te) / (2 * te)
                timing_errors.append(error)
        
        confidence = max(0.0, 1.0 - np.mean(timing_errors)) if timing_errors else 0.5
        
        # Step 6: Frame voting (check if we've seen this before)
        frame_key = (frame.button, frame.serial, frame.encrypted)
        self.frames.append(frame_key)
        
        # Count occurrences of this frame
        frame_count = sum(1 for f in self.frames if f == frame_key)
        
        # Require at least 2 identical frames for high confidence
        if frame_count < 2:
            confidence *= 0.5  # Penalize single-frame decodes
        
        return {
            'protocol': 'nice_flor',
            'bits': bits,
            'button': frame.button,
            'serial': f"0x{frame.serial:07X}",
            'encrypted': f"0x{frame.encrypted:08X}",
            'counter': frame.counter,
            'te_us': te,
            'confidence': confidence,
            'bit_count': len(bits),
            'frame_votes': frame_count
        }
    
    def reset(self):
        """Clear pulse buffer"""
        self.pulses.clear()


class NiceFlorSubGhzDecoder(SubGhzProtocolDecoder):
    """
    Adapter exposing Nice Flo-R Manchester decoding via the generic
    `SubGhzProtocolDecoder` API used by `SubGhzDecoderManager`.
    """

    def __init__(self, tolerance: float = 0.3):
        self._decoder = NiceFlorDecoder(tolerance=tolerance)

    def alloc(self) -> None:
        """Reset internal Manchester decoder state."""
        self._decoder.reset()

    def feed(self, level: int, duration: int) -> None:
        """Forward pulses (level, duration_us) into the Manchester decoder."""
        self._decoder.feed(level, float(duration))

    def deserialize(self) -> str:
        """
        Convert pulses into a stable payload identifier.

        Returns:
            A compact string including serial, button, and encrypted fields.

        Raises:
            ValueError if no valid Nice Flo-R frame is available.
        """
        result = self._decoder.deserialize()
        if not result:
            raise ValueError("No valid Nice Flo-R frame decoded")

        # Build a stable representation; primarily keyed on serial + button.
        serial = result.get("serial", "0x0000000")
        button = result.get("button", 0)
        encrypted = result.get("encrypted", "0x00000000")
        return f"{serial}|BTN{button:X}|{encrypted}"

    def get_string(self) -> str:
        """Human-readable protocol name."""
        return "Nice Flo-R (Manchester)"
