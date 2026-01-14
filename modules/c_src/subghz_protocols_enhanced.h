/**
 * Enhanced Sub-GHz Protocol Decoder (Flipper Zero Architecture)
 * Full 8-method interface with timing validation and state machines
 *
 * Implements: Princeton (PT2262), CAME 12-bit, and generic PWM/Manchester
 */

#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// ========== Protocol Timing Definitions ==========
#define TE_SHORT 320   // Short pulse (Princeton/CAME)
#define TE_LONG 960    // Long pulse
#define TE_DELTA 150   // Tolerance window
#define GAP_RESET 1280 // Min gap for packet reset

// ========== Core Protocol Interface ==========
typedef struct {
  const char *name;
  void *instance;

  // Method 1 & 2: Memory Management
  void *(*alloc)(void);
  void (*free)(void *instance);

  // Method 3: State Reset
  void (*reset)(void *instance);

  // Method 4: Core Pulse Processing
  void (*feed)(void *instance, bool level, uint32_t duration);

  // Method 5 & 6: Persistence
  bool (*deserialize)(void *instance, const char *data);
  char *(*serialize)(void *instance);

  // Method 7: De-duplication
  uint8_t (*get_hash_data)(void *instance);

  // Method 8: UI/Display
  void (*get_string)(void *instance, char *buffer, size_t buflen);

} SubGhzProtocolDecoder;

// ========== Protocol State Machines ==========

typedef enum {
  STATE_IDLE,
  STATE_PREAMBLE,
  STATE_SYNC,
  STATE_DATA,
  STATE_COMPLETE
} DecoderState;

typedef struct {
  DecoderState state;
  uint64_t data;
  uint8_t bit_count;
  uint32_t last_duration;
  bool last_level;
  uint32_t te_short; // Adaptive timing
  uint32_t te_long;
  uint8_t serial; // For CAME serial number
  uint8_t btn;    // For CAME button
} PrincetonInstance;

typedef struct {
  DecoderState state;
  uint16_t data;
  uint8_t bit_count;
  uint32_t te_short;
  bool last_level;
} CAMEInstance;

// ========== Princeton PT2262 Decoder (Enhanced) ==========

void *princeton_alloc(void) {
  PrincetonInstance *inst =
      (PrincetonInstance *)malloc(sizeof(PrincetonInstance));
  memset(inst, 0, sizeof(PrincetonInstance));
  inst->te_short = TE_SHORT;
  inst->te_long = TE_LONG;
  return inst;
}

void princeton_free(void *instance) { free(instance); }

void princeton_reset(void *instance) {
  PrincetonInstance *inst = (PrincetonInstance *)instance;
  inst->state = STATE_IDLE;
  inst->data = 0;
  inst->bit_count = 0;
}

void princeton_feed(void *instance, bool level, uint32_t duration) {
  PrincetonInstance *inst = (PrincetonInstance *)instance;

  // Step 1: Gap Detection (Packet Boundary)
  if (!level && duration > GAP_RESET) {
    if (inst->state == STATE_DATA && inst->bit_count == 24) {
      inst->state = STATE_COMPLETE;
      // Trigger callback or flag completion
    }
    princeton_reset(instance);
    return;
  }

  // Step 2: Timing Validation
  uint32_t te_short_min = inst->te_short - TE_DELTA;
  uint32_t te_short_max = inst->te_short + TE_DELTA;
  uint32_t te_long_min = inst->te_long - TE_DELTA;
  uint32_t te_long_max = inst->te_long + TE_DELTA;

  bool is_short = (duration >= te_short_min) && (duration <= te_short_max);
  bool is_long = (duration >= te_long_min) && (duration <= te_long_max);

  if (!is_short && !is_long) {
    princeton_reset(instance);
    return;
  }

  // Step 3: State Machine (PWM Decoding)
  switch (inst->state) {
  case STATE_IDLE:
    if (is_short && level) {
      inst->state = STATE_PREAMBLE;
    }
    break;

  case STATE_PREAMBLE:
  case STATE_DATA:
    if (level) {
      // Store high pulse for next evaluation
      inst->last_level = true;
      inst->last_duration = duration;
    } else {
      // Low pulse completes the bit
      // PWM: Short-Long = 0, Long-Short = 1
      if (inst->last_level) {
        bool bit_value;
        if (is_short && inst->last_duration > te_long_min) {
          bit_value = 1; // Long-Short
        } else if (is_long && inst->last_duration < te_short_max) {
          bit_value = 0; // Short-Long
        } else {
          princeton_reset(instance);
          return;
        }

        inst->data = (inst->data << 1) | bit_value;
        inst->bit_count++;
        inst->state = STATE_DATA;
        inst->last_level = false;
      }
    }

    // Check for completion
    if (inst->bit_count >= 24) {
      inst->state = STATE_COMPLETE;
    }
    break;

  default:
    break;
  }
}

