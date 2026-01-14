
import time
import random
from typing import Dict, List, Callable
from dataclasses import dataclass, field

@dataclass
class EvasionProfile:
    """Configuration for evasion techniques"""
    passive_only: bool = True  # No active probing
    max_requests_per_hour: int = 5  # Rate limiting
    randomize_timing: bool = True  # Avoid predictable patterns
    min_delay_seconds: int = 60  # Minimum delay between actions
    max_delay_seconds: int = 300  # Maximum delay
    spoof_legitimate_app: bool = True  # Mimic official mobile app
    avoid_anomalous_can: bool = True  # No suspicious CAN messages
    
class VSOCEvasion:
    """
    Evasion techniques for Vehicle Security Operations Center (VSOC) detection
    
    Modern manufacturers employ AI/LLM-based security analytics that:
    - Correlate security events into attack paths
    - Detect anomalous API transactions
    - Flag malicious CAN bus messages
    - Identify unauthorized BLE connections
    """
    
    def __init__(self, profile: EvasionProfile = None):
        self.profile = profile or EvasionProfile()
        self.request_log = []  # Timestamp of each request
        self.last_action_time =  0.0
        
    def can_perform_action(self) -> bool:
        """
        Check if an action can be performed without triggering VSOC
        
        Returns:
            True if action is safe to proceed
        """
        current_time = time.time()
        
        # Check rate limiting (requests per hour)
        hour_ago = current_time - 3600
        recent_requests = [t for t in self.request_log if t > hour_ago]
        
        if len(recent_requests) >= self.profile.max_requests_per_hour:
            time_until_next = 3600 - (current_time - recent_requests[0])
            print(f"⚠️  [VSOC Evasion] Rate limit reached. Wait {time_until_next:.0f}s")
            return False
        
        # Check minimum delay since last action
        if current_time - self.last_action_time < self.profile.min_delay_seconds:
            wait_time = self.profile.min_delay_seconds - (current_time - self.last_action_time)
            print(f"⚠️  [VSOC Evasion] Minimum delay not met. Wait {wait_time:.0f}s")
            return False
        
        return True
    
    def log_action(self):
        """Log an action for rate limiting"""
        current_time = time.time()
        self.request_log.append(current_time)
        self.last_action_time = current_time
        
        # Clean old entries (> 1 hour)
        hour_ago = current_time - 3600
        self.request_log = [t for t in self.request_log if t > hour_ago]
    
    def calculate_delay(self) -> float:
        """
        Calculate random delay to avoid pattern recognition
        
        Returns:
            Delay in seconds
        """
        if not self.profile.randomize_timing:
            return self.profile.min_delay_seconds
        
        delay = random.uniform(
            self.profile.min_delay_seconds,
            self.profile.max_delay_seconds
        )
        
        # Add jitter (±20%)
        jitter = delay * 0.2 * (random.random() - 0.5) * 2
        delay += jitter
        
        return max(delay, self.profile.min_delay_seconds)
    
    def wait_with_jitter(self):
        """Wait for a randomized period to avoid pattern detection"""
        delay = self.calculate_delay()
        print(f"[VSOC Evasion] Sleeping {delay:.1f}s to avoid detection...")
        time.sleep(delay)
    
    def passive_reconnaissance_only(self) -> bool:
        """
        Check if only passive reconnaissance is allowed
        
        Passive techniques:
        - Monitoring Bluetooth advertisements
        - Sniffing Wi-Fi beacons
        - Listening to V2X broadcasts
        - Observing telemetry data
        
        Active techniques (AVOID):
        - Sending BLE commands
        - Injecting CAN messages
        - Making API calls
        - Attempting authentication
        """
        return self.profile.passive_only
    
    def get_legitimate_app_signature(self) -> Dict:
        """
        Generate signature to mimic legitimate mobile app
        
        VSOC systems check:
        - User-Agent strings
        - API request patterns
        - Connection timing
        - Behavior sequences
        """
        signatures = {
            'Tesla': {
                'user_agent': 'Tesla/4.32.5 (iPhone; iOS 17.2.1; Scale/3.00)',
                'api_version': 'v3',
                'typical_actions': ['vehicle_data', 'wake_up', 'climate_on'],
                'request_frequency': 300,  # Seconds between requests
            },
            'Mercedes': {
                'user_agent': 'Mercedes me/6.8.0 Android/13',
                'api_version': 'v2',
                'typical_actions': ['status', 'lock', 'unlock'],
                'request_frequency': 600,
            },
            'BMW': {
                'user_agent': 'BMW Connected/5.3.0',
                'api_version': 'v4',
                'typical_actions': ['status', 'climate', 'location'],
                'request_frequency': 450,
            }
        }
        
        # Return Tesla signature as example
        return signatures['Tesla']
    
    def is_anomalous_can_message(self, arbitration_id: int, data: bytes) -> bool:
        """
        Check if CAN message would be flagged as anomalous
        
        VSOC flags:
        - Messages from unknown IDs
        - Out-of-sequence messages
        - Invalid data ranges
        - Diagnostic commands from non-service sources
        """
        # Diagnostic ID range (0x7E0 - 0x7E7)
        if 0x7E0 <= arbitration_id <= 0x7E7:
            print(f"⚠️  [VSOC] Diagnostic CAN ID {hex(arbitration_id)} may trigger alert")
            return True
        
        # Proprietary security IDs (manufacturer specific)
        security_ids = [0x750, 0x760, 0x770]  # Example Tesla security IDs
        if arbitration_id in security_ids:
            print(f"⚠️  [VSOC] Security CAN ID {hex(arbitration_id)} HIGH RISK")
            return True
        
        return False
    
    def assess_detection_risk(self, action: str, details: Dict = None) -> str:
        """
        Assess risk of VSOC detection for a given action
        
        Returns:
            Risk level: 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
        """
        risk_scores = {
            # Passive actions (LOW risk)
            'monitor_ble': 'LOW',
            'sniff_wifi': 'LOW',
            'listen_v2x': 'LOW',
            'observe_telemetry': 'LOW',
            
            # Active but normal (MEDIUM risk)
            'api_request': 'MEDIUM',
            'ble_connect': 'MEDIUM',
            'unlock_command': 'MEDIUM',
            
            # Suspicious actions (HIGH risk)
            'enroll_key': 'HIGH',
            'inject_can': 'HIGH',
            'firmware_flash': 'HIGH',
            
            # Extremely suspicious (CRITICAL risk)
            'security_bypass': 'CRITICAL',
            'persistent_backdoor': 'CRITICAL',
            'disable_telematics': 'CRITICAL',
        }
        
        risk = risk_scores.get(action, 'UNKNOWN')
        
        # Adjust based on frequency
        if details and 'frequency' in details:
            if details['frequency'] > 10:  # More than 10 times
                if risk == 'LOW':
                    risk = 'MEDIUM'
                elif risk == 'MEDIUM':
                    risk = 'HIGH'
        
        return risk
    
    def get_evasion_recommendations(self, action: str) -> List[str]:
        """
        Get specific evasion recommendations for an action
        
        Returns:
            List of recommended evasion techniques
        """
        recommendations = {
            'enroll_key': [
                "Only attempt during legitimate NFC window",
                "Mimic official app BLE protocol exactly",
                "Limit to single attempt",
                "Perform when vehicle is in motion (harder to correlate)",
                "Use at locations without surveillance cameras"
            ],
            'api_request': [
                "Match timing of legitimate mobile app",
                "Use authentic user-agent string",
                "Maintain session cookies properly",
                "Don't exceed normal request frequency"
            ],
            'inject_can': [
                "Avoid diagnostic ID ranges",
                "Match timing of existing messages",
                "Don't send burst sequences",
                "Use manufacturer-valid data formats",
                "Test on isolated vehicle first"
            ],
            'monitor_ble': [
                "Purely passive - no detection risk",
                "Can run continuously",
                "No evasion needed"
            ]
        }
        
        return recommendations.get(action, ["No specific recommendations - proceed with caution"])
    
    def create_evasion_plan(self, target_actions: List[str]) -> Dict:
        """
        Create comprehensive evasion plan for attack chain
        
        Args:
            target_actions: List of planned actions
        
        Returns:
            Evasion plan with timing, techniques, risk assessment
        """
        plan = {
            'total_estimated_time': 0.0,
            'overall_risk': 'LOW',
            'steps': []
        }
        
        max_risk = 'LOW'
        
        for i, action in enumerate(target_actions):
            risk = self.assess_detection_risk(action)
            recommendations = self.get_evasion_recommendations(action)
            delay = self.calculate_delay()
            
            step = {
                'sequence': i + 1,
                'action': action,
                'risk_level': risk,
                'recommended_delay': delay,
                'evasion_techniques': recommendations
            }
            
            plan['steps'].append(step)
            plan['total_estimated_time'] += delay
            
            # Track highest risk
            risk_levels = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']
            if risk_levels.index(risk) > risk_levels.index(max_risk):
                max_risk = risk
        
        plan['overall_risk'] = max_risk
        
        return plan

