"""
Base Protocol Handler Interface

All protocol handlers must inherit from this abstract base class.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any
from enum import Enum

class ProtocolType(Enum):
    """Protocol categories"""
    WEB = "web"
    EMAIL = "email"
    AUTH = "authentication"
    REMOTE = "remote_access"
    DATABASE = "database"
    FILE_TRANSFER = "file_transfer"

@dataclass
class ProcessingResult:
    """Result of protocol processing"""
    protocol_name: str
    success: bool
    credentials: Optional[Dict[str, str]] = None
    tokens: Optional[Dict[str, str]] = None
    metadata: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class ProtocolHandler(ABC):
    """
    Abstract base class for protocol handlers.
    
    Each protocol handler (HTTP/2, WebSocket, SMTP, etc.) must implement:
    - detect(): Identify if packet belongs to this protocol
    - process(): Extract intelligence from packet
    - modify(): Alter packet for attack purposes
    """
    
    def __init__(self, name: str, protocol_type: ProtocolType):
        self.name = name
        self.protocol_type = protocol_type
        self.enabled = True
        
    @abstractmethod
    def detect(self, packet: bytes) -> bool:
        """
        Detect if this handler can process the packet.
        
        Args:
            packet: Raw packet bytes
            
        Returns:
            True if this protocol handler should process the packet
        """
        pass
    
    @abstractmethod
    def process(self, packet: bytes) -> ProcessingResult:
        """
        Process packet and extract intelligence.
        
        Args:
            packet: Raw packet bytes
            
        Returns:
            ProcessingResult with extracted data (credentials, tokens, etc.)
        """
        pass
    
    @abstractmethod
    def modify(self, packet: bytes, rules: Dict[str, Any]) -> Optional[bytes]:
        """
        Modify packet according to attack rules.
        
        Args:
            packet: Original packet bytes
            rules: Modification rules (e.g., {'inject_header': 'X-Evil: true'})
            
        Returns:
            Modified packet bytes, or None if modification failed
        """
        pass
    
    def enable(self):
        """Enable this handler"""
        self.enabled = True
        
    def disable(self):
        """Disable this handler"""
        self.enabled = False
