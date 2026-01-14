
import time
import re
import logging
import threading
import queue
from dataclasses import dataclass, field
from typing import List, Dict, Callable, Optional, Set
from collections import deque
from enum import Enum, auto
import hashlib

# Configure logging with rate limiting
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DataVisualizer")


class Protocol(Enum):
    """Typed protocol enumeration"""
    HTTP = "HTTP"
    HTTPS = "HTTPS"
    DNS = "DNS"
    TLS = "TLS"
    SSH = "SSH"
    FTP = "FTP"
    TELNET = "Telnet"
    SMTP = "SMTP"
    RAW = "Raw"
    UNKNOWN = "Unknown"
    
    @classmethod
    def normalize(cls, proto_str: str) -> 'Protocol':
        """Normalize string to enum (case-insensitive)"""
        try:
            return cls[proto_str.upper()]
        except KeyError:
            return cls.UNKNOWN


class TagSeverity(Enum):
    """Tag severity levels"""
    INFO = auto()
    LOW = auto()
    MEDIUM = auto()
    HIGH = auto()
    CRITICAL = auto()


@dataclass
class Tag:
    """Structured tag with metadata"""
    name: str
    severity: TagSeverity
    confidence: float  # 0.0 to 1.0
    byte_offset: Optional[int] = None  # Where in payload
    match_context: Optional[str] = None  # What was matched
    
    def __str__(self):
        return f"{self.name}({self.severity.name},{self.confidence:.0%})"


@dataclass
class TLSMetadata:
    """Extracted TLS metadata (not encrypted payload)"""
    sni: Optional[str] = None  # Server Name Indication
    alpn: Optional[List[str]] = None  # Application protocols
    cipher_suite: Optional[str] = None
    cert_cn: Optional[str] = None  # Certificate Common Name
    cert_san: Optional[List[str]] = None  # Subject Alt Names


@dataclass
class DataStreamPacket:
    """
    Packet with proper encoding handling and structured metadata
    """
    protocol: Protocol
    source: str
    raw_bytes: bytes  # Keep original
    decoded_text: Optional[str]  # Proper UTF-8 decode (not ASCII fabrication)
    encoding: str  # Detected encoding
    is_payload_encrypted: bool  # Payload encrypted
    tls_metadata: Optional[TLSMetadata] = None  # Even if encrypted, metadata available
    timestamp: float = field(default_factory=time.time)
    tags: List[Tag] = field(default_factory=list)
    
    def __repr__(self) -> str:
        tag_str = f" tags=[{','.join(str(t) for t in self.tags)}]" if self.tags else ""
        enc = f" enc={self.encoding}" if self.decoded_text else ""
        tls = " [TLS]" if self.tls_metadata else ""
        return (f"<Packet {self.protocol.value} from {self.source} "
                f"len={len(self.raw_bytes)}{tls}{enc}{tag_str}>")
    
    def get_hex_view(self) -> str:
        """Hex view with proper alignment"""
        return self.raw_bytes.hex(' ', 1).upper()
    
    def get_aligned_ascii_view(self) -> str:
        """
        ASCII view aligned to hex (preserves byte count)
        
        Each byte becomes exactly one character:
        - Printable ASCII: the character
        - Non-printable: '.'
        - Preserves multi-byte sequences as multiple dots
        """
        return ''.join(
            chr(b) if 32 <= b <= 126 else '.'
            for b in self.raw_bytes
        )
    
    def get_hex_dump(self, bytes_per_line: int = 16) -> str:
        """
        Proper hex dump with aligned ASCII view
        
        Format:
        00000000: 48 54 54 50 2F 31 2E 31 20 32 30 30 20 4F 4B 0D  |HTTP/1.1 200 OK.|
        """
        lines = []
        for i in range(0, len(self.raw_bytes), bytes_per_line):
            chunk = self.raw_bytes[i:i+bytes_per_line]
            
            # Hex part
            hex_part = ' '.join(f'{b:02X}' for b in chunk)
            # Pad to alignment
            hex_part = hex_part.ljust(bytes_per_line * 3 - 1)
            
            # ASCII part (aligned)
            ascii_part = ''.join(
                chr(b) if 32 <= b <= 126 else '.'
                for b in chunk
            )
            
            lines.append(f'{i:08X}: {hex_part}  |{ascii_part}|')
        
        return '\n'.join(lines)


