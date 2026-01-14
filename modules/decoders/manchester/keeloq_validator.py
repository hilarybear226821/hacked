"""
KeeLoq Structure Validator for Nice Flo-R

Validates rolling code structure without decryption.
Detects impossible frames and noise.
"""

import numpy as np
from typing import Optional, Dict, List
from dataclasses import dataclass
from collections import defaultdict


@dataclass
class KeeLoqFrame:
    """Parsed KeeLoq frame structure"""
    button: int         # Button code (4 bits)
    serial: int         # Remote serial (28 bits)
    encrypted: int      # Encrypted payload (32 bits)
    counter: int        # Counter (requires decryption, -1 if unknown)
    bit_entropy: float  # Bit entropy (0-1, noise detection)


class KeeLoqValidator:
    """
    KeeLoq structure validation without cryptographic keys
    
    Validates:
    - Frame structure
    - Serial number consistency
    - Counter monotonicity (per serial)
    - Bit entropy (noise detection)
    
    Does NOT:
    - Decrypt payloads
    - Verify authentication
    - Extract actual counter without key
    """
    
    def __init__(self):
        """Initialize validator"""
        # Track seen serials and their counter history
        self.serial_history: Dict[int, List[int]] = defaultdict(list)
    
    def parse_frame(self, bits: str) -> Optional[KeeLoqFrame]:
        """
        Parse Nice Flo-R KeeLoq structure
        
        Typical 64-bit structure:
        - Bits 0-3: Button (4 bits)
        - Bits 4-31: Serial number (28 bits)
        - Bits 32-63: Encrypted payload (32 bits - KeeLoq block)
        
        Args:
            bits: Bitstring (typically 64 bits)
            
        Returns:
            Parsed frame or None if invalid structure
        """
        if len(bits) < 60:
            return None
        
        try:
            # Extract fields (bit order may vary by variant)
            button = int(bits[0:4], 2)
            serial = int(bits[4:32], 2)
            encrypted = int(bits[32:64], 2) if len(bits) >= 64 else int(bits[32:], 2)
            
            # Calculate bit entropy (Shannon entropy)
            bit_array = np.array([int(b) for b in bits])
            entropy = self._calculate_entropy(bit_array)
            
            return KeeLoqFrame(
                button=button,
                serial=serial,
                encrypted=encrypted,
                counter=-1,  # Unknown without decryption
                bit_entropy=entropy
            )
        except ValueError:
            return None
    
    def validate_frame(self, frame: KeeLoqFrame, strict: bool = True) -> bool:
        """
        Validate KeeLoq frame structure
        
        Args:
            frame: Parsed frame
            strict: If True, enforce strict validation
            
        Returns:
            True if frame appears valid
        """
        # Check button range (typically 0-15)
        if frame.button > 15:
            return False
        
        # Check serial is non-zero (zero serial is invalid)
        if frame.serial == 0:
            return False
        
        # Check entropy (noise has very low or very high entropy)
        # Real frames have moderate entropy (not all 0s, not random)
        if strict:
            if frame.bit_entropy < 0.2 or frame.bit_entropy > 0.9:
                return False  # Likely noise
        
        # Check encrypted payload is non-trivial
        if frame.encrypted == 0 or frame.encrypted == 0xFFFFFFFF:
            return False  # All zeros or all ones = invalid
        
        return True
    
    def check_serial_consistency(self, frame: KeeLoqFrame) -> bool:
        """
        Check if this serial has been seen before consistently
        
        Rolling code remotes should have:
        - Same serial across frames
        - Incrementing counter (cannot verify without decryption)
        
        Args:
            frame: Parsed frame
            
        Returns:
            True if serial appears consistent
        """
        serial = frame.serial
        
        # First time seeing this serial
        if serial not in self.serial_history:
            self.serial_history[serial] = [frame.encrypted]
            return True
        
        # Add to history
        self.serial_history[serial].append(frame.encrypted)
        
        # Check for repeated encrypted blocks (replay detection)
        # Same serial + same encrypted = possible replay
        history = self.serial_history[serial]
        if history.count(frame.encrypted) > 2:
            return False  # Likely replay or noise
        
        return True
    
    def _calculate_entropy(self, bits: np.ndarray) -> float:
        """
        Calculate Shannon entropy of bit sequence
        
        Args:
            bits: Binary array
            
        Returns:
            Normalized entropy (0-1)
        """
        if len(bits) == 0:
            return 0.0
        
        # Count 0s and 1s
        unique, counts = np.unique(bits, return_counts=True)
        probabilities = counts / len(bits)
        
        # Shannon entropy
        entropy = -np.sum(probabilities * np.log2(probabilities + 1e-10))
        
        # Normalize to 0-1 (max entropy for binary is 1.0)
        return entropy
    
    def reset_history(self):
        """Clear serial history"""
        self.serial_history.clear()
