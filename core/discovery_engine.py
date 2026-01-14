"""
Discovery Engine (formerly Risk Engine)
Metadata normalization and asset categorization
"""

from typing import Dict, List, Optional
from .device_model import Device_Object, Protocol, DeviceType


class DiscoveryEngine:
    """
    Metadata normalization and level assessment for discovered devices.
    (Legacy RiskEngine)
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
    
    def calculate_discovery_level(self, device: Device_Object) -> tuple[int, List[str]]:
        """
        Categorize devices and assign discovery confidence levels.
        """
        factors = []
        level = 30  # Default to INFRA/LOW
        
        # 1. Verification Depth (Cross-Protocol Correlation)
        entity_id = device.metadata.get('physical_entity_id')
        if entity_id:
            level = max(level, 80)
            factors.append("Multi-Interface Correlated Asset")
        
        # 2. Protocol Depth 
        if device.protocol in [Protocol.WIFI_24, Protocol.WIFI_5]:
            if device.metadata.get('encryption') and device.metadata.get('encryption') != 'OPEN':
                level = max(level, 50)
                factors.append("Encrypted Wireless Infrastructure")
            else:
                factors.append("Public Wireless Infrastructure")
        
        # 3. Functional Identification (Inferred by behavior/OUI)
        if device.device_type != DeviceType.UNKNOWN:
            level = max(level, 90)
            factors.append(f"Functionally Identified: {device.device_type.value}")
        
        # IoTScent Specific (Behavioral DNA)
        if device.metadata.get('iotscent_match'):
            level = max(level, 95)
            factors.append("Behavioral Fingerprint Match (IoTScent)")

        # 4. Metadata check
        if device.vendor and device.vendor != "Unknown":
            level += 20 # Changed from 'score' to 'level' to maintain syntactic correctness with existing variable
            factors.append(f"Known Manufacturer: {device.vendor}")
            
        return (min(level, 100), factors)
    
    def normalize_metadata(self, device: Device_Object) -> Dict:
        """Normalize device metadata for asset inventory"""
        return {}
