"""
Decoder Arbiter - Confidence Fusion & Protocol Classification

This module arbitrates between competing decoder classifications,
fusing evidence and emitting high-confidence protocol observations.

Design Principles:
- Decoders do not see each other
- Arbiter has no SDR access
- Emits facts only, never commands
- Deterministic, testable, safe
"""

import time
import logging
from typing import Dict, List, Tuple, Optional, Callable
from dataclasses import dataclass, field
from collections import defaultdict
from enum import Enum

logger = logging.getLogger("DecoderArbiter")

# ============================================================================
# CONFIGURATION
# ============================================================================

# Decoder trust weights (empirically tuned)
DECODER_WEIGHT = {
    "keeloq": 1.0,
    "hcs301": 1.0,
    "hcs200": 0.95,
    "nice_flor": 0.9,
    "nice_flo": 0.9,
    "ev1527": 0.85,
    "princeton": 0.7,
    "came": 0.75,
    "chamberlain": 0.85,
}

# Mutually exclusive protocol groups
MUTEX_GROUPS = [
    {"KeeLoq", "HCS301", "HCS200"},  # All KeeLoq variants
    {"EV1527", "Princeton"},          # Similar OOK protocols
    {"NICE_FLO", "NICE_FLOR"},       # NICE variants
]

# Emission threshold
EMIT_THRESHOLD = 0.75

# Frame collection window (ms)
COLLECTION_WINDOW_MS = 15

# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class DecoderCandidate:
    """Single decoder's classification of a frame"""
    decoder: str
    protocol: str
    confidence: float
    features: Dict
    timestamp: float
    frame_id: str
    
    def adjusted_confidence(self) -> float:
        """Apply decoder trust weight"""
        weight = DECODER_WEIGHT.get(self.decoder, 0.5)
        return self.confidence * weight

@dataclass
class FusedClassification:
    """Final arbitrated classification"""
    frame_id: str
    protocol: str
    confidence: float
    contributors: List[str]
    classification: str
    timestamp: float
    features: Dict = field(default_factory=dict)

class ArbitrationState(Enum):
    """Arbiter state machine"""
    IDLE = "idle"
    COLLECTING = "collecting"
    FUSING = "fusing"

# ============================================================================
# DECODER ARBITER
# ============================================================================

