import time
import statistics
from typing import Dict, List, Tuple
from collections import deque
from .device_model import DeviceType

class TrafficAnalyzer:
    """
    Analyzes encrypted traffic patterns to infer device type (IoTScent concept).
    Tracks:
    - Packet Size Distribution (Variance)
    - Inter-Arrival Time (IAT)
    """
    def __init__(self, window_size=50):
        self.window_size = window_size
        # Map MAC -> {'timestamps': deque, 'sizes': deque}
        self.history: Dict[str, Dict] = {}
        
    def process_packet(self, mac_address: str, size: int, timestamp: float):
        if mac_address not in self.history:
            self.history[mac_address] = {
                'timestamps': deque(maxlen=self.window_size),
                'sizes': deque(maxlen=self.window_size)
            }
            
        record = self.history[mac_address]
        record['timestamps'].append(timestamp)
        record['sizes'].append(size)
        
    def analyze(self, mac_address: str) -> Tuple[str, float]:
        """
        Analyze traffic and return (inferred_category, confidence)
        """
        if mac_address not in self.history:
            return "Unknown", 0.0
            
        record = self.history[mac_address]
        if len(record['sizes']) < 10:
            return "Unknown", 0.0 # Not enough data
            
        sizes = list(record['sizes'])
        timestamps = list(record['timestamps'])
        
        # 1. Size Metrics
        avg_size = statistics.mean(sizes)
        try:
            size_variance = statistics.variance(sizes)
        except:
            size_variance = 0
            
        # 2. Timing Metrics (IAT)
        iats = [t2 - t1 for t1, t2 in zip(timestamps[:-1], timestamps[1:])]
        if not iats:
            avg_iat = 0
        else:
            avg_iat = statistics.mean(iats)
            
        # --- Heuristics ---
        
        # Camera / Audio Stream: High throughput, high variance (I-frames vs P-frames) or constant large packets
        if avg_size > 800 and avg_iat < 0.1:
            return "High Bandwidth (Camera/Stream)", 0.8
            
        # Smart Bulb / Sensor: rare, small packets, periodic
        if avg_size < 200 and avg_iat > 2.0:
            return "Low Bandwidth (Sensor/Bulb)", 0.7
            
        # Hub / Speaker: Bursting
        if size_variance > 50000: # High variance
            return "Bursty (Hub/Complex Device)", 0.5
            
        return "Unknown", 0.0

    def get_stats(self, mac_address: str) -> str:
        if mac_address not in self.history: return "No Data"
        rec = self.history[mac_address]
        if len(rec['sizes']) < 2: return "Insufficient Data"
        return f"AvgSize: {int(statistics.mean(rec['sizes']))}B, Count: {len(rec['sizes'])}"
