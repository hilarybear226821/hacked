
import os
import json
import time
import threading
from typing import Dict, List, Optional
from .sdr_controller import SDRController

class SubGhzRecorder:
    """
    High-level manager for Sub-GHz Record & Replay.
    Manages file storage and metadata.
    """
    
    def __init__(self, sdr: SDRController):
        self.sdr = sdr
        self.base_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "captures", "subghz"
        )
        self.db_file = os.path.join(self.base_dir, "db.json")
        
        try:
            os.makedirs(self.base_dir, exist_ok=True)
        except OSError:
            pass # Handle in _load_db
        self._load_db()
        
    def _load_db(self):
        if not os.path.exists(self.base_dir):
            try:
                os.makedirs(self.base_dir, exist_ok=True)
            except OSError:
                 # Fallback for tests/restricted envs
                 self.base_dir = "/tmp/captures/subghz"
                 os.makedirs(self.base_dir, exist_ok=True)
        
        self.db_file = os.path.join(self.base_dir, "db.json")
        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, 'r') as f:
                    self.db = json.load(f)
            except:
                self.db = []
        else:
            self.db = []
            
    def _save_db(self):
        with open(self.db_file, 'w') as f:
            json.dump(self.db, f, indent=2)
            
    def record(self, name: str, freq_mhz: float, duration_sec: int) -> bool:
        """
        Record a signal.
        """
        filename = f"{int(time.time())}_{name.replace(' ', '_')}.cs16"
        filepath = os.path.join(self.base_dir, filename)
        
        freq_hz = freq_mhz * 1e6
        sample_rate = 2e6 # 2MHz standard for sub-ghz
        
        print(f"[Recorder] Recording '{name}' to {filename}")
        
        success = self.sdr.record_signal(
            filepath,
            duration=float(duration_sec),
            freq=freq_hz,
            sample_rate=sample_rate
        )
        
        if success:
            entry = {
                'id': str(int(time.time())),
                'name': name,
                'filename': filename,
                'filepath': filepath,
                'freq_mhz': freq_mhz,
                'sample_rate': sample_rate,
                'duration': duration_sec,
                'timestamp': time.time()
            }
            self.db.append(entry)
            self._save_db()
            return True
            
        return False
        
    def replay(self, recording_id: str) -> bool:
        """
        Replay a recorded signal by ID.
        """
        entry = next((r for r in self.db if r['id'] == recording_id), None)
        if not entry:
            print(f"[Recorder] Recording ID {recording_id} not found")
            return False
            
        filepath = entry['filepath']
        if not os.path.exists(filepath):
            # Try relative path fix if moved
            filepath = os.path.join(self.base_dir, entry['filename'])
            if not os.path.exists(filepath):
                 print(f"[Recorder] File not found: {filepath}")
                 return False
                 
        print(f"[Recorder] Replaying '{entry['name']}'...")
        
        # --- ENHANCED REPLAY LOGIC ---
        # 1. Pause Scanner (if available via callbacks or direct ref? Scanner usually holds SDR)
        # Note: In this architecture, SDRController is shared.
        # We should ensure SDR is not in RX mode.
        # SDRController.replay_signal() now handles stop_streaming(), but explicit coordination is better.
        
        # 2. Stop Jamming
        self.sdr.stop_jamming()
        
        # 3. Transmit
        return self.sdr.replay_signal(
            filepath,
            freq=entry['freq_mhz'] * 1e6,
            sample_rate=entry['sample_rate']
        )
        
    def start_panic_jamming(self, freq_mhz: float) -> bool:
        """
        Start 'Panic Mode' jamming on specific frequency.
        """
        freq_hz = freq_mhz * 1e6
        print(f"[Recorder] 🚨 PANIC JAMMING INITIATED on {freq_mhz} MHz")
        return self.sdr.start_jamming(freq_hz)
        
    def stop_panic_jamming(self):
        """Stop jamming"""
        self.sdr.stop_jamming()
        
    def list_recordings(self) -> List[Dict]:
        return self.db
        
    def delete_recording(self, recording_id: str):
        entry = next((r for r in self.db if r['id'] == recording_id), None)
        if entry:
            filepath = entry['filepath']
            if os.path.exists(filepath):
                os.remove(filepath)
            self.db.remove(entry)
            self._save_db()