class DecoderArbiter:
    """
    Arbitrates between competing decoder classifications.
    
    Pure function with memory - no SDR control, no state changes.
    """
    
    def __init__(self, emit_callback: Callable):
        """
        Args:
            emit_callback: Function to call with fused classifications
        """
        self.emit = emit_callback
        
        # Frame buffer: frame_id -> [candidates]
        self.buffer: Dict[str, List[DecoderCandidate]] = defaultdict(list)
        
        # Frame timestamps for timeout
        self.frame_timestamps: Dict[str, float] = {}
        
        # State
        self.state = ArbitrationState.IDLE
        
        # Statistics
        self.stats = {
            "frames_processed": 0,
            "candidates_received": 0,
            "emissions": 0,
            "discards": 0,
        }
    
    def submit(self, candidate: Dict):
        """
        Submit a decoder candidate for arbitration.
        
        Args:
            candidate: Decoder output (see contract in docstring)
        """
        # Parse candidate
        try:
            cand = DecoderCandidate(
                decoder=candidate["decoder"],
                protocol=candidate["protocol"],
                confidence=candidate["confidence"],
                features=candidate.get("features", {}),
                timestamp=candidate.get("timestamp", time.time()),
                frame_id=candidate["frame_id"]
            )
        except KeyError as e:
            logger.warning(f"Invalid candidate: missing {e}")
            return
        
        # Validate confidence
        if not (0.0 <= cand.confidence <= 1.0):
            logger.warning(f"Invalid confidence: {cand.confidence}")
            return
        
        # Add to buffer
        frame_id = cand.frame_id
        self.buffer[frame_id].append(cand)
        
        if frame_id not in self.frame_timestamps:
            self.frame_timestamps[frame_id] = time.time()
        
        self.stats["candidates_received"] += 1
        self.state = ArbitrationState.COLLECTING
    
    def finalize(self, frame_id: str):
        """
        Finalize arbitration for a frame.
        
        Performs:
        1. Group candidates
        2. Apply trust weights
        3. Mutex filtering
        4. Evidence fusion
        5. Threshold decision
        
        Args:
            frame_id: Frame to finalize
        """
        self.state = ArbitrationState.FUSING
        
        # Get candidates
        candidates = self.buffer.pop(frame_id, [])
        self.frame_timestamps.pop(frame_id, None)
        
        if not candidates:
            self.state = ArbitrationState.IDLE
            return
        
        self.stats["frames_processed"] += 1
        
        # Step 1: Apply trust weights
        scored = []
        for cand in candidates:
            adj_conf = cand.adjusted_confidence()
            scored.append((cand.protocol, cand.decoder, adj_conf, cand))
        
        # Step 2: Mutex filtering
        scored = self._resolve_mutex(scored)
        
        # Step 3: Fuse by protocol
        fused = self._fuse_by_protocol(scored)
        
        # Step 4: Select best
        if not fused:
            self.stats["discards"] += 1
            self.state = ArbitrationState.IDLE
            return
        
        best_protocol, best_conf, contributors, first_cand = max(
            fused, key=lambda x: x[1]
        )
        
        # Step 5: Threshold decision
        if best_conf >= EMIT_THRESHOLD:
            classification = FusedClassification(
                frame_id=frame_id,
                protocol=best_protocol,
                confidence=best_conf,
                contributors=contributors,
                classification=self._classify_type(best_protocol),
                timestamp=first_cand.timestamp,
                features=first_cand.features
            )
            
            self._emit_classification(classification)
            self.stats["emissions"] += 1
        else:
            logger.debug(f"Frame {frame_id}: confidence {best_conf:.2f} below threshold")
            self.stats["discards"] += 1
        
        self.state = ArbitrationState.IDLE
    
    def _resolve_mutex(self, scored: List[Tuple]) -> List[Tuple]:
        """
        Filter mutually exclusive protocols.
        
        NOTE: This only filters DIFFERENT protocols in the same mutex group.
        Multiple decoders agreeing on the SAME protocol are NOT filtered.
        
        Args:
            scored: [(protocol, decoder, confidence, candidate), ...]
            
        Returns:
            Filtered list with only highest-scoring protocol from each mutex group
        """
        # Group by protocol first (same protocol = consensus, not mutex)
        by_protocol = defaultdict(list)
        for proto, decoder, conf, cand in scored:
            by_protocol[proto].append((proto, decoder, conf, cand))
        
        # Now apply mutex filtering to PROTOCOLS (not decoders)
        mutex_map = {}
        for group_idx, group in enumerate(MUTEX_GROUPS):
            for proto in group:
                mutex_map[proto] = group_idx
        
        # Find best protocol in each mutex group
        group_best = {}
        non_mutex = []
        
        for proto, entries in by_protocol.items():
            # Get highest confidence for this protocol
            best_entry = max(entries, key=lambda x: x[2])
            
            if proto in mutex_map:
                group_idx = mutex_map[proto]
                if group_idx not in group_best or best_entry[2] > group_best[group_idx][2]:
                    # Keep all entries for this protocol (for fusion)
                    group_best[group_idx] = entries
            else:
                non_mutex.extend(entries)
        
        # Combine all entries (flattened)
        result = []
        for entries in group_best.values():
            result.extend(entries)
        result.extend(non_mutex)
        
        return result
    
    def _fuse_by_protocol(self, scored: List[Tuple]) -> List[Tuple]:
        """
        Fuse evidence for same protocol from multiple decoders.
        
        Uses: fused_confidence = 1 - ∏(1 - confidence_i)
        
        Args:
            scored: [(protocol, decoder, confidence, candidate), ...]
            
        Returns:
            [(protocol, fused_confidence, contributors, first_candidate), ...]
        """
        # Group by protocol
        by_protocol = defaultdict(list)
        for proto, decoder, conf, cand in scored:
            by_protocol[proto].append((decoder, conf, cand))
        
        # Fuse each protocol
        fused = []
        for proto, entries in by_protocol.items():
            # Calculate fused confidence
            product = 1.0
            for decoder, conf, cand in entries:
                product *= (1.0 - conf)
            
            fused_conf = 1.0 - product
            contributors = [decoder for decoder, _, _ in entries]
            first_cand = entries[0][2]  # Use first candidate for metadata
            
            fused.append((proto, fused_conf, contributors, first_cand))
        
        return fused
    
    def _classify_type(self, protocol: str) -> str:
        """
        Classify protocol type for higher-level logic.
        
        Args:
            protocol: Protocol name
            
        Returns:
            Classification string
        """
        rolling_codes = {"KeeLoq", "HCS301", "HCS200", "Chamberlain"}
        fixed_codes = {"EV1527", "Princeton", "PT2262"}
        
        if protocol in rolling_codes:
            return "rolling_code"
        elif protocol in fixed_codes:
            return "fixed_code"
        else:
            return "unknown"
    
    def _emit_classification(self, classification: FusedClassification):
        """
        Emit fused classification to event bus.
        
        Args:
            classification: Fused classification result
        """
        event_payload = {
            "event": "protocol_observed",
            "frame_id": classification.frame_id,
            "protocol": classification.protocol,
            "confidence": classification.confidence,
            "contributors": classification.contributors,
            "classification": classification.classification,
            "timestamp": classification.timestamp,
            # Pull bitstream/raw_code to top level if available (SCPE expectation)
            "raw_code": classification.features.get("raw_code", ""),
            "bitstream": classification.features.get("raw_code", ""),
            "frequency": classification.features.get("frequency", 0),
            "features": classification.features
        }
        
        logger.info(
            f"Protocol observed: {classification.protocol} "
            f"(confidence={classification.confidence:.2f}, "
            f"contributors={classification.contributors})"
        )
        
        self.emit(event_payload)
    
    def check_timeouts(self):
        """
        Check for frames that have exceeded collection window.
        Should be called periodically.
        """
        now = time.time()
        timeout_threshold = COLLECTION_WINDOW_MS / 1000.0
        
        timed_out = []
        for frame_id, timestamp in list(self.frame_timestamps.items()):
            if now - timestamp > timeout_threshold:
                timed_out.append(frame_id)
        
        # Finalize timed-out frames
        for frame_id in timed_out:
            logger.debug(f"Frame {frame_id} timed out, finalizing")
            self.finalize(frame_id)
    
    def get_stats(self) -> Dict:
        """Get arbiter statistics"""
        return {
            **self.stats,
            "pending_frames": len(self.buffer),
            "state": self.state.value
        }

# ============================================================================
# TESTING UTILITIES
# ============================================================================

def create_test_candidate(decoder: str, protocol: str, confidence: float, frame_id: str = "test_frame") -> Dict:
    """Create a test candidate for unit testing"""
    return {
        "decoder": decoder,
        "protocol": protocol,
        "confidence": confidence,
        "features": {},
        "timestamp": time.time(),
        "frame_id": frame_id
    }
