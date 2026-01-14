
#include "subghz_protocols.h"
#include <stdbool.h> // FIXED: Issue #1
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// --- Princeton (PT2262) Implementation ---

// Adaptive timing - learned from pulses
#define PRINCETON_MAX_SYMBOL_BITS 24 // PT2262 is 24 bits (12 tri-state symbols)
#define PRINCETON_MIN_TE 150         // Minimum TE (cheap remotes)
#define PRINCETON_MAX_TE 2500        // Maximum TE (voltage/temp drift)
#define PRINCETON_TE_TOLERANCE 0.5   // ±50% tolerance for ratios

// Tri-state symbol representation
typedef enum {
  TRISTATE_0 = 0, // Floating
  TRISTATE_1 = 1, // Logic 1
  TRISTATE_F = 2, // Floating (often used for address)
  TRISTATE_INVALID = 3
} TristateSymbol;

typedef enum {
  PT_STATE_IDLE = 0,
  PT_STATE_LEARNING_TE, // Learning TE from first pulses
  PT_STATE_DECODING     // Decoding symbols
} PrincetonState;

typedef struct {
  // Decoded data (tri-state symbols, 2 bits each)
  uint8_t symbols[PRINCETON_MAX_SYMBOL_BITS];
  uint32_t symbol_count;

  // Timing adaptation
  uint32_t estimated_te;
  bool te_learned;

  // Pulse pair tracking
  uint32_t last_pulse_duration;
  bool last_pulse_level;
  bool pulse_pair_ready;

  // Repeat detection (for validation)
  uint8_t last_frame_symbols[PRINCETON_MAX_SYMBOL_BITS];
  uint32_t last_frame_count;
  uint8_t repeat_count;

  PrincetonState state;
} PrincetonDecoder;

// --- Helper Functions ---

// Check if duration is within ratio tolerance
static inline bool matches_ratio(uint32_t duration, uint32_t te,
                                 float expected_ratio) {
  if (te == 0)
    return false;

  float actual_ratio = (float)duration / te;
  float min_ratio = expected_ratio * (1.0 - PRINCETON_TE_TOLERANCE);
  float max_ratio = expected_ratio * (1.0 + PRINCETON_TE_TOLERANCE);

  return (actual_ratio >= min_ratio && actual_ratio <= max_ratio);
}

// Decode tri-state symbol from pulse pair (PT2262 encoding)
// Short-short = 0, Long-long = 1, Short-long = F
static TristateSymbol decode_symbol(uint32_t high_duration,
                                    uint32_t low_duration, uint32_t te) {
  bool high_short = matches_ratio(high_duration, te, 1.0);
  bool high_long = matches_ratio(high_duration, te, 3.0);
  bool low_short = matches_ratio(low_duration, te, 1.0);
  bool low_long = matches_ratio(low_duration, te, 3.0);

  if (high_short && low_long) {
    return TRISTATE_0; // Short-long
  } else if (high_long && low_short) {
    return TRISTATE_1; // Long-short
  } else if (high_short && low_short) {
    return TRISTATE_F; // Short-short (floating)
  }

  return TRISTATE_INVALID;
}

// --- Callbacks ---

void *princeton_alloc(void) {
  PrincetonDecoder *d = calloc(1, sizeof(PrincetonDecoder));
  if (d) {
    d->state = PT_STATE_IDLE;
    d->estimated_te = 0;
    d->te_learned = false;
    d->last_pulse_duration = 0; // FIXED: Issue #10 - initialized
    d->pulse_pair_ready = false;
  }
  return d;
}

void princeton_free(void *instance) {
  if (instance) {
    free(instance);
  }
}

void princeton_reset(void *instance) {
  if (!instance)
    return;

  PrincetonDecoder *d = (PrincetonDecoder *)instance;

  // FIXED: Issue #5 - don't set state here, let caller control
  d->symbol_count = 0;
  d->pulse_pair_ready = false;
  d->last_pulse_duration = 0;
  // Keep TE learned and repeat history for validation
}

