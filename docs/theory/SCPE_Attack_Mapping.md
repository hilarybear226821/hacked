# SCPE: From Theory to Operational Attack (Mapping Strategy)

 This document maps the **Unified Population Acceptance Functional (UPAF)** theory to concrete software control structures for the `hacked` platform.

## 1. The Mapping Dictionary

We translate abstract control variables into `hacked` system parameters.

| Abstract Variable | Control Theory Interpretation | `hacked` Implementation Parameter | Physical/SDR Action |
| :--- | :--- | :--- | :--- |
| **$x_t$ (State)** | Hidden internal state of receiver (AGC, timer, shift reg) | `ReceiverStateModel` (Hidden Markov Model) | None (Inferred) |
| **$u_t$ (Control)** | Input stimulus trajectory | `IQSampleStream` (Generated) | TX Waveform (Amplitude/Time) |
| **$\tilde{D}_A$ (AED)** | Acceptance Tolerance / Tube Thickness | `tolerance_profile` (JSON) | Variations in pulse width ($\pm$ %), jitter |
| **$R_P$ (PCR)** | Population Correlation / Shared Logic | `UniversalDeviceProfile` | "Generic" preamble/sync structures |
| **$H_R$ (REF)** | Receiver State Reset / Entropy | `SessionPersistence` | Continuous jamming/keep-alive to prevent reset |
| **$C$ (UPAF)** | Success Probability | `confidence_score` | Probability of `Open` event |

## 2. Concrete Attack Vectors

### Attack A: "The Ghost Replay" (Exploiting $\tilde{D}_A > 0$)
**Target:** Fixed-code gates/garages with strict timing but sloppy analog front-ends.

*   **Theory:** The receiver fails to reject signals that deviate in analog shape if they maintain "state trajectory" (trigger the right comparators).
*   **Implementation:**
    1.  **Capture**: Record a valid signal.
    2.  **Analyze**: Measure `short_pulse_us`, `long_pulse_us`.
    3.  **Thicken**: Generate a new signal where every pulse is randomized within $[t - \epsilon, t + \epsilon]$ (where $\epsilon \propto \tilde{D}_A$).
    4.  **Execute**: Transmit the "thickened" signal. This effectively covers a wider volume of the state space, bypassing simple anti-replay checks that rely on exact bit-matching logic if the receiver over-samples.

### Attack B: "State Steering / Conditioning" (Exploiting AGC & $H_R = 0$)
**Target:** Receivers with slow AGC or clock recovery (e.g., cheap OOK modules).

*   **Theory:** Drive the receiver state $x_t$ to a known $x_{ready}$ before sending the payload.
*   **Implementation:**
    1.  **Pre-Condition ($t_0 \to t_1$):** Send continuous carrier (CW) or noise at specific power $P_{target}$.
        *   *Effect:* Forces Receiver AGC to clamp gain to specific level.
        *   *Result:* $x_{AGC}$ is now deterministic, not random.
    2.  **State Hold ($t_1 \to t_2$):** Send "Valid Silence" (Guard Interval).
        *   *Effect:* Receiver logic resets "Bit Counter" but AGC remains stable.
    3.  **Payload Injection ($t > t_2$):** Send the minimal energy required to trigger the "High" comparator.
        *   *Result:* Because AGC is clamped, a weaker signal works, bypassing "Signal Strength" filters or battery saving sleep modes.

### Attack C: "Population Fuzzing" (Exploiting $R_P > 0$)
**Target:** Rolling code systems where implementation bugs are correlated across the population (same chipset).

*   **Theory:** Devices from Vendor X share the same pseudo-random number generator state weakness or timing glitch.
*   **Implementation:**
    1.  **Profile:** Derive a "Canonical Trajectory" from $N$ different devices.
    2.  **Synthesize:** Create a "Super-Stimulus" $u^*(\cdot)$ that lies in the intersection of acceptance basins for the population.
    3.  **Blast:** One transmission opens multiple devices or opens a specific device without needing its specific seed, by triggering the common failure mode.

## 3. Operational Workflow (The `SCPE_Engine`)

We will build a new engine `SCPEEngine` that orchestrates these phases.

#### Phase 1: Ingestion (Observation)
*   **Input:** Raw IQ recordings from `SubGhzRecorder`.
*   **Process:**
    *   Extract Pulse Train.
    *   Estimate `ToleranceProfile` ($\tilde{D}_A$).
    *   Identify Protocol Family ($R_P$ link).

#### Phase 2: Trajectory Generation (Planning)
*   **Goal:** Generate $u(t)$ to maximize $\mathbb{E}[\text{Acceptance}]$.
*   **Algorithm:**
    *   Start with `BaseTrajectory` (the recorded signal).
    *   Apply `StateConditioning` (Pre-ambles, AGC locking).
    *   Apply `TubeThickening` (Jitter injection, Pulse shaping).

#### Phase 3: Execution (Control) 
*   **Action:** `sdr.transmit(stream)`.
*   **Feedback:** If available (e.g., "Gate Opened"), reinforce the successful parameters ($C$ increases).

## 4. Final System "Truth"
By implementing this, we assert:
> "We do not replay messages. We replay the *conditions of acceptance*."

This creates a robust attack framework that withstands standard patches like "check for exact duplicate frame" because we never send an exact duplicate—we send a *statistically equivalent* trajectory.
