"""
OOK Packet Builder

Assembles OOK/ASK packets using protocol specifications.
Replaces broken noise-based packet_generator.py.
"""

import numpy as np
from typing import Optional
from .ook_carrier import CarrierGenerator
from .timing_engine import TimingAccumulator
from .protocol_spec import ProtocolSpec


class OOKPulseBuilder:
    """
    Builds OOK pulses using carrier and timing engines
    
    Generates carrier ON/OFF sequences with accurate TE timing.
    """
    
    def __init__(self, carrier: CarrierGenerator, timing: TimingAccumulator, te: float):
        """
        Initialize pulse builder
        
        Args:
            carrier: Carrier generator
            timing: Timing accumulator
            te: Time Element in seconds
        """
        self.carrier = carrier
        self.timing = timing
        self.te = te
    
    def on(self, te_count: int, shape_edges: bool = False) -> np.ndarray:
        """
        Generate carrier ON for te_count * TE
        
        Args:
            te_count: Number of TE units
            shape_edges: Apply edge shaping (default FALSE - only at packet boundaries)
            
        Returns:
            IQ samples (int16, interleaved)
        """
        if te_count <= 0:
            return np.empty(0, dtype=np.int16)
        
        n = self.timing.samples(te_count * self.te)
        return self.carrier.generate_pulse(n, shape_edges=shape_edges)
    
    def off(self, te_count: int) -> np.ndarray:
        """
        Generate silence (carrier OFF) for te_count * TE
        
        Args:
            te_count: Number of TE units
            
        Returns:
            Zero IQ samples (int16, interleaved)
        """
        if te_count <= 0:
            return np.empty(0, dtype=np.int16)
        
        n = self.timing.samples(te_count * self.te)
        return np.zeros(n * 2, dtype=np.int16)


def build_packet(bits: str, spec: ProtocolSpec, builder: OOKPulseBuilder) -> np.ndarray:
    """
    Build OOK packet from bits using protocol specification
    
    Supports PWM, Manchester, and Biphase encoding.
    Edge shaping applied ONLY at packet boundaries (first/last ON pulse).
    """
    from .protocol_spec import EncodingType
    buf = []
    
    # 1. Preamble: alternating ON/OFF to wake AGC (NO shaping)
    if spec.preamble_cycles > 0:
        for _ in range(spec.preamble_cycles):
            buf.append(builder.on(spec.preamble_on_te, shape_edges=False))
            buf.append(builder.off(spec.preamble_off_te))
    
    # 2. Sync Pulse (Optional)
    if spec.sync_on_te > 0:
        buf.append(builder.on(spec.sync_on_te, shape_edges=False))
        
    # 3. Sync Gap (Silence)
    if spec.sync_off_te > 0:
        buf.append(builder.off(spec.sync_off_te))
    
    # Render Data Block
    pulses_to_render = []
    if spec.encoding == EncodingType.PWM:
        for bit in bits:
            p = spec.one if bit == '1' else spec.zero
            pulses_to_render.append(('on', p.on_te))
            pulses_to_render.append(('off', p.off_te))
    elif spec.encoding == EncodingType.MANCHESTER:
        # Standard Manchester: 1 = ON-OFF (1-0), 0 = OFF-ON (0-1)
        # Each pulse is exactly 1 TE
        for bit in bits:
            if bit == '1':
                pulses_to_render.append(('on', 1))
                pulses_to_render.append(('off', 1))
            else:
                pulses_to_render.append(('off', 1))
                pulses_to_render.append(('on', 1))
                
    # Render Pulses to Samples
    on_pulse_indices = [i for i, (t, _) in enumerate(pulses_to_render) if t == 'on']
    if not on_pulse_indices:
        return np.concatenate(buf) if buf else np.empty(0, dtype=np.int16)
    
    for i, (p_type, te_count) in enumerate(pulses_to_render):
        if p_type == 'on':
            # Edge shape only at extreme boundaries of data block to avoid bit-splatter
            is_boundary = (i == on_pulse_indices[0] or i == on_pulse_indices[-1])
            buf.append(builder.on(te_count, shape_edges=is_boundary))
        else:
            buf.append(builder.off(te_count))
    
    # 5. Inter-frame gap
    if spec.interframe_gap_te > 0:
        buf.append(builder.off(spec.interframe_gap_te))
    
    return np.concatenate(buf)


def build_batch(codes: list, spec: ProtocolSpec, sample_rate: float = 2e6,
                amplitude: int = 10000, tone_offset_hz: float = 10000) -> np.ndarray:
    """
    Build batch of packets with proper spacing
    
    Args:
        codes: List of binary strings to transmit
        spec: Protocol specification
        sample_rate: Sample rate in Hz
        amplitude: Signal amplitude
        tone_offset_hz: Baseband tone offset
        
    Returns:
        Concatenated IQ samples for all packets
    """
    carrier = CarrierGenerator(sample_rate, amplitude, tone_offset_hz)
    timing = TimingAccumulator(sample_rate)
    builder = OOKPulseBuilder(carrier, timing, spec.te)
    
    packets = []
    for code in codes:
        # Repeat each packet per spec
        for _ in range(spec.repeat):
            packets.append(build_packet(code, spec, builder))
    
    return np.concatenate(packets)


def save_to_cs16(samples: np.ndarray, filename: str):
    """
    Save int16 IQ samples to .cs16 file
    
    Args:
        samples: IQ samples (int16, interleaved)
        filename: Output filename
    """
    import os
    os.makedirs(os.path.dirname(os.path.abspath(filename)), exist_ok=True)
    samples.tofile(filename)
