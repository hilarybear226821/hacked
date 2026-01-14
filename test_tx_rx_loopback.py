#!/usr/bin/env python3
"""
Full TX → RX Loopback Test

Validates that TX-generated packets can be decoded correctly.
This is the final gate before real transmission.
"""

import sys
import numpy as np
sys.path.insert(0, '/home/hilary/hacked')

from modules.ook_carrier import CarrierGenerator
from modules.timing_engine import TimingAccumulator
from modules.protocol_spec import PRINCETON
from modules.ook_packet_builder import OOKPulseBuilder, build_packet
from modules.decoders.princeton_decoder import PrincetonDecoder

print("=" * 70)
print("TX → RX Loopback Validation")
print("=" * 70)

# Test case: 12-bit code
test_code = "101010101010"
print(f"\n[Test] Encoding: {test_code}")
print(f"Expected value: 0x{int(test_code, 2):03X}")

# Step 1: Generate TX packet
print("\n[Step 1] Generating TX packet...")
carrier = CarrierGenerator(2e6, amplitude=10000)
timing = TimingAccumulator(2e6)
builder = OOKPulseBuilder(carrier, timing, PRINCETON.te)

iq = build_packet(test_code, PRINCETON, builder)
print(f"✓ Generated {len(iq)//2} IQ samples")

# Step 2: Simulate OOK demod (extract envelope)
print("\n[Step 2] Simulating OOK demodulation...")
# Extract I/Q
i_samples = iq[::2].astype(np.float32)
q_samples = iq[1::2].astype(np.float32)

# Compute envelope (magnitude)
envelope = np.sqrt(i_samples**2 + q_samples**2)

# Threshold to get level (simple slicer)
threshold = np.median(envelope) * 0.5
level_samples = (envelope > threshold).astype(int)

print(f"✓ Demodulated to {len(level_samples)} level samples")

# Step 3: Extract pulses (level + duration)
print("\n[Step 3] Extracting pulses...")
pulses = []
current_level = level_samples[0]
start_idx = 0

for i in range(1, len(level_samples)):
    if level_samples[i] != current_level:
        duration_samples = i - start_idx
        duration_us = (duration_samples / 2e6) * 1e6  # Convert to microseconds
        pulses.append((current_level, duration_us))
        
        current_level = level_samples[i]
        start_idx = i

# Add last pulse
duration_samples = len(level_samples) - start_idx
duration_us = (duration_samples / 2e6) * 1e6
pulses.append((current_level, duration_us))

print(f"✓ Extracted {len(pulses)} pulses")

# Show first few pulses for debugging
print(f"\nFirst 10 pulses:")
for i, (level, dur) in enumerate(pulses[:10]):
    print(f"  {i}: {'HIGH' if level else 'LOW':4s} {dur:7.1f} µs")

# Step 4: Feed to decoder
print("\n[Step 4] Feeding to Princeton decoder...")
decoder = PrincetonDecoder()

for level, duration in pulses:
    decoder.feed(level, duration)

# Step 5: Decode
print("\n[Step 5] Decoding...")
result = decoder.deserialize()

if result is None:
    print("✗ FAIL: Decoder returned None")
    print("\nDiagnostics:")
    print(f"  Total pulses: {len(pulses)}")
    print(f"  HIGH pulses: {sum(1 for l, d in pulses if l == 1)}")
    print(f"  LOW pulses: {sum(1 for l, d in pulses if l == 0)}")
    sys.exit(1)

print("✓ Decode successful!")
print(f"\nResult:")
for key, value in result.items():
    print(f"  {key}: {value}")

# Step 6: Verify
print("\n" + "=" * 70)
print("Verification")
print("=" * 70)

if result['bits'] == test_code:
    print(f"✓ PASS: Bits match ({test_code})")
else:
    print(f"✗ FAIL: Bit mismatch")
    print(f"  Expected: {test_code}")
    print(f"  Got:      {result['bits']}")
    sys.exit(1)

expected_hex = f"{int(test_code, 2):03X}"
if result['hex'] == expected_hex:
    print(f"✓ PASS: Hex matches (0x{expected_hex})")
else:
    print(f"✗ FAIL: Hex mismatch (expected 0x{expected_hex}, got 0x{result['hex']})")
    sys.exit(1)

if result['bit_count'] == 12:
    print(f"✓ PASS: Bit count correct (12)")
else:
    print(f"✗ FAIL: Bit count wrong ({result['bit_count']})")
    sys.exit(1)

print(f"\n✓ Confidence: {result['confidence']:.2%}")
print(f"✓ Estimated TE: {result['te_us']:.1f} µs (nominal {PRINCETON.te * 1e6:.1f} µs)")

print("\n" + "=" * 70)
print("✓✓✓ FULL TX → RX LOOPBACK PASSED ✓✓✓")
print("=" * 70)
print("\nOOK system ready for real transmission.")
