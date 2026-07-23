"""Port für persistierte Event-Log-Metadaten."""

from typing import Protocol
from uuid import UUID

from framework_mvp.domain.models import EventLogArtefakt


class EventLogRepository(Protocol):
    """Abstrakter Speichervertrag für Event Logs."""

    def speichern(self, artefakt: EventLogArtefakt) -> None:
        """Speichert ein Event Log."""
        ...

    def laden(self, event_log_id: UUID) -> EventLogArtefakt | None:
        """Lädt ein Event Log."""
        ...

    def fuer_projekt(self, projekt_id: UUID) -> list[EventLogArtefakt]:
        """Listet Event Logs eines Projekts."""
        ...
