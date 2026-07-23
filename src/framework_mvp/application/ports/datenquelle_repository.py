"""Repository-Schnittstelle für den Datenquellenkatalog."""

from typing import Protocol
from uuid import UUID

from framework_mvp.domain.models import Datenquelle


class DatenquelleRepository(Protocol):
    """Abstraktion der persistenten Datenquellenablage."""

    def speichern(self, datenquelle: Datenquelle) -> None:
        """Speichert eine neue oder aktualisierte Datenquelle."""
        ...

    def laden(self, datenquellen_id: UUID) -> Datenquelle | None:
        """Lädt eine Datenquelle anhand ihrer ID."""
        ...

    def fuer_projekt_auflisten(self, projekt_id: UUID) -> list[Datenquelle]:
        """Lädt alle Datenquellen eines Projekts."""
        ...
