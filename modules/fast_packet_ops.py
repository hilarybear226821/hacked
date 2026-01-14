"""
Python interface to C packet processing library
Provides high-performance operations via ctypes
"""

import ctypes
import os
from typing import Optional, Tuple

# Load C library
_lib_path = os.path.join(os.path.dirname(__file__), '../c_extensions/libmitm_packet.so')
try:
    _libmitm = ctypes.CDLL(_lib_path)
except OSError:
    print(f"[Warning] Could not load {_lib_path} - using Python fallback")
    _libmitm = None

# Function signatures
if _libmitm:
    # void recalc_all_checksums(uint8_t *packet, size_t packet_len)
    _libmitm.recalc_all_checksums.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
    _libmitm.recalc_all_checksums.restype = None
    
    # int classify_protocol(const uint8_t *packet, size_t len)
    _libmitm.classify_protocol.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
    _libmitm.classify_protocol.restype = ctypes.c_int
    
    # int inject_payload(...)
    _libmitm.inject_payload.argtypes = [
        ctypes.c_char_p,  # packet
        ctypes.c_size_t,  # packet_len
        ctypes.c_char_p,  # payload
        ctypes.c_size_t,  # payload_len
        ctypes.c_char_p,  # out_packet
        ctypes.c_size_t   # out_max_len
    ]
    _libmitm.inject_payload.restype = ctypes.c_int
    
    # int extract_http_credentials(...)
    _libmitm.extract_http_credentials.argtypes = [
        ctypes.c_char_p,  # packet
        ctypes.c_size_t,  # len
        ctypes.c_char_p,  # username
        ctypes.c_size_t,  # username_len
        ctypes.c_char_p,  # password
        ctypes.c_size_t   # password_len
    ]
    _libmitm.extract_http_credentials.restype = ctypes.c_int


class FastPacketOps:
    """High-performance packet operations using C extension"""
    
    PROTO_HTTP = 1
    PROTO_HTTPS = 2
    PROTO_FTP = 3
    PROTO_SMTP = 4
    PROTO_SSH = 5
    PROTO_RDP = 6
    PROTO_UNKNOWN = 0
    
    PROTO_NAMES = {
        1: 'HTTP',
        2: 'HTTPS',
        3: 'FTP',
        4: 'SMTP',
        5: 'SSH',
        6: 'RDP',
        0: 'Unknown'
    }
    
    @staticmethod
    def recalc_checksums(packet: bytes) -> bytes:
        """
        Recalculate IP and TCP checksums after modification.
        
        Args:
            packet: Raw packet bytes
            
        Returns:
            Packet with updated checksums (in-place modification)
        """
        if not _libmitm:
            return packet  # Fallback: return unchanged
            
        # Create mutable buffer
        buf = ctypes.create_string_buffer(packet)
        
        _libmitm.recalc_all_checksums(buf, len(packet))
        
        return buf.raw
    
    @staticmethod
    def classify_protocol(packet: bytes) -> int:
        """
        Fast protocol classification.
        
        Returns:
            Protocol constant (PROTO_HTTP, PROTO_HTTPS, etc.)
        """
        if not _libmitm:
            return FastPacketOps.PROTO_UNKNOWN
            
        return _libmitm.classify_protocol(packet, len(packet))
    
    @staticmethod
    def get_protocol_name(packet: bytes) -> str:
        """Get human-readable protocol name"""
        proto_id = FastPacketOps.classify_protocol(packet)
        return FastPacketOps.PROTO_NAMES.get(proto_id, 'Unknown')
    
    @staticmethod
    def inject_payload(packet: bytes, payload: bytes, max_size: int = 65535) -> Optional[bytes]:
        """
        Inject payload into TCP packet.
        
        Args:
            packet: Original packet
            payload: Data to inject
            max_size: Maximum output packet size
            
        Returns:
            Modified packet with injected payload, or None on error
        """
        if not _libmitm:
            return None
            
        out_buf = ctypes.create_string_buffer(max_size)
        
        new_len = _libmitm.inject_payload(
            packet, len(packet),
            payload, len(payload),
            out_buf, max_size
        )
        
        if new_len < 0:
            return None
            
        return out_buf.raw[:new_len]
    
    @staticmethod
    def extract_http_credentials(packet: bytes) -> Optional[Tuple[str, str]]:
        """
        Extract HTTP Basic Auth credentials from packet.
        
        Returns:
            (username, password) tuple, or None if not found
        """
        if not _libmitm:
            return None
            
        username_buf = ctypes.create_string_buffer(256)
        password_buf = ctypes.create_string_buffer(256)
        
        result = _libmitm.extract_http_credentials(
            packet, len(packet),
            username_buf, 256,
            password_buf, 256
        )
        
        if result == 1:
            # Note: C function currently returns base64-encoded string in username
            # Would need to decode in Python
            import base64
            try:
                decoded = base64.b64decode(username_buf.value).decode('utf-8')
                if ':' in decoded:
                    user, passwd = decoded.split(':', 1)
                    return (user, passwd)
            except:
                pass
                
        return None


# Convenience functions
def recalc_checksums(packet: bytes) -> bytes:
    """Recalculate TCP/IP checksums"""
    return FastPacketOps.recalc_checksums(packet)

def classify_protocol(packet: bytes) -> str:
    """Get protocol name"""
    return FastPacketOps.get_protocol_name(packet)

def inject_payload(packet: bytes, payload: bytes) -> Optional[bytes]:
    """Inject payload into packet"""
    return FastPacketOps.inject_payload(packet, payload)
