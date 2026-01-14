#!/bin/bash
# Installation script for Wireless Security Scanner

set -e

echo "======================================================"
echo "  Wireless Security Scanner - Installation Script"
echo "======================================================"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "⚠️  This script should be run as root (sudo)"
    echo "Some dependencies require root access to install"
    exit 1
fi

echo "[1/5] Installing system dependencies..."

# Detect OS
if [ -f /etc/debian_version ]; then
    apt-get update
    apt-get install -y \
        python3 python3-pip python3-dev \
        libhackrf-dev hackrf \
        bluetooth bluez libbluetooth-dev \
        aircrack-ng wireless-tools iw \
        build-essential libffi-dev \
        git wget
elif [ -f /etc/redhat-release ]; then
    yum install -y \
        python3 python3-pip python3-devel \
        hackrf hackrf-devel \
        bluez bluez-libs-devel \
        aircrack-ng wireless-tools \
        gcc make libffi-devel \
        git wget
else
    echo "⚠️  Unsupported OS. Please install dependencies manually."
    echo "Required: python3, hackrf, bluez, aircrack-ng"
fi

echo ""
echo "[2/5] Installing Python dependencies..."

pip3 install -r requirements.txt

echo ""
echo "[3/5] Setting up HackRF udev rules..."

# Create udev rule for HackRF
cat > /etc/udev/rules.d/52-hackrf.rules << 'EOF'
# HackRF One
SUBSYSTEM=="usb", ATTR{idVendor}=="1d50", ATTR{idProduct}=="6089", MODE="0666", GROUP="plugdev"
EOF

# Reload udev rules
udevadm control --reload-rules
udevadm trigger

echo ""
echo "[4/5] Creating data directory..."

mkdir -p data
chmod 755 data

echo ""
echo "[5/5] Downloading OUI database..."

cd data
if [ ! -f oui.txt ]; then
    wget -q http://standards-oui.ieee.org/oui/oui.txt || echo "⚠️  OUI download failed (will download on first run)"
fi
cd ..

echo ""
echo "======================================================"
echo "  Installation Complete!"
echo "======================================================"
echo ""
echo "Next steps:"
echo "  1. Edit config.yaml to match your hardware"
echo "  2. Run: sudo python3 main.py"
echo "  3. Open browser to: http://localhost:5000"
echo ""
echo "Hardware checklist:"
echo "  ☐ Wi-Fi adapter supporting monitor mode"
echo "  ☐ Bluetooth adapter (built-in or USB)"
echo "  ☐ HackRF One or PortaPack H2"
echo ""
echo "For help, see README.md"
echo "======================================================"
