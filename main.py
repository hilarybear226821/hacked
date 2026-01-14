#!/usr/bin/env python3
"""
Wireless Asset Discovery Tool - Main Entry Point
Multi-protocol wireless asset discovery and monitoring with unified inventory
"""

import os
import sys
import signal
import argparse
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from dashboard.app import Dashboard, load_config


def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully"""
    print("\n[Main] Shutdown signal received")
    if 'dashboard' in globals():
        dashboard.shutdown()
    sys.exit(0)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Wireless Asset Discovery Tool - Unified Inventory',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with default config
  sudo python main.py
  
  # Run with custom config
  sudo python main.py --config custom_config.yaml
  
  # Run on specific port
  sudo python main.py --port 8080
  
Note: Requires root/sudo for:
  - Wi-Fi monitor mode
  - Bluetooth scanning
  - HackRF device access
        """
    )
    
    parser.add_argument(
        '--config',
        default='config.yaml',
        help='Path to configuration file (default: config.yaml)'
    )
    
    parser.add_argument(
        '--port',
        type=int,
        help='Dashboard port (overrides config)'
    )
    
    parser.add_argument(
        '--host',
        help='Dashboard host (overrides config)'
    )
    
    parser.add_argument(
        '--no-wifi',
        action='store_true',
        help='Disable Wi-Fi scanning'
    )
    
    parser.add_argument(
        '--no-bluetooth',
        action='store_true',
        help='Disable Bluetooth scanning'
    )
    
    parser.add_argument(
        '--no-sdr',
        action='store_true',
        help='Disable SDR/HackRF scanning'
    )
    
    parser.add_argument(
        '--gui',
        choices=['web', 'tkinter'],
        default='web',
        help='UI mode: web (Flask dashboard) or tkinter (Desktop GUI)'
    )
    
    args = parser.parse_args()
    
    # Check if running as root
    if os.geteuid() != 0:
        print("⚠️  Warning: Not running as root. Some features may not work.")
        print("   Wi-Fi monitor mode and HackRF access typically require root.")
        response = input("Continue anyway? (y/N): ")
        if response.lower() != 'y':
            sys.exit(1)
    
    # Load configuration
    print(f"[Main] Loading configuration from {args.config}")
    config = load_config(args.config)
    
    if not config:
        print(f"[Main] Failed to load config from {args.config}")
        print("[Main] Using default configuration")
        config = {}
    
    # Apply command line overrides
    if args.port:
        config.setdefault('dashboard', {})['port'] = args.port
    
    if args.host:
        config.setdefault('dashboard', {})['host'] = args.host
    
    # Enforce SDR-only mode by default
    config.setdefault('scanning', {})['wifi_enabled'] = False
    config.setdefault('scanning', {})['bluetooth_enabled'] = False
    config.setdefault('scanning', {})['sdr_enabled'] = True
    
    # Apply command line overrides (allow enabling if explicitly asked, though Phase 9 says purge)
    if args.no_sdr:
        config.setdefault('scanning', {})['sdr_enabled'] = False
    
    # Setup signal handler
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Print banner
    print_banner()
    
    # Check if using Tkinter GUI
    if args.gui == 'tkinter':
        print("[Main] Launching Tkinter Desktop GUI...")
        from tkinter_gui import WirelessScannerGUI
        app = WirelessScannerGUI(config)
        app.run()
        return
    
    # Otherwise use web dashboard
    # Create and configure dashboard
    global dashboard
    dashboard = Dashboard(config)
    
    # Initialize scanners
    print("[Main] Initializing scanner modules...")
    dashboard.initialize_scanners()
    
    # Print access information
    host = config.get('dashboard', {}).get('host', '0.0.0.0')
    port = config.get('dashboard', {}).get('port', 5000)
    
    print("\n" + "="*60)
    print("Dashboard Access:")
    print(f"  Local:    http://localhost:{port}")
    if host == '0.0.0.0':
        print(f"  Network:  http://<your-ip>:{port}")
    print("="*60 + "\n")
    
    # Start dashboard server
    try:
        dashboard.run()
    except KeyboardInterrupt:
        print("\n[Main] Shutting down...")
        dashboard.shutdown()
    except Exception as e:
        print(f"\n[Main] Error: {e}")
        dashboard.shutdown()
        sys.exit(1)


def print_banner():
    """Print application banner"""
    banner = """
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║        🔍 Wireless Asset Discovery Tool - Unified Inventory  ║
║                                                              ║
║        Multi-Protocol Asset Detection & Monitoring          ║
║        Sub-GHz (SDR) • Signal Intelligence                  ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
    """
    print(banner)


if __name__ == '__main__':
    main()
