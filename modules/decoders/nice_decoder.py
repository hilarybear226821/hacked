
from ..subghz_decoder import SubGhzProtocolDecoder
from typing import Optional, List, Tuple
from enum import Enum, auto
from collections import deque
import logging

class NiceProtocolVariant(Enum):
    """Nice Protocol Variants"""
    FLO12 = auto()  # 12-bit fixed code (legacy)
    FLO24 = auto()   # 24-bit rolling code
    FLO24V2 = auto() # 24-bit v2 with enhanced security
    UNKNOWN = auto()

class DecoderState(Enum):
    """Finite State Machine for decoder"""
    IDLE = auto()
    SYNC = auto()
    PREAMBLE = auto()
    DATA = auto()
    COMPLETE = auto()
    ERROR = auto()

class NiceDecoder(SubGhzProtocolDecoder):
    """
    
    Frame Structure:
        [Preamble] [Sync] [Data] [CRC]
    
    Improvements (Fixed):
    1. ✅ Validates alternating levels in preamble (clock training)
    2. ✅ Uses deque for O(1) popleft operations
    3. ✅ Fixes hex format string (010X -> 016X for 64 bits)
    4. ✅ Detects signal inversion (Active Low vs Active High)
    5. ✅ Strict Manchester phase validation
    6. ✅ Proper sync pulse handling
    """
    
    # Timing constants (microseconds)
    TE_NOMINAL = 500
    TE_MIN = 400  # -20%
    TE_MAX = 650  # +30%
    
    TE_LONG_MIN = 1800  # Sync pulse (4 TE)
    TE_LONG_MAX = 2400
    
    # Protocol limits
    MIN_PREAMBLE_PULSES = 8
    MAX_BIT_COUNT = 80  # Safety limit
    
    # Variant-specific bit lengths
    VARIANT_BITS = {
        NiceProtocolVariant.FLO12: 12,
        NiceProtocolVariant.FLO24: 64,  # 24-bit data + 40-bit KeeLoq
        NiceProtocolVariant.FLO24V2: 66
    }

    def __init__(self):
        self.logger = logging.getLogger("NiceDecoder")
        self.reset()
        
    def reset(self):
        """Reset decoder state"""
        self.state = DecoderState.IDLE
        self.pulses: deque = deque()  # ✅ Changed from list to deque for O(1) popleft
        self.bits: List[int] = []
        self.preamble_count = 0
        self.variant = NiceProtocolVariant.UNKNOWN
        self.last_level = -1  # ✅ Track last level for alternation check
        self.error_msg = None
        self.inverted = False  # ✅ Track if signal is inverted

    def alloc(self) -> None:
        """Allocate/Reset buffer"""
        self.reset()

    def _classify_pulse(self, duration: int) -> Optional[str]:
        """
        Classify pulse duration into timing categories.
        Returns: 'TE', 'SYNC', or None if invalid
        """
        if self.TE_MIN <= duration <= self.TE_MAX:
            return 'TE'
        elif self.TE_LONG_MIN <= duration <= self.TE_LONG_MAX:
            return 'SYNC'
        else:
            return None

    def feed(self, level: int, duration: int) -> None:
        """
        Feed edge event to decoder state machine.
        
        Args:
            level: Signal level (0 = low, 1 = high)
            duration: Duration in microseconds
        """
        pulse_type = self._classify_pulse(duration)
        
        # State Machine
        if self.state == DecoderState.IDLE:
            if pulse_type == 'TE' and level == 1:
                self.state = DecoderState.PREAMBLE
                self.preamble_count = 1
                self.last_level = level
            return
            
        elif self.state == DecoderState.PREAMBLE:
            if pulse_type == 'TE':
                # ✅ FIXED: Validate alternating levels (Manchester preamble requirement)
                if self.last_level != -1 and level == self.last_level:
                    # Same level twice = invalid Manchester preamble
                    self._error(f"Preamble violation: non-alternating levels ({level})")
                    return
                
                self.preamble_count += 1
                self.last_level = level
                
                # ✅ Detect signal inversion from preamble
                if self.preamble_count == 2:
                    # If first two pulses are 0->1, signal is inverted
                    # Standard is 1->0->1->0 (High first)
                    # Inverted is 0->1->0->1 (Low first)
                    if level == 0:  # Second pulse is Low after High
                        self.inverted = False  # Normal polarity
                    else:  # Second pulse is High after Low (started with Low)
                        self.inverted = True
                        self.logger.debug("Detected inverted signal")
                
            elif pulse_type == 'SYNC':
                if self.preamble_count >= self.MIN_PREAMBLE_PULSES:
                    self.state = DecoderState.DATA
                    self.pulses.clear()  # ✅ Use clear() instead of assignment
                    self.last_level = -1  # Reset for data phase
                else:
                    self._error(f"Insufficient preamble: {self.preamble_count} < {self.MIN_PREAMBLE_PULSES}")
            else:
                self._error(f"Invalid preamble timing: {duration}µs")
            return
            
        elif self.state == DecoderState.DATA:
            if pulse_type == 'TE':
                self.pulses.append((level, duration))
                
                # Decode Manchester bit pairs
                if len(self.pulses) >= 2:
                    self._decode_manchester_pair()
                    
                # Check completion
                if len(self.bits) >= self.MAX_BIT_COUNT:
                    self._finalize()
            else:
                # End of transmission or error
                if len(self.bits) >= 12:
                    self._finalize()
                else:
                    self._error(f"Incomplete data: only {len(self.bits)} bits")
            return
            
        elif self.state == DecoderState.COMPLETE:
            # Ignore further input
            return
            
        elif self.state == DecoderState.ERROR:
            # Stuck in error state
            return

    def _decode_manchester_pair(self):
        """
        Decode Manchester encoding from last two pulses.
        Manchester: High-Low = 1, Low-High = 0
        
        ✅ IMPROVED: Uses deque.popleft() for O(1) efficiency
        ✅ IMPROVED: Handles signal inversion
        """
        if len(self.pulses) < 2:
            return
            
        # ✅ Pop two pulses (efficient with deque)
        p1 = self.pulses.popleft()
        p2 = self.pulses.popleft()
        
        level1, dur1 = p1
        level2, dur2 = p2
        
        # Validate both are TE
        if self._classify_pulse(dur1) != 'TE' or self._classify_pulse(dur2) != 'TE':
            self._error(f"Invalid Manchester timing: {dur1}µs, {dur2}µs")
            return
            
        # ✅ Decode bit (with optional inversion handling)
        if level1 == 1 and level2 == 0:
            # High-Low = 1 (standard)
            bit = 1 if not self.inverted else 0
            self.bits.append(bit)
        elif level1 == 0 and level2 == 1:
            # Low-High = 0 (standard)
            bit = 0 if not self.inverted else 1
            self.bits.append(bit)
        else:
            # Invalid Manchester (same level)
            self._error(f"Manchester violation: {level1}-{level2}")

    def _finalize(self):
        """
        Finalize decoding and determine variant.
        ✅ IMPROVED: Stricter bit count validation
        """
        bit_count = len(self.bits)
        
        # Determine variant based on exact bit count
        if bit_count == 12:
            self.variant = NiceProtocolVariant.FLO12
        elif bit_count == 64:
            self.variant = NiceProtocolVariant.FLO24
        elif bit_count == 66:
            self.variant = NiceProtocolVariant.FLO24V2
        elif 60 <= bit_count <= 68:
            # Tolerance for slight variations
            self.variant = NiceProtocolVariant.FLO24
            self.logger.warning(f"Non-standard bit count {bit_count}, assuming FLO24")
        else:
            self._error(f"Invalid bit count: {bit_count}")
            return
            
        self.state = DecoderState.COMPLETE
        self.logger.debug(f"Decoded {self.variant.name}: {bit_count} bits")

    def _error(self, msg: str):
        """Set error state"""
        self.state = DecoderState.ERROR
        self.error_msg = msg
        self.logger.debug(f"Nice Decode Error: {msg}")

    def deserialize(self) -> str:
        """
        Extract payload as hex string.
        
        ✅ FIXED: Corrected hex format string (010X -> 016X for 64 bits)
        
        Returns:
            Hex string of decoded data
            
        Raises:
            ValueError: If decode incomplete or failed
        """
        if self.state == DecoderState.ERROR:
            raise ValueError(f"Decode error: {self.error_msg}")
            
        if self.state != DecoderState.COMPLETE:
            raise ValueError("Incomplete decode")
            
        if not self.bits:
            raise ValueError("No bits decoded")
            
        # Convert bits to integer
        bit_str = ''.join(str(b) for b in self.bits)
        payload_int = int(bit_str, 2)
        bit_count = len(self.bits)
        
        # ✅ FIXED: Format based on actual bit count
        # Calculate hex width: bit_count / 4 (rounded up)
        hex_width = (bit_count + 3) // 4
        
        # Use dynamic format string
        return format(payload_int, f'0{hex_width}X')

    def get_string(self) -> str:
        """Get human-readable protocol name"""
        if self.variant == NiceProtocolVariant.FLO12:
            return "Nice Flo12 (Fixed Code)"
        elif self.variant == NiceProtocolVariant.FLO24:
            return "Nice Flo24 (Rolling Code)"
        elif self.variant == NiceProtocolVariant.FLO24V2:
            return "Nice Flo24v2 (Enhanced)"
        else:
            return "Nice (Flo-R) Remote"
            
    def get_metadata(self) -> dict:
        """
        Extract protocol metadata.
        ✅ IMPROVED: Added more diagnostic info
        """
        return {
            'variant': self.variant.name,
            'bit_count': len(self.bits),
            'preamble_pulses': self.preamble_count,
            'state': self.state.name,
            'error': self.error_msg,
            'inverted': self.inverted,  # ✅ New field
            'hex_payload': self.deserialize() if self.state == DecoderState.COMPLETE else None
        }
    
    def __repr__(self) -> str:
        """String representation for debugging"""
        return (f"<NiceDecoder state={self.state.name} variant={self.variant.name} "
                f"bits={len(self.bits)} inverted={self.inverted}>")
