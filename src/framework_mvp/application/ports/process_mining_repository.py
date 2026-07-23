"""Port für persistierte Process-Mining-Analysen."""

from typing import Protocol
from uuid import UUID

from framework_mvp.domain.models import ProcessMiningAnalyse


class ProcessMiningRepository(Protocol):
    """Abstrakter Speichervertrag für Discovery-Metadaten."""

    def speichern(self, analyse: ProcessMiningAnalyse) -> None:
        """Speichert eine ausgeführte Analyse unveränderlich."""
        ...

    def laden(self, analyse_id: UUID) -> ProcessMiningAnalyse | None:
        """Lädt eine Analyse anhand ihrer ID."""
        ...

    def fuer_projekt(self, projekt_id: UUID) -> list[ProcessMiningAnalyse]:
        """Listet die Analysen eines Projekts stabil auf."""
        ...
