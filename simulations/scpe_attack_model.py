
import numpy as np
import matplotlib.pyplot as plt
from typing import List, Tuple

class SCPEAttackSimulation:
    def __init__(self, N: int = 10000, W: int = 5, noise_std: float = 10.0):
        self.N = N
        self.W = W
        self.noise_std = noise_std
        # Base counter (latent shared structure)
        self.C0 = 1000 
        # Device counters: C_i = C0 + noise_i (Correlated Population, R_P > 0)
        self.counters = self.C0 + np.random.normal(0, self.noise_std, self.N).astype(int)
        
    def acceptance_functional(self, guess: int, counter: int) -> int:
        """Gamma_i: 1 if guess is within window W of counter"""
        return 1 if abs(guess - counter) <= self.W else 0
        
    def calculate_success_rate(self, guess: int) -> float:
        """Approximates C(u) for a given control u (guess)"""
        successes = sum([self.acceptance_functional(guess, c) for c in self.counters])
        return successes / self.N

    def simulate_attack(self, guess_range: Tuple[int, int]):
        """Scan guesses to find optimal g"""
        guesses = range(guess_range[0], guess_range[1])
        success_rates = [self.calculate_success_rate(g) for g in guesses]
        return guesses, success_rates

    def defense_random_seeds(self):
        """Simulate R_P -> 0 (Per-device random seeds)"""
        # Counters are now uniformly distributed, no correlation
        self.counters = np.random.randint(0, 10000, self.N) 

    def defense_rate_limiting(self):
         """Simulate D_A -> 0 (Shrinking window)"""
         self.W = 0 # Point-like acceptance

    def defense_random_resets(self):
        """Simulate H_R > 0 (High entropy resets)"""
        # Counters drift randomly after reset
        self.counters += np.random.randint(-500, 500, self.N)


def run_simulation():
    print("=== SCPE Attack Simulation (UPAF) ===")
    
    # Scene 1: Exploit Regime (Thick, Correlated, Stable)
    sim = SCPEAttackSimulation(N=10000, W=5, noise_std=15.0)
    guesses, rates = sim.simulate_attack((900, 1100))
    max_rate = max(rates)
    best_guess = guesses[np.argmax(rates)]
    print(f"[Exploit Regime] Max Success Rate (C): {max_rate:.4f} at Guess: {best_guess}")
    
    # Scene 2: Defense - Random Seeds (R_P -> 0)
    sim_rand = SCPEAttackSimulation(N=10000, W=5)
    sim_rand.defense_random_seeds()
    _, rates_rand = sim_rand.simulate_attack((900, 1100))
    print(f"[Defense: Rand Seeds] Max Success Rate (C): {max(rates_rand):.4f} (Correlation Broken)")

    # Scene 3: Defense - Rate Limiting (D_A -> 0)
    sim_tight = SCPEAttackSimulation(N=10000, W=5, noise_std=15.0)
    sim_tight.defense_rate_limiting() # W=0
    _, rates_tight = sim_tight.simulate_attack((900, 1100))
    print(f"[Defense: Rate Limit] Max Success Rate (C): {max(rates_tight):.4f} (Window Collapsed)")

if __name__ == "__main__":
    run_simulation()
