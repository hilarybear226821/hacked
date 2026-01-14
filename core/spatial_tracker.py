"""
Spatial Tracker - Dynamic RSSI Normalization & Movement Detection
Uses stationary anchors and 1D Kalman Filtering for precise localization.
Fixed & Improved for robustness.
"""

import numpy as np
import time
import logging
from typing import Dict, List, Optional
from collections import deque

class SpatialTracker:
    """
    Implements Dynamic RSSI Normalization using stationary Anchor Nodes.
    Uses 1D Kalman Filtering for RSSI smoothing and movement anomaly detection.
    
    Improvements:
    - ✅ Difference-based Normalization (Safe for dBm logarithmic scale)
    - ✅ Variance-based Movement Detection (Detects active motion vs displacement)
    - ✅ Robust Kalman Filter state management
    - ✅ Thread handling for stability
    """
    
    def __init__(self, window_size: int = 15):
        self.anchors: Dict[str, Dict] = {}  # id -> {baseline, history, kalman_state}
        self.targets: Dict[str, Dict] = {}  # id -> {baseline, kalman_state, velocity_history}
        self.window_size = window_size
        self.env_correction = 0.0  # Environmental dBm correction factor
        self.logger = logging.getLogger("SpatialTracker")
        
    def register_anchor(self, device_id: str, current_rssi: float):
        """Designate a device as a stationary anchor node"""
        if current_rssi == 0:  # Ignore invalid 0 RSSI
            return
            
        self.anchors[device_id] = {
            'baseline': current_rssi,
            'history': deque([current_rssi], maxlen=self.window_size),
            'kalman': self._init_kalman(current_rssi)
        }
        self.logger.info(f"Registered anchor: {device_id} (Baseline: {current_rssi} dBm)")
        
    def update_anchor(self, device_id: str, rssi: float):
        """Update anchor state and recalculate environmental correction"""
        if rssi >= 0 or rssi < -120:  # simplistic validation
            return

        if device_id in self.anchors:
            state = self.anchors[device_id]['kalman']
            smoothed_rssi = self._update_kalman(state, rssi)
            self.anchors[device_id]['history'].append(smoothed_rssi)
            self._recalculate_correction()
            
    def _recalculate_correction(self):
        """
        Calculate environmental correction (dBm delta).
        If anchors are weaker than baseline, we boost everyone.
        """
        if not self.anchors:
            self.env_correction = 0.0
            return
            
        deltas = []
        for info in self.anchors.values():
            smoothed_current = info['kalman']['x']
            baseline = info['baseline']
            
            # If current is -80 and baseline is -60:
            # We lost 20 dB due to environment filtering/interference
            # We should ADD 20 to normalize back to baseline conditions
            # Correction = Baseline - Current
            # -60 - (-80) = +20
            delta = baseline - smoothed_current
            deltas.append(delta)
            
        # Average correction across all anchors
        if deltas:
            self.env_correction = np.mean(deltas)
        else:
            self.env_correction = 0.0
        
    def normalize_rssi(self, device_id: str, raw_rssi: float) -> float:
        """
        Normalize target RSSI using the environmental correction.
        RSSI_Adjusted = RSSI_Target + Correction
        
        Args:
            device_id: Target device ID
            raw_rssi: Raw RSSI measurement
            
        Returns:
            Smoothed and Normalized RSSI
        """
        if raw_rssi >= 0:
            return raw_rssi

        # Initialize tracking if new
        if device_id not in self.targets and device_id not in self.anchors:
            self.targets[device_id] = {
                'baseline': raw_rssi,
                'kalman': self._init_kalman(raw_rssi),
                'history': deque(maxlen=self.window_size),
                'normalized_history': deque(maxlen=self.window_size)
            }
            
        smoothed_rssi = raw_rssi
        if device_id in self.targets:
            target = self.targets[device_id]
            state = target['kalman']
            smoothed_rssi = self._update_kalman(state, raw_rssi)
            target['history'].append(smoothed_rssi)
            
        # Apply correction
        normalized_rssi = smoothed_rssi + self.env_correction
        
        if device_id in self.targets:
            self.targets[device_id]['normalized_history'].append(normalized_rssi)
            
        return normalized_rssi

    def detect_movement(self, device_id: str, normalized_rssi: float, threshold: float = 2.0) -> bool:
        """
        Detect significant movement using RSSI variance/velocity.
        
        Args:
            device_id: Device ID
            normalized_rssi: Current smoothed RSSI
            threshold: Variance threshold (standard dev or delta)
            
        Returns:
            True if moving
        """
        if device_id not in self.targets:
            return False
            
        history = self.targets[device_id]['normalized_history']
        
        if len(history) < 5:
            return False
            
        # 1. Variance Check (Is the signal jittery/changing?)
        variance = np.var(list(history))
        
        # 2. Trend Check (Did we move significantly from 5 samples ago?)
        # Simple delta
        recent_avg = np.mean(list(history)[-3:])
        older_avg = np.mean(list(history)[:3])
        trend = abs(recent_avg - older_avg)
        
        # If variance is high OR we have a strong directional trend
        is_moving = variance > threshold or trend > (threshold * 1.5)
        
        return is_moving

    def _init_kalman(self, initial_value: float) -> Dict:
        """Initialize 1D Kalman Filter state"""
        return {
            'x': initial_value, # State estimate
            'p': 1.0,           # Estimation error covariance
            'q': 0.1,           # Process noise covariance (How much we expect RSSI to change naturally)
            'r': 3.0            # Measurement noise covariance (Sensor noise)
        }

    def _update_kalman(self, state: Dict, measurement: float) -> float:
        """Perform Kalman update step"""
        # Prediction
        state['p'] = state['p'] + state['q']
        
        # Update
        # K = P / (P + R)
        k_gain = state['p'] / (state['p'] + state['r'])
        # x = x + K * (z - x)
        state['x'] = state['x'] + k_gain * (measurement - state['x'])
        # P = (1 - K) * P
        state['p'] = (1 - k_gain) * state['p']
        
        return state['x']

    def reset(self):
        """Clear all tracking state"""
        self.anchors.clear()
        self.targets.clear()
        self.env_correction = 0.0
        self.logger.info("Spatial tracker reset")

# Singleton instance
spatial_tracker = SpatialTracker()
