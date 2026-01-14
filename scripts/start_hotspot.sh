#!/bin/bash
# Wireless Scanner - WiFi Hotspot Mode
# Creates standalone WiFi network for phone/tablet access

set -e

INTERFACE="wlan0"
SSID="SCANNER_CONTROL"
PASSWORD="scanner123"
CHANNEL="6"
SCANNER_IP="192.168.100.1"
DHCP_RANGE="192.168.100.10,192.168.100.100"

echo "🔥 Starting WiFi Hotspot Mode"
echo "================================"

# Check root
if [ "$EUID" -ne 0 ]; then 
    echo "Error: Must run as root"
    echo "Usage: sudo $0"
    exit 1
fi

# Stop conflicting services
echo "[1/6] Stopping conflicting services..."
systemctl stop NetworkManager 2>/dev/null || true
killall wpa_supplicant 2>/dev/null || true
killall hostapd 2>/dev/null || true
killall dnsmasq 2>/dev/null || true

# Configure interface
echo "[2/6] Configuring interface ${INTERFACE}..."
ip link set ${INTERFACE} down
iw dev ${INTERFACE} set type __ap
ip link set ${INTERFACE} up
ip addr flush dev ${INTERFACE}
ip addr add ${SCANNER_IP}/24 dev ${INTERFACE}

# Create hostapd configuration
echo "[3/6] Creating WiFi access point..."
cat > /tmp/scanner_hotspot.conf <<EOF
interface=${INTERFACE}
driver=nl80211
ssid=${SSID}
hw_mode=g
channel=${CHANNEL}
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=${PASSWORD}
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
EOF

# Start hostapd in background
hostapd /tmp/scanner_hotspot.conf > /dev/null 2>&1 &
HOSTAPD_PID=$!
sleep 2

# Create dnsmasq configuration
echo "[4/6] Starting DHCP server..."
cat > /tmp/scanner_dnsmasq.conf <<EOF
interface=${INTERFACE}
dhcp-range=${DHCP_RANGE},12h
dhcp-option=3,${SCANNER_IP}
dhcp-option=6,${SCANNER_IP}
server=8.8.8.8
log-queries
log-dhcp
bind-interfaces
EOF

# Start dnsmasq
dnsmasq -C /tmp/scanner_dnsmasq.conf

# Enable IP forwarding (optional - for internet sharing)
echo "[5/6] Configuring network..."
sysctl -w net.ipv4.ip_forward=1 > /dev/null

echo "[6/6] WiFi Hotspot ACTIVE!"
echo ""
echo "================================"
echo "📱 CONNECT YOUR PHONE/TABLET"
echo "================================"
echo ""
echo "Network Name (SSID): ${SSID}"
echo "Password: ${PASSWORD}"
echo ""
echo "After connecting, open browser to:"
echo "  http://${SCANNER_IP}:5000"
echo ""
echo "or simply:"
echo "  http://scanner:5000"
echo ""
echo "================================"
echo ""
echo "Press Ctrl+C to stop hotspot..."

# Keep running
trap "echo 'Stopping hotspot...'; kill $HOSTAPD_PID 2>/dev/null; killall dnsmasq 2>/dev/null; ip addr flush dev ${INTERFACE}; echo 'Hotspot stopped.'" EXIT

wait $HOSTAPD_PID
