
import requests
import time
import sys

BASE_URL = "http://localhost:5001/api"

def test_rolljam():
    print("Testing RollJam Start...")
    try:
        r = requests.post(f"{BASE_URL}/attack/rolljam/start", json={"frequency_hz": 433920000})
        print(f"Status: {r.status_code}")
        print(f"Response: {r.text}")
        
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == "started" and "operation_id" in data:
                print("SUCCESS: RollJam started.")
                op_id = data["operation_id"]
                
                time.sleep(2)
                
                print("Testing RollJam Stop...")
                r_stop = requests.post(f"{BASE_URL}/attack/rolljam/stop")
                print(f"Stop Status: {r_stop.status_code}")
                print(f"Stop Response: {r_stop.text}")
            else:
                print("FAILURE: Invalid response format")
        elif r.status_code == 409:
             print("Please restart server, it is busy.")
        else:
            print("FAILURE: API Error")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_rolljam()
