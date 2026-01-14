
from flask import Flask, render_template, jsonify, request
# Explicitly add local site-packages to path for flask_sock
import sys
import os

try:
    from flask_sock import Sock
    from flask_cors import CORS
except ImportError as e:
    print(f"Import Error: {e}")
    print("Ensure dependencies are installed: pip install flask-sock flask-cors")
    # Setup dummy objects to allow partial startup or fail gracefully
    sys.exit(1)

import threading
import time
import collections
import yaml
import json
import logging
from pathlib import Path

# Configure logging to show INFO messages (SDR, Scanner, etc.)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

# Ensure modules allow import
logger = logging.getLogger("web_server")
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# --- Modules ---
from core.device_model import DeviceRegistry
from modules.sdr_controller import SDRController, SDRState
from modules.subghz_recorder import SubGhzRecorder
from modules.events import event_bus
from modules.operations import operation_manager, OperationState
from modules.auto_rolljam import AutoRollJam
from modules.attacks.camera_jammer import CameraJammer
from modules.attacks.rfid_bruteforce import RFIDBruteForceAttack, RFIDBruteForceConfig
from modules.bruteforce_orchestrator import BruteForceOrchestrator
from modules.subghz_scanner import SubGHzScanner, ScannerEvent
from modules.subghz_decoder_manager import SubGhzDecoderManager
from modules.auto_subghz_engine import AutoSubGhzEngine
from modules.attacks.glass_break_attack import GlassBreakAttack
from modules.evil_twin import EvilTwin
from modules.vehicle_clone import VehicleCloner
from modules.vehicle.tesla_ble_exploit import TeslaBLEExploit
from modules.audio_demodulator import AudioDemodulator
from modules.decoder_arbiter import DecoderArbiter
from modules.scpe_engine import SCPEAttackController

# --- Logging Setup ---
LOG_BUFFER = collections.deque(maxlen=100)

class TeeLogger:
    def __init__(self, stream):
        self.stream = stream
        
    def write(self, message):
        self.stream.write(message)
        self.stream.flush()
        if message.strip():
             LOG_BUFFER.append(f"[{time.strftime('%H:%M:%S')}] {message.strip()}")

    def flush(self):
        self.stream.flush()

sys.stdout = TeeLogger(sys.stdout)

app = Flask(__name__, static_url_path='/static', static_folder='static')
sock = Sock(app)
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

# --- Spectrum Worker ---
from modules.spectrum_worker import SpectrumWorker

SPECTRUM_CLIENTS = set()
SPECTRUM_LOCK = threading.Lock()

def broadcast_spectrum(data):
    msg = data # already json
    with SPECTRUM_LOCK:
        dead = []
        for ws in SPECTRUM_CLIENTS:
            try:
                ws.send(msg)
            except:
                dead.append(ws)
        for d in dead:
            SPECTRUM_CLIENTS.discard(d)

spectrum_worker = SpectrumWorker(broadcast_spectrum)
spectrum_worker.start()

@sock.route('/ws/spectrum')
def ws_spectrum(ws):
    with SPECTRUM_LOCK:
        SPECTRUM_CLIENTS.add(ws)
    try:
        while True:
            ws.receive()
    except:
        pass
    finally:
        with SPECTRUM_LOCK:
            SPECTRUM_CLIENTS.discard(ws)

@app.route('/')
def index():
    return render_template('index.html')

@app.before_request
def log_request_info():
    if request.path.startswith('/api'):
        # Reduced verbosity: only log non-GET or errors if needed, or silence completely
        # print(f"[API] {request.method} {request.path} from {request.remote_addr}")
        pass

# Global State
state = {
    'sdr': None,
    'recorder': None,
    'rolljam': None,
    'camera_jammer': None,
    'bruteforce': None,
    'scanner': None,
    'auto_engine': None,
    'glass_break': None,
    'evil_twin': None,
    'vehicle_clone': None,
    'tesla_exploit': None,
    'audio': None,
    'arbiter': None,
    'rfid_bruteforce': None,
    'decoder_manager': None,
    'scpe': None,
    'initialized': False
}

init_lock = threading.RLock()

SUBGHZ_PRESETS = [
    {'id': 'car_315', 'name': 'Car Fob (US/Asia 315)', 'freq': 315.00, 'category': 'car'},
    {'id': 'car_433', 'name': 'Car Fob (EU 433.92)', 'freq': 433.92, 'category': 'car'},
    {'id': 'garage_genie', 'name': 'Garage (Genie/Chamb 315)', 'freq': 315.00, 'category': 'car'},
    {'id': 'garage_chamb_390', 'name': 'Garage (Chamb 390)', 'freq': 390.00, 'category': 'car'},
    {'id': 'garage_univ_433', 'name': 'Garage (Univ 433.92)', 'freq': 433.92, 'category': 'car'},
    {'id': 'gate_linear', 'name': 'Gate (Linear 318)', 'freq': 318.00, 'category': 'car'},
    {'id': 'weather_915', 'name': 'Weather (US 915)', 'freq': 915.00, 'category': 'iot'},
    {'id': 'zwave_us', 'name': 'Z-Wave (US 908.4)', 'freq': 908.42, 'category': 'iot'},
    {'id': 'zwave_eu', 'name': 'Z-Wave (EU 868.4)', 'freq': 868.42, 'category': 'iot'}
]

# Global state for persistent observations
OBSERVED_DEVICES = collections.OrderedDict() # Use OrderedDict for LRU behavior

def _update_internal_devices(payload):
    mac = payload.get("frame_id", "unknown_" + str(int(time.time())))
    
    # Cap size to 1000 devices (LRU eviction)
    if len(OBSERVED_DEVICES) > 1000 and mac not in OBSERVED_DEVICES:
        OBSERVED_DEVICES.popitem(last=False)
        
    OBSERVED_DEVICES[mac] = {
        "mac": mac,
        "type": payload.get("classification", "subghz"),
        "rssi": -65,
        "last_seen": time.time(),
        "protocol": payload.get("protocol"),
        "vendor": "Generic RF"
    }

def get_sdr() -> SDRController:
    with init_lock:
        if not state['sdr']:
             state['sdr'] = SDRController()
        return state['sdr']

def get_recorder() -> SubGhzRecorder:
    with init_lock:
        if not state['recorder']:
             state['recorder'] = SubGhzRecorder(get_sdr())
        return state['recorder']

def get_rolljam() -> AutoRollJam:
    with init_lock:
        if not state['rolljam']:
             state['rolljam'] = AutoRollJam(get_sdr(), get_recorder(), arbiter=get_arbiter())
        return state['rolljam']

def get_camera_jammer() -> CameraJammer:
    with init_lock:
        if state.get('camera_jammer') is None:
             sdr = get_sdr()
             state['camera_jammer'] = CameraJammer(sdr_controller=sdr)
        return state['camera_jammer']

def get_bruteforce() -> BruteForceOrchestrator:
    with init_lock:
        if state.get('bruteforce') is None:
             sdr = get_sdr()
             state['bruteforce'] = BruteForceOrchestrator(sdr)
        return state['bruteforce']

def get_rfid_bruteforce() -> RFIDBruteForceAttack:
    """Singleton RFID brute-force engine."""
    with init_lock:
        if state.get('rfid_bruteforce') is None:
            sdr = get_sdr()
            state['rfid_bruteforce'] = RFIDBruteForceAttack(sdr)
        return state['rfid_bruteforce']

