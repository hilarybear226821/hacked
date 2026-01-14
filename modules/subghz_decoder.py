from abc import ABC, abstractmethod

class SubGhzProtocolDecoder(ABC):
    """Abstract base for Sub‑GHz protocol decoders.
    Subclasses must implement allocation, pulse feeding, deserialization,
    and a human‑readable name.
    """

    @abstractmethod
    def alloc(self) -> None:
        """Allocate any required state for this decoder instance."""
        pass

    @abstractmethod
    def feed(self, level: int, duration: int) -> None:
        """Ingest a raw pulse.
        *level* is the signal level (0/1) and *duration* is microseconds.
        The implementation should translate the duration into a timing element
        (e.g., TE_SHORT or TE_LONG) based on protocol‑specific thresholds.
        """
        pass

    @abstractmethod
    def deserialize(self) -> str:
        """Convert the validated pulse sequence into a hex string payload.
        Returns the decoded data or raises a ValueError if the sequence is
        invalid.
        """
        pass

    @abstractmethod
    def get_string(self) -> str:
        """Human‑readable protocol name (e.g., "Princeton Doorbell")."""
        pass
