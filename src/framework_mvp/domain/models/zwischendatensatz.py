"""Domänenmodell eines reproduzierbaren Zwischendatensatzes T."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from framework_mvp.domain.exceptions import Domaenenfehler


@dataclass(frozen=True, slots=True)
class Zwischendatensatz:
    """Metadaten der drei zusammengehörenden Interim-Artefakte."""

    zwischendatensatz_id: UUID
    projekt_id: UUID
    transformationsplan_id: UUID
    import_ids: tuple[UUID, ...]
    relativer_daten_pfad: str
    relativer_schema_pfad: str
    relativer_transformation_pfad: str
    sha256: str
    zeilenanzahl: int
    spaltenanzahl: int
    erstellt_am: datetime

    def __post_init__(self) -> None:
        """Prüft Quellen, Prüfsumme, Größen und UTC-Zeitstempel."""
        if not self.import_ids:
            raise Domaenenfehler("Ein Zwischendatensatz benötigt mindestens einen Quellimport.")
        if len(self.sha256) != 64 or any(
            zeichen not in "0123456789abcdef" for zeichen in self.sha256
        ):
            raise Domaenenfehler("Die Prüfsumme des Zwischendatensatzes ist ungültig.")
        if self.zeilenanzahl < 0 or self.spaltenanzahl < 0:
            raise Domaenenfehler("Zeilen- und Spaltenanzahl dürfen nicht negativ sein.")
        if self.erstellt_am.utcoffset() is None:
            raise Domaenenfehler("Der Erstellungszeitpunkt muss zeitzonenbewusst sein.")
        object.__setattr__(self, "erstellt_am", self.erstellt_am.astimezone(UTC))