def get_scanner() -> SubGHzScanner:
    with init_lock:
        if state.get('scanner') is None:
            sdr = get_sdr()
            # Basic config for scanner
            config = {
                'scan_frequencies': [315e6, 433.92e6, 868e6, 915e6],
                'sample_rate': 2e6
            }
            state['scanner'] = SubGHzScanner(sdr, config)
        return state['scanner']

def get_auto_engine():
    with init_lock:
        if not state['auto_engine']:
            state['auto_engine'] = AutoSubGhzEngine(
                get_sdr(), 
                recorder=get_recorder(),
                arbiter=get_arbiter()
            )
        return state['auto_engine']

def get_glass_break() -> GlassBreakAttack:
    with init_lock:
        if state.get('glass_break') is None:
            sdr = get_sdr()
            state['glass_break'] = GlassBreakAttack(sdr_controller=sdr)
        return state['glass_break']

def get_evil_twin() -> EvilTwin:
    with init_lock:
        if state.get('evil_twin') is None:
            state['evil_twin'] = EvilTwin()
        return state['evil_twin']

def get_vehicle_clone() -> VehicleCloner:
    with init_lock:
        if state.get('vehicle_clone') is None:
            sdr = get_sdr()
            rec = get_recorder()
            from modules.protocol_detector import ProtocolDetector
            det = ProtocolDetector()
            state['vehicle_clone'] = VehicleCloner(sdr, rec, det)
        return state['vehicle_clone']

def get_tesla_exploit() -> TeslaBLEExploit:
    with init_lock:
        if state.get('tesla_exploit') is None:
            state['tesla_exploit'] = TeslaBLEExploit(passive_only=False)
        return state['tesla_exploit']

def get_audio() -> AudioDemodulator:
    with init_lock:
        if state.get('audio') is None:
            sdr = get_sdr()
            state['audio'] = AudioDemodulator(sdr)
        return state['audio']

def get_arbiter() -> DecoderArbiter:
    with init_lock:
        if state.get('arbiter') is None:
            # Emit fused protocol events to the event bus
            def emit_proto(payload):
                event_bus.emit("protocol_observed", payload)
                _update_internal_devices(payload)
            state['arbiter'] = DecoderArbiter(emit_proto)
        return state['arbiter']

def get_decoder_manager() -> SubGhzDecoderManager:
    """Singleton Sub-GHz decoder manager (runs all protocol decoders)."""
    with init_lock:
        if state.get('decoder_manager') is None:
            # Config can be extended later (e.g. per‑protocol toggles)
            state['decoder_manager'] = SubGhzDecoderManager(config={})
        return state['decoder_manager']

def get_scpe() -> SCPEAttackController:
    """Singleton SCPE Attack Controller"""
    with init_lock:
        if state.get('scpe') is None:
            sdr = get_sdr()
            rolljam = get_rolljam()
            scpe_ctrl = SCPEAttackController(sdr, rolljam)
           
            # Wire decoder callback via arbiter emit wrapper
            arbiter = get_arbiter()
            original_emit = arbiter.emit
            
            def wrapped_emit(payload):
                # Call original emit (sends to event bus)
                original_emit(payload)
                
                # Also call SCPE decoder callback
                try:
                    logger.debug(f"Arbiter emit called with payload keys: {payload.keys()}")
                    scpe_payload = {
                        "protocol": payload.get("protocol", "Unknown"),
                        "bitstream": payload.get("raw_code", ""),
                        "frequency": payload.get("frequency", 433.92e6),
                        "raw_code": payload.get("raw_code", ""),
                        "snr": payload.get("snr", 0.0),
                        "confidence": payload.get("confidence", 0.0)
                    }
                    if scpe_payload["bitstream"]:
                        logger.info(f"SCPE ingesting: {scpe_payload['protocol']} @ {scpe_payload['frequency']/1e6:.2f}MHz")
                        scpe_ctrl.decoder_callback(scpe_payload)
                    else:
                        logger.debug(f"Skipping SCPE ingest - no bitstream in payload")
                except Exception as e:
                    logger.error(f"SCPE decoder callback error: {e}")
                    import traceback
                    traceback.print_exc()
            
            # Replace arbiter's emit method
            arbiter.emit = wrapped_emit
            
            scpe_ctrl.start()
            state['scpe'] = scpe_ctrl
            
        return state['scpe']


def ensure_scanner_suspended(func):
    """Decorator to suspend passive scanner during active SDR operations"""
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        scanner = get_scanner()
        
        # Check permissions/ownership FIRST
        sdr = get_sdr()
        # sdr is SDRController; sdr.device is HackRFDevice
        if sdr.device.state in {SDRState.TX_RUNNING, SDRState.RX_RUNNING} and scanner.controller.get_state() != ScanState.RUNNING:
             # Already busy with something else
             pass

        was_running = False
        if scanner.controller.is_running():
            print("[System] Suspending passive scanner for active operation...")
            scanner.stop()
            was_running = True
        
        try:
            return func(*args, **kwargs)
        except Exception:
            # If op failed to start, try to resume if we stopped it
             if was_running and state.get('initialized'):
                 scanner.start()
             raise
        finally:
            pass
    return wrapper

def bridge_scanner_to_arbiter():
    """Wire passive Sub-GHz scanner into decoder arbiter + asset inventory.

    Flow:
      SDR IQ → SubGHzScanner → SignalBurst → pulses
      → SubGhzDecoderManager (all protocol decoders)
      → DecoderArbiter → event_bus + OBSERVED_DEVICES
    """
    scanner = get_scanner()
    arbiter = get_arbiter()
    decoder_mgr = get_decoder_manager()

    def _normalize_protocol_name(label: str) -> str:
        """
        Map human-readable decoder names to arbiter protocol keys.
        Keeps existing keys used in DECODER_WEIGHT / MUTEX_GROUPS.
        """
        if not label:
            return "RSSI"
        lbl = label.upper()
        if "KEELOQ" in lbl:
            return "KeeLoq"
        if "EV1527" in lbl:
            return "EV1527"
        if "PRINCETON" in lbl or "PT2262" in lbl:
            return "Princeton"
        if "CAME" in lbl:
            return "CAME"
        if "NICE" in lbl and "FLOR" in lbl:
            return "NICE_FLOR"
        return label
    
    def on_signal(burst):
        # IMMEDIATE LOGGING for User Feedback
        print(f"⚡ [RAW] {burst.frequency/1e6:.2f}MHz | RSSI: {burst.snr_db:.1f}dB | Dur: {burst.duration_seconds*1000:.1f}ms")

        # Base candidate from RSSI / burst stats
        base_candidate = {
            "decoder": "ook_pulse_detector",
            "protocol": "RSSI",
            "confidence": min(burst.snr_db / 50.0, 1.0),
            "frame_id": f"burst_{int(burst.timestamp * 1000)}",
            "timestamp": burst.timestamp,
            "features": {
                "snr": burst.snr_db,
                "duration": burst.duration_seconds,
                "freq": burst.frequency
            }
        }
        
        pulses = scanner._burst_to_pulses(burst)

        # Immediate protocol guess (timing-based)
        proto_result = scanner.detector.analyze_pulses(pulses)
        if proto_result.get('confidence', 0) > 0.5:
            base_candidate["protocol"] = proto_result['protocol']
            base_candidate["confidence"] = proto_result['confidence']
            print(f"   ↳ [GUESS] {proto_result['protocol']} (Conf: {proto_result['confidence']:.2f})")
        
        # Try full decode with all protocol decoders
        decoded_any = False
        try:
            decoder_mgr.reset_decoders()
            for level, dur in pulses:
                decoder_mgr.feed_pulse(level, dur)
            decoded_results = decoder_mgr.get_results(current_rssi=burst.snr_db)
            
            for res in decoded_results:
                decoded_any = True
                proto_label = _normalize_protocol_name(res.protocol)
                frame_id = f"{proto_label}_{res.data}_{int(burst.timestamp * 1000)}"
                
                # IMMEDIATE DECODE LOG
                print(f"   ✓ [DECODED] {proto_label}: {res.data} | {getattr(res, 'desc', '')}")
                
                candidate = {
                    "decoder": "subghz_decoder_manager",
                    "protocol": proto_label,
                    "confidence": 0.9 if not getattr(res, "is_replay", False) else 0.8,
                    "frame_id": frame_id,
                    "timestamp": burst.timestamp,
                    "features": {
                        "raw_code": res.data,
                        "frequency": burst.frequency,
                        "data_hex": res.data,
                        "raw_sig": res.raw_sig,
                        "is_replay": getattr(res, "is_replay", False),
                        "rssi": res.rssi,
                        "snr": burst.snr_db,
                        "duration": burst.duration_seconds,
                        "freq": burst.frequency,
                    }
                }
                arbiter.submit(candidate)
                arbiter.finalize(frame_id)
                
                # AUTO-INGEST into SCPE Asset Inventory
                try:
                    scpe = get_scpe()
                    if scpe:
                        scpe_payload = {
                            "protocol": proto_label,
                            "bitstream": res.data,
                            "frequency": burst.frequency,
                            "raw_code": res.data,
                            "snr": burst.snr_db,
                            "confidence": candidate["confidence"]
                        }
                        scpe.decoder_callback(scpe_payload)
                except Exception as scpe_err:
                    logger.error(f"Failed to auto-ingest into SCPE: {scpe_err}")
        except Exception as e:
            print(f"[System] Decoder manager error: {e}")
        
        if not decoded_any:
            pass

    # Subscribe to the new event-based system (CRITICAL FIX)
    scanner.subscribe(ScannerEvent.SIGNAL_DETECTED, on_signal)
    
    # Legacy callback - DISABLED to prevent duplicates
    # scanner.register_callback(scanner_callback)
    
    print("[System] Scanner -> Arbiter bridge established (Event Driven)")

