"""
Protocol Auto-Detection Engine
Automatically identifies RF protocols from signal characteristics
"""

import numpy as np
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass

@dataclass
class ProtocolSignature:
    """Protocol identification signature"""
    name: str
    te_min: int  # Minimum time element (microseconds)
    te_max: int  # Maximum time element
    frame_bits_min: int
    frame_bits_max: int
    preamble_pattern: Optional[str] = None
    common_freqs: List[float] = None  # MHz
    
class ProtocolDetector:
    """
    Automatically detect RF protocol from signal characteristics
    
    Supports:
    - KeeLoq (car fobs)
    - EV1527 (cheap remotes)
    - Princeton PT2260/2262
    - CAME 12-bit
    - Nice Flo-R
    - Chamberlain Security+
    """
    
    # Protocol signatures database
    PROTOCOLS = {
        "KeeLoq": ProtocolSignature(
            name="KeeLoq",
            te_min=350,
            te_max=450,
            frame_bits_min=66,
            frame_bits_max=66,
            common_freqs=[315.0, 433.92]
        ),
        "EV1527": ProtocolSignature(
            name="EV1527",
            te_min=250,
            te_max=450,
            frame_bits_min=24,
            frame_bits_max=24,
            common_freqs=[315.0, 433.92]
        ),
        "Princeton": ProtocolSignature(
            name="Princeton PT2262",
            te_min=300,
            te_max=500,
            frame_bits_min=24,
            frame_bits_max=24,
            common_freqs=[315.0, 433.92]
        ),
        "CAME": ProtocolSignature(
            name="CAME 12-bit",
            te_min=300,
            te_max=400,
            frame_bits_min=12,
            frame_bits_max=12,
            common_freqs=[433.92]
        ),
        "NiceFlorR": ProtocolSignature(
            name="Nice Flo-R",
            te_min=500,
            te_max=700,
            frame_bits_min=12,
            frame_bits_max=12,
            common_freqs=[433.92]
        ),
        "SecurityPlus": ProtocolSignature(
            name="Security+ (Chamberlain)",
            te_min=1500,
            te_max=2500,
            frame_bits_min=40,
            frame_bits_max=40,
            common_freqs=[310.0, 315.0, 390.0]
        )
    }
    
    def __init__(self):
        self.last_detection = None
    
    def analyze_pulses(self, pulses: List[Tuple[int, int]]) -> Dict:
        """
        Analyze pulse stream to identify protocol
        
        Args:
            pulses: List of (level, duration_us) tuples
        
        Returns:
            dict with detection results
        """
        if not pulses or len(pulses) < 10:
            return {"protocol": "Unknown", "confidence": 0.0, "reason": "Insufficient data"}
        
        # Calculate pulse statistics
        durations = [dur for _, dur in pulses]
        high_pulses = [dur for level, dur in pulses if level == 1]
        low_pulses = [dur for level, dur in pulses if level == 0]
        
        # Estimate TE (time element)
        te_estimate = self._estimate_te(durations)
        
        # Estimate bit count
        bit_count = len(pulses) // 2  # Rough estimate
        
        # Score each protocol
        scores = {}
        for proto_name, signature in self.PROTOCOLS.items():
            score = self._score_protocol(signature, te_estimate, bit_count)
            scores[proto_name] = score
        
        # Best match
        best_protocol = max(scores, key=scores.get)
        best_score = scores[best_protocol]
        
        result = {
            "protocol": best_protocol,
            "confidence": best_score,
            "te_estimate": te_estimate,
            "estimated_bits": bit_count,
            "all_scores": scores
        }
        
        # Add decoder recommendation
        if best_score > 0.7:
            result["decoder"] = self._get_decoder_class(best_protocol)
            result["action"] = "decode"
        elif best_score > 0.4:
            result["decoder"] = self._get_decoder_class(best_protocol)
            result["action"] = "try_decode"
        else:
            result["decoder"] = None
            result["action"] = "record_only"
        
        self.last_detection = result
        return result
    
    def _estimate_te(self, durations: List[int]) -> int:
        """
        Estimate the base time element (TE) from pulse durations
        
        Uses GCD-like approach to find fundamental timing unit
        """
        if not durations:
            return 0
        
        # Filter out very short glitches (< 100us) and very long pauses (> 10ms)
        filtered = [d for d in durations if 100 < d < 10000]
        
        if not filtered:
            return 0
        
        # Use histogram to find common durations
        hist, bins = np.histogram(filtered, bins=50)
        
        # Find peaks in histogram
        peaks = []
        for i in range(1, len(hist) - 1):
            if hist[i] > hist[i-1] and hist[i] > hist[i+1] and hist[i] > 2:
                peaks.append(int(bins[i]))
        
        if not peaks:
            return int(np.median(filtered))
        
        # TE is typically the smallest common duration
        return min(peaks)
    
    def _score_protocol(self, signature: ProtocolSignature, te: int, bits: int) -> float:
        """
        Score how well signal matches protocol signature
        
        Returns:
            Score from 0.0 (no match) to 1.0 (perfect match)
        """
        score = 0.0
        
        # Check TE timing (40% weight)
        if signature.te_min <= te <= signature.te_max:
            # Perfect match
            te_center = (signature.te_min + signature.te_max) / 2
            te_deviation = abs(te - te_center) / te_center
            score += 0.4 * (1.0 - min(te_deviation, 1.0))
        else:
            # Partial credit for close timing
            te_center = (signature.te_min + signature.te_max) / 2
            te_deviation = abs(te - te_center) / te_center
            if te_deviation < 0.5:
                score += 0.2 * (1.0 - te_deviation)
        
        # Check bit count (60% weight)
        if signature.frame_bits_min <= bits <= signature.frame_bits_max:
            score += 0.6
        else:
            # Partial credit for similar bit count
            bit_center = (signature.frame_bits_min + signature.frame_bits_max) / 2
            bit_deviation = abs(bits - bit_center) / bit_center
            if bit_deviation < 0.5:
                score += 0.3 * (1.0 - bit_deviation)
        
        return min(score, 1.0)
    
    def _get_decoder_class(self, protocol_name: str) -> str:
        """Get decoder module name for protocol"""
        decoder_map = {
            "KeeLoq": "keeloq_decoder.KeeLoqDecoder",
            "EV1527": "ev1527_decoder.EV1527Decoder",
            "Princeton": "princeton_decoder.PrincetonDecoder",
            "CAME": "came_decoder.CAMEDecoder",
            "NiceFlorR": "nice_decoder.NiceDecoder",
            "SecurityPlus": "securityplus_decoder.SecurityPlusDecoder"
        }
        return decoder_map.get(protocol_name, None)
    
    def detect_from_file(self, filename: str, sample_rate: int = 2e6) -> Dict:
        """
        Detect protocol from recorded IQ file
        
        Args:
            filename: Path to CS16 or complex sample file
            sample_rate: Sample rate in Hz
        
        Returns:
            Detection results dict
        """
        try:
            # Load IQ samples
            with open(filename, 'rb') as f:
                data = np.fromfile(f, dtype=np.int8)
            
            # Convert to complex
            iq = data[::2] + 1j * data[1::2]
            
            # Demodulate to get pulses (simple envelope detection)
            magnitude = np.abs(iq)
            threshold = np.mean(magnitude) + 2 * np.std(magnitude)
            
            # Extract pulses
            pulses = self._extract_pulses(magnitude, threshold, sample_rate)
            
            # Analyze
            result = self.analyze_pulses(pulses)
            result["pulses"] = pulses
            return result
            
        except Exception as e:
            return {
                "protocol": "Unknown",
                "confidence": 0.0,
                "reason": f"Error: {e}"
            }
    
    def _extract_pulses(self, magnitude: np.ndarray, threshold: float, sample_rate: float) -> List[Tuple[int, int]]:
        """
        Extract pulse list from magnitude data
        
        Returns:
            List of (level, duration_us) tuples
        """
        pulses = []
        current_level = int(magnitude[0] > threshold)
        pulse_start = 0
        
        for i in range(1, len(magnitude)):
            level = int(magnitude[i] > threshold)
            
            if level != current_level:
                # Pulse transition
                duration_samples = i - pulse_start
                duration_us = int((duration_samples / sample_rate) * 1e6)
                
                pulses.append((current_level, duration_us))
                
                current_level = level
                pulse_start = i
        
        return pulses
    
    def get_attack_recommendations(self, protocol: str) -> List[str]:
        """
        Get recommended attacks for detected protocol
        
        Returns:
            List of attack names
        """
        recommendations = {
            "KeeLoq": [
                "RollJam (2-code capture)",
                "Replay Attack",
                "Brute Force Serial (28-bit)",
                "Jam Only"
            ],
            "EV1527": [
                "Replay Attack",
                "Brute Force (24-bit)",
                "Clone to Flipper Zero"
            ],
            "Princeton": [
                "Replay Attack",
                "Brute Force (24-bit)",
                "Protocol Analysis"
            ],
            "CAME": [
                "Replay Attack",
                "Brute Force (12-bit - FAST!)",
                "RollJam"
            ],
            "NiceFlorR": [
                "RollJam",
                "Brute Force (12-bit)",
                "Replay Attack"
            ],
            "SecurityPlus": [
                "RollJam (complex)",
                "Capture & Analyze",
                "Frequency Hopping Track"
            ]
        }
        
        return recommendations.get(protocol, ["Replay Attack", "Signal Analysis"])

