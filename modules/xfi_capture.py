from scapy.all import Dot11, RadioTap
from .xfi_processor import XFiProcessor
from core import DeviceRegistry, Device_Object, DeviceType

class XFiCapture:
    """
    Hooks into Wi‑Fi monitor to analyze corrupted frames for IoT signatures.
    """
    
    def __init__(self, registry: DeviceRegistry):
        self.registry = registry
        self.processor = XFiProcessor()
        
    def process_packet(self, packet):
        """
        Analyze a raw 802.11 packet for narrow-band interference signatures.
        """
        # We look for packets that are either marked as having a bad FCS
        # or are significantly malformed but contain data.
        
        fcs_valid = True
        if packet.haslayer(RadioTap):
            # Check for FCS error flag in RadioTap header
            # Bits in RadioTap flags vary by driver, but we look for common indicators
            flags = getattr(packet[RadioTap], 'notfcs', 0)
            if flags:
                fcs_valid = False
        
        # Or if Scapy fails to find a higher level layer in a Data packet
        if packet.haslayer(Dot11) and packet[Dot11].type == 2: # Data frame
            if not fcs_valid or len(packet.payload) > 50:
                # Potential Hitchhiking candidate
                result = self.processor.analyze_frame(bytes(packet), fcs_valid)
                if result:
                    self._handle_detection(result)
                    
    def _handle_detection(self, result):
        """Register the detected cross-tech device"""
        device = Device_Object(
            device_id=result.dev_id,
            name=f"XFi {result.protocol.value} Device",
            protocol=result.protocol,
            frequency=2400.0, # Approximate for 2.4GHz Wi-Fi overlap
            device_type=DeviceType.UNKNOWN,
            signal_strength=int(result.rssi),
            metadata={
                'source': 'XFi Hitchhiking',
                'payload_rebuilt': result.payload,
                'confidence': 0.85
            }
        )
        self.registry.add_or_update(device)
        print(f"[XFi] Detected {result.protocol.value} device via Wi-Fi hitchhiking!")
