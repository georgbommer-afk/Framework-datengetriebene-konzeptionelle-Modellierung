"""Unveränderliche Modelle kanonischer Event-Log-Artefakte."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from framework_mvp.domain.exceptions import Domaenenfehler


class EventLogStatus(StrEnum):
    """Lebenszyklus eines gespeicherten Event Logs."""

    ENTWURF = "entwurf"
    ERZEUGT = "erzeugt"
    UNGUELTIG = "ungueltig"


@dataclass(frozen=True, slots=True)
class EventLogArtefakt:
    """Metadaten eines kanonischen, unveränderlichen Event Logs."""

    event_log_id: UUID
    projekt_id: UUID
    zwischendatensatz_id: UUID
    mapping_id: UUID
    status: EventLogStatus
    ereignisanzahl: int
    fallanzahl: int
    aktivitaetsanzahl: int
    zeitraum_von: datetime | None
    zeitraum_bis: datetime | None
    relativer_csv_pfad: str
    relativer_schema_pfad: str
    relativer_lineage_pfad: str
    relativer_xes_pfad: str
    sha256: str
    erstellt_am: datetime

    def __post_init__(self) -> None:
        """Prüft Größen, Prüfsumme und zeitzonenbewussten Erstellungszeitpunkt."""
        if min(self.ereignisanzahl, self.fallanzahl, self.aktivitaetsanzahl) < 0:
            raise Domaenenfehler("Event-Log-Kennzahlen dürfen nicht negativ sein.")
        if len(self.sha256) != 64:
            raise Domaenenfehler("Die Event-Log-Prüfsumme ist ungültig.")
        if self.erstellt_am.utcoffset() is None:
            raise Domaenenfehler("Der Erstellungszeitpunkt muss zeitzonenbewusst sein.")
        object.__setattr__(self, "erstellt_am", self.erstellt_am.astimezone(UTC))
