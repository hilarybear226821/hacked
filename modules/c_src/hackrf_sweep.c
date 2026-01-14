/*
 * hackrf_sweep.c
 * High-performance frequency hopper with Universal Protocol Decoder
 *
 * Uses libhackrf directly.
 * Implements OOK Demodulation + Flipper-like Protocol Decoding.
 */

#define _DEFAULT_SOURCE // For usleep and other BSD/POSIX extensions

#include "subghz_protocols.h"
#include <libhackrf/hackrf.h>
#include <math.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define SAMPLE_RATE 20000000.0 // 20 MHz
#define LNA_GAIN 32
#define VGA_GAIN 30
#define SWEEP_BUFFER_SIZE 131072 // Renamed to avoid libhackrf conflict

// Target frequencies (Hz)
const uint64_t TARGETS[] = {315000000, 433920000, 868350000, 915000000};
const int NUM_TARGETS = 4;

hackrf_device *device = NULL;
volatile int do_exit = 0;
uint64_t current_freq = 0;
int current_target_idx = 0;

// Protocol Decoders
void *princeton_inst = NULL;

// Pulse Engine State
bool last_level = false;
uint32_t current_duration_samples = 0;
double noise_floor = 0.001; // Initial low value

// --- Pulse Engine ---

void process_pulse(bool level, uint32_t duration_samples) {
  // Convert samples to microseconds
  uint32_t duration_us =
      (uint32_t)((double)duration_samples * 1000000.0 / SAMPLE_RATE);

  // Feed Princeton
  if (princeton_protocol.feed(princeton_inst, level, duration_us)) {
    uint64_t data = 0;
    uint32_t bits = 0;
    if (princeton_protocol.deserialize(princeton_inst, &data, &bits)) {
      char desc[64];
      princeton_protocol.get_string(princeton_inst, desc, sizeof(desc));

      // Output JSON
      printf("{\"type\": \"decode\", \"protocol\": \"%s\", \"info\": \"%s\", "
             "\"data\": \"%llX\", \"freq\": %llu, \"ts\": %ld}\n",
             princeton_protocol.name, desc, (unsigned long long)data,
             (unsigned long long)current_freq, time(NULL));
      fflush(stdout);

      princeton_protocol.reset(princeton_inst);
    }
  }
}

void process_block(void *buffer, int length) {
  int8_t *buf = (int8_t *)buffer; // Signed 8-bit I/Q

  // Adaptive thresholding: Update noise floor infrequently
  // Simple OOK: Magnitude > Threshold

  // Optimizing loop: process every Nth sample to save CPU?
  // No, for pulse width we need resolution. But at 20MHz, 1 sample is 0.05us.
  // TE_SHORT is ~300us (6000 samples). We can skip a bit.

  // Let's use magnitude squared to avoid sqrt()
  // Threshold sq = 0.01 (approx -20dB relative) varies by gain
  // Actually, HackRF samples are -128 to 127.
  // Noise floor is typically ~10-20. MagSq ~ 200-400. Signal ~ 10000.

  int threshold_sq = 2000; // Hardcoded for now, typical for strong signal

  for (int i = 0; i < length; i += 2) { // i=I, i+1=Q
    int32_t i_val = buf[i];
    int32_t q_val = buf[i + 1];
    int32_t mag_sq = i_val * i_val + q_val * q_val;

    bool level = (mag_sq > threshold_sq);

    if (level == last_level) {
      current_duration_samples++;
    } else {
      // Edge detected
      process_pulse(last_level, current_duration_samples);
      last_level = level;
      current_duration_samples = 0;
    }
  }
}

// Simple RSSI calculation in dB (Legacy support)
double calculate_rssi(void *buffer, int length) {
  int8_t *buf = (int8_t *)buffer;
  double sum_sq = 0;
  int step = 10; // Skip samples for speed
  for (int i = 0; i < length; i += step) {
    sum_sq += buf[i] * buf[i];
  }
  double mean_sq = sum_sq / (length / step);
  if (mean_sq < 1.0)
    mean_sq = 1.0;
  return 10.0 * log10(mean_sq) - 40.0;
}

int rx_callback(hackrf_transfer *transfer) {
  if (do_exit)
    return -1;

  // 1. Process Protocols
  process_block(transfer->buffer, transfer->valid_length);

  // 2. RSSI periodic report (keep it scarce)
  // Only report if likely signal present
  double rssi = calculate_rssi(transfer->buffer, transfer->valid_length);
  if (rssi > -50.0) {
    printf(
        "{\"type\": \"signal\", \"freq\": %llu, \"rssi\": %.2f, \"ts\": %ld}\n",
        (unsigned long long)current_freq, rssi, time(NULL));
    fflush(stdout);
  }

  return 0;
}

void hop_timer() {
  while (!do_exit) {
    current_target_idx = (current_target_idx + 1) % NUM_TARGETS;
    current_freq = TARGETS[current_target_idx];

    int result = hackrf_set_freq(device, current_freq);
    if (result != HACKRF_SUCCESS) {
      fprintf(stderr, "hackrf_set_freq() failed: %s\n",
              hackrf_error_name(result));
    }

    // Reset decoders on hop
    princeton_protocol.reset(princeton_inst);

    // Fast hop: 200ms dwell time
    usleep(200000);
  }
}

int main() {
  int result;

  // Init Decoders
  princeton_inst = princeton_protocol.alloc();

  result = hackrf_init();
  if (result != HACKRF_SUCCESS) {
    fprintf(stderr, "hackrf_init() failed: %s\n", hackrf_error_name(result));
    return EXIT_FAILURE;
  }

  result = hackrf_open(&device);
  if (result != HACKRF_SUCCESS) {
    fprintf(stderr, "hackrf_open() failed: %s\n", hackrf_error_name(result));
    hackrf_exit();
    return EXIT_FAILURE;
  }

  // Configure
  hackrf_set_sample_rate(device, SAMPLE_RATE);
  hackrf_set_amp_enable(device, 0);
  hackrf_set_lna_gain(device, LNA_GAIN);
  hackrf_set_vga_gain(device, VGA_GAIN);

  // Initial freq
  current_freq = TARGETS[0];
  hackrf_set_freq(device, current_freq);

  // Start RX
  result = hackrf_start_rx(device, rx_callback, NULL);
  if (result != HACKRF_SUCCESS) {
    fprintf(stderr, "hackrf_start_rx() failed: %s\n",
            hackrf_error_name(result));
    hackrf_close(device);
    hackrf_exit();
    return EXIT_FAILURE;
  }

  fprintf(stderr,
          "{\"type\": \"status\", \"msg\": \"Universal Decoder Started\"}\n");

  // Main thread handles hopping
  hop_timer();

  hackrf_stop_rx(device);
  hackrf_close(device);
  hackrf_exit();

  // Free decoders
  princeton_protocol.free(princeton_inst);

  return EXIT_SUCCESS;
}
