/*
 * subghz_protocols.h
 * Universal Sub-GHz Protocol Decoder Interface
 * Architecture influenced by Flipper Zero / Derek Jamison
 */

#ifndef SUBGHZ_PROTOCOLS_H
#define SUBGHZ_PROTOCOLS_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// --- Interface Definition ---

typedef struct SubGhzProtocolDecoder SubGhzProtocolDecoder;

struct SubGhzProtocolDecoder {
  const char *name;
  void *(*alloc)(void);
  void (*free)(void *instance);
  void (*reset)(void *instance);

  /**
   * Feed a level/duration pair.
   * @param instance Decoder instance
   * @param level Logic level (true=High, false=Low)
   * @param duration Duration of the pulse in microseconds
   * @return true if a frame is complete and ready to deserialize
   */
  bool (*feed)(void *instance, bool level, uint32_t duration);

  /**
   * Deserialize the captured data into a simplified hash/ID.
   * @param out_data The 64-bit extracted key/data
   * @param out_bits The number of bits decoded
   * @return true on success
   */
  bool (*deserialize)(void *instance, uint64_t *out_data, uint32_t *out_bits);

  /**
   * Get a human-readable string representation of the data.
   */
  void (*get_string)(void *instance, char *buffer, size_t len);
};

// Expose the Princeton protocol instance
extern const SubGhzProtocolDecoder princeton_protocol;

#ifdef __cplusplus
}
#endif

#endif // SUBGHZ_PROTOCOLS_H
