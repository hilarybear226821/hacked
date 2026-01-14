"""
Performance Monitor - Track scanner metrics and optimize resource usage
"""

import time
import psutil
import threading
from dataclasses import dataclass
from typing import Dict, List
from collections import deque

@dataclass
class PerformanceMetrics:
    """Real-time performance statistics"""
    packets_per_second: float = 0.0
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    device_count: int = 0
    gui_fps: float = 0.0
    packet_drop_rate: float = 0.0

class PerformanceMonitor:
    """
    Monitors scanner performance and resource usage
    Provides optimization recommendations
    """
    
    def __init__(self):
        self.metrics = PerformanceMetrics()
        self.packet_history = deque(maxlen=100)  # Last 100 packet timestamps
        self.gui_update_history = deque(maxlen=60)  # Last 60 GUI updates
        
        self.running = False
        self.thread = None
        
        # Process handle for memory/CPU tracking
        self.process = psutil.Process()
        
        print("[Performance] Monitor initialized")
    
    def start(self):
        """Start performance monitoring thread"""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True, name="PerfMonitor")
        self.thread.start()
        print("[Performance] Monitoring started")
    
    def stop(self):
        """Stop monitoring"""
        self.running = False
    
    def record_packet(self):
        """Record packet processing event"""
        self.packet_history.append(time.time())
    
    def record_gui_update(self):
        """Record GUI update event"""
        self.gui_update_history.append(time.time())
    
    def _monitor_loop(self):
        """Background monitoring loop"""
        while self.running:
            try:
                # Update metrics
                self._update_metrics()
                
                # Check for performance issues
                self._check_warnings()
                
                time.sleep(2)  # Update every 2 seconds
                
            except Exception as e:
                print(f"[Performance] Monitor error: {e}")
    
    def _update_metrics(self):
        """Calculate current performance metrics"""
        current_time = time.time()
        
        # Packets per second (last 10 seconds)
        recent_packets = [t for t in self.packet_history if current_time - t < 10]
        self.metrics.packets_per_second = len(recent_packets) / 10.0
        
        # GUI FPS (last 5 seconds)
        recent_updates = [t for t in self.gui_update_history if current_time - t < 5]
        self.metrics.gui_fps = len(recent_updates) / 5.0
        
        # CPU and Memory
        self.metrics.cpu_percent = self.process.cpu_percent(interval=0.1)
        mem_info = self.process.memory_info()
        self.metrics.memory_mb = mem_info.rss / (1024 * 1024)  # Convert to MB
    
    def _check_warnings(self):
        """Check for performance warnings"""
        # High CPU
        if self.metrics.cpu_percent > 80:
            print(f"[Performance] ⚠️  High CPU: {self.metrics.cpu_percent:.1f}%")
        
        # High Memory
        if self.metrics.memory_mb > 500:
            print(f"[Performance] ⚠️  High Memory: {self.metrics.memory_mb:.0f} MB")
        
        # Low GUI FPS
        if self.metrics.gui_fps < 0.5 and len(self.gui_update_history) > 10:
            print(f"[Performance] ⚠️  Low GUI FPS: {self.metrics.gui_fps:.1f} fps")
    
    def get_summary(self) -> str:
        """Get human-readable performance summary"""
        return (
            f"Performance Metrics:\n"
            f"  Packets/sec: {self.metrics.packets_per_second:.1f}\n"
            f"  CPU: {self.metrics.cpu_percent:.1f}%\n"
            f"  Memory: {self.metrics.memory_mb:.0f} MB\n"
            f"  GUI FPS: {self.metrics.gui_fps:.1f}\n"
        )
    
    def get_recommendations(self) -> List[str]:
        """Get optimization recommendations"""
        recommendations = []
        
        if self.metrics.packets_per_second > 100:
            recommendations.append("Consider enabling packet sampling (process 1 in N packets)")
        
        if self.metrics.memory_mb > 300:
            recommendations.append("Enable device history pruning (limit stored packets per device)")
        
        if self.metrics.cpu_percent > 60:
            recommendations.append("Reduce GUI update frequency to 1-2 seconds")
        
        if self.metrics.gui_fps < 1.0:
            recommendations.append("Disable real-time graphs or reduce update rate")
        
        return recommendations
