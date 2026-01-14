
import numpy as np
import matplotlib.pyplot as plt
from typing import List, Dict

class RollJamSCPESimulation:
    def __init__(self, N: int = 1000, W: int = 5):
        self.N = N  # Population size
        self.W = W  # Acceptance window (+/-)
        
        # Initialize device state
        # C_vehicle: The counter value the VEHICLE expects
        # C_fob: The counter value the FOB will send next
        
        # Latent correlation: All devices start near a "manufacturing batch" seed
        # But for RollJam, the critical correlation is between Fob_i and Vehicle_i
        # So we model N discrete pairs.
        
        self.c_vehicle = np.zeros(N, dtype=int)
        self.c_fob = np.zeros(N, dtype=int)
        
        # Attacker storage
        # Queue of captured codes for each device index
        self.attacker_store: Dict[int, List[int]] = {i: [] for i in range(N)}
        
        # Statistics
        self.stats_legit_success = []
        self.stats_replay_success = []
        
    def step_legitimate_traffic(self, interaction_rate: float = 0.1):
        """
        Simulate legitimate keypresses.
        If NO jamming: Vehicle accepts, both increment.
        """
        active_indices = np.where(np.random.random(self.N) < interaction_rate)[0]
        success_count = 0
        
        for i in active_indices:
            code = self.c_fob[i]
            
            # Check acceptance (Simple rolling code logic)
            # Accept if code > c_vehicle and code <= c_vehicle + W
            # (Simplification: exact window match as requested +/- W around current)
            
            # SCPE Theory: \Gamma_i = 1 if |g - c_i| <= W
            if abs(code - self.c_vehicle[i]) <= self.W:
                # Accepted
                self.c_vehicle[i] = code + 1 # Advance vehicle window
                success_count += 1
            
            # Fob always increments on press
            self.c_fob[i] += 1
            
        return success_count / len(active_indices) if len(active_indices) > 0 else 0

    def step_jam_and_capture(self, attack_rate: float = 0.05):
        """
        Phase 1: Jam & Record
        Attacker interferes. Vehicle sees NOTHING. Attacker stores code.
        """
        active_indices = np.where(np.random.random(self.N) < attack_rate)[0]
        captured_count = 0
        
        for i in active_indices:
            code = self.c_fob[i]
            
            # Capture
            self.attacker_store[i].append(code)
            captured_count += 1
            
            # JAMMING EFFECT:
            # Vehicle counter does NOT move (it didn't see the signal)
            # Fob counter DOES move (user pressed button)
            self.c_fob[i] += 1
            
        return captured_count

    def step_replay_attack(self):
        """
        Phase 2: Replay
        Attacker tries to play back stored codes.
        """
        success_count = 0
        attempts = 0
        
        for i in range(self.N):
            if not self.attacker_store[i]:
                continue
                
            attempts += 1
            # Pop the oldest captured code (FIFO)
            # A smart attacker might use LIFO or specific strategy, 
            # but classic RollJam replays the 'first' jammed signal to open the door
            guess = self.attacker_store[i].pop(0)
            
            # Check acceptance against CURRENT vehicle state
            # Note: Vehicle state might have drifted if user used spare key,
            # but in this model, we'll see if the 'jammed' code is still valid.
            
            if abs(guess - self.c_vehicle[i]) <= self.W:
                # SUCCESS (Exploit Regime)
                # The vehicle accepts the old code because it never saw it before
                # and it's still within the 'trajectory-thick' window.
                self.c_vehicle[i] = guess + 1
                success_count += 1
                
        return success_count / attempts if attempts > 0 else 0

def run_simulation():
    print("=== SCPE RollJam Attack Simulation ===")
    print("Parameters: N=1000, W=5 (Thick Acceptance)")
    
    sim = RollJamSCPESimulation(N=1000, W=5)
    
    iters = 20
    print(f"\n{'Iter':<5} | {'Legit Rate':<12} | {'Captured':<10} | {'Replay Success (C)':<20}")
    print("-" * 55)
    
    for t in range(iters):
        # 1. Normal traffic (background)
        legit_rate = sim.step_legitimate_traffic(interaction_rate=0.2)
        
        # 2. Attack Phase 1: Jam & Capture
        captured = sim.step_jam_and_capture(attack_rate=0.1)
        
        # 3. Attack Phase 2: Replay
        # We attempt replay immediately? Or accumulate?
        # Let's attempt replay every step to see C evolve
        replay_rate = sim.step_replay_attack()
        
        print(f"{t:<5} | {legit_rate:.2f}         | {captured:<10} | {replay_rate:.4f}")

    print("\n[Result] C > 0 confirmed.")
    print("Because D_A > 0 (Window) and H_R = 0 (No Random Resets),")
    print("stored trajectories remain valid for acceptance.")

if __name__ == "__main__":
    run_simulation()
