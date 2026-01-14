"""
Frame Assembly and Multi-Frame Voting for Nice Flo-R

Enforces frame grammar and votes across repeated transmissions.
"""

import numpy as np
from typing import List, Optional, Dict
from dataclasses import dataclass
from collections import Counter


@dataclass
class FrameGrammar:
    """Frame structure requirements"""
    min_preamble_cycles: int = 8
    exact_bit_lengths: List[int] = None  # e.g., [12, 64, 66]
    min_repetitions: int = 3
    max_bit_disagreement: float = 0.1  # 10% max disagreement in voting
    
    def __post_init__(self):
        if self.exact_bit_lengths is None:
            self.exact_bit_lengths = [12, 52, 64, 66]  # Nice variants


@dataclass
class Frame:
    """Decoded frame"""
    bits: str
    confidence: float
    vote_count: int
    
    @property
    def bit_length(self) -> int:
        return len(self.bits)


class FrameAssembler:
    """
    Frame assembly with grammar enforcement and multi-frame voting
    
    Responsibilities:
    - Validate frame structure
    - Vote across repeated frames
    - Enforce minimum repetition count
    """
    
    def __init__(self, grammar: FrameGrammar = None):
        """
        Initialize frame assembler
        
        Args:
            grammar: Frame grammar rules
        """
        self.grammar = grammar or FrameGrammar()
        self.frame_buffer: List[str] = []  # Bitstrings
        self.current_bits: List[int] = []
    
    def add_bit(self, bit: int):
        """Add decoded bit to current frame"""
        self.current_bits.append(bit)
    
    def finalize_frame(self) -> bool:
        """
        Finalize current frame and add to buffer
        
        Returns:
            True if frame is valid
        """
        if not self.current_bits:
            return False
        
        # Convert to bitstring
        bits = ''.join(str(b) for b in self.current_bits)
        
        # Validate bit length
        if len(bits) not in self.grammar.exact_bit_lengths:
            self.current_bits.clear()
            return False
        
        # Add to buffer
        self.frame_buffer.append(bits)
        self.current_bits.clear()
        
        return True
    
    def vote_and_finalize(self) -> Optional[Frame]:
        """
        Vote across buffered frames and return stable frame
        
        Algorithm:
        1. Group frames by bit length
        2. Align frames
        3. Vote per bit position (majority)
        4. Check disagreement < threshold
        5. Require minimum repetitions
        
        Returns:
            Voted Frame or None if insufficient consensus
        """
        if len(self.frame_buffer) < self.grammar.min_repetitions:
            return None
        
        # Group by bit length
        length_groups: Dict[int, List[str]] = {}
        for frame in self.frame_buffer:
            length = len(frame)
            if length not in length_groups:
                length_groups[length] = []
            length_groups[length].append(frame)
        
        # Find most common length
        max_count = 0
        best_group = None
        for length, frames in length_groups.items():
            if len(frames) > max_count:
                max_count = len(frames)
                best_group = frames
        
        if not best_group or len(best_group) < self.grammar.min_repetitions:
            return None
        
        # Vote per bit position
        bit_length = len(best_group[0])
        voted_bits = []
        total_disagreement = 0
        
        for pos in range(bit_length):
            # Collect bits at this position
            bits_at_pos = [int(frame[pos]) for frame in best_group]
            
            # Vote (majority)
            counter = Counter(bits_at_pos)
            most_common_bit, count = counter.most_common(1)[0]
            
            # Track disagreement
            disagreement = 1.0 - (count / len(bits_at_pos))
            total_disagreement += disagreement
            
            voted_bits.append(str(most_common_bit))
        
        # Check overall disagreement
        avg_disagreement = total_disagreement / bit_length
        if avg_disagreement > self.grammar.max_bit_disagreement:
            return None  # Too much disagreement
        
        # Compute confidence
        confidence = 1.0 - avg_disagreement
        
        return Frame(
            bits=''.join(voted_bits),
            confidence=confidence,
            vote_count=len(best_group)
        )
    
    def reset(self):
        """Clear all buffers"""
        self.frame_buffer.clear()
        self.current_bits.clear()
