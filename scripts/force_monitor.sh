#!/bin/bash

# Force Monitor Mode on Interface
# Usage: ./force_monitor.sh <interface>

IFACE=$1

if [ -z "$IFACE" ]; then
    echo "Usage: $0 <interface>"
    exit 1
fi

echo "[*] Setting up monitor mode on $IFACE..."

# 1. Kill interfering processes
echo "    > Killing wpa_supplicant/NetworkManager..."
sudo airmon-ng check kill > /dev/null 2>&1
sudo killall wpa_supplicant > /dev/null 2>&1
sudo killall NetworkManager > /dev/null 2>&1
sleep 1

# 2. Reset RF
echo "    > Unblocking RF..."
sudo rfkill unblock wifi
sudo rfkill unblock all

# 3. Bring Down & Rename
echo "    > Bringing interface DOWN..."
sudo ip link set $IFACE down
sleep 0.5

# Rename to wlan0mon (Standard Convention)
if [ "$IFACE" != "wlan0mon" ]; then
    echo "    > Renaming $IFACE to wlan0mon..."
    sudo ip link set $IFACE name wlan0mon
    IFACE="wlan0mon"
fi

# 4. Set Mode
echo "    > Setting Monitor Mode on $IFACE..."
sudo iw dev $IFACE set type monitor

# 5. Bring Up
echo "    > Bringing interface UP..."
sudo ip link set $IFACE up
sleep 0.5

# 6. Apply Intel Fixes
echo "    > Applying Intel AX201 Fixes (Power Save OFF)..."
sudo iw dev $IFACE set power_save off > /dev/null 2>&1
sudo iw dev $IFACE set channel 6 > /dev/null 2>&1

# 7. Verify
MODE=$(iw dev $IFACE info | grep type | awk '{print $2}')
echo "[*] Done. Current Mode: $MODE"

if [ "$MODE" == "monitor" ]; then
    exit 0
else
    exit 1
fi
