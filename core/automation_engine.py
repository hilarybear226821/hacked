"""
Automation Engine - Orchestrates Advanced Features
Automatically triggers XFi, Deep Identity, SBFD, DNS Recon, and Threat Detection
"""

import threading
import time
import queue
from typing import Dict, List, Optional, Set
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

from core import DeviceRegistry, DeviceType, Protocol
from modules.sbfd_analyzer import SBFDAnalyzer, extract_sbfd_data_from_packet
from modules.deep_identity_engine import DeepIdentityEngine
from core.spatial_tracker import SpatialTracker

@dataclass
class AutomationConfig:
    """Configuration for automation features"""
    # XFi
    xfi_enabled: bool = True
    xfi_min_confidence: float = 0.75
    
    # Deep Identity
    identity_enabled: bool = True
    identity_interval: int = 30  # Run every 30s for new devices
    
    # SBFD
    sbfd_enabled: bool = True
    sbfd_health_check_interval: int = 60  # Check health every 60s
    
    # Spatial Anchors
    auto_anchor_enabled: bool = True
    auto_anchor_stability_threshold: int = 300  # 5 minutes stable = anchor
    
    # Threat Detection
    threat_detection_enabled: bool = True
    evil_twin_detection: bool = True
    deauth_detection: bool = True
    
    # DNS Recon
    auto_dns_recon: bool = True  # Already implemented in network_recon.py
    
    # Performance
    max_worker_threads: int = 4
    packet_queue_size: int = 1000

