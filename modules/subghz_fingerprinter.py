
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from core import DeviceType

@dataclass
class RFSignature:
    name: str
    device_type: DeviceType
    vendor: str
    pattern: str # Hex regex or bit pattern
    confidence: float

class SubGhzFingerprinter:
    """
    Identifies device manufacturers and types from raw Sub-GHz payloads.
    Equivalent to 'OS Fingerprinting' but for RF IoT.
    """
    
    def __init__(self):
        # Knowledge Base of RF Signatures
        # Patterns match decoded hex payloads
        self.signatures = [
            # Security Systems
            RFSignature("DSC Security Sensor", DeviceType.SENSOR, "DSC", r"^3[a-f0-9]{5}$", 0.9),
            RFSignature("Honeywell 5800", DeviceType.SENSOR, "Honeywell", r"^a[0-9]{6}$", 0.9),
            RFSignature("Interlogix / GE", DeviceType.SENSOR, "Interlogix", r"^[0-9a-f]{6}0[0-9a-f]$", 0.8),
            
            # Vehicles (TPMS / Fobs)
            RFSignature("Schrader TPMS", DeviceType.SENSOR, "Schrader", r"^0[0-9a-f]{7}$", 0.85),
            RFSignature("Honda Key Fob", DeviceType.REMOTE, "Honda", r"^e[0-9a-f]{7}$", 0.7),
            RFSignature("Ford Key Fob", DeviceType.REMOTE, "Ford", r"^3[0-9a-f]{16}$", 0.7),
            
            # Weather Stations
            RFSignature("Acurite Weather", DeviceType.SENSOR, "Acurite", r"^c[0-9a-f]{10,}$", 0.8),
            RFSignature("Ambient Weather", DeviceType.SENSOR, "Ambient", r"^f[0-9a-f]{10,}$", 0.8),
            
            # Generic Chipsets
            RFSignature("Generic EV1527", DeviceType.REMOTE, "Generic", r"^[0-9a-f]{6}$", 0.6),
            RFSignature("Generic PT2262", DeviceType.REMOTE, "Generic", r"^[0-9a-f]{3,}$", 0.5),
        ]

    def fingerprint(self, payload_hex: str, protocol_name: str) -> Optional[RFSignature]:
        """
        Match payload against known signatures.
        """
        import re
        
        best_match = None
        highest_conf = 0.0
        
        # 1. Protocol-specific checks
        if "Honda" in protocol_name: 
            return RFSignature("Honda Remote", DeviceType.REMOTE, "Honda", "protocol", 0.9)
            
        # 2. Payload Regex Matching
        for sig in self.signatures:
            try:
                if re.match(sig.pattern, payload_hex, re.IGNORECASE):
                    if sig.confidence > highest_conf:
                        best_match = sig
                        highest_conf = sig.confidence
            except: continue
            
        return best_match