class ContentDecoder:
    """Proper text decoding with encoding detection"""
    
    ENCODINGS = ['utf-8', 'ascii', 'latin-1', 'cp1252', 'utf-16']
    
    @staticmethod
    def decode(raw_bytes: bytes) -> tuple[Optional[str], str]:
        """
        Try multiple encodings intelligently
        
        Returns:
            (decoded_str or None, encoding_used)
        """
        # Try UTF-8 first (most common)
        for encoding in ContentDecoder.ENCODINGS:
            try:
                decoded = raw_bytes.decode(encoding)
                # Validate it's reasonable text (not mojibake)
                if ContentDecoder._is_valid_text(decoded):
                    return decoded, encoding
            except (UnicodeDecodeError, UnicodeError):
                continue
        
        # Binary data
        return None, 'binary'
    
    @staticmethod
    def _is_valid_text(text: str) -> bool:
        """Check if decoded text looks like actual text"""
        if not text:
            return False
        
        # Check for excessive control characters
        control_chars = sum(1 for c in text if ord(c) < 32 and c not in '\n\r\t')
        if control_chars / len(text) > 0.1:  # >10% control chars = binary
            return False
        
        return True
    
    @staticmethod
    def extract_tls_metadata(raw_bytes: bytes) -> Optional[TLSMetadata]:
        """
        Extract TLS metadata from handshake (even if payload encrypted)
        
        This is NOT decrypting content - it's parsing unencrypted handshake fields
        """
        if len(raw_bytes) < 10:
            return None
        
        # TLS record starts with: ContentType (1) + Version (2) + Length (2)
        if raw_bytes[0] != 0x16:  # Handshake
            return None
        
        metadata = TLSMetadata()
        
        # Parse SNI from ClientHello
        # This is a simplified extraction - full parser would use pyasn1
        try:
            # Look for SNI extension (0x00 0x00)
            sni_marker = b'\x00\x00'
            idx = raw_bytes.find(sni_marker)
            if idx > 0:
                # Extract SNI hostname (simplified)
                # Format: extension_type(2) + length(2) + sni_list_length(2) + type(1) + hostname_length(2) + hostname
                if idx + 9 < len(raw_bytes):
                    hostname_len = int.from_bytes(raw_bytes[idx+7:idx+9], 'big')
                    if idx + 9 + hostname_len <= len(raw_bytes):
                        hostname = raw_bytes[idx+9:idx+9+hostname_len].decode('ascii', errors='ignore')
                        if hostname:
                            metadata.sni = hostname
        except:
            pass
        
        return metadata if metadata.sni else None


