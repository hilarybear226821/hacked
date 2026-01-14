"""
SCPE Population Optimizer
Middleware orchestrator that integrates all control modules with protocol-aware intelligence.
"""

import logging
from typing import Dict, Optional
import numpy as np

logger = logging.getLogger("SCPE_Optimizer")

class SCPEPopulationOptimizer:
    """
    High-level orchestrator for SCPE attack optimization.
    Manages protocol-aware scheduling, adaptive parameter tuning, and feedback integration.
    """
    
    # Protocol-specific settings database
    PROTOCOL_SETTINGS = {
        "Keeloq": {
            "min_jitter": 0.03,
            "max_jitter": 0.15,
            "power_priority": 1.5,
            "slot_duration": 0.3,
            "critical": True  # Requires precise timing
        },
        "Nice_FLO": {
            "min_jitter": 0.02,
            "max_jitter": 0.12,
            "power_priority": 1.3,
            "slot_duration": 0.25,
            "critical": True
        },
        "Somfy_RTS": {
            "min_jitter": 0.04,
            "max_jitter": 0.18,
            "power_priority": 1.2,
            "slot_duration": 0.35,
            "critical": False
        },
        "Princeton_PT2262": {
            "min_jitter": 0.05,
            "max_jitter": 0.20,
            "power_priority": 1.0,
            "slot_duration": 0.2,
            "critical": False
        },
        "Security+": {
            "min_jitter": 0.02,
            "max_jitter": 0.10,
            "power_priority": 1.8,  # High priority
            "slot_duration": 0.4,
            "critical": True
        },
        "Unknown": {
            "min_jitter": 0.05,
            "max_jitter": 0.15,
            "power_priority": 1.0,
            "slot_duration": 0.3,
            "critical": False
        }
    }
    
    def __init__(self, power_allocator, waveform_scheduler, jitter_controller):
        """
        Args:
            power_allocator: DynamicPowerAllocator instance
            waveform_scheduler: WaveformScheduler instance
            jitter_controller: AdaptiveJitterController instance
        """
        self.power_allocator = power_allocator
        self.scheduler = waveform_scheduler
        self.jitter_ctrl = jitter_controller
        
        # Device tracking
        self.device_info = {}  # device_id -> {freq, protocol, last_update}
        
    def update_device_info(self, device_id: str, freq: float, protocol: str):
        """
        Register or update device information with protocol-aware parameters.
        """
        # Normalize protocol name
        protocol_key = self._normalize_protocol(protocol)
        
        self.device_info[device_id] = {
            "freq": freq,
            "protocol": protocol_key,
            "last_update": np.datetime64('now')
        }
        
        # Apply protocol-specific jitter bounds
        settings = self.PROTOCOL_SETTINGS.get(protocol_key, self.PROTOCOL_SETTINGS["Unknown"])
        if device_id in self.jitter_ctrl.device_profiles:
            profile = self.jitter_ctrl.device_profiles[device_id]
            # Clamp existing jitter to protocol bounds
            profile["jitter_pct"] = np.clip(
                profile["jitter_pct"],
                settings["min_jitter"],
                settings["max_jitter"]
            )
        
        # Apply protocol-specific power priority
        if settings.get("critical", False):
            # Critical protocols get boosted priority
            current_priority = self.power_allocator.priorities.get(device_id, 1.0)
            self.power_allocator.update_priority(device_id, current_priority * settings["power_priority"])
            
        logger.info(f"Updated device {device_id}: {protocol_key} @ {freq/1e6:.2f}MHz")
        
    def _normalize_protocol(self, protocol: str) -> str:
        """Normalize protocol name to match settings database"""
        protocol = protocol.upper()
        for key in self.PROTOCOL_SETTINGS.keys():
            if key.upper() in protocol or protocol in key.upper():
                return key
        return "Unknown"
        
    def prepare_waveforms(self, raw_waveforms: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
        """
        Apply adaptive jitter and power shaping to raw waveforms.
        
        Args:
            raw_waveforms: {device_id: waveform_samples}
            
        Returns:
            Adjusted waveforms ready for scheduling
        """
        adjusted = {}
        
        for device_id, waveform in raw_waveforms.items():
            if len(waveform) == 0:
                continue
                
            # Get protocol-specific settings
            info = self.device_info.get(device_id, {})
            protocol = info.get("protocol", "Unknown")
            settings = self.PROTOCOL_SETTINGS.get(protocol, self.PROTOCOL_SETTINGS["Unknown"])
            
            # Apply power shaping based on protocol criticality
            if settings.get("critical", False):
                # Critical protocols: boost amplitude slightly
                waveform = waveform * 1.1
                # Clip to prevent overflow
                waveform = np.clip(waveform, -1.0, 1.0)
                
            adjusted[device_id] = waveform
            
        return adjusted
        
    def schedule_waveforms(self, waveforms: Dict[str, np.ndarray]) -> list:
        """
        Protocol-aware scheduling with intelligent slot allocation.
        
        Returns:
            Schedule list compatible with WaveformScheduler output
        """
        if self.scheduler.mode == "PROTOCOL_AWARE":
            return self._schedule_protocol_aware(waveforms)
        else:
            # Fall back to standard scheduler
            weights = self.power_allocator.allocate()
            
            if self.scheduler.mode == "CROSSFADE":
                composite = self.scheduler.blend_waveforms(waveforms, weights)
                return [("composite", composite, len(composite))]
            elif self.scheduler.mode == "WRR":
                return self.scheduler.wrr_schedule(waveforms, weights)
            else:  # TDM
                return self.scheduler.tdm_schedule(waveforms, weights)
                
    def _schedule_protocol_aware(self, waveforms: Dict[str, np.ndarray]) -> list:
        """
        Advanced scheduling: prioritize critical protocols, group by frequency.
        """
        schedule = []
        
        # Group devices by criticality
        critical_devices = []
        normal_devices = []
        
        for device_id in waveforms.keys():
            info = self.device_info.get(device_id, {})
            protocol = info.get("protocol", "Unknown")
            settings = self.PROTOCOL_SETTINGS.get(protocol, self.PROTOCOL_SETTINGS["Unknown"])
            
            if settings.get("critical", False):
                critical_devices.append(device_id)
            else:
                normal_devices.append(device_id)
                
        # Critical protocols get first slots with longer duration
        weights = self.power_allocator.allocate()
        
        for dev_id in critical_devices:
            if dev_id not in waveforms:
                continue
            wf = waveforms[dev_id]
            info = self.device_info.get(dev_id, {})
            protocol = info.get("protocol", "Unknown")
            settings = self.PROTOCOL_SETTINGS.get(protocol, self.PROTOCOL_SETTINGS["Unknown"])
            
            slot_samples = int(settings["slot_duration"] * self.scheduler.sample_rate)
            repeats = int(np.ceil(slot_samples / len(wf))) if len(wf) > 0 else 1
            tiled = np.tile(wf, repeats)[:slot_samples]
            
            schedule.append((dev_id, tiled, slot_samples))
            
        # Normal protocols get remaining slots
        for dev_id in normal_devices:
            if dev_id not in waveforms:
                continue
            wf = waveforms[dev_id]
            info = self.device_info.get(dev_id, {})
            protocol = info.get("protocol", "Unknown")
            settings = self.PROTOCOL_SETTINGS.get(protocol, self.PROTOCOL_SETTINGS["Unknown"])
            
            slot_samples = int(settings["slot_duration"] * self.scheduler.sample_rate)
            repeats = int(np.ceil(slot_samples / len(wf))) if len(wf) > 0 else 1
            tiled = np.tile(wf, repeats)[:slot_samples]
            
            schedule.append((dev_id, tiled, slot_samples))
            
        return schedule
        
    def update_feedback(self, device_id: str, metrics: dict):
        """
        Update control parameters based on physical layer feedback.
        
        Args:
            metrics: {
                'snr': float,
                'success': bool,
                'latency_ms': float (optional)
            }
        """
        # Forward to jitter controller
        self.jitter_ctrl.update_feedback(device_id, metrics)
        
        # Adjust power based on SNR
        if metrics.get('snr', 0) < 10.0:
            # Low SNR: boost power priority
            current_priority = self.power_allocator.priorities.get(device_id, 1.0)
            self.power_allocator.update_priority(device_id, min(10.0, current_priority * 1.2))
            logger.debug(f"Boosted power for {device_id} due to low SNR")
        elif metrics.get('snr', 0) > 30.0 and metrics.get('success', False):
            # High SNR + success: can reduce power slightly
            current_priority = self.power_allocator.priorities.get(device_id, 1.0)
            self.power_allocator.update_priority(device_id, max(0.5, current_priority * 0.9))
            
    def get_status(self) -> dict:
        """Get optimizer status for monitoring"""
        return {
            "tracked_devices": len(self.device_info),
            "protocol_distribution": self._get_protocol_distribution(),
            "scheduler_mode": self.scheduler.mode
        }
        
    def _get_protocol_distribution(self) -> dict:
        """Count devices by protocol"""
        dist = {}
        for info in self.device_info.values():
            protocol = info.get("protocol", "Unknown")
            dist[protocol] = dist.get(protocol, 0) + 1
        return dist
