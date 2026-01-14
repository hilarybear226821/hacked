"""
Vehicle & Garage Door Remote Cloning Module
One-click workflow for capturing and cloning car fobs and garage remotes
"""

import time
import os
import json
from typing import Optional, Dict, List
from dataclasses import dataclass, asdict
import numpy as np

@dataclass
class ClonedRemote:
    """Captured remote control data"""
    id: str
    name: str
    protocol: str
    frequency_mhz: float
    raw_file: str
    decoded_data: Optional[str]
    captured_time: float
    button: Optional[str] = None
    serial: Optional[str] = None
    manufacturer: Optional[str] = None
    clone_count: int = 0  # How many times transmitted

class VehicleCloner:
    """
    One-click vehicle remote cloning system
    
    Workflow:
    1. Quick Capture (5 seconds)
    2. Auto Protocol Detection
    3. Decode Signal
    4. Save with metadata
    5. Ready for instant replay
    """
    
    def __init__(self, sdr_controller, recorder, protocol_detector):
        self.sdr = sdr_controller
        self.recorder = recorder
        self.detector = protocol_detector
        
        self.db_file = "captures/vehicle_clones.json"
        self.clones = self._load_db()
    
    def quick_clone(self, freq_mhz: float = 315.0, duration: float = 5.0) -> Dict:
        """
        One-click capture and decode
        
        Args:
            freq_mhz: Frequency to monitor
            duration: Capture duration in seconds
        
        Returns:
            dict with clone info
        """
        print(f"\n{'='*60}")
        print(f"🔑 VEHICLE CLONE MODE - {freq_mhz} MHz")
        print(f"{'='*60}")
        print(f"Press the remote button NOW!")
        print(f"Capturing for {duration} seconds...")
        print(f"{'='*60}\n")
        
        # Capture signal
        timestamp = int(time.time())
        filename = f"clone_{int(freq_mhz)}MHz_{timestamp}.cs16"
        filepath = f"captures/subghz/{filename}"
        
        try:
            # Record signal
            success = self.sdr.record_signal(
                filename=filepath,
                duration=duration,
                freq=freq_mhz * 1e6,
                sample_rate=2e6
            )
            
            if not success:
                return {
                    "success": False,
                    "error": "Failed to capture signal"
                }
            
            print(f"✅ Signal captured: {filename}")
            
            # Auto-detect protocol
            print(f"🔍 Analyzing protocol...")
            detection = self.detector.detect_from_file(filepath, sample_rate=2e6)
            
            protocol = detection.get("protocol", "Unknown")
            confidence = detection.get("confidence", 0.0)
            
            print(f"📡 Protocol: {protocol} (confidence: {confidence:.1%})")
            
            # Try to decode
            decoded_data = None
            button = None
            serial = None
            manufacturer = None
            
            if detection.get("decoder") and confidence > 0.5:
                try:
                    decoded_info = self._decode_signal(filepath, detection["decoder"], detection.get("pulses"))
                    decoded_data = decoded_info.get("data")
                    button = decoded_info.get("button")
                    serial = decoded_info.get("serial")
                    manufacturer = decoded_info.get("manufacturer")
                    
                    print(f"🔓 Decoded: {decoded_data}")
                    if button:
                        print(f"   Button: {button}")
                    if serial:
                        print(f"   Serial: {serial}")
                    if manufacturer:
                        print(f"   Manufacturer: {manufacturer}")
                        
                except Exception as e:
                    print(f"⚠️  Decode failed: {e}")
            
            # Create clone entry
            clone = ClonedRemote(
                id=str(timestamp),
                name=f"{protocol}_{int(freq_mhz)}MHz",
                protocol=protocol,
                frequency_mhz=freq_mhz,
                raw_file=filepath,
                decoded_data=decoded_data,
                captured_time=timestamp,
                button=button,
                serial=serial,
                manufacturer=manufacturer
            )
            
            # Save to database
            self.clones.append(clone)
            self._save_db()
            
            print(f"\n✅ Clone saved! ID: {clone.id}")
            print(f"   Use 'Replay Clone' button to transmit")
            
            # Add to recorder database
            if self.recorder:
                self.recorder.db.append({
                    'id': clone.id,
                    'name': clone.name,
                    'filename': filename,
                    'filepath': filepath,
                    'freq_mhz': freq_mhz,
                    'sample_rate': 2e6,
                    'duration': duration,
                    'timestamp': timestamp,
                    'protocol': protocol,
                    'decoded': decoded_data
                })
                self.recorder._save_db()
            
            return {
                "success": True,
                "clone": asdict(clone),
                "detection": detection
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def replay_clone(self, clone_id: str) -> bool:
        """
        Replay a cloned remote
        
        Args:
            clone_id: Clone ID to replay
        
        Returns:
            True if successful
        """
        clone = self.get_clone(clone_id)
        if not clone:
            print(f"❌ Clone {clone_id} not found")
            return False
        
        print(f"\n{'='*60}")
        print(f"📡 TRANSMITTING CLONE: {clone.name}")
        print(f"   Protocol: {clone.protocol}")
        print(f"   Frequency: {clone.frequency_mhz} MHz")
        if clone.button:
            print(f"   Button: {clone.button}")
        print(f"{'='*60}\n")
        
        try:
            success = self.sdr.replay_signal(
                filename=clone.raw_file,
                freq=clone.frequency_mhz * 1e6,
                sample_rate=2e6
            )
            
            if success:
                clone.clone_count += 1
                self._save_db()
                print(f"✅ Transmission complete (used {clone.clone_count}x)")
                return True
            else:
                print(f"❌ Transmission failed")
                return False
                
        except Exception as e:
            print(f"❌ Replay error: {e}")
            return False
    
    def list_clones(self) -> List[ClonedRemote]:
        """Get all cloned remotes"""
        return self.clones
    
    def get_clone(self, clone_id: str) -> Optional[ClonedRemote]:
        """Get specific clone by ID"""
        for clone in self.clones:
            if clone.id == clone_id:
                return clone
        return None
    
    def delete_clone(self, clone_id: str) -> bool:
        """Delete a clone"""
        clone = self.get_clone(clone_id)
        if not clone:
            return False
        
        # Remove from list
        self.clones = [c for c in self.clones if c.id != clone_id]
        
        # Delete file
        try:
            if os.path.exists(clone.raw_file):
                os.remove(clone.raw_file)
        except:
            pass
        
        self._save_db()
        return True
    
    def _decode_signal(self, filepath: str, decoder_class: str, pulses: List = None) -> Dict:
        """
        Decode signal using specified decoder
        
        Returns:
            dict with decoded info
        """
        # Import appropriate decoder
        module_name, class_name = decoder_class.rsplit('.', 1)
        
        if "keeloq" in module_name:
            from modules.decoders.keeloq_decoder import KeeLoqDecoder
            decoder = KeeLoqDecoder()
        elif "ev1527" in module_name:
            from modules.decoders.ev1527_decoder import EV1527Decoder
            decoder = EV1527Decoder()
        elif "princeton" in module_name:
            from modules.decoders.princeton_decoder import PrincetonDecoder
            decoder = PrincetonDecoder()
        elif "came" in module_name:
            from modules.decoders.came_decoder import CAMEDecoder
            decoder = CAMEDecoder()
        elif "nice" in module_name:
            from modules.decoders.nice_decoder import NiceDecoder
            decoder = NiceDecoder()
        else:
            raise ValueError(f"Unknown decoder: {decoder_class}")
        
        # Load and decode
        if pulses and hasattr(decoder, 'feed_pulse'):
            for level, dur in pulses:
                decoder.feed_pulse(level, dur)
        
        info = decoder.get_protocol_info() if hasattr(decoder, 'get_protocol_info') else {}
        
        return {
            "data": str(info),
            "button": info.get("button_code"),
            "serial": info.get("serial_number"),
            "manufacturer": info.get("manufacturer")
        }
    
    def export_to_flipper(self, clone_id: str, output_file: str) -> bool:
        """
        Export clone to Flipper Zero .sub format
        
        Args:
            clone_id: Clone to export
            output_file: Output .sub file path
        
        Returns:
            True if successful
        """
        clone = self.get_clone(clone_id)
        if not clone:
            return False
        
        # Flipper Zero .sub file format
        sub_content = f"""Filetype: Flipper SubGhz RAW File
Version: 1
Frequency: {int(clone.frequency_mhz * 1000000)}
Preset: FuriHalSubGhzPresetOok650Async
Protocol: RAW
"""
        
        # Would need to convert IQ to Flipper timing format
        # This is a simplified stub
        sub_content += f"# Captured with HackRF Scanner\n"
        sub_content += f"# Protocol: {clone.protocol}\n"
        if clone.decoded_data:
            sub_content += f"# Decoded: {clone.decoded_data}\n"
        
        try:
            with open(output_file, 'w') as f:
                f.write(sub_content)
            return True
        except:
            return False
    
    def _load_db(self) -> List[ClonedRemote]:
        """Load clones database"""
        if not os.path.exists(self.db_file):
            return []
        
        try:
            with open(self.db_file, 'r') as f:
                data = json.load(f)
            return [ClonedRemote(**item) for item in data]
        except:
            return []
    
    def _save_db(self):
        """Save clones database"""
        os.makedirs(os.path.dirname(self.db_file), exist_ok=True)
        
        with open(self.db_file, 'w') as f:
            data = [asdict(clone) for clone in self.clones]
            json.dump(data, f, indent=2)
    
    def get_statistics(self) -> Dict:
        """Get cloning statistics"""
        protocols = {}
        manufacturers = {}
        total_replays = 0
        
        for clone in self.clones:
            protocols[clone.protocol] = protocols.get(clone.protocol, 0) + 1
            
            if clone.manufacturer:
                manufacturers[clone.manufacturer] = manufacturers.get(clone.manufacturer, 0) + 1
            
            total_replays += clone.clone_count
        
        return {
            "total_clones": len(self.clones),
            "protocols": protocols,
            "manufacturers": manufacturers,
            "total_replays": total_replays,
            "most_cloned_protocol": max(protocols, key=protocols.get) if protocols else None
        }

