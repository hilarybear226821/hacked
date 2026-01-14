#!/bin/bash
# Launcher for Wireless Security Scanner GUI
# CRITICAL: GUI must run unprivileged - hardware access requires udev rules or setcap

set -euo pipefail

# Resolve actual script location (handles symlinks correctly)
SCRIPT_DIR="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
cd "$SCRIPT_DIR"

# === Environment Diagnostics ===
echo "[Launcher] Python Executable: $(which python3)"
echo "[Launcher] Python Version: $(python3 --version 2>&1)"
echo "[Launcher] Working Directory: $PWD"
echo ""

# === Security Check ===
if [ "$EUID" -eq 0 ]; then
    echo "ERROR: Do NOT run this GUI as root."
    echo ""
    echo "Running GUIs as root is a security risk and breaks display ownership."
    echo ""
    echo "If you need hardware access for SDR/WiFi:"
    echo "  1. Set up udev rules (recommended)"
    echo "  2. Use setcap on specific binaries"
    echo "  3. Or use a helper subprocess with pkexec/sudo -n"
    echo ""
    echo "Never run the entire GUI process as root."
    exit 1
fi

# === Display Environment ===
# Use existing DISPLAY or fall back to :0 (minimal, safe default)
export DISPLAY="${DISPLAY:-:0}"

# Export XAUTHORITY if not set (required for Tk on many systems)
if [ -z "${XAUTHORITY:-}" ]; then
    # Try common location, but don't fail if missing
    if [ -f "$HOME/.Xauthority" ]; then
        export XAUTHORITY="$HOME/.Xauthority"
    fi
fi

echo "[Launcher] Display: $DISPLAY"
[ -n "${XAUTHORITY:-}" ] && echo "[Launcher] XAuthority: $XAUTHORITY"

# === Wayland Detection ===
if [ -n "${WAYLAND_DISPLAY:-}" ]; then
    echo ""
    echo "WARNING: Wayland session detected."
    echo "This application requires X11. Some features may not work correctly:"
    echo "  - Input handling"
    echo "  - Focus management"
    echo "  - Clipboard operations"
    echo "  - SDR hotkeys"
    echo ""
    echo "Recommendation: Run in an X11 session or use XWayland compatibility mode."
    echo ""
    read -p "Continue anyway? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 0
    fi
fi

# === Dependency Validation ===
echo "[Launcher] Checking dependencies..."

# Check Python Tkinter
if ! python3 - <<'EOF' 2>/dev/null
import tkinter
EOF
then
    echo "ERROR: python3-tk is not installed."
    echo ""
    echo "Install with:"
    echo "  Debian/Ubuntu: sudo apt install python3-tk"
    echo "  Fedora/RHEL:   sudo dnf install python3-tkinter"
    echo "  Arch:          sudo pacman -S tk"
    exit 1
fi

# Check if Tk can actually connect to the display
if ! python3 - <<'EOF' 2>/dev/null
import tkinter
root = tkinter.Tk()
root.destroy()
EOF
then
    echo "ERROR: Tkinter cannot connect to display $DISPLAY"
    echo ""
    echo "Possible causes:"
    echo "  1. DISPLAY is set incorrectly"
    echo "  2. XAUTHORITY is missing or incorrect"
    echo "  3. X server is not running"
    echo "  4. Running over SSH without X11 forwarding (use: ssh -X)"
    echo ""
    echo "Debug steps:"
    echo "  - Check if X is running: ps aux | grep X"
    echo "  - Try: xhost +local:"
    echo "  - Verify XAUTHORITY: echo \$XAUTHORITY"
    exit 1
fi

echo "[Launcher] ✓ Tkinter OK"

# Check for required SDR tools (optional, warn only)
if ! command -v hackrf_info &>/dev/null; then
    echo "[Launcher] ⚠ hackrf_info not found - HackRF features will not work"
fi

# === Launch GUI ===
echo ""
echo "[Launcher] Starting Wireless Security Scanner GUI..."
echo ""

exec python3 tkinter_gui.py
