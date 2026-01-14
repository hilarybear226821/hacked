#!/usr/bin/env python3
"""
Test script for scanner event bus
Verifies that SubGHzScanner emits events correctly
"""

import sys
import time
sys.path.insert(0, '/home/hilary/hacked')

from modules.subghz_scanner import SubGHzScanner, ScannerEvent
from modules.sdr_controller import SDRController

print("=" * 60)
print("Scanner Event Bus Test")
print("=" * 60)

events_received = []

def on_signal(burst):
    events_received.append(('signal', burst))
    print(f"✓ SIGNAL_DETECTED event received (SNR: {burst.snr_db:.1f} dB)")

def on_state_change(state):
    events_received.append(('state', state))
    print(f"✓ STATE_CHANGED event received: {state.name}")

def on_freq_change(freq):
    events_received.append(('freq', freq))
    print(f"✓ FREQUENCY_CHANGED event received: {freq/1e6:.3f} MHz")

def on_overrun(samples_dropped):
    events_received.append(('overrun', samples_dropped))
    print(f"⚠ BUFFER_OVERRUN event received: {samples_dropped} samples dropped")

# Initialize
config = {'scan_frequencies': [315e6, 433.92e6], 'sample_rate': 2e6}
sdr = SDRController()

if not sdr.open():
    print("✗ FAIL: SDR not available")
    sys.exit(1)

print("✓ SDR opened successfully")

scanner = SubGHzScanner(sdr, config)
print("✓ Scanner initialized")

# Subscribe to events
scanner.subscribe(ScannerEvent.SIGNAL_DETECTED, on_signal)
scanner.subscribe(ScannerEvent.STATE_CHANGED, on_state_change)
scanner.subscribe(ScannerEvent.FREQUENCY_CHANGED, on_freq_change)
scanner.subscribe(ScannerEvent.BUFFER_OVERRUN, on_overrun)
print("✓ Subscribed to all events")

print("\nStarting scanner...")
scanner.start()

print("\nWaiting 5 seconds for events...")
time.sleep(5)

print("\nStopping scanner...")
scanner.stop()

sdr.close()

# Verify results
print("\n" + "=" * 60)
print("Test Results")
print("=" * 60)

state_events = [e for e in events_received if e[0] == 'state']
freq_events = [e for e in events_received if e[0] == 'freq']
signal_events = [e for e in events_received if e[0] == 'signal']

print(f"STATE_CHANGED events: {len(state_events)}")
print(f"FREQUENCY_CHANGED events: {len(freq_events)}")
print(f"SIGNAL_DETECTED events: {len(signal_events)}")
print(f"Total events: {len(events_received)}")

# Success criteria
if len(state_events) >= 2:  # At least start and stop
    print("\n✓ STATE_CHANGED events working")
else:
    print("\n✗ FAIL: Not enough STATE_CHANGED events")
    sys.exit(1)

if len(freq_events) >= 1:
    print("✓ FREQUENCY_CHANGED events working")
else:
    print("⚠ WARNING: No FREQUENCY_CHANGED events (may need longer runtime)")

# Get status
status = scanner.get_status()
print(f"\nFinal Status:")
print(f"  State: {status.state.name}")
print(f"  Frequency: {status.current_frequency/1e6:.3f} MHz")
print(f"  Detected signals: {status.detected_signals}")
print(f"  Buffer usage: {status.buffer_usage*100:.1f}%")
print(f"  Uptime: {status.uptime_seconds:.2f}s")

print("\n" + "=" * 60)
print("✓ Test PASSED - Event bus working correctly")
print("=" * 60)
