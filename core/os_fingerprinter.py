"""
Passive OS Fingerprinting - p0f-style TCP/IP stack analysis
Identifies operating systems via passive traffic analysis.
Fixed & Improved for accuracy and robustness.
"""

import logging
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, field
from scapy.all import IP, TCP

@dataclass
class OSSignature:
    """OS fingerprint signature result"""
    os_name: str
    version: str
    confidence: float
    details: Dict[str, Any]
    
    def __repr__(self) -> str:
        return f"<OS: {self.os_name} {self.version} ({self.confidence:.1%})>"

class PassiveOSFingerprinter:
    """
    Passive OS Detection via TCP/IP Stack Analysis.
    
    Based on p0f methodology (SYN packet analysis):
    - TCP Window Size & Scale
    - IP TTL (Time To Live)
    - IP DF (Don't Fragment) bit
    - TCP Options ordering and values
    - MSS (Maximum Segment Size)
    
    Improvements:
    - ✅ Strict TCP option ordering check (critical for p0f)
    - ✅ Robust Scapy flag handling
    - ✅ Weighted scoring system
    - ✅ Proper logging
    """
    
    # Scoring Weights
    WEIGHT_TTL = 30.0
    WEIGHT_WINDOW = 25.0
    WEIGHT_OPTIONS = 25.0
    WEIGHT_DF = 10.0
    WEIGHT_MSS = 10.0
    
    # OS Signature Database
    # Format: window, ttl, df, options_list, mss_list
    SIGNATURES = {
        'windows_10_11': {
            'window_sizes': [8192, 65535, 64240],
            'ttl': 128,
            'df_bit': True,
            'tcp_options': ['mss', 'nop', 'ws', 'nop', 'nop', 'sackok'],
            'mss_values': [1460, 1452, 1440]
        },
        'windows_7_8': {
            'window_sizes': [8192, 65535],
            'ttl': 128,
            'df_bit': True,
            'tcp_options': ['mss', 'nop', 'nop', 'sackok'],
            'mss_values': [1460]
        },
        'linux_kernel_5+': {
            'window_sizes': [64240, 29200, 5792, 28960],
            'ttl': 64,
            'df_bit': True,
            'tcp_options': ['mss', 'sackok', 'ts', 'nop', 'ws'],
            'mss_values': [1460]
        },
        'linux_generic': {
            'window_sizes': [5840, 14600, 29200],
            'ttl': 64,
            'df_bit': True,
            'tcp_options': ['mss', 'sackok', 'ts', 'nop', 'ws'],
            'mss_values': [1460]
        },
        'macos': {
            'window_sizes': [65535],
            'ttl': 64,
            'df_bit': True,
            'tcp_options': ['mss', 'nop', 'ws', 'nop', 'nop', 'ts', 'sackok', 'eol'],
            'mss_values': [1460]
        },
        'ios_mobile': {
            'window_sizes': [65535],
            'ttl': 64,
            'df_bit': True,
            'tcp_options': ['mss', 'nop', 'ws', 'nop', 'nop', 'ts', 'sackok', 'eol'],
            'mss_values': [1460, 1440]
        },
        'android': {
            'window_sizes': [65535, 14600],
            'ttl': 64,
            'df_bit': True,
            'tcp_options': ['mss', 'sackok', 'ts', 'nop', 'ws'],
            'mss_values': [1460, 1440]
        },
    }
    
    def __init__(self):
        self.fingerprints: Dict[str, OSSignature] = {}
        self.logger = logging.getLogger("OSFingerprinter")
    
    def analyze_packet(self, packet) -> Optional[OSSignature]:
        """
        Analyze TCP/IP packet for OS fingerprinting.
        Best results on TCP SYN packets (initial handshake).
        """
        if not packet.haslayer(IP) or not packet.haslayer(TCP):
            return None
        
        try:
            ip = packet[IP]
            tcp = packet[TCP]
            
            # Simple optimization: only allow SYN packets (flags=0x02 or 'S')
            # But allow SYN-ACK (0x12) for passive client fingerprinting too if desired
            # For now, we process all, but features are most distinct in SYN.
            
            features = self._extract_features(ip, tcp)
            match = self._match_signature(features)
            
            return match
            
        except Exception as e:
            self.logger.error(f"Analysis failed: {e}")
            return None
    
    def _extract_features(self, ip, tcp) -> Dict[str, Any]:
        """Extract fingerprinting features"""
        
        # Scapy flags can be a FlagValue object or int
        flags_int = int(ip.flags) if hasattr(ip.flags, '__int__') else 0
        df_bit = bool(flags_int & 0x02) or (str(ip.flags).find('DF') >= 0)
        
        features = {
            'ttl': ip.ttl,
            'df_bit': df_bit,
            'window_size': tcp.window,
            'tcp_options': self._parse_tcp_options(tcp),
            'mss': None,
            'window_scale': None
        }
        
        # Extract MSS and WScale
        # Scapy options: [('MSS', 1460), ('NOP', None), ...]
        for opt in tcp.options:
            name = opt[0]
            value = opt[1]
            
            if name == 'MSS':
                features['mss'] = value
            elif name == 'WScale':
                features['window_scale'] = value
                
        return features
    
    def _parse_tcp_options(self, tcp) -> List[str]:
        """Parse TCP option names in order"""
        options = []
        for opt in tcp.options:
            name = opt[0]
            # Normalize names
            if isinstance(name, str):
                options.append(name.lower())
            else:
                options.append(str(name).lower())
        return options
    
    def _match_signature(self, features: Dict) -> Optional[OSSignature]:
        """Match features against DB with weighted scoring"""
        best_match = None
        best_score = 0.0
        
        max_possible_score = (self.WEIGHT_TTL + self.WEIGHT_WINDOW + 
                              self.WEIGHT_OPTIONS + self.WEIGHT_DF + self.WEIGHT_MSS)
        
        for os_key, sig in self.SIGNATURES.items():
            score = 0.0
            
            # 1. TTL Check (allow small hops for routers)
            # Exact match is best, but usually it's decremented by hops
            # We assume initial TTL is power of 2 (32, 64, 128, 255)
            # If features['ttl'] is close to sig['ttl'] (e.g. 64 vs 61)
            dist = sig['ttl'] - features['ttl']
            if 0 <= dist <= 30: 
                # Closer is better
                score += self.WEIGHT_TTL * (1.0 - (dist / 40.0))
            
            # 2. Window Size Check
            if features['window_size'] in sig['window_sizes']:
                score += self.WEIGHT_WINDOW
            
            # 3. DF Bit Check
            if features['df_bit'] == sig['df_bit']:
                score += self.WEIGHT_DF
                
            # 4. TCP Options (Order Critical)
            sim = self._compare_option_order(features['tcp_options'], sig['tcp_options'])
            score += sim * self.WEIGHT_OPTIONS
            
            # 5. MSS Check (Relaxed)
            # Only check if MSS was present in packet
            if features.get('mss'):
                if features['mss'] in sig.get('mss_values', []):
                    score += self.WEIGHT_MSS
                else:
                    # Partial credit if MSS is standard
                    score += self.WEIGHT_MSS * 0.5
            else:
                # If no MSS in packet but expected, small penalty? 
                # Just ignore for now (neutral)
                score += self.WEIGHT_MSS * 0.5
                
            confidence = score / max_possible_score
            
            if confidence > best_score:
                best_score = confidence
                best_match = os_key
        
        if best_match and best_score >= 0.6:
            parts = best_match.split('_')
            os_name = parts[0].capitalize()
            version = parts[1] if len(parts) > 1 else "Generic"
            
            return OSSignature(
                os_name=os_name,
                version=version,
                confidence=best_score,
                details=features
            )
            
        return None
    
    def _compare_option_order(self, observed: List[str], expected: List[str]) -> float:
        """
        Compare TCP options sequence similarity.
        Strict ordering check.
        """
        if not observed or not expected:
            return 0.0
            
        if observed == expected:
            return 1.0
            
        # Longest Common Subsequence (LCS) approach for similarity
        # or simple position matching. Let's use position matching for speed.
        matches = 0
        min_len = min(len(observed), len(expected))
        for i in range(min_len):
            if observed[i] == expected[i]:
                matches += 1
                
        # Length penalty
        len_diff = abs(len(observed) - len(expected))
        penalty = len_diff * 0.1
        
        score = (matches / max(len(expected), 1)) - penalty
        return max(0.0, min(1.0, score))

    def store_fingerprint(self, device_id: str, signature: OSSignature):
        """Cache fingerprint for device"""
        if not signature:
            return
        
        existing = self.fingerprints.get(device_id)
        # Update if confidence is higher or new
        if not existing or signature.confidence > existing.confidence:
            self.fingerprints[device_id] = signature
            self.logger.info(f"Fingerprinted {device_id}: {signature.os_name} {signature.version} ({signature.confidence:.0%})")
            
    def get_fingerprint(self, device_id: str) -> Optional[OSSignature]:
        return self.fingerprints.get(device_id)

# Singleton instance
os_fingerprinter = PassiveOSFingerprinter()
