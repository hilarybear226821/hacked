# SCPE Attack Real-World Implementation — High-Level Coding Plan

This document outlines the 8-layer architecture for the real-world implementation of the **State-Conditioned Probabilistic Emulation (SCPE)** engine within the `hacked` platform.

## 1. Hardware Abstraction Layer (HAL)
**Goal:** Abstract interaction with real SDR hardware (HackRF, LimeSDR, etc.).
**Existing Mapping:** `modules/sdr_controller.py` (`SDRController`, `ProcessManager`).

*   **Core Responsibilities:**
    *   Frequency tuning & gain control.
    *   Start/stop RX streaming with precise sample buffering.
    *   Start/stop TX streaming with low-latency waveform output.
    *   Timing and synchronization (hardware timestamping if available).
    *   Jamming waveform generation (noise, pulses).
    *   Buffer and error handling for real-time streaming.

*   **Key Interfaces:**
    *   `set_frequency(freq_hz)`
    *   `set_gain(gain_db)`
    *   `start_rx() / stop_rx()`
    *   `read_samples()` → IQ samples buffer
    *   `start_tx() / stop_tx()`
    *   `write_samples(waveform)` → transmit IQ samples
    *   `jam(duration, pattern)` → send interference during RX window

## 2. Signal Processing & Detection Layer
**Goal:** Process raw IQ samples to detect and decode signals.
**Existing Mapping:** `modules/auto_rolljam.py` (`SignalDetector`), `modules/subghz_scanner.py`.

*   **Core Responsibilities:**
    *   Apply filtering, demodulation (ASK/OOK/FSK etc.).
    *   Perform synchronization & bit extraction (decode symbols).
    *   Detect preambles, packet structures, and rolling code payloads.
    *   Extract metadata: frequency, timestamp, SNR, device ID.
    *   Track signal quality and confidence scores.

*   **Key Interfaces:**
    *   `process_samples(iq_buffer)` → list of `SignalDetection` events
    *   `decode_packet(signal_detection)` → decoded payload, counters
    *   `estimate_device_id(decoded_payload)` → unique target identifier

## 3. Population State Management Layer
**Goal:** Maintain estimated states of multiple targets.
**Existing Mapping:** `modules/scpe_engine.py` (`DeviceState`, `PopulationManager`).

*   **Core Responsibilities:**
    *   Store per-device state: counters, last seen time, capture queue.
    *   Model acceptance window size ($\tilde{D}_A$) and correlate across devices ($R_P$).
    *   Track entropy injection/reset events ($H_R$).
    *   Provide thread-safe access and updates.

*   **Key Interfaces:**
    *   `register_device(device_id, protocol, freq)`
    *   `update_capture(device_id, decoded_packet)`
    *   `get_replay_candidate(device_id)` → best stored code
    *   `update_state_on_replay_success(device_id)`

## 4. Attack Orchestration Layer
**Goal:** Coordinate SCPE attack steps.
**Existing Mapping:** `modules/scpe_engine.py` (`SCPEAttackController`).

*   **Core Responsibilities:**
    *   Decide logic: Listen vs Jam vs Capture vs Replay.
    *   Implement multi-step sequences:
        *   **Listen**: Passively gather codes.
        *   **Jam**: Freeze device state.
        *   **Capture**: Store intercepted valid codes.
        *   **Replay**: Transmit stored codes with SCPE modifications.
        *   **State Steering**: Inject conditioning signals.
    *   Manage timing critical sequences.
    *   Dynamically switch attack modes (`GHOST_REPLAY`, `STATE_STEERING`).

*   **Key Interfaces:**
    *   `start_attack() / stop_attack()`
    *   `perform_jam(device_id, duration)`
    *   `capture_signal(device_id, signal_detection)`
    *   `execute_replay(device_id, mode)`
    *   `steer_state(device_id)`

## 5. Waveform Generation & Signal Synthesis Layer
**Goal:** Create precise waveform samples for replay and jamming.
**Status:** **Needs Implementation** (Extension of `packet_generator.py`).

*   **Core Responsibilities:**
    *   Generate baseband modulation (OOK, FSK) for protocols.
    *   **Thickening**: Apply pulse shaping and jittering for $\tilde{D}_A$ exploitation.
    *   Incorporate timing offsets and power ramping.
    *   Convert bitstreams to complex IQ waveforms.

*   **Key Interfaces:**
    *   `generate_waveform(decoded_packet, mode)` → IQ numpy array
    *   `apply_jitter(waveform, params)`
    *   `apply_state_steering_modifications(waveform)`

## 6. Timing & Synchronization Manager
**Goal:** Ensure precise timing coordination.
**Status:** Architecture defined, partially handled by `SDRController`.

*   **Core Responsibilities:**
    *   High-resolution scheduling for TX/RX windows.
    *   Clock drift management.
    *   Precise delays between jamming end and replay start.

*   **Key Interfaces:**
    *   `schedule_event(callback, timestamp)`
    *   `get_current_time()`
    *   `wait_until(timestamp)`

## 7. Logging, Monitoring, & Feedback Layer
**Goal:** Record attack states and adapt.
**Existing Mapping:** `web_server.py`, `modules/events.py`.

*   **Core Responsibilities:**
    *   Store per-device attack statistics.
    *   Log SDR hardware status.
    *   Real-time feedback via Websockets.
    *   Feed metrics to adaptive control logic.

*   **Key Interfaces:**
    *   `log_event(device_id, event_type, details)`
    *   `get_attack_statistics(device_id)`
    *   `report_status()`

## 8. System Orchestration and Main Loop
**Goal:** Tie all components together.
**Existing Mapping:** `modules/scpe_engine.py` (Integration logic).

*   **Core Responsibilities:**
    *   Initialize all layers.
    *   Start RX streaming.
    *   Update population state on detection.
    *   Manage concurrency.
    *   Clean shutdown.

---

### Summary Matrix

| Layer | Responsibility | Key Challenges | Status in `hacked` |
| :--- | :--- | :--- | :--- |
| **1. HAL** | Hardware I/O | Latency, Buffering | ✅ `SDRController` |
| **2. Signal Proc** | Detection/Decoding | Noise, Demod | ✅ `AutoRollJam`/`SignalDetector` |
| **3. State Mgr** | Population Modeling | Multi-target Threading | ✅ `PopulationManager` |
| **4. Orchestration** | Logic & Decisions | Timing, Adaptation | ✅ `SCPEAttackController` |
| **5. Waveform** | Synthesis (Jitter) | Protocol Accuracy | ⚠️ Partial (`packet_generator`) |
| **6. Timing** | Precision Sched | Clock Drift | ⚠️ Implicit |
| **7. Logging** | Feedback | Data Volume | ✅ `EventBus` |
| **8. System** | Lifecycle | Concurrency | ✅ `scpe_engine.py` |