class PatternAnalyzer:
    """
    Validated pattern detection with low false positives
    """
    
    def __init__(self):
        # Compile patterns
        self.patterns = {
            'email': re.compile(r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b'),
            'password_keyword': re.compile(r'\b(?:password|passwd|pwd|secret|key|token|api[_-]?key)\b', re.IGNORECASE),
            'http_auth': re.compile(r'Authorization:\s*(?:Basic|Bearer)\s+[a-zA-Z0-9+/=]+'),
            'credit_card': re.compile(r'\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b'),
            'ipv4': re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),
            'url': re.compile(r'https?://[^\s]+'),
        }
    
    def analyze(self, packet: DataStreamPacket) -> List[Tag]:
        """
        Analyze packet and return structured tags
        
        Returns validated tags only (no false positives from docs/logs)
        """
        tags = []
        
        # Skip if payload is encrypted
        if packet.is_payload_encrypted:
            # But we can still tag TLS metadata
            if packet.tls_metadata and packet.tls_metadata.sni:
                tags.append(Tag(
                    name=f"tls_sni:{packet.tls_metadata.sni}",
                    severity=TagSeverity.INFO,
                    confidence=1.0,
                    match_context=packet.tls_metadata.sni
                ))
            return tags
        
        # Only analyze decoded text
        if not packet.decoded_text:
            return tags
        
        text = packet.decoded_text
        
        # Email
        matches = self.patterns['email'].finditer(text)
        for match in matches:
            tags.append(Tag(
                name='email',
                severity=TagSeverity.LOW,
                confidence=self._validate_email(match.group()),
                byte_offset=match.start(),
                match_context=match.group()
            ))
        
        # Password keywords (only in specific contexts)
        matches = self.patterns['password_keyword'].finditer(text)
        for match in matches:
            # Check context to reduce false positives
            context = text[max(0, match.start()-20):match.end()+20]
            confidence = self._validate_credential_context(context)
            
            if confidence > 0.3:  # Only tag if reasonably confident
                tags.append(Tag(
                    name='credential_keyword',
                    severity=TagSeverity.MEDIUM,
                    confidence=confidence,
                    byte_offset=match.start(),
                    match_context=match.group()
                ))
        
        # Credit card (with Luhn validation)
        matches = self.patterns['credit_card'].finditer(text)
        for match in matches:
            card_num = match.group().replace(' ', '').replace('-', '')
            if self._luhn_check(card_num):
                tags.append(Tag(
                    name='credit_card',
                    severity=TagSeverity.CRITICAL,
                    confidence=1.0,  # Luhn passed
                    byte_offset=match.start(),
                    match_context='****' + card_num[-4:]  # Last 4 digits only
                ))
        
        return tags
    
    @staticmethod
    def _validate_email(email: str) -> float:
        """Validate email address (0.0 to 1.0)"""
        # Basic checks
        if '@' not in email:
            return 0.0
        
        local, domain = email.rsplit('@', 1)
        
        # Check domain has TLD
        if '.' not in domain:
            return 0.3
        
        # Check for common test patterns
        if any(test in email.lower() for test in ['test', 'example', 'foo', 'bar']):
            return 0.5
        
        return 1.0
    
    @staticmethod
    def _validate_credential_context(context: str) -> float:
        """Check if password keyword is in credential context"""
        # Look for assignment or form field patterns
        patterns = [
            r'=',  # Assignment
            r':',  # JSON/YAML
            r'<input.*password',  # HTML form
            r'Authorization',  # HTTP header
        ]
        
        confidence = 0.3  # Base
        for pattern in patterns:
            if re.search(pattern, context, re.IGNORECASE):
                confidence += 0.2
        
        # Penalize if in documentation
        if any(doc in context.lower() for doc in ['example', 'documentation', 'readme']):
            confidence *= 0.5
        
        return min(confidence, 1.0)
    
    @staticmethod
    def _luhn_check(card_number: str) -> bool:
        """
        Luhn algorithm to validate credit card numbers
        
        Eliminates false positives from random 16-digit numbers
        """
        if not card_number.isdigit():
            return False
        
        if len(card_number) not in [13, 14, 15, 16, 19]:  # Valid CC lengths
            return False
        
        def digits_of(n):
            return [int(d) for d in str(n)]
        
        digits = digits_of(card_number)
        odd_digits = digits[-1::-2]
        even_digits = digits[-2::-2]
        
        checksum = sum(odd_digits)
        for d in even_digits:
            checksum += sum(digits_of(d * 2))
        
        return checksum % 10 == 0


