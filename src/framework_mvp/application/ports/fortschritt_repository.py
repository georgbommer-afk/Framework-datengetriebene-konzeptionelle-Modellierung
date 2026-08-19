"""Port zum Rekonstruieren des Fortschritts aus gespeicherten Fachartefakten."""

from typing import Protocol
from uuid import UUID


class FortschrittRepository(Protocol):
    def hoechster_gespeicherter_schritt(self, projekt_id: UUID) -> int: ...
