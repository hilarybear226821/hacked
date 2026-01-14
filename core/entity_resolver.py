import time
import json
import os
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field, asdict
from collections import deque
from .device_model import Device_Object, Protocol

@dataclass
class PhysicalEntity:
    entity_id: str
    device_ids: Set[str] = field(default_factory=set)
    inferred_name: str = "Unknown Entity"
    last_seen: float = field(default_factory=time.time)

    def to_dict(self):
        d = asdict(self)
        d['device_ids'] = list(self.device_ids)
        return d

class EntityResolver:
    """
    Resolves multiple wireless interfaces (Wi-Fi, BLE, Zigbee) 
    into a single physical asset using Palo Alto Networks-inspired heuristics.
    Implements SBFD (Sequence Based Failure Detection) and Temporal Correlation.
    """
    
    def __init__(self, registry, storage_path: str = "data/entities.json"):
        self.registry = registry
        self.entities: Dict[str, PhysicalEntity] = {}
        self.device_to_entity: Dict[str, str] = {}
        self.storage_path = storage_path
        # Trace buffers for SBFD-like correlation (last 20 checksums per device)
        self.checksum_traces: Dict[str, deque] = {} 
        self._load_persistence()
        
    def run_resolution_pass(self):
        devices = self.registry.get_active()
        
        # 1. Update Sequence Traces (SBFD concept)
        for device in devices:
            self._update_sequence_signature(device)
            
        # 2. Pairwise Correlation
        for i in range(len(devices)):
            for j in range(i + 1, len(devices)):
                d1, d2 = devices[i], devices[j]
                if d1.device_id == d2.device_id or d1.protocol == d2.protocol:
                    continue
                if self._should_merge(d1, d2):
                    self._merge_into_entity(d1, d2)
        
        self._save_persistence()

    def _update_sequence_signature(self, device: Device_Object):
        """Tag observations with a Fletcher Checksum proxy based on metadata sequence"""
        if device.device_id not in self.checksum_traces:
            self.checksum_traces[device.device_id] = deque(maxlen=20)
            
        # Generate a Fletcher-16 checksum from metadata payload/sequence
        data = str(device.metadata.get('decoded_payload', '')) + str(device.metadata.get('seq', ''))
        if not data: return
        checksum = self._fletcher16(data.encode())
        self.checksum_traces[device.device_id].append((time.time(), checksum))

    def _fletcher16(self, data: bytes) -> int:
        """Standard Fletcher-16 Checksum for sequence analysis"""
        sum1, sum2 = 0, 0
        for b in data:
            sum1 = (sum1 + b) % 255
            sum2 = (sum2 + sum1) % 255
        return (sum2 << 8) | sum1

    def _should_merge(self, d1: Device_Object, d2: Device_Object) -> bool:
        """Palo Alto Networks Asset Inventory Merging Heuristics"""
        score = 0
        
        # 1. MAC OUI Sibling Match (Same Vendor + close MAC suffix)
        m1 = d1.metadata.get('mac', '').replace(':', '').upper()
        m2 = d2.metadata.get('mac', '').replace(':', '').upper()
        if m1 and m2 and m1[:6] == m2[:6]:
            try:
                diff = abs(int(m1[6:], 16) - int(m2[6:], 16))
                if diff < 10: score += 65
                else: score += 40
            except: score += 40
            
        # 2. Temporal Correlation (e.g. Zigbee trigger -> Wi-Fi burst < 100ms)
        if abs(d1.last_seen - d2.last_seen) < 0.1: # 100ms window
            score += 55

        # 3. Sequence Analysis (SBFD Checksum Correlation)
        if self._correlate_checksums(d1.device_id, d2.device_id):
            score += 70

        # 4. Hostname Match
        h1 = d1.metadata.get('hostname')
        h2 = d2.metadata.get('hostname')
        if h1 and h2 and h1 == h2 and h1 != "Unknown":
            score += 90

        return score >= 75

    def _correlate_checksums(self, id1: str, id2: str) -> bool:
        """Correlation logic: match sequence checksums across protocols in tight time-windows"""
        trace1, trace2 = self.checksum_traces.get(id1), self.checksum_traces.get(id2)
        if not trace1 or not trace2 or len(trace1) < 2 or len(trace2) < 2:
            return False
        
        match_count = 0
        for t1, c1 in trace1:
            for t2, c2 in trace2:
                if abs(t1 - t2) < 0.25 and c1 == c2: # 250ms window for checksum overlap
                    match_count += 1
        return match_count >= 2

    def _merge_into_entity(self, d1: Device_Object, d2: Device_Object):
        e1_id = self.device_to_entity.get(d1.device_id)
        e2_id = self.device_to_entity.get(d2.device_id)
        
        if e1_id and e2_id:
            if e1_id == e2_id: return
            if e1_id not in self.entities or e2_id not in self.entities: return
            
            # Merge e2 into e1
            for dev_id in list(self.entities[e2_id].device_ids):
                self.entities[e1_id].device_ids.add(dev_id)
                self.device_to_entity[dev_id] = e1_id
            del self.entities[e2_id]
        elif e1_id and e1_id in self.entities:
            self.entities[e1_id].device_ids.add(d2.device_id)
            self.device_to_entity[d2.device_id] = e1_id
        elif e2_id and e2_id in self.entities:
            self.entities[e2_id].device_ids.add(d1.device_id)
            self.device_to_entity[d1.device_id] = e2_id
        else:
            new_id = f"PHYS_{int(time.time())}_{d1.device_id[-4:]}"
            self.entities[new_id] = PhysicalEntity(new_id, {d1.device_id, d2.device_id}, d1.name)
            self.device_to_entity[d1.device_id] = new_id
            self.device_to_entity[d2.device_id] = new_id

    def _load_persistence(self):
        if not os.path.exists(self.storage_path): 
            return
        
        try:
            with open(self.storage_path, 'r') as f:
                data = json.load(f)
                
            if not isinstance(data, dict):
                print(f"[Entity] Invalid persistence format: expected dict, got {type(data)}")
                return
                
            self.device_to_entity = data.get('mappings', {})
            entities_raw = data.get('entities', {})
            
            for eid, info in entities_raw.items():
                if not isinstance(info, dict): continue
                
                # Robustly handle device_ids set
                raw_ids = info.get('device_ids', [])
                if raw_ids is None: raw_ids = []
                
                self.entities[eid] = PhysicalEntity(
                    entity_id=eid,
                    device_ids=set(raw_ids),
                    inferred_name=info.get('inferred_name', "Unknown"),
                    last_seen=info.get('last_seen', time.time())
                )
            print(f"[Entity] Loaded {len(self.entities)} entities from persistence")
                
        except json.JSONDecodeError as e:
            print(f"[Entity] JSON decode error in persistence: {e}")
        except Exception as e:
            print(f"[Entity] Persistence load error: {e}")
            import traceback
            traceback.print_exc()

    def _save_persistence(self):
        try:
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
            data = {
                'mappings': self.device_to_entity,
                'entities': {eid: e.to_dict() for eid, e in self.entities.items()}
            }
            with open(self.storage_path, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            print(f"[Entity] Failed to save persistence: {e}")
