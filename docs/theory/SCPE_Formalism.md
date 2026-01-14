# Unified Population Acceptance Functional & SCPE Formalism

## 1. Unified Population Acceptance Functional (UPAF)

$$
C := \limsup_{N \to \infty} \sup_{u(\cdot) \in U_{adm}} \mathbb{E} \left[ \frac{1}{N} \sum_{i=1}^N \Gamma_i(x_i(\cdot; \omega, u), u(\cdot)) \right]
$$

where:
- $U_{adm}$ is the set of causal, bounded admissible controls.
- $\Gamma_i : X([0, T]) \times U \to \{0, 1\}$ are acceptance functionals.
- $x_i(\cdot; \omega, u)$ are stochastic trajectories under control $u$.

## 2. Acceptance Entropy Dimension (AED)

Define the acceptance tube thickening:
$$T_\epsilon(A) := \{x : d(x, A) \le \epsilon\}$$

The AED is defined as:
$$
\tilde{D}_A := - \limsup_{\epsilon \to 0} \frac{\log \mu(T_\epsilon(A))}{\log \epsilon}
$$

**Interpretation:**
- $\tilde{D}_A = 0$: Cryptographic (point-like) acceptance.
- $\tilde{D}_A > 0$: Trajectory-thick acceptance (exploitable via SCPE).

## 3. Population Correlation Rank (PCR)

Define vector of functionals $\Gamma^{(N)} := (\Gamma_1, \dots, \Gamma_N)^\top$.

Covariance matrix:
$$
\Sigma_N := \mathbb{E}[\Gamma^{(N)} (\Gamma^{(N)})^\top] - \mathbb{E}[\Gamma^{(N)}] \mathbb{E}[\Gamma^{(N)}]^\top
$$

Population Correlation Rank:
$$
R_P := \limsup_{N \to \infty} \text{rank} \left( \frac{1}{N} \Sigma_N \right)
$$

**Spectral Refinement:**
$\lambda_k := \limsup_{N \to \infty} \lambda_k(\frac{1}{N} \Sigma_N)$.
Then $R_P > 0 \iff \exists k : \lambda_k > 0$.

## 4. Reset Entropy Flux (REF)

Reset times $\{\tau_k\}$, pre/post reset states $X_k^- := X(\tau_k^-), X_k^+ := X(\tau_k^+)$.

Entropy flux rate:
$$
H_R := \liminf_{T \to \infty} \frac{1}{T} \sum_{\tau_k \le T} H(X_k^+ \mid X_k^-)
$$

Net entropy flux (optional):
$$
H_R^{net} := \liminf_{T \to \infty} \frac{1}{T} \sum_{\tau_k \le T} [H(X_k^+ \mid X_k^-) - I(X_k^+; X_{future})]
$$

## 5. Unified Population Acceptance Theorem (Trichotomy)

Exactly one of the following regimes holds:

1.  **Cryptographic Regime:**
    $$ \tilde{D}_A = 0 \implies C = 0 $$
    *(Acceptance is mathematically negligible)*

2.  **Chaotic Regime:**
    $$ R_P = 0 \text{ or } H_R > 0 \implies C = 0 $$
    *(System has no usable correlation or resets destroy entropy)*

3.  **Exploit Regime:**
    $$ \tilde{D}_A > 0 \land R_P > 0 \land H_R = 0 \implies C > 0 $$
    *(Thick acceptance + correlated population + low reset entropy = EXPLOITABLE)*

---

### Summary
- **$C$**: Asymptotic maximal acceptance rate (Success Rate).
- **$\tilde{D}_A$**: Geometric thickness of acceptance (Tolerance).
- **$R_P$**: Latent correlation structure (Common Vulnerability).
- **$H_R$**: Entropy injection via resets (Defensive Randomization).

This formalizes the **State-Conditioned Probabilistic Emulation (SCPE)** approach: we target the "Exploit Regime" where acceptance basins are thick ($\tilde{D}_A > 0$) and stable ($H_R \approx 0$).

## 6. Descriptive Analysis of Defensive Mechanisms (Bypassed Invariants)

The framework explicitly classifies defensive mechanisms by which invariant they fail to maintain in the "Exploit Regime" ($C > 0$).

| Defense Mechanism | Why Bypassed / Invalidated in SCPE | Math Invariant Violated if Defense Holds |
| :--- | :--- | :--- |
| **Cryptographic MACs** | Acceptance set becomes measure-zero in path space (point-like) | $\tilde{D}_A = 0$ (Zero-volume acceptance tube) |
| **Rolling Codes** | Discrete acceptance sets; trajectories fail thickness requirement | $\tilde{D}_A = 0$ (Acceptance is not trajectory-thick) |
| **Per-Device Seeds** | Breaks correlation by isolating device behavior | $R_P = 0$ (Covariance collapse, no latent structure) |
| **Random Resets** | Inject entropy breaking deterministic evolution | $H_R > 0$ (Positive entropy flux destroys correlation) |
| **Clock Jitter** | Induces weak convergence to independence | $R_P \to 0$ (Loss of correlation rank) |
| **Rate Limiting** | Shrinks measure of acceptance tube | $\tilde{D}_A \downarrow 0$ (Acceptance volume approaches zero) |

### Necessary Conditions for SCPE Exploitation

To enable $C > 0$ (successful exploitation), the target system must **simultaneously** satisfy:

1.  **Trajectory-thick acceptance** ($\tilde{D}_A > 0$): The receiver tolerates analog/timing deviations (e.g., analog circuits, flexible firmware).
2.  **Population-level latent correlation** ($R_P > 0$): Devices share common latent states or bugs (e.g., shared vendor firmware, identical physics).
3.  **Zero entropy injection by resets** ($H_R = 0$): Resets are deterministic or state-preserving (e.g., warm reboots, non-volatile state).
