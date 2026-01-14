"""
SCPE Advanced Control Modules
Implements "Military-Grade" logic for:
1. Dynamic Power Allocation (Priority-based)
2. Waveform Scheduling (Crossfade / TDM / WRR)
3. Adaptive Jitter Control (PID-based Feedback Loop)
"""

import numpy as np
import logging
import time

logger = logging.getLogger("SCPE_Advanced")

class DynamicPowerAllocator:
    """
    Allocates TX power weights to multiple targets based on priority,
    ensuring total power constraints are met. Includes smooth ramping.
    """
    def __init__(self, max_total_power: float = 1.0, enable_ramping: bool = True):
        self.max_total_power = max_total_power
        self.priorities = {}  # device_id -> priority (0.0 - 10.0)
        self.current_weights = {}  # Smoothed weights for ramping
        self.enable_ramping = enable_ramping
        self.ramp_rate = 0.1  # Max change per cycle (10% per call)

    def update_priority(self, device_id: str, priority: float):
        self.priorities[device_id] = max(0.0, priority)

    def remove_target(self, device_id: str):
        if device_id in self.priorities:
            del self.priorities[device_id]

    def allocate(self) -> dict:
        """
        Returns normalized power weights {device_id: weight}
        with optional smooth ramping.
        """
        if not self.priorities:
            return {}
            
        total_prio = sum(self.priorities.values())
        if total_prio == 0:
            # Even split if all 0
            count = len(self.priorities)
            target_weights = {dev: (self.max_total_power / count) for dev in self.priorities}
        else:
            # Linear allocation
            target_weights = {}
            for dev, prio in self.priorities.items():
                w = (prio / total_prio) * self.max_total_power
                target_weights[dev] = w
        
        if not self.enable_ramping:
            return target_weights
            
        # Smooth ramping toward target
        for dev in target_weights:
            current = self.current_weights.get(dev, 0.0)
            target = target_weights[dev]
            delta = target - current
            
            # Limit change rate
            if abs(delta) > self.ramp_rate:
                delta = np.sign(delta) * self.ramp_rate
                
            self.current_weights[dev] = current + delta
            
        # Remove devices no longer in target
        for dev in list(self.current_weights.keys()):
            if dev not in target_weights:
                # Ramp down to zero before removal
                if self.current_weights[dev] > self.ramp_rate:
                    self.current_weights[dev] -= self.ramp_rate
                else:
                    del self.current_weights[dev]
                    
        return self.current_weights

class WaveformScheduler:
    """
    Schedules multiple waveforms onto the single SDR TX stream.
    Supports:
    - CROSSFADE: Simultaneously transmitted (summed) with weights.
    - TDM: Time-Division Multiplexed slots.
    - WRR: Weighted Round Robin time slicing.
    """
    def __init__(self, sample_rate: float):
        self.sample_rate = sample_rate
        self.mode = "CROSSFADE" # or "TDM" or "WRR"
        self.tdm_slot_duration = 0.5 # Seconds
        self.wrr_slot_duration = 0.2 # Seconds per minimum slot
        
    def crossfade_weights(self, current_weights: dict, next_weights: dict, step_fraction: float) -> dict:
        """
        Interpolates weights for smooth transitions.
        step_fraction: 0.0 (current) -> 1.0 (next)
        """
        all_keys = set(current_weights.keys()) | set(next_weights.keys())
        blended = {}
        for dev in all_keys:
            cw = current_weights.get(dev, 0.0)
            nw = next_weights.get(dev, 0.0)
            blended[dev] = cw * (1 - step_fraction) + nw * step_fraction
        return blended

    def blend_waveforms(self, waveforms: dict, weights: dict) -> np.ndarray:
        """
        Sum multiple waveforms into one composite signal.
        """
        if not waveforms:
            return np.array([], dtype=np.complex64)
            
        # Find max length
        max_len = max(len(wf) for wf in waveforms.values())
        if max_len == 0:
             return np.array([], dtype=np.complex64)
             
        composite = np.zeros(max_len, dtype=np.complex64)
        
        for dev, wf in waveforms.items():
            w = weights.get(dev, 0.0)
            if w > 0 and len(wf) > 0:
                # Pad to max_len
                current_len = len(wf)
                if current_len < max_len:
                    padded = np.pad(wf, (0, max_len - current_len), 'constant')
                    composite += padded * w
                else:
                    composite += wf * w
                    
        # Hard Limiter / Normalization to avoid clipping
        max_amp = np.max(np.abs(composite))
        if max_amp > 1.0:
            composite /= max_amp
            
        return composite

    def tdm_schedule(self, waveforms: dict, weights: dict) -> list:
        """
        Returns ordered list of (device_id, waveform_slice, length_samples)
        Allocates time proportional to weight.
        """
        total_weight = sum(weights.values())
        if total_weight == 0:
            return []
            
        schedule = []
        for dev, wf in waveforms.items():
            w = weights.get(dev, 0.0)
            if w > 0:
                # Calculate slot time
                slot_sec = self.tdm_slot_duration * (w / total_weight)
                slot_samples = int(slot_sec * self.sample_rate)
                
                if len(wf) == 0: continue
                
                # Tiling to fill slot if needed
                necessary_repeats = int(np.ceil(slot_samples / len(wf)))
                tiled = np.tile(wf, necessary_repeats)[:slot_samples]
                
                schedule.append((dev, tiled, slot_samples))
                
        return schedule
    
    def wrr_schedule(self, waveforms: dict, weights: dict) -> list:
        """
        Weighted Round Robin scheduler.
        Allocates slots proportional to weight, cycling through devices.
        
        Returns: List of (device_id, waveform_slice, length_samples)
        """
        total_weight = sum(weights.values())
        if total_weight == 0 or not weights:
            return []
            
        # Calculate normalized slot counts per device
        min_weight = min(weights.values())
        total_slots = int(np.ceil(sum(weights.values()) / min_weight))
        slots_per_device = {
            dev: max(1, int(round((w / total_weight) * total_slots))) 
            for dev, w in weights.items()
        }
        
        slot_samples = int(self.wrr_slot_duration * self.sample_rate)
        schedule = []
        
        # Round robin cycle
        devices = list(slots_per_device.keys())
        slot_counts = {dev: 0 for dev in devices}
        total_slots_needed = sum(slots_per_device.values())
        idx = 0
        
        while sum(slot_counts.values()) < total_slots_needed:
            dev = devices[idx % len(devices)]
            
            if slot_counts[dev] < slots_per_device[dev]:
                wf = waveforms.get(dev)
                if wf is not None and len(wf) > 0:
                    # Tile or cut waveform to fill slot
                    repeats = int(np.ceil(slot_samples / len(wf)))
                    tiled = np.tile(wf, repeats)[:slot_samples]
                    schedule.append((dev, tiled, slot_samples))
                    slot_counts[dev] += 1
                    
            idx += 1
            
            # Safety: prevent infinite loop
            if idx > total_slots_needed * len(devices) * 2:
                break
                
        return schedule

