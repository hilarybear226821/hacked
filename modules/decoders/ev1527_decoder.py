from ..subghz_decoder import SubGhzProtocolDecoder

class EV1527Decoder(SubGhzProtocolDecoder):
    """
    Decoder for EV1527 protocol.
    Characteristic timing (TE): ~300-400us
    Logic 0: 1 TE High, 3 TE Low
    Logic 1: 3 TE High, 1 TE Low
    Sync/Preamble: 1 TE High, 31 TE Low
    Frame: 20 bits code + 4 bits data (24 bits total)
    """

    TE_THRESHOLD = 500

    def __init__(self):
        self.pulses = []

    def alloc(self) -> None:
        self.pulses = []

    def feed(self, level: int, duration: int) -> None:
        if duration < self.TE_THRESHOLD:
            element = 'TE_SHORT'
        else:
            element = 'TE_LONG'
        self.pulses.append((level, element))

    def deserialize(self) -> str:
        bits = ''
        i = 0
        while i < len(self.pulses) - 1:
            lev1, elem1 = self.pulses[i]
            lev2, elem2 = self.pulses[i+1]
            
            if lev1 == 1 and lev2 == 0:
                if elem1 == 'TE_SHORT' and elem2 == 'TE_LONG':
                    bits += '0'
                elif elem1 == 'TE_LONG' and elem2 == 'TE_SHORT':
                    bits += '1'
                i += 2
            else:
                i += 1

        if len(bits) < 24:
            raise ValueError('Insufficient bits for EV1527 payload')
            
        try:
            # Last 24 bits
            payload = bits[-24:]
            val = int(payload, 2)
            return f"{val:06X}"
        except:
            raise ValueError('Invalid bitstream')

    def get_string(self) -> str:
        return "EV1527 Sensor"