def bridge_cameras_to_arbiter():
    """Wires camera detections to the arbiter"""
    jammer = get_camera_jammer()
    arbiter = get_arbiter()
    
    def on_camera(cam):
        candidate = {
            "decoder": "wifi_camera_detector",
            "protocol": f"WiFi Cam ({cam.vendor})",
            "confidence": 0.95,
            "frame_id": f"cam_{cam.mac_address}",
            "timestamp": cam.timestamp,
            "device_id": cam.mac_address,
            "metadata": {
                "mac": cam.mac_address,
                "ssid": cam.ssid,
                "channel": cam.channel,
                "rssi": cam.signal_strength
            }
        }
        arbiter.submit(candidate)
        
    jammer.set_camera_callback(on_camera)
    print("[System] Camera -> Arbiter bridge established")

# --- Heartbeat Engine ---
def heartbeat_loop():
    # Lazy get SDR to avoid early blocking
    start_time = time.time()
    while True:
        try:
            sdr = get_sdr()
            # Check arbiter timeouts periodically
            with init_lock:
                if state.get('arbiter'):
                    state['arbiter'].check_timeouts()
            
            ops = []
            with operation_manager.lock:
                for op in operation_manager.active.values():
                     ops.append({
                         "id": op.id,
                         "name": op.name,
                         "state": op.state.value if hasattr(op.state, "value") else str(op.state),
                         "progress": op.progress,
                         "message": op.message,
                         "owner": op.owner
                     })
            
            # Check if any operations just finished and resume passive task
            # Check if any operations just finished and resume passive task
            if len(ops) == 0:
                 # Auto-resume scanner if no active operations are running
                 # and system is initialized
                 if state.get('initialized') and state.get('scanner'):
                     scanner = state['scanner']
                     sdr = get_sdr()
                     
                     # Only start if stopped and SDR is chemically idle
                     # Use sdr.device.state.name because get_sdr() returns Controller wrapper
                     # Allow CLOSED because we want to open it if it's currently closed
                     if not scanner.controller.is_running() and sdr.device.state.name in {"OPEN", "CONFIGURED", "IDLE", "CLOSED"}:
                         print("[Heartbeat] Auto-resuming passive scanner...")
                         scanner.start()

            ops.sort(key=lambda x: x["id"])
            
            payload = {
                "timestamp": time.time(),
                "backend_uptime_sec": time.time() - start_time,
                "sdr": sdr.status(),
                "operations": ops
            }
            # Heartbeats might be spammy, log only errors
            event_bus.emit("heartbeat", payload)
        except Exception as e:
            print(f"[Heartbeat] Error: {e}")
        time.sleep(1.0)

# ============================================================================
# 1. WebSocket Endpoint
# ============================================================================
@sock.route('/ws/events')
def ws_events(ws):
    event_bus.register(ws)
    
    try:
        # Send Initial Snapshot (MANDATORY per spec)
        sdr = get_sdr()
        snapshot = sdr.get_state_snapshot()
        
        # READ-ONLY sequence for snapshot
        seq = 0
        with event_bus.lock:
             seq = event_bus.sequence
             
        msg = {
            "event": "state_snapshot",
            "timestamp": time.time(),
            "sequence": seq,
            "payload": snapshot
        }
        ws.send(json.dumps(msg))
        
        # Keep alive / Read loop
        while True:
            # Standard blocking receive
            ws.receive() 
            
    except Exception as e:
        # print(f"WS Error: {e}")
        pass
    finally:
        try:
            event_bus.unregister(ws)
        except:
            pass

@sock.route('/ws/logs')
def ws_logs(ws):
    """Live log streaming endpoint"""
    try:
        # Initial dump
        initial = list(LOG_BUFFER)
        for log in initial:
             ws.send(json.dumps({"log": log}))
        
        last_log = initial[-1] if initial else ""
        
        while True:
            # Poll for new logs (Faster interval)
            time.sleep(0.05)
            
            current_logs = list(LOG_BUFFER)
            if not current_logs: continue
            
            try:
                # Find index of last_log
                start_idx = 0
                if last_log in current_logs:
                    start_idx = current_logs.index(last_log) + 1
                else:
                    # Buffer rolled over or gap, just send all
                    start_idx = 0
                
                if start_idx < len(current_logs):
                    for log in current_logs[start_idx:]:
                        ws.send(json.dumps({"log": log}))
                    last_log = current_logs[-1]
            except ValueError:
                # Fallback
                last_log = current_logs[-1]
                
    except Exception as e:
        pass
    finally:
        pass

