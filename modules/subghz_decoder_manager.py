import time
import hashlib
from typing import List, Dict, Optional, Type
from collections import deque
from .subghz_decoder import SubGhzProtocolDecoder
from .decoders.came_decoder import CameDecoder
from .decoders.nice_decoder import NiceDecoder
from .decoders.nice_flor_decoder import NiceFlorSubGhzDecoder
from .decoders.princeton_decoder import PrincetonSubGhzDecoder
from .decoders.ev1527_decoder import EV1527Decoder

class DecodedResult:
    def __init__(self, protocol: str, data: str, raw_sig: str, timestamp: float, rssi: float):
        self.protocol = protocol
        self.data = data
        self.raw_sig = raw_sig
        self.timestamp = timestamp
        self.rssi = rssi

class SubGhzDecoderManager:
    """
    Manages multiple protocol decoders for RF asset monitoring.
    Implements Replay Protection by buffering unique signal hashes.
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.decoders: List[SubGhzProtocolDecoder] = [
            CameDecoder(),
            NiceDecoder(),
            NiceFlorSubGhzDecoder(),
            PrincetonSubGhzDecoder(),
            EV1527Decoder(),
        ]
        # Replay protection buffer: (hash, timestamp)
        self.recent_hashes: deque = deque(maxlen=10)
        
    def feed_pulse(self, level: int, duration_us: int):
        for decoder in self.decoders:
            decoder.feed(level, duration_us)
            
    def reset_decoders(self):
        for decoder in self.decoders:
            decoder.alloc()
            
    def get_results(self, current_rssi: float) -> List[DecodedResult]:
        results = []
        timestamp = time.time()
        
        for decoder in self.decoders:
            try:
                hex_data = decoder.deserialize()
                protocol_name = decoder.get_string()
                
                # Use data hash for replay tracking
                sig_hash = hashlib.md5(hex_data.encode()).hexdigest()
                
                result = DecodedResult(
                    protocol=protocol_name,
                    data=hex_data,
                    raw_sig=hex_data,
                    timestamp=timestamp,
                    rssi=current_rssi
                )
                
                # Check for replay attack
                if self._is_replay(sig_hash, current_rssi, timestamp):
                    logger.warning(f"[SubGHz] !!! REPLAY ATTACK DETECTED: {protocol_name} ({hex_data})")
                    result.is_replay = True # Added attribute
                else:
                    self.recent_hashes.append((sig_hash, timestamp))
                    result.is_replay = False
                
                results.append(result)
            except (ValueError, Exception):
                continue
                
        return results

    def _is_replay(self, sig_hash: str, rssi: float, timestamp: float) -> bool:
        """
        Flipper-style Replay Detection:
        If hash seen < 5s ago and RSSI is significantly high, flag it.
        """
        for h, t in self.recent_hashes:
            if h == sig_hash:
                if (timestamp - t) < 5.0:
                    # Optional: High RSSI threshold for replay sanity check
                    if rssi > 0.05: # Arbitrary threshold for "loud" replay
                        return True
        return False

