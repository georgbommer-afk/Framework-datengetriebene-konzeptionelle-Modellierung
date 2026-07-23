"""Repository-Schnittstelle für bestätigte Importvorgänge."""

from typing import Protocol
from uuid import UUID

from framework_mvp.domain.models import Importvorgang


class ImportvorgangRepository(Protocol):
    """Abstraktion der persistenten Importmetadaten."""

    def speichern(self, importvorgang: Importvorgang) -> None:
        """Speichert einen Importvorgang transaktional."""
        ...

    def laden(self, import_id: UUID) -> Importvorgang | None:
        """Lädt einen Importvorgang anhand seiner ID."""
        ...

    def fuer_projekt_auflisten(self, projekt_id: UUID) -> list[Importvorgang]:
        """Lädt alle Importvorgänge eines Projekts."""
        ...

    def fuer_datenquelle_auflisten(self, datenquellen_id: UUID) -> list[Importvorgang]:
        """Lädt alle Importvorgänge einer Datenquelle."""
        ...
