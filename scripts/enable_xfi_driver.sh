#!/bin/bash
# enable_xfi_driver.sh
# Configures the Wi-Fi interface to pass FCS-failed (corrupted) frames to userspace.
# This is required for XFi (Cross-Technology) signal hitchhiking.

INTERFACE=$1

if [ -z "$INTERFACE" ]; then
    echo "Usage: $0 <interface>"
    exit 1
fi

# Helper to run as root if needed
run_with_privilege() {
    if [ "$EUID" -ne 0 ]; then
        sudo "$@"
    else
        "$@"
    fi
}

echo "[XFi] Configuring driver for $INTERFACE..."

# Ensure interface is down before configuring
run_with_privilege ip link set "$INTERFACE" down

# Set monitor mode (if not already)
run_with_privilege iw dev "$INTERFACE" set type monitor

# Enable FCS fail (pass bad frames)
# This command is specific to cfg80211/mac80211 drivers
run_with_privilege iw dev "$INTERFACE" set monitor fcsfail

# Bring interface up
run_with_privilege ip link set "$INTERFACE" up

# Check if flag was accepted
FLAGS=$(run_with_privilege iw dev "$INTERFACE" info | grep "monitor flags")
if [[ "$FLAGS" == *"fcsfail"* ]]; then
    echo "[XFi] SUCCESS: fcsfail flag enabled on $INTERFACE"
    exit 0
else
    echo "[XFi] WARNING: fcsfail flag not seen. Driver might not support it."
    # We exit 0 anyway so the scanner proceeds (maybe in partial mode)
    exit 0
fi