class AdaptiveJitterController:
    """
    Maintains and adjusts Jitter parameters per device using PID control.
    Feedback: SNR, Age (Latency), Success Rate
    """
    def __init__(self, use_pid: bool = True):
        self.device_profiles = {} # dev_id -> {jitter_pct, integral, last_error, last_update}
        self.use_pid = use_pid
        
        # Hyperparams
        self.min_jitter = 0.01
        self.max_jitter = 0.20
        
        # PID gains
        self.kp = 0.1  # Proportional gain
        self.ki = 0.01 # Integral gain
        self.kd = 0.05 # Derivative gain
        
        # Simple fallback learning rate
        self.learning_rate = 0.01

    def get_jitter(self, device_id: str) -> float:
        if device_id not in self.device_profiles:
            # Default init
            self.device_profiles[device_id] = {
                "jitter_pct": 0.05,
                "integral": 0.0,
                "last_error": 0.0,
                "last_update": time.time(),
                "confidence": 0.5
            }
        return self.device_profiles[device_id]["jitter_pct"]

    def update_feedback(self, device_id: str, metrics: dict):
        """
        metrics: {
            'snr': float (db),
            'success': bool (did attack work?),
            'seen_recently': bool
        }
        """
        if device_id not in self.device_profiles:
            self.get_jitter(device_id) # Init
            
        profile = self.device_profiles[device_id]
        
        if self.use_pid:
            # PID-based control
            success = metrics.get('success', False)
            snr = metrics.get('snr', 20.0)
            
            # Error signal: failure = 1.0, success = 0.0
            # (Could refine with partial credit based on SNR)
            error = 0.0 if success else 1.0
            
            # If SNR is very low, increase error to widen jitter
            if snr < 10.0:
                error = max(error, 0.5)
            
            now = time.time()
            dt = now - profile["last_update"]
            profile["last_update"] = now
            
            if dt > 0:
                # PID calculations
                profile["integral"] += error * dt
                # Anti-windup: clamp integral
                profile["integral"] = max(-1.0, min(1.0, profile["integral"]))
                
                derivative = (error - profile["last_error"]) / dt
                profile["last_error"] = error
                
                # PID output
                adjustment = self.kp * error + self.ki * profile["integral"] + self.kd * derivative
                
                jitter = profile["jitter_pct"] + adjustment
            else:
                jitter = profile["jitter_pct"]
        else:
            # Simple heuristic fallback
            current = profile["jitter_pct"]
            snr = metrics.get('snr', 20.0)
            success = metrics.get('success', False)
            
            if success:
                pass # Stable
            else:
                if snr > 25.0:
                     # Strong signal but no effect? Timing is off.
                     current = min(self.max_jitter, current + self.learning_rate)
                elif snr < 10.0:
                     # Weak signal. Tighten up.
                     current = max(self.min_jitter, current - self.learning_rate)
                     
            jitter = current
                
        # Clamp to bounds
        profile["jitter_pct"] = min(max(self.min_jitter, jitter), self.max_jitter)
        return profile["jitter_pct"]
