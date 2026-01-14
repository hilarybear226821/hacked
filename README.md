# Wireless Asset Discovery & Monitoring Tool

A production-grade multi-protocol wireless asset discovery tool with a unified inventory dashboard. Discovers cameras, sensors, IoT devices, and infrastructure components across Wi-Fi, Bluetooth, and Sub-GHz RF bands.

## Features

### Multi-Protocol Asset Discovery
- **Wi-Fi (2.4/5 GHz)**: Beacon parsing, hidden SSID resolution, device fingerprinting
- **Bluetooth (Classic & BLE)**: Device discovery, GATT service enumeration, static/random MAC analysis
- **Sub-GHz RF (315/433/868/915 MHz)**: Passive monitoring of sensors, remotes, and telemetry signals
- **Zigbee (2.4 GHz)**: Identification of Zigbee mesh nodes and controllers
- **Z-Wave (908/868 MHz)**: Inventory of home automation and environmental sensors

### Unified Inventory Dashboard
- **Real-Time Map**: Unified device list with auto-refresh and pagination
- **Asset Details**: Technical metadata including protocol, manufacturer, and signal strength
- **Lifecycle Management**: TTL-based tracking of active vs stale assets
- **Spectrum Visualization**: Real-time FFT-based waterfall for spectrum occupancy monitoring
- **Physical Entity Mapping**: Cross-protocol correlation to link multiple interfaces (Wi-Fi/BT) to a single physical device

### Advanced Analysis
- **OUI Fingerprinting**: Automatic manufacturer identification via MAC address
- **Identity Inference**: Behavioral analysis to categorize devices (Cameras, Panels, Sensors)
- **Protocol Metadata**: Detailed extraction of technical parameters (SSID, UUIDs, Frequencies)

## Hardware Requirements

- **Wi-Fi Adapter**: Monitor mode capable (e.g., Alfa AWUS036ACH)
- **Bluetooth**: Built-in or USB adapter
- **SDR**: HackRF One or PortaPack H2 (for Sub-GHz/Zigbee/Z-Wave)

## Installation

### 1. Install System Dependencies

```bash
# Debian/Ubuntu
sudo apt-get update
sudo apt-get install -y \
    python3 python3-pip \
    libhackrf-dev hackrf \
    bluetooth bluez libbluetooth-dev \
    aircrack-ng wireless-tools \
    build-essential

# Install Python HackRF bindings
sudo pip3 install hackrf

# Install PyBluez dependencies
sudo pip3 install pybluez
```

### 2. Install Python Dependencies

```bash
cd wireless-asset-discovery
pip3 install -r requirements.txt
```

### 3. Configure Hardware

Edit `config.yaml` to match your hardware:

```yaml
hardware:
  wifi_adapter: "wlan0"       # Your Wi-Fi interface
  bluetooth_adapter: "hci0"   # Bluetooth adapter
  hackrf_device: 0            # HackRF device ID
```

## Usage

### Launching the Tool

```bash
# Run with root privileges (required for raw socket access and SDR control)
sudo python3 main.py --gui tkinter
```

Access the desktop GUI or local logs for discovered assets.

## Configuration

### Scan Settings

```yaml
scanning:
  wifi_enabled: true
  bluetooth_enabled: true
  sdr_enabled: true
  
  # Scan intervals (seconds)
  wifi_interval: 2
  bluetooth_interval: 3
  subghz_interval: 5
  
  # Device TTL
  device_ttl: 60
```


### Sub-GHz Frequencies

```yaml
subghz_frequencies:
  - 315.0    # US garage doors, car keys
  - 433.92   # ISM band (sensors, remotes)
  - 868.35   # EU ISM band
  - 915.0    # US ISM band
```

## Dashboard Interface

### Asset List
- **Real-time updates**: Assets appear automatically as signals are detected
- **Protocol Indicators**: Icons representing Wi-Fi, Bluetooth, or SDR sources
- **Filtering**: By protocol or manufacturer
- **Sorting**: By signal strength or last seen time

### Spectrum Monitor
- Real-time FFT visualization of RF environments
- Multiple band support (433/868/915 MHz, 2.4 GHz)
- Identification of high-utilization channels

### Asset Details View
- **Information**: Complete technical breakdown of the selected device
- **Metadata**: Protocol-specific details (e.g., BLE services, Wi-Fi capabilities)
- **Discovery History**: Temporal tracking of asset presence
- **Manufacturer Identification**: Automatic lookup via OUI database

## Architecture

```
wireless-asset-discovery/
├── core/
│   ├── device_model.py        # Unified asset representation & registry
│   ├── risk_engine.py         # Metadata normalization (Legacy Risk Engine)
│   └── entity_resolver.py     # Cross-protocol physical mapping
├── modules/
│   ├── wifi_monitor.py        # Wi-Fi passive collection
│   ├── bluetooth_monitor.py   # Bluetooth asset scanning
│   ├── sdr_controller.py      # HackRF hardware interface
│   ├── subghz_scanner.py      # Sub-GHz signal monitoring
│   ├── jamming_detector.py    # Spectrum power analysis
│   └── oui_database.py        # MAC vendor identification
├── main.py                    # Entry point & scanner manager
├── config.yaml               # Environment configuration
└── requirements.txt          # Python dependencies
```

## Passive Monitoring Policy

- This tool is designed for passive inventory and asset management
- It does not perform deauthentication, packet injection, or any active disruption
- Operates strictly within listeners for authorized spectrum monitoring
- Comply with local wireless communication laws regarding passive signal analysis

## Troubleshooting

### Wi-Fi Monitor Mode Issues

```bash
# Check if adapter supports monitor mode
iw list | grep "Supported interface modes" -A 10

# Manually enable monitor mode
sudo airmon-ng start wlan0

# Kill interfering processes
sudo airmon-ng check kill
```

### HackRF Not Detected

```bash
# Check device connection
hackrf_info

# Check permissions
sudo chmod 666 /dev/bus/usb/*/※

# Add udev rule (permanent fix)
sudo nano /etc/udev/rules.d/52-hackrf.rules
# Add: SUBSYSTEM=="usb", ATTR{idVendor}=="1d50", ATTR{idProduct}=="6089", MODE="0666"
sudo udevadm control --reload-rules
```

### Bluetooth Scanning Issues

```bash
# Check Bluetooth status
sudo systemctl status bluetooth

# Scan manually
sudo hcitool lescan
```

## Performance Notes

- **FFT Processing**: Real-time spectrum monitoring is designed for minimal CPU overhead
- **Memory**: Tailored for environments with thousands of discovered assets
- **Scalability**: Dashboard updates are throttled to maintain high responsiveness

## Future Enhancements

- Zigbee protocol decoder for industrial sensor nets
- Z-Wave packet analysis for facility management
- NFC/RFID asset tagging integration
- LoRaWAN gateway monitoring
- Export to Prometheus/Grafana
- Historical inventory logging
- Presence alert notifications (webhook)

## License

For authorized asset management and diagnostic research only.

## Author

Created for professional wireless inventory and spectrum analysis.
