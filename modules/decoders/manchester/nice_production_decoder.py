"""
Production Nice Flo-R Manchester Decoder

Orchestrates all layers:
1. Timing Recovery
2. Bit Clock
3. Frame Assembly
4. Confidence Model
5. KeeLoq Validation
"""

from typing import Optional, Dict, List, Tuple
import logging
import numpy as np

from .timing_recovery import TimingRecovery, TEStats, PulseClass
from .bit_clock import BitClock, BitSample
from .frame_assembler import FrameAssembler, Frame, FrameGrammar
from .confidence_model import ConfidenceModel, ConfidenceInputs, ConfidenceScore
from .keeloq_validator import KeeLoqValidator, KeeLoqFrame


logger = logging.getLogger(__name__)


class NiceFlorProductionDecoder:
    """
    Production-grade Nice Flo-R decoder with layered architecture
    
    Signal flow:
    Raw Pulses → Timing Recovery → Bit Clock → Frame Assembly
    → Confidence → KeeLoq Validation → Final Decode
    """
    
    def __init__(self, tolerance: float = 0.35):
        """
        Initialize decoder
        
        Args:
            tolerance: Timing tolerance (default 35%)
        """
        self.tolerance = tolerance
        
        # Layer 1: Timing recovery
        self.timing = TimingRecovery(tolerance=tolerance)
        
        # Layer 2: Bit clock (initialized once TE known)
        self.bit_clock: Optional[BitClock] = None
        
        # Layer 3: Frame assembly
        self.frame_asm = FrameAssembler(FrameGrammar())
        
        # Layer 4: Confidence model
        self.confidence = ConfidenceModel(acceptance_threshold=0.7)
        
        # Layer 5: KeeLoq validator
        self.keeloq = KeeLoqValidator()
        
        # State
        self.te_stats: Optional[TEStats] = None
        self.pulses: List[Tuple[int, float]] = []
        self.manchester_violations = 0
        self.phase_errors: List[float] = []
        
    def feed(self, level: int, duration_us: float):
        """
        Feed pulse to decoder
        
        Args:
            level: Signal level (0 or 1)
            duration_us: Pulse duration in microseconds
        """
        # Store pulse
        self.pulses.append((level, duration_us))
        
        # Layer 1: Timing recovery
        self.timing.feed(duration_us)
        
        # Try to estimate TE
        if self.te_stats is None:
            self.te_stats = self.timing.estimate_te()
            
            if self.te_stats:
                # Initialize bit clock once TE known
                self.bit_clock = BitClock(self.te_stats.te, tolerance=self.tolerance)
                self.bit_clock.set_bit_callback(self._on_bit)
                logger.info(f"TE estimated: {self.te_stats.te:.1f} µs (confidence={self.te_stats.confidence:.1%})")
        
        # Layer 2: Bit clock (if initialized)
        if self.bit_clock:
            self.bit_clock.feed(level, duration_us)
    
    def _on_bit(self, bit_sample: BitSample):
        """
        Bit clock callback - receives decoded bits
        
        Args:
            bit_sample: Decoded bit with confidence and error metrics
        """
        # Track Manchester violations
        if bit_sample.manchester_violation:
            self.manchester_violations += 1
        
        # Track phase errors for confidence
        self.phase_errors.append(bit_sample.phase_error)
        
        # Add to frame assembler
        self.frame_asm.add_bit(bit_sample.bit)
    
    def _calculate_agc_stability(self) -> float:
        """
        Calculate AGC stability from early pulses
        
        AGC ramp-up causes first few pulses to have inconsistent amplitudes/durations.
        Stability = consistency of early pulse durations.
        
        Returns:
            Stability score (0-1), higher is better
        """
        if len(self.pulses) < 10:
            return 0.5  # Unknown
        
        # Use first 10 pulses
        early_durations = [dur for level, dur in self.pulses[:10]]
        
        # Calculate coefficient of variation (CV)
        mean_dur = np.mean(early_durations)
        std_dur = np.std(early_durations)
        
        if mean_dur == 0:
            return 0.0
        
        cv = std_dur / mean_dur
        
        # Convert CV to stability score (lower CV = higher stability)
        stability = max(0.0, 1.0 - cv)
        
        return stability
    
    def deserialize(self) -> Optional[Dict]:
        """
        Finalize decoding and return result
        
        Automatically resets state after decode attempt to prevent stale data.
        
        Returns:
            Decoded frame dict or None if validation fails
        """
        try:
            if not self.te_stats:
                logger.debug("Decode failed: No TE estimate")
                return None
            
            logger.info(f"TE: {self.te_stats.te:.1f}µs (conf={self.te_stats.confidence:.1%}, var={self.te_stats.variance:.1%})")
            
            # Layer 3: Finalize and vote frames
            voted_frame = self.frame_asm.vote_and_finalize()
            
            if not voted_frame:
                logger.debug("Decode failed: Frame voting failed")
                return None
            
            logger.info(f"Frame: {voted_frame.vote_count} votes, {len(voted_frame.bits)} bits, conf={voted_frame.confidence:.1%}")
            
            # Layer 4: Confidence scoring
            agc_stability = self._calculate_agc_stability()
            
            confidence_inputs = ConfidenceInputs(
                te_variance=self.te_stats.variance,
                manchester_violations=self.manchester_violations,
                pulse_jitter=self.te_stats.variance,
                frame_disagreement=1.0 - voted_frame.confidence,
                agc_stability=agc_stability,
                phase_errors=self.phase_errors
            )
            
            confidence_score = self.confidence.evaluate(confidence_inputs)
            logger.info(f"Confidence: {confidence_score}")
            
            if not confidence_score.accept:
                logger.warning(f"Decode rejected: {confidence_score}")
                return None
            
            # Layer 5: KeeLoq validation
            keeloq_frame = self.keeloq.parse_frame(voted_frame.bits)
            
            if not keeloq_frame:
                logger.debug("Decode failed: KeeLoq parsing failed")
                return None
            
            if not self.keeloq.validate_frame(keeloq_frame, strict=True):
                logger.warning(f"KeeLoq failed: btn={keeloq_frame.button}, entropy={keeloq_frame.bit_entropy:.2f}")
                return None
            
            if not self.keeloq.check_serial_consistency(keeloq_frame):
                logger.warning(f"Serial 0x{keeloq_frame.serial:07X} inconsistent (replay?)")
            
            # Success
            logger.info(f"✓ Decoded: btn={keeloq_frame.button}, serial=0x{keeloq_frame.serial:07X}, conf={confidence_score.score:.1%}")
            
            return {
                'protocol': 'nice_flor',
                'bits': voted_frame.bits,
                'button': keeloq_frame.button,
                'serial': f"0x{keeloq_frame.serial:07X}",
                'encrypted': f"0x{keeloq_frame.encrypted:08X}",
                'counter': keeloq_frame.counter,
                'te_us': self.te_stats.te,
                'confidence': confidence_score.score,
                'bit_count': len(voted_frame.bits),
                'frame_votes': voted_frame.vote_count,
                'entropy': keeloq_frame.bit_entropy,
                'confidence_breakdown': {
                    'timing': confidence_score.timing_score,
                    'decode': confidence_score.decode_score,
                    'voting': confidence_score.voting_score
                },
                'manchester_violations': self.manchester_violations
            }
        finally:
            # Auto-reset after decode (success or failure)
            self.reset()
    
    def reset(self):
        """Reset decoder state"""
        self.timing.reset()
        self.frame_asm.reset()
        self.bit_clock = None
        self.te_stats = None
        self.pulses.clear()
        self.manchester_violations = 0
        self.phase_errors.clear()
