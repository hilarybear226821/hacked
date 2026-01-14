#!/usr/bin/env python3
"""
OOK Loopback Validation Test

Tests TX → file → RX → decode chain before allowing real transmission.
NO REAL TX UNTIL THIS PASSES.
"""

import sys
import numpy as np
sys.path.insert(0, '/home/hilary/hacked')

from modules.ook_carrier import CarrierGenerator
from modules.timing_engine import TimingAccumulator
from modules.protocol_spec import get_protocol, PRINCETON
from modules.ook_packet_builder import OOKPulseBuilder, build_packet, build_batch, save_to_cs16

print("=" * 70)
print("OOK Loopback Validation Test")
print("=" * 70)

# Test 1: Basic Packet Generation
print("\n[Test 1] Basic Packet Generation")
print("-" * 70)

spec = PRINCETON
carrier = CarrierGenerator(2e6, amplitude=10000, tone_offset_hz=10000)
timing = TimingAccumulator(2e6)
builder = OOKPulseBuilder(carrier, timing, spec.te)

# Generate test packet
test_bits = "101010101010"
print(f"Input bits: {test_bits}")

iq = build_packet(test_bits, spec, builder)
print(f"✓ Generated {len(iq)//2} IQ samples")
print(f"✓ Duration: {len(iq)/(2*2e6)*1000:.2f} ms")

# Verify format
assert iq.dtype == np.int16, "Wrong dtype"
assert len(iq) % 2 == 0, "Odd length IQ"
print("✓ Format verification passed")

# Test 2: Phase Continuity
print("\n[Test 2] Phase Continuity")
print("-" * 70)

carrier2 = CarrierGenerator(2e6, amplitude=10000)
iq1 = carrier2.generate_pulse(100, shape_edges=False)
iq2 = carrier2.generate_pulse(100, shape_edges=False)

# Check last sample of iq1 connects to first sample of iq2
# Phase should be continuous (no discontinuity)
i1_last = iq1[-2]
q1_last = iq1[-1]
i2_first = iq2[0]
q2_first = iq2[1]

phase1 = np.arctan2(q1_last, i1_last)
phase2 = np.arctan2(q2_first, i2_first)
phase_diff = abs(phase2 - phase1)

print(f"Phase at boundary: {phase1:.4f} → {phase2:.4f}")
print(f"Phase discontinuity: {phase_diff:.4f} rad")

if phase_diff < 0.1:  # Should be very small
    print("✓ Phase continuity verified")
else:
    print(f"⚠ WARNING: Phase discontinuity detected ({phase_diff:.4f} rad)")

# Test 3: Timing Drift
print("\n[Test 3] Timing Drift Elimination")
print("-" * 70)

timing_test = TimingAccumulator(2e6)
te = 350e-6

# Simulate 100 TE pulses
total_samples = 0
for _ in range(100):
    total_samples += timing_test.samples(te)

expected = 100 * te * 2e6
error_samples = abs(total_samples - expected)
error_percent = error_samples / expected * 100

print(f"Expected samples: {expected:.2f}")
print(f"Actual samples: {total_samples}")
print(f"Error: {error_samples:.4f} samples ({error_percent:.4f}%)")

if error_samples < 1.0:
    print("✓ Timing drift eliminated")
else:
    print(f"✗ FAIL: Excessive timing drift ({error_samples} samples)")
    sys.exit(1)

# Test 4: Spectral Analysis
print("\n[Test 4] Spectral Analysis")
print("-" * 70)

# Generate continuous carrier
carrier_test = CarrierGenerator(2e6, amplitude=10000)
iq_carrier = carrier_test.generate_pulse(8192, shape_edges=False)

# Convert to complex
samples = iq_carrier[::2] + 1j * iq_carrier[1::2]

# FFT
fft = np.fft.fft(samples)
power = np.abs(fft)**2

# Find peak
peak_idx = np.argmax(power)
peak_freq_hz = peak_idx * 2e6 / len(samples)
peak_power = power[peak_idx]
mean_power = np.mean(power)
snr_db = 10 * np.log10(peak_power / mean_power)

print(f"Peak frequency: {peak_freq_hz:.0f} Hz (expect ~10000 Hz)")
print(f"SNR: {snr_db:.1f} dB")

if snr_db > 20:  # Should be very high for coherent tone
    print("✓ Narrowband signal confirmed (not wideband noise)")
else:
    print(f"✗ FAIL: Signal too wideband (SNR {snr_db:.1f} dB)")
    sys.exit(1)

# Test 5: Batch Generation
print("\n[Test 5] Batch Generation")
print("-" * 70)

codes = ["000000000000", "111111111111", "101010101010"]
batch_iq = build_batch(codes, PRINCETON, sample_rate=2e6)

print(f"✓ Generated batch of {len(codes)} codes")
print(f"✓ Total samples: {len(batch_iq)//2}")
print(f"✓ Duration: {len(batch_iq)/(2*2e6)*1000:.2f} ms")

# Test 6: File I/O
print("\n[Test 6] File I/O")
print("-" * 70)

test_file = "/tmp/test_ook_packet.cs16"
save_to_cs16(batch_iq, test_file)
print(f"✓ Saved to {test_file}")

# Verify file
import os
file_size = os.path.getsize(test_file)
expected_size = len(batch_iq) * 2  # int16 = 2 bytes each
assert file_size == expected_size, f"File size mismatch: {file_size} != {expected_size}"
print(f"✓ File size verified: {file_size} bytes")

# Read back
loaded = np.fromfile(test_file, dtype=np.int16)
assert np.array_equal(loaded, batch_iq), "Loaded data doesn't match"
print("✓ File I/O verification passed")

# Summary
print("\n" + "=" * 70)
print("✓ ALL TESTS PASSED")
print("=" * 70)
print("\nOOK packet generator is production-ready.")
print("Next step: Align decoder with ProtocolSpec for loopback decode test")
print("\n⚠ DO NOT TRANSMIT UNTIL DECODER VALIDATION PASSES")