# ============================================================================
# 2. Capability Discovery
# ============================================================================
@app.route('/api/capabilities')
def get_capabilities():
    return jsonify({
      "device": "HackRF One",
      "backend_version": "1.0.0",
      "supported_operations": [
        "rx_stream",
        "tx_file",
        "jam_noise",
        "record",
        "rolljam",
        "camera_jammer",
        "bruteforce",
        "scanner",
        "auto_engine",
        "glass_break",
        "evil_twin",
        "vehicle_clone",
        "audio"
      ],
      "rx": {
        "min_freq_hz": 1000000,
        "max_freq_hz": 6000000000,
        "sample_rates": [2000000, 4000000, 8000000, 10000000, 20000000],
        "formats": ["cs8"]
      },
      "tx": {
        "formats": ["cs8"],
        "max_gain_db": 47,
        "supports_repeat": True
      },
      "attacks": {
        "rolljam": {
          "description": "Rolling code exploitation for car fobs and garage openers",
          "requires_sdr": True
        },
        "camera_jammer": {
          "description": "WiFi camera jamming (2.4GHz/5GHz)",
          "requires_sdr": True,
          "bands": ["2.4GHz", "5GHz", "both"]
        },
        "bruteforce": {
          "description": "Fixed-code brute force (Nice FLO-R 12-bit)",
          "requires_sdr": True,
          "code_range": [0, 4095]
        },
        "scanner": {
          "description": "Passive Sub-GHz protocol detection and identification",
          "requires_sdr": True
        },
        "auto_engine": {
          "description": "Autonomous preset active scanning and signal capture",
          "requires_sdr": True
        },
        "glass_break": {
          "description": "Wireless glass break sensor detection and triggering",
          "requires_sdr": True
        },
        "evil_twin": {
          "description": "WiFi AP spoofing and credential harvesting",
          "requires_sdr": False
        },
        "vehicle_clone": {
          "description": "Vehicle key enrollment and cloning attacks",
          "requires_sdr": True
        },
        "audio": {
          "description": "Live AM/FM/NFM audio demodulation and streaming",
          "requires_sdr": True
        }
      }
    })

# ============================================================================
# 3. Status Endpoint (App Compatibility)
# ============================================================================
@app.route('/api/status')
def get_status():
    """Simple status check for app connectivity"""
    sdr = get_sdr()
    
    # Get current state
    snapshot = sdr.get_state_snapshot() if hasattr(sdr, 'get_state_snapshot') else {}
    
    # App expects {ok: true, data: {...}}
    return jsonify({
        "ok": True,
        "data": {
            "sdr_available": sdr.is_open if hasattr(sdr, 'is_open') else False,
            "sdr_state": snapshot.get("device_state", "UNKNOWN"),
            "frequency_mhz": snapshot.get("config", {}).get("frequency_hz", 0) / 1e6,
            "sample_rate_msps": snapshot.get("config", {}).get("sample_rate_hz", 0) / 1e6,
            "active_attacks": [op.name for op in operation_manager._active.values()]
        }
    })

# ============================================================================
# 4. Authoritative State Endpoint
# ============================================================================
@app.route('/api/state')
def get_state():
    sdr = get_sdr()
    return jsonify(sdr.get_state_snapshot())

# ============================================================================
# 5. Command Endpoints
# ============================================================================

# 5.1 Open/Close
@app.route('/api/device/open', methods=['POST'])
def device_open():
    sdr = get_sdr()
    if sdr.open():
        return jsonify({"status": "ok"})
    else:
        return jsonify({"code": "DEVICE_NOT_FOUND", "message": "Failed to open HackRF"}), 500

@app.route('/api/device/close', methods=['POST'])
def device_close():
    sdr = get_sdr()
    sdr.close()
    return jsonify({"status": "ok"})

# 5.2 Configure
@app.route('/api/device/configure', methods=['POST'])
def device_configure():
    sdr = get_sdr()
    try:
        data = request.json
        # Map JSON to config params
        params = {
            "frequency_hz": data.get("frequency_hz"),
            "sample_rate_hz": data.get("sample_rate_hz"),
            "lna_gain_db": 40,  # LNA Gain (0-40 dB, steps of 8)
            "vga_gain_db": 62,  # VGA Gain (0-62 dB, steps of 2)
            "amp_enabled": data.get("amp_enabled", True)
        }
        sdr.configure(params)
        return jsonify({"status": "configured"})
    except ValueError as e:
        return jsonify({"code": "CONFIG_INVALID", "message": str(e)}), 400
    except RuntimeError as e:
         return jsonify({"code": "INVALID_STATE", "message": str(e)}), 409
    except Exception as e:
         return jsonify({"code": "INTERNAL_ERROR", "message": str(e)}), 500

# 5.3 RX Streaming
@app.route('/api/rx/start', methods=['POST'])
@ensure_scanner_suspended
def rx_start():
    sdr = get_sdr()
    data = request.json
    fmt = data.get("format", "cs8")
    
    # Define dummy callback (or link to recorder/websocket later)
    def dummy_cb(samples):
        pass 
        
    try:
        # returns {"status": "started", "operation_id": ...}
        # SDRController.start_rx now takes requester.
        # We can pass remote_addr or just "api"
        requester = f"api:{request.remote_addr}"
        result = sdr.start_rx(dummy_cb, requester=requester)
        return jsonify(result)
    except RuntimeError as e:
         return jsonify({"code": "INVALID_STATE", "message": str(e)}), 409
    except Exception as e:
         return jsonify({"code": "INTERNAL_ERROR", "message": str(e)}), 500

@app.route('/api/rx/stop', methods=['POST'])
def rx_stop():
    sdr = get_sdr()
    try:
        requester = f"api:{request.remote_addr}"
        sdr.stop_rx(requester=requester)
        return jsonify({"status": "stopped"})
    except PermissionError as e:
         return jsonify({"code": "PERMISSION_DENIED", "message": str(e)}), 403

# 5.4 TX / Attacks
@app.route('/api/tx/start', methods=['POST'])
@ensure_scanner_suspended
def tx_start():
    sdr = get_sdr()
    data = request.json
    # Mode switch
    mode = data.get("mode", "tx_file")
    filepath = data.get("filepath", "/tmp/signal.cs8")
    repeat = data.get("repeat", False)
    
    requester = f"api:{request.remote_addr}"
    
    try:
        if mode == "jam_noise":
             # Use the helper
             # Note: current_config might be None if not configured.
             # start_jamming sets freq.
             result = sdr.start_jamming(sdr.current_config.frequency_hz if sdr.current_config else 433e6, requester=requester)
        else:
             result = sdr.start_tx(Path(filepath), repeat=repeat, mode=mode, requester=requester)
             
        # Merge mode into result for clarity
        if isinstance(result, dict):
             result["mode"] = mode
        return jsonify(result)

    except RuntimeError as e:
         return jsonify({"code": "INVALID_STATE", "message": str(e)}), 409
    except Exception as e:
         return jsonify({"code": "INTERNAL_ERROR", "message": str(e)}), 500

@app.route('/api/attack/stop', methods=['POST'])
def attack_stop():
    sdr = get_sdr()
    data = request.json
    op = data.get("operation")
    op_id = data.get("operation_id")
    
    requester = f"api:{request.remote_addr}"
    
    try:
        sdr.stop(requester=requester, operation_id=op_id)
        # Also clean up rolljam if generic stop called?
        # Ideally user calls /rolljam/stop, but for safety:
        # If op_id provided, manager handles.
        return jsonify({"status": "stopped", "operation": op, "operation_id": op_id})
    except PermissionError:
         return jsonify({"code": "PERMISSION_DENIED"}), 403

