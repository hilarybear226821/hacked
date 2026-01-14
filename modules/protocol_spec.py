from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Dict, List, Optional


class EncodingType(Enum):
    """Supported OOK/ASK encoding types"""
    PWM = auto()        # Pulse Width Modulation (short/long pulses)
    MANCHESTER = auto() # Manchester encoding (IEEE 802.3 standard: 1->0=1, 0->1=0)
    BIPHASE = auto()    # Bi-phase encoding
    RAW = auto()         # Raw TE-based bitstream (1=ON, 0=OFF)


@dataclass(frozen=True)
class PulseSpec:
    """Specification for a single pulse bit in PWM mode"""
    on_te: int   # TE units with carrier ON
    off_te: int  # TE units with carrier OFF


@dataclass(frozen=True)
class ProtocolSpec:
    """Complete protocol specification for transmission and detection"""
    name: str
    encoding: EncodingType
    te: float              # Time Element in seconds (base timing unit)
    
    # Pulse-based (PWM) bit definitions
    zero: Optional[PulseSpec] = None
    one: Optional[PulseSpec] = None
    
    # Preamble/Sync
    preamble_on_te: int = 0
    preamble_off_te: int = 0
    preamble_cycles: int = 0
    sync_on_te: int = 0    # Some protocols (KeeLoq) have a sync pulse
    sync_off_te: int = 0   # Sync gap duration
    
    # Frame metadata
    bit_length: int = 0
    interframe_gap_te: int = 20
    repeat: int = 3
    
    verified: bool = False
    
    def validate(self):
        """Validate protocol specification"""
        if self.te <= 0:
            raise ValueError(f"TE must be > 0, got {self.te}")
            
        if self.encoding == EncodingType.PWM:
            if not self.zero or not self.one:
                raise ValueError("PWM encoding requires zero and one pulse specs")
            if self.zero.on_te + self.zero.off_te == 0:
                raise ValueError("Zero bit has zero total duration")
            if self.one.on_te + self.one.off_te == 0:
                raise ValueError("One bit has zero total duration")
        
        if self.sync_off_te < 0:
            raise ValueError(f"Sync gap must be >= 0")
            
        if self.repeat < 1:
            raise ValueError(f"Repeat must be >= 1")


# ============================================================================
# Protocol Definitions (VERIFIED)
# ============================================================================

# Princeton / EV1527 (433.92MHz / 315MHz)
# Common in cheap garage/light remotes
PRINCETON = ProtocolSpec(
    name="princeton",
    encoding=EncodingType.PWM,
    te=350e-6,
    zero=PulseSpec(on_te=1, off_te=3),
    one=PulseSpec(on_te=3, off_te=1),
    preamble_on_te=1,
    preamble_off_te=1,
    preamble_cycles=20,
    sync_off_te=31,
    bit_length=24,
    verified=True
)

# KeeLoq (HCS200/301) - 433.92MHz / 315MHz
# Widely used in car fobs (VW, Toyota, etc.)
KEELOQ = ProtocolSpec(
    name="keeloq",
    encoding=EncodingType.PWM,
    te=400e-6,
    zero=PulseSpec(on_te=1, off_te=2),  # 1:2 ratio
    one=PulseSpec(on_te=2, off_te=1),   # 2:1 ratio
    sync_off_te=10,  # Sync gap before bits
    bit_length=66,
    verified=True
)

# Nice Flo-R (Rolling) - 433.92MHz
# Uses Manchester encoding
NICE_FLOR = ProtocolSpec(
    name="nice_flor",
    encoding=EncodingType.MANCHESTER,
    te=500e-6,
    preamble_cycles=10,
    preamble_on_te=1,
    preamble_off_te=1,
    sync_off_te=4,
    bit_length=64,
    verified=True
)

# Came (Top/Tam) - 433.92MHz
CAME = ProtocolSpec(
    name="came",
    encoding=EncodingType.PWM,
    te=320e-6,
    zero=PulseSpec(on_te=1, off_te=2),
    one=PulseSpec(on_te=2, off_te=1),
    sync_on_te=1,
    sync_off_te=36,
    bit_length=24,
    verified=True
)

# Protocol Registry
PROTOCOLS: Dict[str, ProtocolSpec] = {
    "princeton": PRINCETON,
    "keeloq": KEELOQ,
    "nice_flor": NICE_FLOR,
    "came": CAME,
}

# Auto-validate all on load
for p in PROTOCOLS.values():
    p.validate()


def get_protocol(name: str) -> ProtocolSpec:
    return PROTOCOLS[name.lower()]
