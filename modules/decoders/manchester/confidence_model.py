"""
Confidence Model for Nice Flo-R Decoding

Multi-input scoring system for decode reliability assessment.
"""

import numpy as np
from typing import List, Dict
from dataclasses import dataclass


@dataclass
class ConfidenceInputs:
    """Inputs for confidence scoring"""
    te_variance: float          # TE estimation variance (0-1)
    manchester_violations: int  # Count of Manchester violations
    pulse_jitter: float         # Pulse timing jitter (0-1)
    frame_disagreement: float   # Bit disagreement during voting (0-1)
    agc_stability: float        # Early pulse stability (0-1)
    phase_errors: List[float]   # Bit clock phase errors


@dataclass
class ConfidenceScore:
    """Overall confidence assessment"""
    score: float          # Overall confidence (0-1)
    timing_score: float   # Timing quality (0-1)
    decode_score: float   # Decode quality (0-1)
    voting_score: float   # Voting consensus (0-1)
    accept: bool         # Whether to accept decode
    
    def __str__(self) -> str:
        return f"Confidence: {self.score:.1%} (timing={self.timing_score:.1%}, decode={self.decode_score:.1%}, voting={self.voting_score:.1%})"


class ConfidenceModel:
    """
    Multi-input confidence scoring for decode reliability
    
    Combines multiple quality metrics into overall confidence score.
    """
    
    def __init__(self, acceptance_threshold: float = 0.7):
        """
        Initialize confidence model
        
        Args:
            acceptance_threshold: Minimum confidence to accept decode
        """
        self.acceptance_threshold = acceptance_threshold
    
    def evaluate(self, inputs: ConfidenceInputs) -> ConfidenceScore:
        """
        Evaluate confidence from multiple inputs
        
        Args:
            inputs: Confidence input metrics
            
        Returns:
            Overall confidence score
        """
        # Timing quality score
        te_score = 1.0 - inputs.te_variance
        jitter_score = 1.0 - inputs.pulse_jitter
        agc_score = inputs.agc_stability
        
        timing_score = (te_score + jitter_score + agc_score) / 3.0
        
        # Decode quality score
        manchester_penalty = min(1.0, inputs.manchester_violations / 10.0)
        
        # Phase error score (mean of bit clock phase errors)
        if inputs.phase_errors:
            phase_error_mean = np.mean(inputs.phase_errors)
            phase_score = 1.0 - phase_error_mean
        else:
            phase_score = 0.5  # Unknown
        
        decode_score = (1.0 - manchester_penalty) * phase_score
        
        # Voting quality score
        voting_score = 1.0 - inputs.frame_disagreement
        
        # Overall score (weighted average)
        overall_score = (
            timing_score * 0.3 +
            decode_score * 0.4 +
            voting_score * 0.3
        )
        
        # Acceptance decision
        accept = overall_score >= self.acceptance_threshold
        
        return ConfidenceScore(
            score=overall_score,
            timing_score=timing_score,
            decode_score=decode_score,
            voting_score=voting_score,
            accept=accept
        )