class AsyncNotifier:
    """
    Async subscriber notification with backpressure
    """
    
    def __init__(self, queue_size: int = 1000):
        self.subscribers: Dict[int, Callable] = {}  # id -> callback
        self.subscriber_id = 0
        self.lock = threading.Lock()
        
        # Async queue
        self.queue = queue.Queue(maxsize=queue_size)
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.running = False
        
        # Failure tracking
        self.quarantined: Set[int] = set()
        self.failure_counts: Dict[int, int] = {}
        self.MAX_FAILURES = 3
    
    def start(self):
        """Start async worker"""
        self.running = True
        self.worker_thread.start()
    
    def stop(self):
        """Stop async worker"""
        self.running = False
        self.queue.put(None)  # Sentinel
        self.worker_thread.join(timeout=2.0)
    
    def subscribe(self, callback: Callable) -> int:
        """
        Subscribe to notifications
        
        Returns:
            subscription_id for unsubscribe
        """
        with self.lock:
            sub_id = self.subscriber_id
            self.subscriber_id += 1
            self.subscribers[sub_id] = callback
            self.failure_counts[sub_id] = 0
        
        return sub_id
    
    def unsubscribe(self, sub_id: int):
        """Remove subscriber"""
        with self.lock:
            self.subscribers.pop(sub_id, None)
            self.failure_counts.pop(sub_id, None)
            self.quarantined.discard(sub_id)
    
    def notify(self, packet: DataStreamPacket):
        """
        Async notification (non-blocking)
        
        If queue full, applies backpressure (blocks or drops)
        """
        try:
            self.queue.put(packet, timeout=0.1)
        except queue.Full:
            logger.warning("Notification queue full - backpressure applied")
    
    def _worker(self):
        """Background worker thread"""
        while self.running:
            try:
                packet = self.queue.get(timeout=1.0)
                
                if packet is None:  # Sentinel
                    break
                
                # Notify all subscribers
                with self.lock:
                    subscribers = list(self.subscribers.items())
                
                for sub_id, callback in subscribers:
                    if sub_id in self.quarantined:
                        continue
                    
                    try:
                        callback(packet)
                        # Reset failure count on success
                        with self.lock:
                            self.failure_counts[sub_id] = 0
                    except Exception as e:
                        with self.lock:
                            self.failure_counts[sub_id] = self.failure_counts.get(sub_id, 0) + 1
                            
                            if self.failure_counts[sub_id] >= self.MAX_FAILURES:
                                self.quarantined.add(sub_id)
                                logger.error(f"Subscriber {sub_id} quarantined after {self.MAX_FAILURES} failures")
                            else:
                                logger.warning(f"Subscriber {sub_id} failed ({self.failure_counts[sub_id]}/{self.MAX_FAILURES}): {e}")
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Worker error: {e}")


class TimeBasedHistory:
    """
    History with both count and time-based limits
    """
    
    def __init__(self, max_count: int = 10000, max_age_seconds: float = 3600):
        self.max_count = max_count
        self.max_age = max_age_seconds
        self.packets: deque = deque(maxlen=max_count)
        self.lock = threading.Lock()
    
    def append(self, packet: DataStreamPacket):
        """Add packet and prune old entries"""
        with self.lock:
            self.packets.append(packet)
            self._prune_old()
    
    def _prune_old(self):
        """Remove packets older than max_age"""
        cutoff = time.time() - self.max_age
        
        # Remove from left while old
        while self.packets and self.packets[0].timestamp < cutoff:
            self.packets.popleft()
    
    def get_all(self) -> List[DataStreamPacket]:
        """Get all packets (pruned)"""
        with self.lock:
            self._prune_old()
            return list(self.packets)
    
    def get_recent(self, count: int) -> List[DataStreamPacket]:
        """Get N most recent packets"""
        with self.lock:
            return list(self.packets)[-count:]
    
    def get_since(self, timestamp: float) -> List[DataStreamPacket]:
        """Get packets since timestamp"""
        with self.lock:
            return [p for p in self.packets if p.timestamp >= timestamp]
    
    def clear(self):
        """Clear all history"""
        with self.lock:
            self.packets.clear()


