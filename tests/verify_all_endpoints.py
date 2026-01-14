#!/usr/bin/env python3
"""
Complete Backend Verification - All Endpoints
"""

import requests
import sys

BASE_URL = "http://localhost:5001"

def test_all_endpoints():
    """Test all backend endpoints"""
    print("=" * 60)
    print("Complete Backend Endpoint Verification")
    print("=" * 60 + "\n")
    
    endpoints = [
        # Core
        ("GET", "/api/status", "Status"),
        ("GET", "/api/capabilities", "Capabilities"),
        ("GET", "/api/state", "State"),
        ("GET", "/api/logs", "Logs"),
        
        # Device
        ("POST", "/api/device/open", "Device Open"),
        ("POST", "/api/device/close", "Device Close"),
        
        # Attacks
        ("GET", "/api/attack/camera_jammer/cameras", "Camera List"),
        
        # Stubs
        ("GET", "/api/subghz/live", "SubGHz Live"),
        ("GET", "/api/terminal/output", "Terminal Output"),
        ("POST", "/api/stop_all", "Emergency Stop"),
    ]
    
    passed = 0
    failed = 0
    
    for method, path, name in endpoints:
        try:
            url = f"{BASE_URL}{path}"
            if method == "GET":
                r = requests.get(url, timeout=2)
            else:
                r = requests.post(url, json={}, timeout=2)
            
            if r.status_code in [200, 409]:  # 409 = already running, acceptable
                print(f"✅ {name:30s} [{r.status_code}]")
                passed += 1
            else:
                print(f"❌ {name:30s} [{r.status_code}]")
                failed += 1
        except Exception as e:
            print(f"❌ {name:30s} [ERROR: {str(e)[:40]}]")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"Results: {passed}/{passed+failed} endpoints working")
    
    if failed == 0:
        print("✅ ALL ENDPOINTS OPERATIONAL")
    else:
        print(f"⚠️  {failed} endpoints failed")
    
    print("=" * 60)
    
    return failed == 0

if __name__ == "__main__":
    success = test_all_endpoints()
    sys.exit(0 if success else 1)