# 5.5 RollJam
@app.route('/api/attack/rolljam/start', methods=['POST'])
@ensure_scanner_suspended
def rolljam_start():
    data = request.json
    freq = data.get("frequency_hz", 433920000)
    
    rj = get_rolljam()
    sdr = get_sdr()
    
    if rj.running:
         return jsonify({"code": "BUSY", "message": "RollJam already running"}), 409

    owner = f"api:{request.remote_addr}"
    op = operation_manager.create("rolljam", owner=owner)
    
    try:
        rj.target_freq = freq
        
        # SMART HOPPING: Add common variations
        freqs = [freq]
        
        # Common 315 variations
        if 314e6 <= freq <= 316e6:
            # Add Drifted: 315.0, 314.9, 315.1, 318.0 (Linear), 310.0 (Old Linear), 390 (Chamberlain) - wait 390 is far
            # Just stick to "slightly off" and common neighbors
            freqs = [315.0e6, 314.85e6, 315.15e6, 318.0e6, 310.0e6]
            print(f"[System] Smart Hopping Enabled: {freqs}")
            
        elif 433e6 <= freq <= 434e6:
             freqs = [433.92e6, 433.075e6, 434.42e6]
             
        rj.frequencies = freqs
        
        event_bus.emit("operation_started", {"id": op.id, "name": "rolljam"})
        op.state = OperationState.RUNNING
        
        rj.start()
        
        return jsonify({"status": "started", "operation_id": op.id})
    except Exception as e:
        op.state = OperationState.FAILED
        operation_manager.remove(op.id)
        return jsonify({"code": "INTERNAL_ERROR", "message": str(e)}), 500

@app.route('/api/attack/rolljam/stop', methods=['POST'])
def rolljam_stop():
    rj = get_rolljam()
    
    if rj.running:
        rj.stop()
        
    # Ensure op is removed
    op = operation_manager.get_running_by_name("rolljam")
    if op:
        op.state = OperationState.ABORTED
        operation_manager.remove(op.id)
        
    return jsonify({"status": "stopped"})

# 5.6 Camera Jammer
@app.route('/api/attack/camera_jammer/start', methods=['POST'])
@ensure_scanner_suspended
def camera_jammer_start():
    data = request.json
    band = data.get("band", "2.4GHz")  # "2.4GHz", "5GHz", or "both"
    channels = data.get("channels")  # Optional list of specific channels
    sweep = data.get("sweep", False)
    timeout = data.get("timeout", 300)  # Default 5 min safety timeout
    
    jammer = get_camera_jammer()
    
    if jammer.is_jamming():
        return jsonify({"code": "BUSY", "message": "Camera jammer already running"}), 409
    
    owner = f"api:{request.remote_addr}"
    op = operation_manager.create("camera_jammer", owner=owner)
    
    try:
        event_bus.emit("operation_started", {"id": op.id, "name": "camera_jammer"})
        op.state = OperationState.RUNNING
        
        # Start jamming in background thread
        threading.Thread(
            target=jammer.start_jamming,
            args=(band, channels, sweep, timeout),
            daemon=True
        ).start()
        
        return jsonify({"status": "started", "operation_id": op.id, "band": band})
    except Exception as e:
        op.state = OperationState.FAILED
        operation_manager.remove(op.id)
        return jsonify({"code": "INTERNAL_ERROR", "message": str(e)}), 500

@app.route('/api/attack/camera_jammer/stop', methods=['POST'])
def camera_jammer_stop():
    jammer = get_camera_jammer()
    jammer.stop_jamming()
    
    op = operation_manager.get_running_by_name("camera_jammer")
    if op:
        op.state = OperationState.COMPLETED
        event_bus.emit("operation_completed", {"id": op.id})
        operation_manager.remove(op.id)
        
    return jsonify({"status": "stopped"})

@app.route('/api/attack/camera_jammer/detect', methods=['POST'])
def camera_jammer_detect():
    """Start camera detection scan"""
    data = request.json
    duration = data.get("duration", 30)
    channel = data.get("channel")
    
    jammer = get_camera_jammer()
    
    try:
        threading.Thread(
            target=jammer.start_camera_detection,
            args=(duration, channel),
            daemon=True
        ).start()
        
        return jsonify({"status": "scanning", "duration": duration})
    except Exception as e:
        return jsonify({"code": "INTERNAL_ERROR", "message": str(e)}), 500

@app.route('/api/attack/camera_jammer/cameras', methods=['GET'])
def camera_jammer_get_cameras():
    """Get list of detected cameras"""
    jammer = get_camera_jammer()
    cameras = jammer.get_detected_cameras()
    
    return jsonify({
        "cameras": [
            {
                "mac": cam.mac_address,
                "ssid": cam.ssid,
                "vendor": cam.vendor,
                "channel": cam.channel,
                "signal": cam.signal_strength,
                "type": cam.device_type
            }
            for cam in cameras
        ]
    })

# 5.7 Brute Force
@app.route('/api/attack/bruteforce/start', methods=['POST'])
def bruteforce_start():
    data = request.json
    start_code = data.get("start_code", 0)
    end_code = data.get("end_code", 4095)
    
    bf = get_bruteforce()
    
    if bf.is_running:
        return jsonify({"code": "BUSY", "message": "Brute force already running"}), 409
    
    owner = f"api:{request.remote_addr}"
    op = operation_manager.create("bruteforce", owner=owner)
    
    try:
        event_bus.emit("operation_started", {"id": op.id, "name": "bruteforce"})
        op.state = OperationState.RUNNING
        
        # Start brute force in background thread
        threading.Thread(
            target=bf.start_attack,
            args=(start_code, end_code),
            daemon=True
        ).start()
        
        return jsonify({
            "status": "started",
            "operation_id": op.id,
            "range": {"start": start_code, "end": end_code}
        })
    except Exception as e:
        op.state = OperationState.FAILED
        operation_manager.remove(op.id)
        return jsonify({"code": "INTERNAL_ERROR", "message": str(e)}), 500


@app.route('/api/attack/rfid_bruteforce/start', methods=['POST'])
@ensure_scanner_suspended
def rfid_bruteforce_start():
    """
    Start RFID brute-force attack using HackRF.
    Body (JSON, all optional):
      - start_id, end_id
      - carrier_hz (default 13.56e6)
      - sample_rate
    """
    data = request.json or {}
    engine = get_rfid_bruteforce()

    if engine.is_running:
        return jsonify({"code": "BUSY", "message": "RFID brute-force already running"}), 409

    # Update configuration
    cfg = engine.config
    cfg.start_id = int(data.get("start_id", cfg.start_id))
    cfg.end_id = int(data.get("end_id", cfg.end_id))
    cfg.carrier_hz = float(data.get("carrier_hz", cfg.carrier_hz))
    cfg.sample_rate = float(data.get("sample_rate", cfg.sample_rate))
    cfg.protocol = str(data.get("protocol", cfg.protocol))

    owner = f"api:{request.remote_addr}"
    op = operation_manager.create("rfid_bruteforce", owner=owner)

    try:
        event_bus.emit("operation_started", {"id": op.id, "name": "rfid_bruteforce"})
        op.state = OperationState.RUNNING

        # Run in background thread
        threading.Thread(target=engine.run, daemon=True).start()

        return jsonify({
            "status": "started",
            "operation_id": op.id,
            "start_id": cfg.start_id,
            "end_id": cfg.end_id,
            "carrier_hz": cfg.carrier_hz
        })
    except Exception as e:
        op.state = OperationState.FAILED
        operation_manager.remove(op.id)
        return jsonify({"code": "INTERNAL_ERROR", "message": str(e)}), 500


@app.route('/api/attack/rfid_bruteforce/stop', methods=['POST'])
def rfid_bruteforce_stop():
    """Stop RFID brute-force attack."""
    engine = get_rfid_bruteforce()
    engine.stop()

    op = operation_manager.get_running_by_name("rfid_bruteforce")
    if op:
        op.state = OperationState.COMPLETED
        event_bus.emit("operation_completed", {"id": op.id})
        operation_manager.remove(op.id)

    return jsonify({"status": "stopped"})


