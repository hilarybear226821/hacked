/*
 * test_decoder.c
 * Test program for SubGHz protocol decoders
 */

#include "subghz_protocols.h"
#include <stdio.h>
#include <stdlib.h>

// Simulate Princeton PT2262 signal
// Format: Short-High + Long-Low = 0
//         Long-High + Short-Low = 1
// Example: Decode 0xABCDEF (24 bits)

void test_princeton() {
  printf("=== Testing Princeton PT2262 Decoder ===\n\n");

  // Allocate decoder instance
  void *decoder = princeton_protocol.alloc();
  if (!decoder) {
    fprintf(stderr, "Failed to allocate decoder\n");
    return;
  }

  princeton_protocol.reset(decoder);

  // Simulate a signal: 0b101010 (6 bits for simplicity)
  // Let's decode: 0xA (1010 in binary, 4 bits)
  // Bit pattern: 1, 0, 1, 0

  uint32_t te_short = 400; // microseconds
  uint32_t te_long = 1200;
  uint32_t gap = 5000;

  printf("Feeding signal pattern for 0xA (1010):\n");

  // Start with a gap (sync)
  printf("  [Gap: %d us]\n", gap);
  princeton_protocol.feed(decoder, false, gap);

  // Bit 1 (LSB): Long-High + Short-Low
  printf("  Bit 0: Long-High (%d) + Short-Low (%d) = 1\n", te_long, te_short);
  princeton_protocol.feed(decoder, true, te_long);
  princeton_protocol.feed(decoder, false, te_short);

  // Bit 0: Short-High + Long-Low
  printf("  Bit 1: Short-High (%d) + Long-Low (%d) = 0\n", te_short, te_long);
  princeton_protocol.feed(decoder, true, te_short);
  princeton_protocol.feed(decoder, false, te_long);

  // Bit 1: Long-High + Short-Low
  printf("  Bit 2: Long-High (%d) + Short-Low (%d) = 1\n", te_long, te_short);
  princeton_protocol.feed(decoder, true, te_long);
  princeton_protocol.feed(decoder, false, te_short);

  // Bit 0: Short-High + Long-Low
  printf("  Bit 3: Short-High (%d) + Long-Low (%d) = 0\n", te_short, te_long);
  princeton_protocol.feed(decoder, true, te_short);
  princeton_protocol.feed(decoder, false, te_long);

  // Add more bits to reach minimum (16 bits)
  for (int i = 0; i < 12; i++) {
    // Add alternating pattern
    if (i % 2 == 0) {
      princeton_protocol.feed(decoder, true, te_long);
      princeton_protocol.feed(decoder, false, te_short);
    } else {
      princeton_protocol.feed(decoder, true, te_short);
      princeton_protocol.feed(decoder, false, te_long);
    }
  }

  // End with gap to trigger frame completion
  printf("  [Gap: %d us] - Frame Complete\n\n", gap);
  bool complete = princeton_protocol.feed(decoder, false, gap);

  if (complete) {
    printf("✓ Frame decoded successfully!\n\n");

    // Deserialize
    uint64_t data;
    uint32_t bits;
    if (princeton_protocol.deserialize(decoder, &data, &bits)) {
      printf("Decoded Data:\n");
      printf("  Raw: 0x%llX\n", (unsigned long long)data);
      printf("  Bits: %d\n", bits);
      printf("  Binary: ");
      for (int i = bits - 1; i >= 0; i--) {
        printf("%d", (int)((data >> i) & 1));
        if (i > 0 && i % 4 == 0)
          printf(" ");
      }
      printf("\n\n");

      // Get string representation
      char buffer[256];
      princeton_protocol.get_string(decoder, buffer, sizeof(buffer));
      printf("String: %s\n", buffer);
    }
  } else {
    printf("✗ Frame not complete (need more pulses)\n");
  }

  // Cleanup
  princeton_protocol.free(decoder);
  printf("\n=== Test Complete ===\n");
}

int main() {
  printf("SubGHz Protocol Decoder Test Suite\n");
  printf("===================================\n\n");

  test_princeton();

  return 0;
}
