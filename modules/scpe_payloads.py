"""
SCPE Payload Registry
Defines protocol structures and parameters for SCPE Waveform Synthesis.
Includes "Military-Grade" definitions for common rolling code systems.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable

@dataclass
class ProtocolDefinition:
    """Defines the physical layer and frame structure for a protocol"""
    name: str
    freq_mhz: float
    modulation: str # 'OOK' or 'FSK'
    pulse_width_us: int
    preamble: str
    sync: str
    packet_len_bits: int
    
    # Advanced Params
    fsk_deviation_hz: float = 0.0
    baud_rate: float = 0.0
    
    # Validation
    validate_crc: bool = False

# ============================================================================
# PROTOCOL DATABASE
# ============================================================================
PROTOCOLS = {
    # ------------------------------------------------------------------------
    # FIXED / SIMPLE ROLLING CODES (OOK)
    # ------------------------------------------------------------------------
    "Keeloq_Normal": ProtocolDefinition(
        name="Keeloq_Normal",
        freq_mhz=433.92,
        modulation="OOK",
        pulse_width_us=400, # TE
        preamble="1" * 12, # ~12 bits high usually
        sync="0", # often followed by header
        packet_len_bits=66,
        validate_crc=False
    ),
    
    "Nice_FLO": ProtocolDefinition(
        name="Nice_FLO",
        freq_mhz=433.92,
        modulation="OOK",
        pulse_width_us=700,
        preamble="1"*12, # Rough approx
        sync="0",
        packet_len_bits=12, # Fixed code usually
    ),
    
    "Came_TOP": ProtocolDefinition(
        name="Came_TOP",
        freq_mhz=433.92,
        modulation="OOK",
        pulse_width_us=320,
        preamble="1010", 
        sync="0",
        packet_len_bits=12 # or 24
    ),
    
    "Princeton_PT2262": ProtocolDefinition(
        name="Princeton_PT2262",
        freq_mhz=315.00,
        modulation="OOK",
        pulse_width_us=350, # Alpha
        preamble="",
        sync="10000000", # Usually sync bit is distinctive
        packet_len_bits=24
    ),

    "EV1527_Generic": ProtocolDefinition(
        name="EV1527",
        freq_mhz=433.92,
        modulation="OOK",
        pulse_width_us=300, # Osc dependent
        preamble="1"*16,
        sync="00000001",
        packet_len_bits=24
    ),

    "Somfy_RTS": ProtocolDefinition(
        name="Somfy_RTS",
        freq_mhz=433.42,
        modulation="OOK",
        pulse_width_us=640, # 1208us symbol
        preamble="11111111", # HW sync
        sync="101010101010", # SW sync
        packet_len_bits=56,
        validate_crc=True # 4-bit CRC
    ),

    "SecurityPlus_1.0": ProtocolDefinition(
        name="Security+_1.0",
        freq_mhz=315.00, # or 390
        modulation="OOK",
        pulse_width_us=500, # 1ms bit period
        preamble="", 
        sync="1111111111", # Blanking time then sync
        packet_len_bits=32 # Rolling
    ),

    "SecurityPlus_2.0": ProtocolDefinition(
        name="Security+_2.0",
        freq_mhz=315.00, # Tri-band usually
        modulation="OOK", 
        pulse_width_us=250, # Faster
        preamble="",
        sync="1", # Complex sync
        packet_len_bits=64
    ),

    # ------------------------------------------------------------------------
    # ADVANCED FSK PROTOCOLS (Modern Auto)
    # ------------------------------------------------------------------------
    "Modern_Remote_Keyless": ProtocolDefinition(
        name="Modern_RKE_FSK",
        freq_mhz=315.00,
        modulation="FSK",
        pulse_width_us=100, # 10kbps
        preamble="1010101010101010", 
        sync="11001100",
        packet_len_bits=128,
        fsk_deviation_hz=40000.0,
        baud_rate=10000.0
    ),
    
    "Honda_FSK": ProtocolDefinition(
        name="Honda_FSK",
        freq_mhz=433.92,
        modulation="FSK", 
        pulse_width_us=500, # ~2kbps
        preamble="1"*10 + "0"*10,
        sync="1010",
        packet_len_bits=64,
        fsk_deviation_hz=30000.0,
        baud_rate=2000.0
    ),
    
    "Ford_Generic_OOK": ProtocolDefinition(
        name="Ford_Generic",
        freq_mhz=315.00,
        modulation="OOK",
        pulse_width_us=250,
        preamble="",
        sync="00000001",
        packet_len_bits=104
    )
}

def get_protocol_def(name_or_heuristics: str) -> Optional[ProtocolDefinition]:
    """Retrieve protocol definition by name or matching characteristics"""
    if name_or_heuristics in PROTOCOLS:
        return PROTOCOLS[name_or_heuristics]
    
    # Heuristic match (stub)
    for p_name, p_def in PROTOCOLS.items():
        if p_name.lower() in name_or_heuristics.lower():
            return p_def
            
    return None

def construct_payload(protocol_name: str, data_bits: str) -> dict:
    """
    Builds the components for SCPE Waveform Generator.
    Returns kwargs dict for generator.
    """
    proto = get_protocol_def(protocol_name)
    if not proto:
        # Default fallback
        return {
            "preamble": "10101010",
            "sync": "1100",
            "payload": data_bits,
            "modulation": "OOK",
            "params": {"pulse_width_us": 400}
        }
        
    return {
        "preamble_bits": proto.preamble,
        "sync_bits": proto.sync,
        "payload_bits": data_bits, # User must format this
        "modulation": proto.modulation,
        "params": {
            "pulse_width_us": proto.pulse_width_us,
            "baud_rate": proto.baud_rate,
            "dev_hz": proto.fsk_deviation_hz,
            "center_freq": 0.0
        }
    }