@app.route('/api/attack/rfid_bruteforce/status', methods=['GET'])
def rfid_bruteforce_status():
    """Get current status/progress of RFID brute-force attack."""
    engine = get_rfid_bruteforce()
    cfg = engine.config
    return jsonify({
        "running": engine.is_running,
        "current_id": engine.current_id,
        "start_id": cfg.start_id,
        "end_id": cfg.end_id,
        "protocol": cfg.protocol,
        "carrier_hz": cfg.carrier_hz
    })

@app.route('/api/attack/bruteforce/stop', methods=['POST'])
def bruteforce_stop():
    bf = get_bruteforce()
    bf.stop()
    
    op = operation_manager.get_running_by_name("bruteforce")
    if op:
        op.state = OperationState.ABORTED
        event_bus.emit("operation_aborted", {"id": op.id, "reason": "user_stop"})
        operation_manager.remove(op.id)
        
    return jsonify({"status": "stopped"})

# 5.8 Sub-GHz Scanner (Passive)
@app.route('/api/subghz/scanner/start', methods=['POST'])
def scanner_start():
    data = request.json or {}
    freqs = data.get("frequencies", [315e6, 433.92e6])
    
    scanner = get_scanner()
    if scanner.controller.is_running():
        return jsonify({"code": "BUSY", "message": "Scanner already running"}), 409
        
    owner = f"api:{request.remote_addr}"
    op = operation_manager.create("scanner", owner=owner)
    
    try:
        scanner.frequencies = freqs
        event_bus.emit("operation_started", {"id": op.id, "name": "scanner"})
        op.state = OperationState.RUNNING
        
        scanner.start()
        return jsonify({"status": "started", "operation_id": op.id})
    except Exception as e:
        op.state = OperationState.FAILED
        operation_manager.remove(op.id)
        return jsonify({"code": "INTERNAL_ERROR", "message": str(e)}), 500

@app.route('/api/subghz/scanner/stop', methods=['POST'])
def scanner_stop():
    scanner = get_scanner()
    scanner.stop()
    
    op = operation_manager.get_running_by_name("scanner")
    if op:
        op.state = OperationState.COMPLETED
        event_bus.emit("operation_completed", {"id": op.id})
        operation_manager.remove(op.id)
        
    return jsonify({"status": "stopped"})

# 5.9 Sub-GHz Active Engine (Preset Scanning)
@app.route('/api/subghz/presets', methods=['GET'])
def get_presets():
    return jsonify(SUBGHZ_PRESETS)

@app.route('/api/subghz/auto/start', methods=['POST'])
@ensure_scanner_suspended
def auto_engine_start():
    data = request.json or {}
    freq_mhz = data.get("frequency_mhz")
    
    # The mobile app "Auto RollJam" hits this endpoint.
    # If freq_mhz is provided, we use the specialized AutoRollJam engine.
    if freq_mhz:
        engine = get_rolljam()
        engine.target_freq = float(freq_mhz) * 1e6
        op_name = "rolljam"
    else:
        # General cycling auto-engine
        engine = get_auto_engine()
        op_name = "auto_engine"
        
    if engine.running:
        return jsonify({"code": "BUSY", "message": f"{op_name.capitalize()} engine already running"}), 409
        
    owner = f"api:{request.remote_addr}"
    op = operation_manager.create(op_name, owner=owner)
    
    try:
        event_bus.emit("operation_started", {"id": op.id, "name": op_name})
        op.state = OperationState.RUNNING
        
        # Non-blocking start
        engine.start()
        return jsonify({"status": "started", "operation_id": op.id, "mode": op_name})
    except Exception as e:
        op.state = OperationState.FAILED
        operation_manager.remove(op.id)
        return jsonify({"code": "INTERNAL_ERROR", "message": str(e)}), 500

@app.route('/api/subghz/auto/stop', methods=['POST'])
def auto_engine_stop():
    # Stop both possible engines for safety
    get_auto_engine().stop()
    get_rolljam().stop()
    
    # Cleanup operations
    names = ["auto_engine", "rolljam"]
    stopped = []
    for name in names:
        op = operation_manager.get_running_by_name(name)
        if op:
            op.state = OperationState.COMPLETED
            event_bus.emit("operation_completed", {"id": op.id})
            operation_manager.remove(op.id)
            stopped.append(name)
        
    return jsonify({"status": "stopped", "engines": stopped})

# 5.10 Glass Break Attack
@app.route('/api/attack/glass_break/start', methods=['POST'])
def glass_break_start():
    data = request.json or {}
    mode = data.get("mode", "detect") # "detect" or "trigger"
    
    gb = get_glass_break()
    owner = f"api:{request.remote_addr}"
    op = operation_manager.create("glass_break", owner=owner)
    
    try:
        event_bus.emit("operation_started", {"id": op.id, "name": "glass_break"})
        op.state = OperationState.RUNNING
        
        if mode == "detect":
            threading.Thread(target=gb.start_detection, daemon=True).start()
        elif mode == "trigger":
            freq = data.get("frequency_mhz", 433.92)
            pattern = data.get("pattern", "standard")
            threading.Thread(target=gb.trigger_synthetic, args=(freq, pattern), daemon=True).start()
            
        return jsonify({"status": "started", "operation_id": op.id, "mode": mode})
    except Exception as e:
        op.state = OperationState.FAILED
        operation_manager.remove(op.id)
        return jsonify({"code": "INTERNAL_ERROR", "message": str(e)}), 500

@app.route('/api/attack/glass_break/stop', methods=['POST'])
def glass_break_stop():
    gb = get_glass_break()
    gb.stop_detection()
    
    op = operation_manager.get_running_by_name("glass_break")
    if op:
        op.state = OperationState.COMPLETED
        event_bus.emit("operation_completed", {"id": op.id})
        operation_manager.remove(op.id)
        
    return jsonify({"status": "stopped"})

# 5.11 Evil Twin
@app.route('/api/attack/evil_twin/start', methods=['POST'])
def evil_twin_start():
    data = request.json or {}
    ssid = data.get("ssid", "Free_Public_WiFi")
    interface = data.get("interface", "wlan0mon")
    karma = data.get("karma", False)
    channel = int(data.get("channel", 6))
    
    et = get_evil_twin()
    owner = f"api:{request.remote_addr}"
    op = operation_manager.create("evil_twin", owner=owner)
    
    try:
        if et.start(ssid, channel=channel, interface=interface):
            event_bus.emit("operation_started", {"id": op.id, "name": "evil_twin"})
            op.state = OperationState.RUNNING
            return jsonify({"status": "started", "operation_id": op.id, "ssid": ssid})
        else:
            raise RuntimeError("Failed to start Evil Twin stack")
    except Exception as e:
        op.state = OperationState.FAILED
        operation_manager.remove(op.id)
        return jsonify({"code": "INTERNAL_ERROR", "message": str(e)}), 500

@app.route('/api/attack/evil_twin/stop', methods=['POST'])
def evil_twin_stop():
    et = get_evil_twin()
    et.stop()
    
    op = operation_manager.get_running_by_name("evil_twin")
    if op:
        op.state = OperationState.COMPLETED
        event_bus.emit("operation_completed", {"id": op.id})
        operation_manager.remove(op.id)
        
    return jsonify({"status": "stopped"})

