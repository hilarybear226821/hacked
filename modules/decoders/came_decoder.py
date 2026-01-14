from ..subghz_decoder import SubGhzProtocolDecoder

class CameDecoder(SubGhzProtocolDecoder):
    """Decoder for CAME garage door remote (315 MHz).
    The protocol uses OOK with a pre‑amble of 8 bits (0xAA) followed by
    a 24‑bit payload (address + command). Durations:
    * TE_SHORT ≈ 500 µs
    * TE_LONG  ≈ 1500 µs
    """

    TE_SHORT = 500
    TE_LONG = 1500

    def __init__(self):
        self.pulses = []

    def alloc(self) -> None:
        self.pulses = []

    def feed(self, level: int, duration: int) -> None:
        # Convert duration to timing element based on thresholds
        if duration < (self.TE_SHORT + self.TE_LONG) / 2:
            element = 'TE_SHORT'
        else:
            element = 'TE_LONG'
        self.pulses.append((level, element))

    def _bits_from_pulses(self) -> str:
        # CAME encodes bits as high pulse durations
        bits = ''
        for level, elem in self.pulses:
            if level == 1:
                if elem == 'TE_SHORT':
                    bits += '0'
                else:
                    bits += '1'
        return bits

    def deserialize(self) -> str:
        bits = self._bits_from_pulses()
        # Expect at least preamble + payload (8 + 24 = 32 bits)
        if len(bits) < 32:
            raise ValueError('Insufficient bits for CAME payload')
        # Strip preamble (first 8 bits)
        payload_bits = bits[8:32]
        # Convert to hex string
        payload_int = int(payload_bits, 2)
        return f"{payload_int:06X}"  # 24‑bit payload as 6‑digit hex

    def get_string(self) -> str:
        return "CAME Garage Door Remote"
