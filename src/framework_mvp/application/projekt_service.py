"""Anwendungsservice für die Projektverwaltung."""

from uuid import UUID

from framework_mvp.application.ports.projekt_repository import ProjektRepository
from framework_mvp.domain.exceptions import ProjektNichtGefunden
from framework_mvp.domain.models import Projekt, Projektstatus, Untersuchungsauftrag


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
        status: Projektstatus = Projektstatus.ENTWURF,
        beteiligte_personen: tuple[str, ...] = (),
    ) -> Projekt:
        """Erzeugt und speichert ein neues Projekt."""
        projekt = Projekt.neu(
            bezeichnung=bezeichnung,
            untersuchungsauftrag=untersuchungsauftrag,
            status=status,
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
        beteiligte_personen: tuple[str, ...] = (),
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