# 5.12 Vehicle Clone
@app.route('/api/attack/vehicle/clone', methods=['POST'])
@ensure_scanner_suspended
def vehicle_clone_start():
    data = request.json or {}
    target = data.get("target", "tesla")
    
    vc = get_vehicle_clone()
    owner = f"api:{request.remote_addr}"
    op = operation_manager.create("vehicle_clone", owner=owner)
    
    try:
        event_bus.emit("operation_started", {"id": op.id, "name": "vehicle_clone"})
        op.state = OperationState.RUNNING
        
        # This usually involves a sequence, we'll run it in a thread
        def run_clone():
            try:
                if target == "tesla":
                    # Use the dedicated Tesla BLE exploit module
                    te = get_tesla_exploit()
                    # We need a target vehicle, for now we scan and take the first one
                    # or monitor for a window. This is a stub for the complex flow.
                    teslas = te.scan_for_teslas(duration=10.0)
                    if teslas:
                        event_bus.emit("tesla_detected", {"vin": teslas[0].vin})
                        success = te.attempt_key_enrollment(teslas[0])
                        if success:
                            event_bus.emit("tesla_enrolled", {"vin": teslas[0].vin})
                else:
                    # General Sub-GHz fob cloning
                    vc = get_vehicle_clone()
                    vc.quick_clone()
                op.state = OperationState.COMPLETED
                event_bus.emit("operation_completed", {"id": op.id})
            except Exception as e:
                op.state = OperationState.FAILED
                event_bus.emit("operation_failed", {"id": op.id, "error": str(e)})
            finally:
                operation_manager.remove(op.id)

        threading.Thread(target=run_clone, daemon=True).start()
        return jsonify({"status": "started", "operation_id": op.id})
    except Exception as e:
        op.state = OperationState.FAILED
        operation_manager.remove(op.id)
        return jsonify({"code": "INTERNAL_ERROR", "message": str(e)}), 500

# 5.13 Audio Demodulation
@app.route('/api/audio/start', methods=['POST'])
@ensure_scanner_suspended
def audio_start():
    data = request.json or {}
    freq = data.get("frequency_hz", 100.1e6)
    mode = data.get("mode", "FM")
    
    audio = get_audio()
    owner = f"api:{request.remote_addr}"
    op = operation_manager.create("audio_stream", owner=owner)
    
    try:
        event_bus.emit("operation_started", {"id": op.id, "name": "audio_stream"})
        op.state = OperationState.RUNNING
        
        audio.start_streaming(freq, mode)
        return jsonify({"status": "started", "operation_id": op.id})
    except Exception as e:
        op.state = OperationState.FAILED
        operation_manager.remove(op.id)
        return jsonify({"code": "INTERNAL_ERROR", "message": str(e)}), 500

@app.route('/api/audio/stop', methods=['POST'])
def audio_stop():
    audio = get_audio()
    audio.stop()
    
    op = operation_manager.get_running_by_name("audio_stream")
    if op:
        op.state = OperationState.COMPLETED
        event_bus.emit("operation_completed", {"id": op.id})
        operation_manager.remove(op.id)
        
    return jsonify({"status": "stopped"})

@app.route('/api/recordings', methods=['GET'])
def get_recordings():
    recorder = get_recorder()
    recs = recorder.list_recordings()
    # Map to mobile app expected format {freq: ...}
    for r in recs:
        if 'freq_mhz' in r and 'freq' not in r:
            r['freq'] = r['freq_mhz']
    return jsonify(recs)

@app.route('/api/recordings/delete', methods=['DELETE', 'POST'])
def delete_record():
    data = request.json or {}
    rid = data.get("id")
    if rid:
        get_recorder().delete_recording(rid)
        return jsonify({"status": "deleted"})
    return jsonify({"error": "No ID"}), 400

@app.route('/api/devices', methods=['GET'])
def get_devices():
    # Merge subghz observations and camera jammer results
    jammer = get_camera_jammer()
    cameras = jammer.get_detected_cameras()
    
    combined = list(OBSERVED_DEVICES.values())
    for cam in cameras:
        combined.append({
            "mac": getattr(cam, 'mac_address', '??:??'),
            "ssid": getattr(cam, 'ssid', 'HIDDEN'),
            "vendor": getattr(cam, 'vendor', 'Unknown'),
            "type": "camera",
            "rssi": getattr(cam, 'signal_strength', -80),
            "last_seen": time.time()
        })
    return jsonify(combined)

# ==================== SCPE API ENDPOINTS ====================
@app.route('/api/scpe/status', methods=['GET'])
def scpe_status():
    """Get SCPE engine status and device list"""
    try:
        scpe = get_scpe()
        status = scpe.get_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/scpe/add_target', methods=['POST'])
def scpe_add_target():
    """Enlist a device for continuous SCPE attack"""
    data = request.json or {}
    device_id = data.get("device_id")
    priority = float(data.get("priority", 1.0))
    
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
        
    try:
        scpe = get_scpe()
        scpe.add_target(device_id, priority)
        return jsonify({"status": "target_added", "device_id": device_id, "priority": priority})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/scpe/remove_target', methods=['POST'])
