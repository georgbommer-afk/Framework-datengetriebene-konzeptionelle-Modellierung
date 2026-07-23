"""Unit-Tests für den Projektservice."""

from uuid import UUID, uuid4

import pytest

from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.exceptions import (
    ProjektNichtGefunden,
    UnvollstaendigerUntersuchungsauftrag,
)
from framework_mvp.domain.models import (
    BeteiligtePerson,
    Projekt,
    Projektstatus,
    Systemtyp,
    Untersuchungsauftrag,
)


class InMemoryProjektRepository:
    """Kleiner Testadapter ohne externe Persistenz."""

    def __init__(self) -> None:
        """Erzeugt einen leeren, testlokalen Projektspeicher."""
        self.projekte: dict[UUID, Projekt] = {}

    def speichern(self, projekt: Projekt) -> None:
        """Speichert das Projekt anhand seiner ID."""
        self.projekte[projekt.projekt_id] = projekt

    def laden(self, projekt_id: UUID) -> Projekt | None:
        """Lädt ein Projekt aus dem Testadapter."""
        return self.projekte.get(projekt_id)

    def auflisten(self) -> list[Projekt]:
        """Gibt alle Testprojekte zurück."""
        return list(self.projekte.values())


def _auftrag(*, vollstaendig: bool = True) -> Untersuchungsauftrag:
    return Untersuchungsauftrag(
        problemstellung="Problem" if vollstaendig else "",
        untersuchungszweck="Ziel",
        systemtyp=Systemtyp.PRODUKTION,
        systemgrenze="Systemgrenze",
    )


def test_projekt_anlegen_und_speichern() -> None:
    """Der Service speichert ein neu erzeugtes Projekt im Adapter."""
    repository = InMemoryProjektRepository()
    service = ProjektService(repository)

    projekt = service.projekt_anlegen(
        bezeichnung="Projekt A",
        untersuchungsauftrag=_auftrag(),
        beteiligte_personen=(BeteiligtePerson("Ada"),),
    )

    assert repository.laden(projekt.projekt_id) == projekt


def test_aktualisierung_eines_unbekannten_projekts() -> None:
    """Eine unbekannte Projekt-ID führt zu einer fachlichen Ausnahme."""
    service = ProjektService(InMemoryProjektRepository())

    with pytest.raises(ProjektNichtGefunden):
        service.projekt_aktualisieren(
            uuid4(),
            bezeichnung="Unbekannt",
            untersuchungsauftrag=_auftrag(),
            status=Projektstatus.ENTWURF,
        )


@pytest.mark.parametrize("status", [Projektstatus.AKTIV, Projektstatus.ABGESCHLOSSEN])
def test_unvollstaendiger_auftrag_wird_fuer_fortgeschrittenen_status_abgelehnt(
    status: Projektstatus,
) -> None:
    """Aktive und abgeschlossene Projekte benötigen einen vollständigen Auftrag."""
    service = ProjektService(InMemoryProjektRepository())

    with pytest.raises(UnvollstaendigerUntersuchungsauftrag):
        service.projekt_anlegen(
            bezeichnung="Projekt",
            untersuchungsauftrag=_auftrag(vollstaendig=False),
            status=status,
        )


def test_aktualisierung_erhaelt_id_und_erstellungszeitpunkt() -> None:
    """Eine Aktualisierung erzeugt eine neue Instanz mit stabiler Identität."""
    repository = InMemoryProjektRepository()
    service = ProjektService(repository)
    ursprung = service.projekt_anlegen(bezeichnung="Projekt A", untersuchungsauftrag=_auftrag())

    aktualisiert = service.projekt_aktualisieren(
        ursprung.projekt_id,
        bezeichnung="Projekt B",
        untersuchungsauftrag=_auftrag(),
        status=Projektstatus.AKTIV,
        beteiligte_personen=(BeteiligtePerson("Grace"),),
    )

    assert aktualisiert is not ursprung
    assert aktualisiert.projekt_id == ursprung.projekt_id
    assert aktualisiert.erstellt_am == ursprung.erstellt_am
    assert aktualisiert.geaendert_am >= ursprung.geaendert_am
    assert repository.laden(ursprung.projekt_id) == aktualisiert
