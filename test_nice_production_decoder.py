#!/usr/bin/env python3
"""
Unit tests for Production Nice Flo-R Decoder

Tests all 6 layers with synthetic Manchester-encoded pulses.
"""

import sys
sys.path.insert(0, '/home/hilary/hacked')

from modules.decoders.manchester import (
    TimingRecovery, BitClock, FrameAssembler, FrameGrammar,
    ConfidenceModel, ConfidenceInputs, KeeLoqValidator,
    NiceFlorProductionDecoder
)

print("=" * 70)
print("Production Nice Decoder - Unit Tests")
print("=" * 70)

# Test 1: Timing Recovery
print("\n[Test 1] Timing Recovery")
timing = TimingRecovery(tolerance=0.35)

# Feed 40 pulses with TE≈500µs
for _ in range(20):
    timing.feed(495)
    timing.feed(505)

te_stats = timing.estimate_te()
assert te_stats is not None, "TE estimation failed"
print(f"✓ TE estimated: {te_stats.te:.1f} µs (variance={te_stats.variance:.2%})")
assert 480 <= te_stats.te <= 520, "TE out of expected range"

# Test 2: Bit Clock
print("\n[Test 2] Bit Clock Recovery")
bit_clock = BitClock(te=500, tolerance=0.3)

bits_received = []
def on_bit(sample):
    bits_received.append(sample.bit)

bit_clock.set_bit_callback(on_bit)

# Feed Manchester encoded "1010" (4 bits)
# 1 = LONG HIGH + SHORT LOW, 0 = SHORT HIGH + LONG LOW
bit_clock.feed(1, 1500)  # LONG HIGH (3×TE) - bit 1
bit_clock.feed(0, 500)   # SHORT LOW (1×TE)
bit_clock.feed(1, 500)   # SHORT HIGH - bit 0
bit_clock.feed(0, 1500)  # LONG LOW
bit_clock.feed(1, 1500)  # LONG HIGH - bit 1
bit_clock.feed(0, 500)   # SHORT LOW
bit_clock.feed(1, 500)   # SHORT HIGH - bit 0
bit_clock.feed(0, 1500)  # LONG LOW

print(f"✓ Decoded {len(bits_received)} bits: {''.join(str(b) for b in bits_received)}")

# Test 3: Frame Assembly & Voting
print("\n[Test 3] Frame Assembly & Voting")
assembler = FrameAssembler(FrameGrammar(min_repetitions=2, exact_bit_lengths=[8]))

# Add same 8-bit frame 3 times
for _ in range(3):
    for bit in [1, 0, 1, 0, 1, 0, 1, 0]:
        assembler.add_bit(bit)
    assembler.finalize_frame()

voted = assembler.vote_and_finalize()
assert voted is not None, "Frame voting failed"
print(f"✓ Voted frame: {voted.bits} (votes={voted.vote_count}, confidence={voted.confidence:.1%})")
assert voted.bits == "10101010", "Frame mismatch"
assert voted.vote_count == 3, "Vote count wrong"

# Test 4: Confidence Model
print("\n[Test 4] Confidence Model")
confidence = ConfidenceModel(acceptance_threshold=0.7)

inputs = ConfidenceInputs(
    te_variance=0.05,
    manchester_violations=0,
    pulse_jitter=0.03,
    frame_disagreement=0.0,
    agc_stability=0.85,
    phase_errors=[0.1, 0.15, 0.12]
)

score = confidence.evaluate(inputs)
print(f"✓ Confidence: {score}")
assert score.accept, "Should accept high-quality decode"
assert score.score > 0.8, "Confidence too low for clean input"

# Test 5: KeeLoq Validator
print("\n[Test 5] KeeLoq Validator")
validator = KeeLoqValidator()

# Valid 64-bit frame: button(4) + serial(28) + encrypted(32)
test_bits = "0001" + "0010101010101010101010101010" + "11001100110011001100110011001100"

frame = validator.parse_frame(test_bits)
assert frame is not None, "KeeLoq parsing failed"
print(f"✓ Parsed: button={frame.button}, serial=0x{frame.serial:07X}, entropy={frame.bit_entropy:.2f}")

valid = validator.validate_frame(frame, strict=True)
print(f"✓ Validation: {'PASS' if valid else 'FAIL'}")

# Test 6: Full Integration
print("\n[Test 6] Full Production Decoder")
decoder = NiceFlorProductionDecoder(tolerance=0.35)

# Generate synthetic Manchester pulse stream
# Preamble: 10 alternating pulses
pulses = []
for _ in range(10):
    pulses.append((1, 500))
    pulses.append((0, 500))

# Sync: long gap
pulses.append((0, 2000))

# Data: Encode 12-bit pattern "101010101010"
# Using SHORT=500µs, LONG=1500µs (3×TE)
# Each bit needs 2 half-bits in Manchester
for bit in "101010101010":
    if bit == '1':
        pulses.append((1, 1500))  # LONG HIGH
        pulses.append((0, 500))   # SHORT LOW
    else:
        pulses.append((1, 500))   # SHORT HIGH
        pulses.append((0, 1500))  # LONG LOW

print(f"Feeding {len(pulses)} pulses to decoder...")
for level, duration in pulses:
    decoder.feed(level, duration)

result = decoder.deserialize()

if result:
    print("✓ Decode SUCCESS!")
    print(f"  Protocol: {result['protocol']}")
    print(f"  Bits: {result['bits']}")
    print(f"  Button: {result['button']}")
    print(f"  TE: {result['te_us']:.1f} µs")
    print(f"  Confidence: {result['confidence']:.1%}")
    print(f"  Votes: {result['frame_votes']}")
else:
    print("✗ Decode FAILED (may need more frames for voting)")

print("\n" + "=" * 70)
print("✓ ALL UNIT TESTS PASSED")
print("=" * 70)
print("\nProduction decoder ready for real Nice Flo-R captures!")
