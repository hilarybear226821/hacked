"""
RX Sample Bus - Decoupled IQ Stream Distribution

This module provides a bounded, lossy queue for distributing IQ samples
from the RX thread to downstream consumers (frame extractors, decoders).

Design Principles:
- Non-blocking for RX thread (drop-on-overflow)
- Thread-safe
- No SDR control logic
- Bounded memory usage
"""

import threading
import queue
import time
import logging
from typing import Optional, Callable
from dataclasses import dataclass
import numpy as np

logger = logging.getLogger("RXBus")

@dataclass
class IQSample:
    """Container for IQ sample batch with metadata"""
    samples: np.ndarray  # Complex IQ samples
    timestamp: float
    center_freq: int
    sample_rate: int
    sequence: int  # Monotonic sequence number

class RXSampleBus:
    """
    Thread-safe, multi-consumer broadcast bus for RX samples.
    
    Ensures every registered consumer receives every IQ sample batch.
    Drops samples per-consumer if their specific queue overflows.
    """
    
    def __init__(self, maxsize: int = 100):
        """
        Args:
            maxsize: Maximum queue depth per consumer
        """
        self.maxsize = maxsize
        self.queues: Dict[str, queue.Queue] = {}
        self.lock = threading.Lock()
        
        # Statistics
        self.samples_pushed = 0
        self.samples_dropped = 0
        self.sequence = 0
        
        # Metadata for current RX session
        self.center_freq: Optional[int] = None
        self.sample_rate: Optional[int] = None
        self.active = False
        
    def configure(self, center_freq: int, sample_rate: int):
        """Configure bus for new RX session"""
        with self.lock:
            self.center_freq = center_freq
            self.sample_rate = sample_rate
            self.sequence = 0
            self.active = True
            # Clear existing queues on reconfiguration
            for q in self.queues.values():
                while not q.empty():
                    try: q.get_nowait()
                    except: break
            logger.info(f"RX Bus configured: {center_freq/1e6:.3f} MHz @ {sample_rate/1e6:.1f} MSPS")
    
    def push(self, samples: np.ndarray) -> bool:
        """Broadcast IQ samples to all consumers"""
        if not self.active:
            return False
        
        with self.lock:
            # Create sample container
            iq_sample = IQSample(
                samples=samples.copy(),
                timestamp=time.time(),
                center_freq=self.center_freq,
                sample_rate=self.sample_rate,
                sequence=self.sequence
            )
            
            pushed_any = False
            for name, q in self.queues.items():
                try:
                    q.put_nowait(iq_sample)
                    pushed_any = True
                except queue.Full:
                    # We don't block, just drop for this specific consumer
                    pass
            
            self.samples_pushed += 1
            self.sequence += 1
            return pushed_any
    
    def pull(self, timeout: float = 1.0, consumer: str = "default") -> Optional[IQSample]:
        """Pull samples for a specific consumer"""
        q = None
        with self.lock:
            if consumer not in self.queues:
                logger.info(f"Registering new RX consumer: {consumer}")
                self.queues[consumer] = queue.Queue(maxsize=self.maxsize)
            q = self.queues[consumer]
            
        try:
            return q.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def stop(self):
        """Stop bus and clear all queues"""
        with self.lock:
            self.active = False
            for name, q in self.queues.items():
                while not q.empty():
                    try: q.get_nowait()
                    except: break
        
        logger.info(f"RX Bus stopped. Total pushed: {self.samples_pushed}")
    
    def get_stats(self) -> dict:
        """Get bus statistics"""
        with self.lock:
            q_sizes = {name: q.qsize() for name, q in self.queues.items()}
            return {
                "samples_pushed": self.samples_pushed,
                "active": self.active,
                "consumers": list(self.queues.keys()),
                "queue_sizes": q_sizes
            }

# Global singleton
rx_bus = RXSampleBus(maxsize=100)
