#!/bin/bash
# Prepare Mobile Connection (USB/ADB)

# 1. Check for ADB
if ! command -v adb &> /dev/null; then
    echo "❌ ADB not found. Please install android-tools-adb."
    exit 1
fi

# 2. Check for connected devices
DEVICE_COUNT=$(adb devices | grep -v "List" | grep "device" | wc -l)
if [ "$DEVICE_COUNT" -eq 0 ]; then
    echo "❌ No Android devices found over USB."
    echo "Ensure 'USB Debugging' is enabled in Developer Options."
    exit 1
fi

# 3. Setup Port Forwarding
# This allows the phone to reach 'localhost:5000' and talk to the PC
echo "🔌 Setting up ADB reverse port forwarding (5000 -> 5000)..."
adb reverse tcp:5000 tcp:5000

if [ $? -eq 0 ]; then
    echo "✅ Success! The Android app can now connect to http://localhost:5000"
    echo "Keep this script or terminal open while using the mobile app."
else
    echo "❌ Failed to setup port forwarding."
fi