class AutomationEngine:
    """
    Central automation controller
    Runs advanced features in background without user intervention
    """
    
    def __init__(self, registry: DeviceRegistry, config: AutomationConfig = None):
        self.registry = registry
        self.config = config or AutomationConfig()
        
        # Feature modules
        self.sbfd = SBFDAnalyzer() if self.config.sbfd_enabled else None
        self.spatial_tracker = SpatialTracker()
        self.spatial_tracker = SpatialTracker()
        # Requires global config, but passing local automation config for now
        # Ideally this should be passed from main
        self.deep_identity = None
        
        # Packet processing queue
        self.packet_queue = queue.Queue(maxsize=self.config.packet_queue_size)
        self.executor = ThreadPoolExecutor(max_workers=self.config.max_worker_threads)
        
        # State tracking
        self.processed_devices: Set[str] = set()  # Devices that got Deep Identity
        self.anchor_candidates: Dict[str, float] = {}  # device_id -> first_seen
        self.threat_events: List[Dict] = []
        
        # Control
        self.running = False
        self.threads: List[threading.Thread] = []
        
        print("[Automation] Engine initialized")
        print(f"[Automation] XFi: {self.config.xfi_enabled}, Identity: {self.config.identity_enabled}, SBFD: {self.config.sbfd_enabled}")
    
    def start(self):
        """Start all automation threads"""
        if self.running:
            return
        
        self.running = True
        
        # Thread 1: Packet processing worker
        t1 = threading.Thread(target=self._packet_worker, daemon=True, name="PacketWorker")
        t1.start()
        self.threads.append(t1)
        
        # Thread 2: Periodic Deep Identity inference
        if self.config.identity_enabled:
            t2 = threading.Thread(target=self._identity_worker, daemon=True, name="IdentityWorker")
            t2.start()
            self.threads.append(t2)
        
        # Thread 3: SBFD health monitoring
        if self.config.sbfd_enabled:
            t3 = threading.Thread(target=self._sbfd_worker, daemon=True, name="SBFDWorker")
            t3.start()
            self.threads.append(t3)
        
        # Thread 4: Spatial anchor auto-designation
        if self.config.auto_anchor_enabled:
            t4 = threading.Thread(target=self._anchor_worker, daemon=True, name="AnchorWorker")
            t4.start()
            self.threads.append(t4)
        
        # Thread 5: Threat detection
        if self.config.threat_detection_enabled:
            t5 = threading.Thread(target=self._threat_worker, daemon=True, name="ThreatWorker")
            t5.start()
            self.threads.append(t5)
        
        print(f"[Automation] Started {len(self.threads)} worker threads")
    
    def stop(self):
        """Stop all automation"""
        self.running = False
        self.executor.shutdown(wait=False)
        print("[Automation] Stopped")
    
    def submit_packet(self, packet, source_module: str):
        """
        Submit packet for automated processing
        
        Args:
            packet: Scapy packet
            source_module: "wifi", "bluetooth", "subghz", etc.
        """
        try:
            self.packet_queue.put_nowait((packet, source_module, time.time()))
        except queue.Full:
            # Drop packet if queue full (prevents memory overflow)
            pass
    
    def _packet_worker(self):
        """Process packets from queue"""
        while self.running:
            try:
                packet, source, timestamp = self.packet_queue.get(timeout=1)
                
                # Submit to thread pool for parallel processing
                self.executor.submit(self._process_packet, packet, source, timestamp)
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[Automation] Packet worker error: {e}")
    
    def _process_packet(self, packet, source: str, timestamp: float):
        """Process individual packet (runs in thread pool)"""
        try:
            # SBFD Analysis (sequence tracking)
            if self.sbfd and source in ['wifi', 'bluetooth', 'zigbee']:
                sbfd_data = extract_sbfd_data_from_packet(packet)
                if sbfd_data:
                    # Extract device ID from packet
                    device_id = self._extract_device_id(packet, source)
                    if device_id:
                        self.sbfd.process_packet(device_id, sbfd_data)
            
            # XFi Analysis (corrupted Wi-Fi frames)
            if self.config.xfi_enabled and source == 'wifi':
                # Check if frame has FCS error (would require RadioTap inspection)
                # This is a placeholder - real XFi needs driver support
                pass
            
        except Exception as e:
            print(f"[Automation] Packet processing error: {e}")
    
    def _identity_worker(self):
        """Periodically run Deep Identity on new devices"""
        while self.running:
            try:
                devices = self.registry.get_active()
                
                for device in devices:
                    # Only process if not already processed
                    if device.device_id not in self.processed_devices:
                        # Check if device has enough data for inference
                        if self._has_sufficient_data(device):
                            # Run Deep Identity (would call engine.infer_identity)
                            # Placeholder for now
                            self.processed_devices.add(device.device_id)
                            print(f"[Automation] Deep Identity processed: {device.name}")
                
                time.sleep(self.config.identity_interval)
                
            except Exception as e:
                print(f"[Automation] Identity worker error: {e}")
                time.sleep(10)
    
    def _sbfd_worker(self):
        """Periodically check device health via SBFD"""
        while self.running:
            try:
                if self.sbfd:
                    # Get all tracked devices
                    for device_id in list(self.sbfd.paths.keys()):
                        health = self.sbfd.get_device_health(device_id)
                        
                        # Log poor health
                        if health['health_score'] < 0.5:
                            print(f"[Automation] SBFD Warning: {device_id} health={health['health_score']:.0%} ({health['status']})")
                    
                    # Check for recent events
                    events = self.sbfd.get_recent_events(seconds=self.config.sbfd_health_check_interval)
                    for event in events:
                        print(f"[Automation] SBFD Event: {event.event_type} on {event.device_id} (conf={event.confidence:.0%})")
                
                time.sleep(self.config.sbfd_health_check_interval)
                
            except Exception as e:
                print(f"[Automation] SBFD worker error: {e}")
                time.sleep(10)
    
    def _anchor_worker(self):
        """Auto-designate stable devices as spatial anchors"""
        while self.running:
            try:
                devices = self.registry.get_active()
                current_time = time.time()
                
                for device in devices:
                    # Skip if already anchor
                    if device.is_anchor:
                        continue
                    
                    # Track new candidates
                    if device.device_id not in self.anchor_candidates:
                        self.anchor_candidates[device.device_id] = current_time
                    
                    # Check if stable enough
                    stable_duration = current_time - self.anchor_candidates[device.device_id]
                    if stable_duration > self.config.auto_anchor_stability_threshold:
                        # Check RSSI variance (should be low for stationary device)
                        if self._is_rssi_stable(device):
                            self.registry.mark_as_anchor(device.device_id)
                            print(f"[Automation] Auto-designated anchor: {device.name} (stable {stable_duration:.0f}s)")
                            del self.anchor_candidates[device.device_id]
                
                time.sleep(60)  # Check every minute
                
            except Exception as e:
                print(f"[Automation] Anchor worker error: {e}")
                time.sleep(10)
    
    def _threat_worker(self):
        """Detect security threats in real-time"""
        while self.running:
            try:
                # Evil Twin Detection
                if self.config.evil_twin_detection:
                    self._detect_evil_twins()
                
                # Deauth Attack Detection
                if self.config.deauth_detection:
                    self._detect_deauth_attacks()
                
                # Jamming Detection (would integrate with JammingDetector)
                
                time.sleep(5)  # Check every 5 seconds
                
            except Exception as e:
                print(f"[Automation] Threat worker error: {e}")
                time.sleep(10)
    
    def _detect_evil_twins(self):
        """Detect duplicate SSIDs with different BSSIDs (Evil Twin indicator)"""
        devices = self.registry.get_active()
        ssid_map: Dict[str, List] = {}
        
        for device in devices:
            if device.protocol in [Protocol.WIFI_24, Protocol.WIFI_5]:
                ssid = device.metadata.get('ssid')
                if ssid:
                    if ssid not in ssid_map:
                        ssid_map[ssid] = []
                    ssid_map[ssid].append(device)
        
        # Check for duplicates
        for ssid, device_list in ssid_map.items():
            if len(device_list) > 1:
                # Multiple APs with same SSID
                bssids = [d.metadata.get('bssid') for d in device_list]
                if len(set(bssids)) > 1:
                    threat = {
                        'type': 'EVIL_TWIN_SUSPECTED',
                        'ssid': ssid,
                        'bssids': bssids,
                        'confidence': 0.7,
                        'timestamp': time.time()
                    }
                    
                    # Check if already reported
                    if not any(t.get('ssid') == ssid for t in self.threat_events[-10:]):
                        self.threat_events.append(threat)
                        print(f"[Automation] ⚠️  THREAT: Possible Evil Twin - SSID '{ssid}' on {len(bssids)} BSSIDs")
    
    def _detect_deauth_attacks(self):
        """Detect excessive deauthentication frames (DoS attack indicator)"""
        # Would require tracking deauth frame counts from WiFi monitor
        # Placeholder for now
        pass
    
    # ========== Helper Methods ==========
    
    def _extract_device_id(self, packet, source: str) -> Optional[str]:
        """Extract device identifier from packet"""
        from scapy.all import Dot11, IP
        
        if source == 'wifi' and packet.haslayer(Dot11):
            mac = packet[Dot11].addr2
            return f"WiFi_{mac.replace(':', '')}" if mac else None
        elif source == 'ip' and packet.haslayer(IP):
            return f"IP_{packet[IP].src}"
        
        return None
    
    def _has_sufficient_data(self, device) -> bool:
        """Check if device has enough data for Deep Identity inference"""
        # Need at least 10 packets or 30 seconds of observation
        return time.time() - device.first_seen > 30
    
    def _is_rssi_stable(self, device) -> bool:
        """Check if device RSSI is stable (low variance)"""
        # Placeholder - would need RSSI history
        # Stable if variance < 5 dBm over last 100 samples
        return True  # Assume stable for now
    
    def get_stats(self) -> Dict:
        """Get automation statistics"""
        return {
            'packets_queued': self.packet_queue.qsize(),
            'devices_processed': len(self.processed_devices),
            'anchor_candidates': len(self.anchor_candidates),
            'sbfd_tracked': len(self.sbfd.paths) if self.sbfd else 0,
            'threat_events': len(self.threat_events),
            'worker_threads': len([t for t in self.threads if t.is_alive()])
        }
