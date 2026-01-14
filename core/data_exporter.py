"""
Export Module - Export device data to various formats
"""

import json
import csv
import time
from datetime import datetime
from typing import List, Dict
from pathlib import Path

class DataExporter:
    """Export device and scan data to multiple formats"""
    
    @staticmethod
    def export_to_json(devices: List, filename: str = None) -> str:
        """
        Export devices to JSON
        
        Args:
            devices: List of Device objects or dicts
            filename: Output file path (auto-generated if None)
        
        Returns:
            Path to created file
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"wireless_scan_{timestamp}.json"
        
        # Convert devices to dictionaries
        data = {
            'scan_time': datetime.now().isoformat(),
            'total_devices': len(devices),
            'devices': []
        }
        
        for dev in devices:
            if hasattr(dev, 'to_dict'):
                dev_dict = dev.to_dict()
            else:
                dev_dict = dev
            data['devices'].append(dev_dict)
        
        # Write JSON
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"[Export] Saved {len(devices)} devices to {filename}")
        return filename
    
    @staticmethod
    def export_to_csv(devices: List, filename: str = None) -> str:
        """
        Export devices to CSV
        
        Args:
            devices: List of Device objects or dicts
            filename: Output file path (auto-generated if None)
        
        Returns:
            Path to created file
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"wireless_scan_{timestamp}.csv"
        
        if not devices:
            print("[Export] No devices to export")
            return None
        
        # Get device dictionaries
        device_dicts = []
        for dev in devices:
            if hasattr(dev, 'to_dict'):
                device_dicts.append(dev.to_dict())
            else:
                device_dicts.append(dev)
        
        # Get all possible fields
        all_fields = set()
        for dev in device_dicts:
            all_fields.update(dev.keys())
        
        # Sort fields for consistent column order
        fieldnames = sorted(all_fields)
        
        # Write CSV
        with open(filename, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(device_dicts)
        
        print(f"[Export] Saved {len(devices)} devices to {filename}")
        return filename
    
    @staticmethod
    def export_security_report(devices: List, threat_events: List = None, filename: str = None) -> str:
        """
        Generate comprehensive security report in markdown
        
        Args:
            devices: List of devices
            threat_events: List of threat events from automation engine
            filename: Output file path
        
        Returns:
            Path to created file
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"security_report_{timestamp}.md"
        
        report = []
        report.append("# Wireless Security Scan Report\n")
        report.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\\n\\n")
        
        # Summary
        report.append("## Summary\n")
        report.append(f"- **Total Devices:** {len(devices)}\n")
        
        # Device breakdown by protocol
        protocols = {}
        for dev in devices:
            dev_dict = dev.to_dict() if hasattr(dev, 'to_dict') else dev
            proto = dev_dict.get('protocol', 'Unknown')
            protocols[proto] = protocols.get(proto, 0) + 1
        
        report.append("\n### Devices by Protocol\n")
        for proto, count in sorted(protocols.items()):
            report.append(f"- **{proto}:** {count}\n")
        
        # Security cameras/sensors
        report.append("\n## Security Devices Detected\n")
        security_count = 0
        for dev in devices:
            dev_dict = dev.to_dict() if hasattr(dev, 'to_dict') else dev
            dev_type = dev_dict.get('type', '')
            if dev_type in ['CAMERA', 'SENSOR']:
                report.append(f"- {dev_dict.get('name', 'Unknown')} ({dev_type})\n")
                security_count += 1
        
        if security_count == 0:
            report.append("*No security cameras or sensors detected.*\n")
        
        # Threat Events
        if threat_events:
            report.append("\n## Threat Events\n")
            for event in threat_events:
                report.append(f"- **{event.get('type', 'UNKNOWN')}**: {event.get('details', 'N/A')}\n")
        
        # Write report
        with open(filename, 'w') as f:
            f.writelines(report)
        
        print(f"[Export] Security report saved to {filename}")
        return filename
