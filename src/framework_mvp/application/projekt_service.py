"""Anwendungsservice für die Projektverwaltung."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from framework_mvp.application.ports.projekt_repository import ProjektRepository
from framework_mvp.domain.exceptions import Domaenenfehler, ProjektNichtGefunden
from framework_mvp.domain.models import (
    BeteiligtePerson,
    Projekt,
    Projektstatus,
    Untersuchungsauftrag,
)


class ProjektService:
    """Orchestriert fachliche Projektoperationen und deren Speicherung."""

    def __init__(self, repository: ProjektRepository) -> None:
        """Erzeugt den Service mit einem austauschbaren Repository."""
        self._repository = repository

    def projekt_anlegen(
        self,
        *,
        bezeichnung: str,
        untersuchungsauftrag: Untersuchungsauftrag,
        beteiligte_personen: tuple[BeteiligtePerson, ...] = (),
    ) -> Projekt:
        """Erzeugt und speichert ein neues Projekt."""
        projekt = Projekt.neu(
            bezeichnung=bezeichnung,
            untersuchungsauftrag=untersuchungsauftrag,
            status=Projektstatus.ENTWURF,
            beteiligte_personen=beteiligte_personen,
        )
        self._repository.speichern(projekt)
        return projekt

    def projekt_laden(self, projekt_id: UUID) -> Projekt | None:
        """Lädt ein Projekt oder gibt bei unbekannter ID nichts zurück."""
        return self._repository.laden(projekt_id)

    def projekte_auflisten(self) -> list[Projekt]:
        """Gibt alle gespeicherten Projekte zurück."""
        return self._repository.auflisten()

    def projekt_aktualisieren(
        self,
        projekt_id: UUID,
        *,
        bezeichnung: str,
        untersuchungsauftrag: Untersuchungsauftrag,
        status: Projektstatus,
        beteiligte_personen: tuple[BeteiligtePerson, ...] = (),
    ) -> Projekt:
        """Aktualisiert ein vorhandenes Projekt kontrolliert und speichert die Kopie."""
        projekt = self._repository.laden(projekt_id)
        if projekt is None:
            raise ProjektNichtGefunden(f"Das Projekt mit der ID {projekt_id} wurde nicht gefunden.")
        aktualisiert = projekt.aktualisiert(
            bezeichnung=bezeichnung,
            untersuchungsauftrag=untersuchungsauftrag,
            status=status,
            beteiligte_personen=beteiligte_personen,
        )
        self._repository.speichern(aktualisiert)
        return aktualisiert

    def betrachtungszeitraum_aus_event_log_aktualisieren(
        self,
        projekt_id: UUID,
        *,
        fruehester_ereigniszeitpunkt: datetime,
        spaetester_ereigniszeitpunkt: datetime,
    ) -> Projekt:
        """Übernimmt den fachlichen Zeitraum ausschließlich aus einem erzeugten Event Log."""
        projekt = self._repository.laden(projekt_id)
        if projekt is None:
            raise ProjektNichtGefunden(f"Das Projekt mit der ID {projekt_id} wurde nicht gefunden.")
        if (
            fruehester_ereigniszeitpunkt.utcoffset() is None
            or spaetester_ereigniszeitpunkt.utcoffset() is None
        ):
            raise Domaenenfehler(
                "Ereigniszeitpunkte für den Betrachtungszeitraum müssen zeitzonenbewusst sein."
            )
        from framework_mvp.domain.models import (
            Betrachtungszeitraum,
            BetrachtungszeitraumModus,
        )

        zeitraum = Betrachtungszeitraum(
            BetrachtungszeitraumModus.AUS_DATEN,
            fruehester_ereigniszeitpunkt.astimezone(UTC).date(),
            spaetester_ereigniszeitpunkt.astimezone(UTC).date(),
        )
        auftrag = replace(projekt.untersuchungsauftrag, betrachtungszeitraum=zeitraum)
        aktualisiert = projekt.aktualisiert(
            bezeichnung=projekt.bezeichnung,
            untersuchungsauftrag=auftrag,
            status=projekt.status,
            beteiligte_personen=projekt.beteiligte_personen,
        )
        self._repository.speichern(aktualisiert)
        return aktualisiert