bool princeton_deserialize(void *instance, const char *data) {
  // Parse .sub file format: "Key: 0x123456"
  PrincetonInstance *inst = (PrincetonInstance *)instance;
  uint64_t value = 0;
  if (sscanf(data, "Key: 0x%lx", &value) == 1) {
    inst->data = value;
    inst->bit_count = 24;
    inst->state = STATE_COMPLETE;
    return true;
  }
  return false;
}

char *princeton_serialize(void *instance) {
  PrincetonInstance *inst = (PrincetonInstance *)instance;
  static char buffer[128];
  snprintf(buffer, sizeof(buffer),
           "Protocol: Princeton\nKey: 0x%06lX\nBit: 24\n",
           inst->data & 0xFFFFFF);
  return buffer;
}

uint8_t princeton_get_hash(void *instance) {
  PrincetonInstance *inst = (PrincetonInstance *)instance;
  return (inst->data >> 16) ^ (inst->data & 0xFFFF);
}

void princeton_get_string(void *instance, char *buffer, size_t buflen) {
  PrincetonInstance *inst = (PrincetonInstance *)instance;
  snprintf(buffer, buflen, "Princeton 24bit\nKey:0x%06lX",
           inst->data & 0xFFFFFF);
}

// ========== CAME 12-bit Decoder ==========

void *came_alloc(void) {
  CAMEInstance *inst = (CAMEInstance *)malloc(sizeof(CAMEInstance));
  memset(inst, 0, sizeof(CAMEInstance));
  inst->te_short = TE_SHORT;
  return inst;
}

void came_free(void *instance) { free(instance); }

void came_reset(void *instance) {
  CAMEInstance *inst = (CAMEInstance *)instance;
  inst->state = STATE_IDLE;
  inst->data = 0;
  inst->bit_count = 0;
}

void came_feed(void *instance, bool level, uint32_t duration) {
  CAMEInstance *inst = (CAMEInstance *)instance;

  // Gap reset
  if (!level && duration > GAP_RESET * 2) {
    if (inst->state == STATE_DATA && inst->bit_count == 12) {
      inst->state = STATE_COMPLETE;
    }
    came_reset(instance);
    return;
  }

  // Timing validation
  bool is_short =
      (duration >= TE_SHORT - TE_DELTA) && (duration <= TE_SHORT + TE_DELTA);
  bool is_long =
      (duration >= TE_LONG - TE_DELTA) && (duration <= TE_LONG + TE_DELTA);

  if (!is_short && !is_long) {
    came_reset(instance);
    return;
  }

  // Manchester decoding (rising edge = 1, falling = 0)
  if (inst->state == STATE_IDLE && level && is_short) {
    inst->state = STATE_DATA;
  }

  if (inst->state == STATE_DATA) {
    if (level) {
      // Rising edge
      inst->data = (inst->data << 1) | 1;
      inst->bit_count++;
    } else {
      // Falling edge
      inst->data = (inst->data << 1) | 0;
      inst->bit_count++;
    }
  }

  if (inst->bit_count >= 12) {
    inst->state = STATE_COMPLETE;
  }
}

bool came_deserialize(void *instance, const char *data) {
  CAMEInstance *inst = (CAMEInstance *)instance;
  uint32_t value = 0;
  if (sscanf(data, "Key: 0x%x", &value) == 1) {
    inst->data = value & 0xFFF;
    inst->bit_count = 12;
    return true;
  }
  return false;
}

char *came_serialize(void *instance) {
  CAMEInstance *inst = (CAMEInstance *)instance;
  static char buffer[128];
  snprintf(buffer, sizeof(buffer), "Protocol: CAME\nKey: 0x%03X\nBit: 12\n",
           inst->data);
  return buffer;
}

uint8_t came_get_hash(void *instance) {
  CAMEInstance *inst = (CAMEInstance *)instance;
  return inst->data & 0xFF;
}

void came_get_string(void *instance, char *buffer, size_t buflen) {
  CAMEInstance *inst = (CAMEInstance *)instance;
  snprintf(buffer, buflen, "CAME 12bit\nKey:0x%03X", inst->data);
}

// ========== Protocol Registry ==========

static SubGhzProtocolDecoder princeton_protocol = {
    .name = "Princeton",
    .alloc = princeton_alloc,
    .free = princeton_free,
    .reset = princeton_reset,
    .feed = princeton_feed,
    .deserialize = princeton_deserialize,
    .serialize = princeton_serialize,
    .get_hash_data = princeton_get_hash,
    .get_string = princeton_get_string};

static SubGhzProtocolDecoder came_protocol = {.name = "CAME",
                                              .alloc = came_alloc,
                                              .free = came_free,
                                              .reset = came_reset,
                                              .feed = came_feed,
                                              .deserialize = came_deserialize,
                                              .serialize = came_serialize,
                                              .get_hash_data = came_get_hash,
                                              .get_string = came_get_string};

// Export both protocols
SubGhzProtocolDecoder *get_princeton_protocol() { return &princeton_protocol; }

SubGhzProtocolDecoder *get_came_protocol() { return &came_protocol; }
