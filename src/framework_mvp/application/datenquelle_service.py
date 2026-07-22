"""Anwendungsservice für den Datenquellenkatalog Q."""

from uuid import UUID

from framework_mvp.application.ports.datenquelle_repository import DatenquelleRepository
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import Datenquelle, Quellenart, Quellsystemtyp


class DatenquelleService:
    """Orchestriert das Anlegen, Laden und Aktualisieren von Datenquellen."""

    def __init__(self, repository: DatenquelleRepository) -> None:
        """Erzeugt den Service mit einem austauschbaren Repository."""
        self._repository = repository

    def datenquelle_anlegen(
        self,
        *,
        projekt_id: UUID,
        bezeichnung: str,
        quellsystemtyp: Quellsystemtyp,
        quellenart: Quellenart,
        konkretes_quellsystem: str = "",
        fachliche_beschreibung: str = "",
        herkunft_oder_verantwortungsbereich: str = "",
        erwartete_tabellen_oder_blaetter: tuple[str, ...] = (),
        bekannte_schluesselattribute: tuple[str, ...] = (),
    ) -> Datenquelle:
        """Erzeugt und speichert eine neue Datenquelle."""
        datenquelle = Datenquelle.neu(
            projekt_id=projekt_id,
            bezeichnung=bezeichnung,
            quellsystemtyp=quellsystemtyp,
            quellenart=quellenart,
            konkretes_quellsystem=konkretes_quellsystem,
            fachliche_beschreibung=fachliche_beschreibung,
            herkunft_oder_verantwortungsbereich=herkunft_oder_verantwortungsbereich,
            erwartete_tabellen_oder_blaetter=erwartete_tabellen_oder_blaetter,
            bekannte_schluesselattribute=bekannte_schluesselattribute,
        )
        self._repository.speichern(datenquelle)
        return datenquelle

    def datenquelle_laden(self, datenquellen_id: UUID) -> Datenquelle | None:
        """Lädt eine einzelne Datenquelle."""
        return self._repository.laden(datenquellen_id)

    def datenquellen_fuer_projekt(self, projekt_id: UUID) -> list[Datenquelle]:
        """Gibt den Datenquellenkatalog eines Projekts zurück."""
        return self._repository.fuer_projekt_auflisten(projekt_id)

    def datenquelle_aktualisieren(
        self,
        datenquellen_id: UUID,
        *,
        bezeichnung: str,
        quellsystemtyp: Quellsystemtyp,
        quellenart: Quellenart,
        konkretes_quellsystem: str = "",
        fachliche_beschreibung: str = "",
        herkunft_oder_verantwortungsbereich: str = "",
        erwartete_tabellen_oder_blaetter: tuple[str, ...] = (),
        bekannte_schluesselattribute: tuple[str, ...] = (),
    ) -> Datenquelle:
        """Aktualisiert eine vorhandene Datenquelle kontrolliert."""
        datenquelle = self._repository.laden(datenquellen_id)
        if datenquelle is None:
            raise Domaenenfehler(
                f"Die Datenquelle mit der ID {datenquellen_id} wurde nicht gefunden."
            )
        aktualisiert = datenquelle.aktualisiert(
            bezeichnung=bezeichnung,
            quellsystemtyp=quellsystemtyp,
            quellenart=quellenart,
            konkretes_quellsystem=konkretes_quellsystem,
            fachliche_beschreibung=fachliche_beschreibung,
            herkunft_oder_verantwortungsbereich=herkunft_oder_verantwortungsbereich,
            erwartete_tabellen_oder_blaetter=erwartete_tabellen_oder_blaetter,
            bekannte_schluesselattribute=bekannte_schluesselattribute,
        )
        self._repository.speichern(aktualisiert)
        return aktualisiert