bool princeton_feed(void *instance, bool level, uint32_t duration) {
  PrincetonDecoder *d = (PrincetonDecoder *)instance;

  // Validate duration sanity (FIXED: Issue #15 - noise floor)
  if (duration < PRINCETON_MIN_TE || duration > PRINCETON_MAX_TE) {
    return false; // Noise
  }

  // Gap detection (polarity-agnostic) - FIXED: Issue #3
  bool is_gap = (duration > 30 * (d->te_learned ? d->estimated_te : 400));

  if (is_gap) {
    // Frame boundary detected
    if (d->state == PT_STATE_DECODING &&
        d->symbol_count == PRINCETON_MAX_SYMBOL_BITS) {
      // FIXED: Issue #6 - exact 24-bit frames only
      // Valid frame complete

      // FIXED: Issue #14 - repeat detection
      bool is_repeat =
          (d->last_frame_count == d->symbol_count &&
           memcmp(d->symbols, d->last_frame_symbols, d->symbol_count) == 0);

      if (is_repeat) {
        d->repeat_count++;
        if (d->repeat_count >= 2) {
          // Require 2+ identical repeats for validation
          d->state = PT_STATE_IDLE;
          return true; // Valid frame
        }
      } else {
        // New frame, save for repeat detection
        memcpy(d->last_frame_symbols, d->symbols, d->symbol_count);
        d->last_frame_count = d->symbol_count;
        d->repeat_count = 1;
      }
    }

    // Reset for next frame (FIXED: Issue #4 - soft reset)
    d->symbol_count = 0;
    d->pulse_pair_ready = false;
    d->state = PT_STATE_LEARNING_TE;
    return false;
  }

  // State machine
  switch (d->state) {
  case PT_STATE_IDLE:
    // Waiting for gap
    return false;

  case PT_STATE_LEARNING_TE:
    // Learn TE from first few pulses (FIXED: Issue #2 - adaptive TE)
    if (!d->te_learned) {
      // Use first short pulse as TE estimate
      if (duration >= 200 && duration <= 800) {
        d->estimated_te = duration;
        d->te_learned = true;
        d->state = PT_STATE_DECODING;
      }
    } else {
      d->state = PT_STATE_DECODING;
    }
    // Fall through to decoding
    // Don't use break to fall through

  case PT_STATE_DECODING:
    if (!d->pulse_pair_ready) {
      // Store first pulse of pair
      d->last_pulse_duration = duration;
      d->last_pulse_level = level;
      d->pulse_pair_ready = true;
    } else {
      // Have pulse pair - decode symbol
      uint32_t high_dur, low_dur;

      if (d->last_pulse_level) {
        high_dur = d->last_pulse_duration;
        low_dur = duration;
      } else {
        high_dur = duration;
        low_dur = d->last_pulse_duration;
      }

      // FIXED: Issue #8 - tri-state support
      TristateSymbol symbol = decode_symbol(high_dur, low_dur, d->estimated_te);

      if (symbol != TRISTATE_INVALID &&
          d->symbol_count < PRINCETON_MAX_SYMBOL_BITS) {
        d->symbols[d->symbol_count++] = symbol;
      } else if (symbol == TRISTATE_INVALID) {
        // FIXED: Issue #4 - soft error, don't wipe everything
        // Just invalidate this symbol and continue
        d->pulse_pair_ready = false;
        return false;
      }

      // FIXED: Issue #11 - hard cap at 24 bits
      if (d->symbol_count >= PRINCETON_MAX_SYMBOL_BITS) {
        // Frame complete, wait for gap
        d->pulse_pair_ready = false;
        return false;
      }

      d->pulse_pair_ready = false;
    }
    break;
  }

  return false;
}

bool princeton_deserialize(void *instance, uint64_t *out_data,
                           uint32_t *out_bits) {
  PrincetonDecoder *d = (PrincetonDecoder *)instance;

  // FIXED: Issue #12 - exact bit count validation
  if (d->symbol_count != PRINCETON_MAX_SYMBOL_BITS) {
    return false;
  }

  // Convert tri-state symbols to binary (MSB first) - FIXED: Issue #7
  uint64_t binary_data = 0;
  for (int i = 0; i < d->symbol_count; i++) {
    // Encode tri-state as 2 bits: 00=0, 01=1, 10=F
    uint8_t sym = d->symbols[i];
    binary_data = (binary_data << 2) | sym;
  }

  *out_data = binary_data;
  *out_bits = d->symbol_count * 2; // 2 bits per tri-state symbol
  return true;
}

void princeton_get_string(void *instance, char *buffer, size_t len) {
  PrincetonDecoder *d = (PrincetonDecoder *)instance;

  // FIXED: Issue #13 - improved representation
  if (d->symbol_count > 0) {
    int offset = snprintf(buffer, len, "PT2262 [");

    // Show tri-state symbols
    for (int i = 0; i < d->symbol_count && i < 12; i++) {
      char c = '?';
      switch (d->symbols[i]) {
      case TRISTATE_0:
        c = '0';
        break;
      case TRISTATE_1:
        c = '1';
        break;
      case TRISTATE_F:
        c = 'F';
        break;
      default:
        c = '?';
        break;
      }
      if (offset < len - 1) {
        buffer[offset++] = c;
      }
    }

    snprintf(buffer + offset, len - offset, "] (%d symbols, %d repeats)",
             d->symbol_count, d->repeat_count);
  } else {
    snprintf(buffer, len, "PT2262: No Data");
  }
}

// --- Protocol Instance ---

const SubGhzProtocolDecoder princeton_protocol = {
    .name = "Princeton_PT2262",
    .alloc = princeton_alloc,
    .free = princeton_free,
    .reset = princeton_reset,
    .feed = princeton_feed,
    .deserialize = princeton_deserialize,
    .get_string = princeton_get_string};
