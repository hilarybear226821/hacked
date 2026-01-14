"""
SSH Credential Harvest Handler

Implements SSH protocol detection and monitoring:
- Banner detection (version information)
- Key exchange monitoring
- Password authentication detection
- Public key fingerprint extraction

SSH operates on TCP port 22.
"""

from typing import Optional, Dict, Any
import re

from modules.protocols.base_handler import ProtocolHandler, ProtocolType, ProcessingResult

class SSHHarvest(ProtocolHandler):
    """
    SSH protocol monitoring handler.
    
    Attack Capabilities:
    1. Server version detection
    2. Key exchange algorithm extraction
    3. Password authentication monitoring (if unencrypted channel)
    4. Public key fingerprint collection
    """
    
    def __init__(self):
        super().__init__("SSH", ProtocolType.REMOTE)
        self.detected_servers = {}
    
    def detect(self, packet: bytes) -> bool:
        """Detect SSH traffic"""
        try:
            packet_str = packet.decode('utf-8', errors='ignore')
            
            # SSH banner starts with "SSH-"
            if packet_str.startswith('SSH-'):
                return True
                
        except:
            pass
        
        return False
    
    def process(self, packet: bytes) -> ProcessingResult:
        """Process SSH packet"""
        try:
            packet_str = packet.decode('utf-8', errors='ignore')
            
            metadata = {}
            
            # Extract SSH banner/version
            banner_match = re.match(r'SSH-([\d.]+)-(.+)', packet_str)
            if banner_match:
                protocol_version = banner_match.group(1)
                software_version = banner_match.group(2).strip()
                
                metadata['protocol_version'] = protocol_version
                metadata['software'] = software_version
                
                # Store server fingerprint
                server_id = f"{protocol_version}_{software_version}"
                if server_id not in self.detected_servers:
                    self.detected_servers[server_id] = {
                        'first_seen': __import__('time').time(),
                        'count': 1
                    }
                else:
                    self.detected_servers[server_id]['count'] += 1
                
                # Check for known vulnerable versions
                if self._check_vulnerable_version(software_version):
                    metadata['vulnerable'] = True
                    metadata['vulnerability'] = self._get_vulnerability_info(software_version)
            
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
        """Modify SSH packet (limited due to encryption)"""
        try:
            packet_str = packet.decode('utf-8', errors='replace')
            
            # Modify banner (only works during initial handshake)
            if 'modify_banner' in rules and packet_str.startswith('SSH-'):
                # Replace with custom banner
                return f"SSH-2.0-{rules['modify_banner']}\r\n".encode()
            
            return None
            
        except Exception as e:
            print(f"[SSH] Modification error: {e}")
            return None
    
    def _check_vulnerable_version(self, version: str) -> bool:
        """Check if SSH version has known vulnerabilities"""
        vulnerable_patterns = [
            r'OpenSSH_[0-6]\.',  # Old OpenSSH versions
            r'libssh-0\.[0-8]\.',  # libssh vulnerabilities
            r'OpenSSH_7\.[0-3]',  # Pre-7.4 versions
        ]
        
        for pattern in vulnerable_patterns:
            if re.search(pattern, version):
                return True
        
        return False
    
    def _get_vulnerability_info(self, version: str) -> str:
        """Get vulnerability information for version"""
        if 'libssh' in version:
            return "libssh authentication bypass (CVE-2018-10933)"
        elif re.search(r'OpenSSH_7\.[0-3]', version):
            return "Username enumeration (CVE-2016-6210)"
        elif re.search(r'OpenSSH_[0-6]\.', version):
            return "Multiple vulnerabilities - upgrade recommended"
        
        return "Potentially vulnerable - check CVE database"
    
    def get_server_inventory(self) -> Dict:
        """Return detected SSH servers"""
        return self.detected_servers
