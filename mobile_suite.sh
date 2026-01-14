#!/bin/bash
# SDR Mobile Suite Orchestrator - v1.0
# Combined Backend + Mobile Bridge

echo "🚀 Starting SDR Mobile Suite..."

# 1. Cleanup legacy SDR locks
echo "🧹 Cleaning up legacy SDR processes (hackrf_transfer)..."
sudo pkill -9 hackrf_transfer 2>/dev/null || true
echo "🧹 Killing old web server instances..."
pkill -f web_server.py 2>/dev/null || true

# 1b. Check dependencies
if ! pip3 show flask-cors &> /dev/null; then
    echo "📦 Installing missing dependency: flask-cors..."
    pip3 install flask-cors --break-system-packages
fi
if ! pip3 show zeroconf &> /dev/null; then
    echo "📦 Installing missing dependency: zeroconf..."
    pip3 install zeroconf --break-system-packages
fi

# 2. Start Backend Web Server in background
echo "🌐 Starting Flask Backend (web_server.py)..."
python3 web_server.py > backend.log 2>&1 &
BACKEND_PID=$!

# Wait for backend to bind
sleep 2
if ps -p $BACKEND_PID > /dev/null; then
    echo "✅ Backend started (PID: $BACKEND_PID, Logging to backend.log)"
else
    echo "❌ Backend failed to start. Check backend.log"
    exit 1
fi

# 3. Setup ADB Bridge
if command -v adb &> /dev/null; then
    DEVICE_COUNT=$(adb devices | grep -v "List" | grep "device" | wc -l)
    if [ "$DEVICE_COUNT" -gt 0 ]; then
        echo "🔌 Setting up ADB reverse port forwarding (5000 -> 5000)..."
        adb reverse tcp:5000 tcp:5000
        echo "✅ Mobile Bridge Active!"
    else
        echo "⚠️ No Android devices found over USB. WiFi mode only."
    fi
else
    echo "⚠️ ADB not found. Skipping bridge setup."
fi

echo ""
echo "📱 Mobile Suite is ready!"
echo "- Mobile URL: http://localhost:5000 (over ADB) or your laptop IP (over WiFi)"
echo "- Press Ctrl+C to stop the suite."

# 4. Wait for interrupt and cleanup
function cleanup {
    echo ""
    echo "⏹️ Stopping Mobile Suite..."
    kill $BACKEND_PID
    echo "Done."
    exit
}

trap cleanup SIGINT

# Keep script running to maintain bridge and log backend status
while true; do
    if ! ps -p $BACKEND_PID > /dev/null; then
        echo "⚠️ Backend crashed! Check backend.log"
        exit 1
    fi
    sleep 5
done
