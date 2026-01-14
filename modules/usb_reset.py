#!/usr/bin/env python3
import os
import sys
import fcntl
import subprocess
import glob

def reset_usb_device(dev_path):
    print(f"Resetting {dev_path}...")
    try:
        fd = os.open(dev_path, os.O_WRONLY)
        try:
            # USBDEVFS_RESET = 21780
            USBDEVFS_RESET = ord('U') << (4*2) | 20
            fcntl.ioctl(fd, USBDEVFS_RESET, 0)
            print("Reset successful.")
        finally:
            os.close(fd)
    except Exception as e:
        print(f"Failed to reset: {e}")

def find_hackrf_device():
    # HackRF One VID:PID = 1d50:6089
    # Use lsusb to find bus/device
    try:
        output = subprocess.check_output(['lsusb', '-d', '1d50:6089']).decode()
        if not output:
             print("No HackRF found via lsusb.")
             return None
             
        # Bus 001 Device 005: ID 1d50:6089 Great Scott Gadgets HackRF One
        parts = output.strip().split()
        bus = parts[1]
        dev = parts[3].strip(':')
        
        dev_path = f"/dev/bus/usb/{bus}/{dev}"
        return dev_path
    except Exception as e:
        print(f"Error finding HackRF: {e}")
        return None

if __name__ == "__main__":
    path = find_hackrf_device()
    if path:
        reset_usb_device(path)
    else:
        print("HackRF not found.")