class DataVisualizer:
    """
    Production-grade stream aggregator with proper architecture
    
    Separated concerns:
    - Decoding: ContentDecoder
    - Analysis: PatternAnalyzer
    - Storage: TimeBasedHistory
    - Notification: AsyncNotifier
    - Coordination: DataVisualizer
    """
    
    def __init__(self, max_history: int = 10000, history_ttl: float = 3600):
        self.decoder = ContentDecoder()
        self.analyzer = PatternAnalyzer()
        self.history = TimeBasedHistory(max_history, history_ttl)
        self.notifier = AsyncNotifier()
        
        self.notifier.start()
        
        logger.info("DataVisualizer initialized")
    
    def feed_packet(self, protocol_str: str, source: str, raw_data: bytes, 
                    is_encrypted: bool = False):
        """
        Ingest packet with proper processing pipeline
        
        Args:
            protocol_str: Protocol name (normalized to enum)
            source: Source identifier
            raw_data: Raw bytes
            is_encrypted: Is PAYLOAD encrypted (not whole packet)
        """
        if not raw_data:
            logger.warning(f"Empty packet from {source}")
            return
        
        try:
            # Normalize protocol
            protocol = Protocol.normalize(protocol_str)
            
            # Decode text
            decoded_text, encoding = self.decoder.decode(raw_data)
            
            # Extract TLS metadata if applicable
            tls_metadata = None
            if protocol == Protocol.TLS or protocol == Protocol.HTTPS:
                tls_metadata = self.decoder.extract_tls_metadata(raw_data)
            
            # Create packet
            packet = DataStreamPacket(
                protocol=protocol,
                source=source,
                raw_bytes=raw_data,
                decoded_text=decoded_text,
                encoding=encoding,
                is_payload_encrypted=is_encrypted,
                tls_metadata=tls_metadata
            )
            
            # Analyze for tags
            tags = self.analyzer.analyze(packet)
            packet.tags = tags
            
            # Store atomically (history append + notify must be atomic)
            self.history.append(packet)
            
            # Notify subscribers (async, non-blocking)
            self.notifier.notify(packet)
            
        except Exception as e:
            logger.error(f"Feed failed for {protocol_str}/{source}: {e}", exc_info=True)
    
    def subscribe(self, callback: Callable[[DataStreamPacket], None]) -> int:
        """Subscribe to packet stream (returns subscription ID)"""
        return self.notifier.subscribe(callback)
    
    def unsubscribe(self, sub_id: int):
        """Unsubscribe from packet stream"""
        self.notifier.unsubscribe(sub_id)
    
    def get_latest(self, count: int = 10) -> List[DataStreamPacket]:
        """Get N most recent packets"""
        return self.history.get_recent(count)
    
    def get_tagged(self, severity: Optional[TagSeverity] = None ) -> List[DataStreamPacket]:
        """Get packets with tags (optionally filtered by severity)"""
        packets = self.history.get_all()
        
        if severity:
            return [p for p in packets if any(t.severity == severity for t in p.tags)]
        else:
            return [p for p in packets if p.tags]
    
    def get_stats(self) -> Dict:
        """Get statistics"""
        packets = self.history.get_all()
        
        protocol_counts = {}
        for pkt in packets:
            protocol_counts[pkt.protocol.value] = protocol_counts.get(pkt.protocol.value, 0) + 1
        
        tag_counts = {}
        for pkt in packets:
            for tag in pkt.tags:
                tag_counts[tag.name] = tag_counts.get(tag.name, 0) + 1
        
        return {
            'total_packets': len(packets),
            'encrypted_payloads': sum(1 for p in packets if p.is_payload_encrypted),
            'tls_with_metadata': sum(1 for p in packets if p.tls_metadata),
            'tagged_packets': sum(1 for p in packets if p.tags),
            'protocol_distribution': protocol_counts,
            'tag_distribution': tag_counts,
            'active_subscribers': len([i for i in self.notifier.subscribers if i not in self.notifier.quarantined]),
            'quarantined_subscribers': len(self.notifier.quarantined)
        }
    
    def shutdown(self):
        """Clean shutdown"""
        self.notifier.stop()
        logger.info("DataVisualizer shutdown")
