import time
import requests
import json
from typing import Dict, Any, Optional
from core import Device_Object, DeviceType

class DeepIdentityEngine:
    """
    Advanced identity inference using LLM (LLaMA 3.1 8B) and JA4 fingerprints.
    Uses Proxy Conditional Mutual Information (CMI) to weigh feature stability.
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.enabled = config.get('deep_identity', {}).get('enabled', True)
        self.api_url = config.get('deep_identity', {}).get('api_url', 'http://localhost:11434/api/generate')
        self.model = config.get('deep_identity', {}).get('model', 'llama3.1:8b')
        
        # Stability weights (Proxy CMI)
        # Higher index = more stable/reliable feature
        self.feature_reliability = {
            'oui': 0.4,
            'user_agent': 0.6,
            'ja4': 0.8,
            'hostname': 0.95,
            'open_ports': 0.7
        }
        
    def infer_identity(self, device: Device_Object) -> Dict[str, Any]:
        if not self.enabled:
            return {'inferred_type': DeviceType.UNKNOWN, 'confidence': 0.0, 'explanation': "Disabled"}

        metadata = device.metadata
        features = {
            'oui': device.vendor or "Unknown",
            'hostname': metadata.get('hostname', "Unknown"),
            'ja4': metadata.get('ja4_fingerprint', "None"),
            'user_agent': metadata.get('user_agent', "Unknown"),
            'open_ports': metadata.get('open_ports', []),
            'protocol': device.protocol.value
        }
        
        # Weigh features for the prompt
        weighed_data = self._calculate_proxy_cmi(features)
        
        prompt = self._build_cot_prompt(device, weighed_data)
        
        try:
            response = requests.post(
                self.api_url,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.1} # Low temp for consistency
                },
                timeout=12
            )
            
            if response.status_code == 200:
                result = json.loads(response.json().get('response', '{}'))
                
                # Use Chain-of-Thought result
                inferred_str = result.get('final_classification', 'UNKNOWN').upper()
                try:
                    inferred_type = DeviceType[inferred_str]
                except KeyError:
                    inferred_type = DeviceType.UNKNOWN
                    
                return {
                    'inferred_type': inferred_type,
                    'confidence': float(result.get('confidence_score', 0.0)),
                    'explanation': result.get('reasoning_path', "Chain-of-Thought Inference")
                }
            else:
                return self._fallback_logic(features)
                
        except Exception as e:
            print(f"[DeepID] Inference error: {e}")
            return self._fallback_logic(features)
            
    def _calculate_proxy_cmi(self, features: Dict) -> str:
        """Prioritize features based on reliability indices to prevent hallucinations"""
        sorted_features = sorted(features.items(), 
                                key=lambda x: self.feature_reliability.get(x[0], 0.1), 
                                reverse=True)
        
        output = "PRIMARY FEATURES (High Stability):\n"
        for k, v in sorted_features:
            weight = self.feature_reliability.get(k, 0.1)
            if weight >= 0.8:
                output += f"- {k.upper()}: {v}\n"
        
        output += "\nSECONDARY FEATURES (Low Stability/OUI):\n"
        for k, v in sorted_features:
            weight = self.feature_reliability.get(k, 0.1)
            if weight < 0.8:
                output += f"- {k.upper()}: {v}\n"
        return output

    def _build_cot_prompt(self, device: Device_Object, weighed_data: str) -> str:
        """Implementation of Stage 2 (LLM Inference) with Chain-of-Thought"""
        return f"""
        Role: Security System Identity Expert.
        Task: Identify the physical device category from wireless telemetry.
        
        INPUT DATA:
        {weighed_data}
        Observed Signal Name: {device.name}
        
        INSTRUCTIONS:
        1. Perform Chain-of-Thought (CoT) reasoning. Analyze the relationship between Hostname and OUI first.
        2. Evaluate JA4 fingerprint if present to identify the specific application layer.
        3. Prioritize stable features (Hostname/JA4) over volatile ones (OUI/MAC).
        4. Return ONLY a JSON object with:
           "reasoning_path": "your step-by-step thinking",
           "final_classification": "CAMERA, SENSOR, LOCK, ACCESS_CONTROL, CONTROL_PANEL, KEYPAD, REMOTE, SIREN, GATEWAY, or UNKNOWN",
           "confidence_score": 0.0 to 1.0
        """

    def _fallback_logic(self, features: Dict) -> Dict[str, Any]:
        oui = features.get('oui', '').lower()
        if any(v in oui for v in ['wyze', 'ring', 'hikvision', 'dahua']):
            return {'inferred_type': DeviceType.CAMERA, 'confidence': 0.65, 'explanation': "OUI match (Fallback)"}
        return {'inferred_type': DeviceType.UNKNOWN, 'confidence': 0.0, 'explanation': "Inference failed"}
