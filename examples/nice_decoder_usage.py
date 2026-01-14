"""
Example usage of NiceFlorProductionDecoder

Demonstrates proper integration with pulse stream.
"""

from modules.decoders.manchester import NiceFlorProductionDecoder

# Initialize decoder
decoder = NiceFlorProductionDecoder(tolerance=0.35)

# Simulate pulse stream (level, duration_us)
pulse_stream = [
    # Preamble: alternating ~500µs pulses
    (1, 480), (0, 510), (1, 495), (0, 505),
    (1, 490), (0, 515), (1, 500), (0, 500),
    # Sync: long gap ~2000µs
    (0, 2050),
    # Data: Manchester encoded bits...
    # (would continue with actual data pulses)
]

# Feed pulses as they arrive
for level, duration in pulse_stream:
    decoder.feed(level, duration)

# Once enough data collected or end of burst, attempt decode
result = decoder.deserialize()

if result:
    print(f"✓ Decoded frame:")
    print(f"  Protocol: {result['protocol']}")
    print(f"  Button: {result['button']}")
    print(f"  Serial: {result['serial']}")
    print(f"  Encrypted: {result['encrypted']}")
    print(f"  TE: {result['te_us']:.1f} µs")
    print(f"  Confidence: {result['confidence']:.1%}")
    print(f"  Frame votes: {result['frame_votes']}")
    print(f"  Manchester violations: {result['manchester_violations']}")
else:
    print("✗ Decode failed or low confidence")

# Note: decoder auto-resets after deserialize(),
# ready for next frame immediately