def scpe_remove_target():
    """Remove a device from active attack list"""
    data = request.json or {}
    device_id = data.get("device_id")
    
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
        
    try:
        scpe = get_scpe()
        scpe.remove_target(device_id)
        return jsonify({"status": "target_removed", "device_id": device_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/scpe/trigger_replay', methods=['POST'])
def scpe_trigger_replay():
    """Manually trigger a replay attack on a specific device"""
    data = request.json or {}
    device_id = data.get("device_id")
    mode = data.get("mode", "SCPE_THICK")
    duration = float(data.get("duration", 1.0))
    
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
        
    try:
        scpe = get_scpe()
        success = scpe.trigger_replay(device_id, mode, duration)
        return jsonify({"status": "success" if success else "failed", "device_id": device_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/scpe/loop/start', methods=['POST'])
def scpe_loop_start():
    """Start the background multi-target attack loop"""
    try:
        scpe = get_scpe()
        scpe.start_background_loop()
        return jsonify({"status": "loop_started"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/scpe/loop/stop', methods=['POST'])
def scpe_loop_stop():
    """Stop the background attack loop"""
    try:
        scpe = get_scpe()
        scpe.stop_background_loop()
        return jsonify({"status": "loop_stopped"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/scpe/configure', methods=['POST'])
def scpe_configure():
    """Configure SCPE monitoring frequency and mode"""
    data = request.json or {}
    freq_mhz = data.get("frequency_mhz")
    mode = data.get("mode")
    
    try:
        scpe = get_scpe()
        freq_hz = float(freq_mhz) * 1e6 if freq_mhz else None
        scpe.set_monitor_config(freq_hz=freq_hz, mode=mode)
        
        # Sync scanner to stay on this frequency if provided
        if freq_hz:
            scanner = get_scanner()
            # Lock scanner to this frequency to prevent hopping conflict
            with scanner.lock:
                scanner.scan_frequencies = [freq_hz]
                scanner.freq_idx = 0
                print(f"[System] SCPE Sync: Scanner locked to {freq_mhz} MHz")
            
        return jsonify({
            "status": "configured",
            "frequency_mhz": freq_mhz,
            "mode": mode
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============================================================

@app.route('/api/subghz/replay', methods=['POST'])
@ensure_scanner_suspended
def subghz_replay():
    data = request.json or {}
    rid = data.get("id")
    if not rid:
        return jsonify({"error": "Missing ID"}), 400
    
    recorder = get_recorder()
    if recorder.replay(rid):
        return jsonify({"status": "replayed"})
    return jsonify({"error": "Replay failed"}), 500
@app.route('/api/subghz/live', methods=['GET'])
def subghz_live():
    """Live feed from scanner"""
    scanner = get_scanner()
    # In a real app, this might be a WebSocket stream, but we can return
    # the last N signals for simple compatibility.
    return jsonify({
        "signals": [], 
        "active": scanner.controller.is_running(),
        "frequency": scanner.current_frequency
    })


@app.route('/api/signal/psd', methods=['GET'])
def signal_psd():
    """
    Capture a short IQ snapshot and return a simple power spectrum
    for live signal graphing.

    Query params:
      - frequency_hz (optional, keep current if omitted)
      - sample_rate_hz (optional, default 2e6)
    """
    sdr = get_sdr()
    freq = float(request.args.get("frequency_hz", 0)) or None
    sample_rate = float(request.args.get("sample_rate_hz", 2e6))

    try:
        # Optionally retune SDR
        if freq is not None:
            sdr.set_frequency(freq)

        # Capture short snapshot (e.g., 2048 samples)
        num_samples = 4096
        samples = sdr.capture_samples(num_samples=num_samples, timeout=1.0)
        if samples is None or len(samples) == 0:
            return jsonify({"error": "no_samples"}), 503

        # Compute simple PSD (magnitude squared)
        import numpy as np
        samples = samples - np.mean(samples)
        window = np.hanning(len(samples))
        spec = np.fft.fftshift(np.fft.fft(samples * window))
        power = 20 * np.log10(np.abs(spec) + 1e-9)
        freqs = np.fft.fftshift(np.fft.fftfreq(len(samples), d=1.0 / sample_rate))

        # Downsample for lighter payload (e.g., 256 points)
        stride = max(1, len(freqs) // 256)
        freqs_ds = freqs[::stride]
        power_ds = power[::stride]

        return jsonify({
            "center_freq_hz": sdr.current_config.frequency_hz if sdr.current_config else freq,
            "sample_rate_hz": sample_rate,
            "points": [
                [float(f), float(p)] for f, p in zip(freqs_ds, power_ds)
            ]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@sock.route('/ws/signal/psd')
def ws_signal_psd(ws):
    """
    WebSocket stream of live PSD snapshots for real-time signal graphs.

    Client can optionally send a single JSON message with:
      {"frequency_hz": ..., "sample_rate_hz": ...}
    Otherwise, current SDR tuning and 2e6 sample rate are used.
    """
    import json as _json
    import numpy as _np

    sdr = get_sdr()
    # Optional initial config from first message (non-blocking try)
    try:
        msg = ws.receive(timeout=0.1)
        if msg:
            try:
                cfg = _json.loads(msg)
                freq = cfg.get("frequency_hz")
                sample_rate = cfg.get("sample_rate_hz", 2e6)
                if freq:
                    sdr.set_frequency(float(freq))
            except Exception:
                sample_rate = 2e6
        else:
            sample_rate = 2e6
    except Exception:
        sample_rate = 2e6

    try:
        while True:
            try:
                num_samples = 4096
                samples = sdr.capture_samples(num_samples=num_samples, timeout=1.0)
                if samples is None or len(samples) == 0:
                    ws.send(_json.dumps({"error": "no_samples"}))
                    time.sleep(0.5)
                    continue

                samples = samples - _np.mean(samples)
                window = _np.hanning(len(samples))
                spec = _np.fft.fftshift(_np.fft.fft(samples * window))
                power = 20 * _np.log10(_np.abs(spec) + 1e-9)
                freqs = _np.fft.fftshift(_np.fft.fftfreq(len(samples), d=1.0 / sample_rate))

                stride = max(1, len(freqs) // 256)
                freqs_ds = freqs[::stride]
                power_ds = power[::stride]

                payload = {
                    "center_freq_hz": sdr.current_config.frequency_hz if sdr.current_config else None,
                    "sample_rate_hz": sample_rate,
                    "points": [
                        [float(f), float(p)] for f, p in zip(freqs_ds, power_ds)
                    ]
                }
                ws.send(_json.dumps(payload))
                time.sleep(0.5)
            except Exception as e:
                ws.send(_json.dumps({"error": str(e)}))
                time.sleep(1.0)
    except Exception:
        # Client disconnected or error; just exit loop
        pass

@app.route('/api/terminal/session', methods=['POST'])
def terminal_session():
    """Stub: Terminal session"""
    return jsonify({"session_id": "stub", "status": "not_implemented"})

@app.route('/api/terminal/input', methods=['POST'])
def terminal_input():
    """Stub: Terminal input"""
    return jsonify({"status": "not_implemented"})

@app.route('/api/terminal/output', methods=['GET'])
def terminal_output():
    """Stub: Terminal output"""
    return jsonify({"output": "", "status": "not_implemented"})

@app.route('/api/stop_all', methods=['POST'])
def stop_all():
    """Emergency stop all operations and background engines"""
    # 1. Stop high-level engines
    try:
        get_scanner().stop()
        get_auto_engine().stop()
        get_rolljam().stop()
        get_camera_jammer().stop()
        get_bruteforce().stop()
        # Add thread joins or waits here if critical
    except Exception as e:
        print(f"[System] Warning during stop_all: {e}")

    # 2. Release SDR (Force)
    sdr = get_sdr()
    sdr.stop_force() # FORCE STOP
    
    # 3. Abort all tracked operations
    for op in list(operation_manager._active.values()):
        op.state = OperationState.ABORTED
        event_bus.emit("operation_aborted", {"id": op.id, "reason": "emergency_stop"})
        operation_manager.remove(op.id)
    
    return jsonify({"status": "all_stopped"})

@app.route('/api/sdr/reset', methods=['POST'])
def sdr_reset():
    """Reset SDR"""
    sdr = get_sdr()
    try:
        sdr.close()
        time.sleep(0.5)
        sdr.open()
        return jsonify({"status": "reset_complete"})
    except Exception as e:
        return jsonify({"status": "reset_failed", "error": str(e)}), 500

# --- Logs ---
@app.route('/api/logs')
def get_logs():
    return jsonify(list(LOG_BUFFER))

# --- Server Start ---
def start_server():
    # Initialize system-wide bridges
    try:
        bridge_scanner_to_arbiter()
        bridge_cameras_to_arbiter()
    except Exception as e:
        print(f"[System] Warning: Failed to wire bridges: {e}")
    
    # Start background heartbeat engine
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    
    # Ensure SDR is open for background tasks
    try:
        sdr = get_sdr()
        if sdr.device.state.name == "CLOSED":
            print("[System] Opening SDR device...")
            sdr.open()
            time.sleep(2) # Stabilize
    except Exception as e:
        print(f"[System] Warning: Failed to open SDR: {e}")
    
    # Start SCPE Engine automatically
    try:
        print("[System] Auto-starting SCPE Engine...")
        scpe = get_scpe()
        scpe.start()
        # Initial sync for 315MHz
        scanner = get_scanner()
        with scanner.lock:
            scanner.scan_frequencies = [315.0e6]
            scanner.freq_idx = 0
            print("[System] SCPE Sync: Scanner initialized to 315 MHz")
    except Exception as e:
        print(f"[System] Warning: Failed to start SCPE engine: {e}")

    # Mark system as initialized (enables background tasks)
    state['initialized'] = True

    port = int(os.environ.get('PORT', 5001))
    print(f"[WebServer] Starting on 0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, threaded=True)

if __name__ == '__main__':
    # Initialize system state
    from core.system_state import system_state_manager, SystemState
    if system_state_manager.state == SystemState.INIT:
        print("Initializing system state to IDLE")
        system_state_manager.transition(SystemState.IDLE, requester="server_init")
    
    start_server()
