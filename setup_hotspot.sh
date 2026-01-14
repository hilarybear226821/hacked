#!/bin/bash
# SDR Hotspot Setup - Wireless but Offline access
# Creates a local WAP so your phone can connect directly to the laptop.

SSID="SDR_INTELLIGENCE_SUITE"
PASS="hacktheplanet"

if ! command -v nmcli &> /dev/null; then
    echo "❌ nmcli not found. This script requires NetworkManager."
    exit 1
fi

echo "🚀 Creating Offline Hotspot..."
echo "SSID: $SSID"
echo "Password: $PASS"

# 1. Delete existing connection if it exists
sudo nmcli con delete "$SSID" &> /dev/null || true

# 2. Create the hotspot
sudo nmcli con add type wifi ifname "*" con-name "$SSID" autoconnect yes ssid "$SSID"
sudo nmcli con modify "$SSID" 802-11-wireless.mode ap 802-11-wireless.band bg ipv4.method shared
sudo nmcli con modify "$SSID" wifi-sec.key-mgmt wpa-psk
sudo nmcli con modify "$SSID" wifi-sec.psk "$PASS"

# 3. Start the hotspot
echo "📡 Starting $SSID..."
sudo nmcli con up "$SSID"

if [ $? -eq 0 ]; then
    echo "✅ Hotspot Active!"
    echo "Connect your phone to '$SSID' using password '$PASS'."
    echo "Then launch the SDR Mobile Suite: ./mobile_suite.sh"
else
    echo "❌ Failed to start hotspot. Ensure your WiFi card supports AP mode."
fi
