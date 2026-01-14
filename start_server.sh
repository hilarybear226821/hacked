#!/bin/bash
# SDR Backend Startup Script

# Set port
export PORT=${1:-5001}

# Aggressive Cleanup
echo "Cleaning up existing instances..."
fuser -k -9 $PORT/tcp 2>/dev/null
pkill -9 -f "web_server.py" 2>/dev/null
pkill -9 -f "hackrf_transfer" 2>/dev/null
sleep 1

echo "Starting SDR Backend on port $PORT..."
python3 web_server.py
