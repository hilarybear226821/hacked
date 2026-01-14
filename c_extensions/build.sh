#!/bin/bash
# Build all C extensions for MITM

set -e

echo "[+] Building C extensions..."

# Build packet processing library
echo "[+] Building libmitm_packet.so..."
gcc -shared -fPIC -O3 -Wall \
    -o libmitm_packet.so \
    libmitm_packet.c

# Build SSL/TLS library
echo "[+] Building libmitm_ssl.so..."
gcc -shared -fPIC -O3 -Wall \
    -o libmitm_ssl.so \
    libmitm_ssl.c \
    -lssl -lcrypto

echo "[+] Testing libraries..."
if [ -f "libmitm_packet.so" ] && [ -f "libmitm_ssl.so" ]; then
    echo "[✓] libmitm_packet.so: $(ls -lh libmitm_packet.so | awk '{print $5}')"
    echo "[✓] libmitm_ssl.so: $(ls -lh libmitm_ssl.so | awk '{print $5}')"
else
    echo "[✗] Build failed"
    exit 1
fi

echo "[+] Build complete"
