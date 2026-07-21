"""Repository-Schnittstelle für Projekte."""

from typing import Protocol
from uuid import UUID

from framework_mvp.domain.models import Projekt


class ProjektRepository(Protocol):
    """Abstraktion der dauerhaften Projektablage."""

    def speichern(self, projekt: Projekt) -> None:
        """Speichert ein neues oder aktualisiertes Projekt."""
        ...

    def laden(self, projekt_id: UUID) -> Projekt | None:
        """Lädt ein Projekt anhand seiner eindeutigen ID."""
        ...

    def auflisten(self) -> list[Projekt]:
        """Lädt alle Projekte in reproduzierbarer Reihenfolge."""
        ...
