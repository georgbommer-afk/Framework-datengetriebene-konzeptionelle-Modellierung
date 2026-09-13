"""Unit-Tests für den Projektservice."""

from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.exceptions import (
    ProjektNichtGefunden,
    UnvollstaendigerUntersuchungsauftrag,
)
from framework_mvp.domain.models import (
    BeteiligtePerson,
    LogistischeZielgroesse,
    Projekt,
    Projektstatus,
    Systemtyp,
    Untersuchungsauftrag,
)


class AenderungsfolgenSpy:
    def __init__(self) -> None:
        self.projekt_ids: list[UUID] = []

    def kpi_auswahl_geaendert(self, projekt_id: UUID) -> None:
        self.projekt_ids.append(projekt_id)


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
    projekt = service.projekt_anlegen(
        bezeichnung="Projekt",
        untersuchungsauftrag=_auftrag(vollstaendig=False),
    )

    with pytest.raises(UnvollstaendigerUntersuchungsauftrag):
        service.projekt_aktualisieren(
            projekt.projekt_id,
            bezeichnung=projekt.bezeichnung,
            untersuchungsauftrag=_auftrag(vollstaendig=False),
            status=status,
        )


def test_neues_projekt_ist_immer_entwurf() -> None:
    """Nur eine spätere explizite Aktualisierung darf den Status ändern."""
    service = ProjektService(InMemoryProjektRepository())
    projekt = service.projekt_anlegen(
        bezeichnung="Projekt",
        untersuchungsauftrag=_auftrag(),
    )
    assert projekt.status is Projektstatus.ENTWURF


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


def test_nur_tatsaechliche_reine_kpi_aenderung_loest_selektive_folgen_aus() -> None:
    repository = InMemoryProjektRepository()
    folgen = AenderungsfolgenSpy()
    service = ProjektService(repository, folgen)
    auftrag = replace(
        _auftrag(),
        logistische_zielgroessen=(
            LogistischeZielgroesse.LIEFERFAEHIGKEIT,
            LogistischeZielgroesse.NACHARBEIT,
        ),
        ausgewaehlte_kpi_ids=("servicegrad",),
    )
    projekt = service.projekt_anlegen(bezeichnung="Projekt", untersuchungsauftrag=auftrag)

    nur_umbenannt = service.projekt_aktualisieren(
        projekt.projekt_id,
        bezeichnung="Neue Bezeichnung",
        untersuchungsauftrag=auftrag,
        status=projekt.status,
    )
    assert folgen.projekt_ids == []

    mit_kpi = replace(
        auftrag,
        ausgewaehlte_kpi_ids=("servicegrad", "nacharbeitsquote_rr"),
    )
    service.projekt_aktualisieren(
        projekt.projekt_id,
        bezeichnung=nur_umbenannt.bezeichnung,
        untersuchungsauftrag=mit_kpi,
        status=projekt.status,
    )
    assert folgen.projekt_ids == [projekt.projekt_id]

    service.projekt_aktualisieren(
        projekt.projekt_id,
        bezeichnung=nur_umbenannt.bezeichnung,
        untersuchungsauftrag=replace(mit_kpi, anmerkungen="fachlich geändert"),
        status=projekt.status,
    )
    assert folgen.projekt_ids == [projekt.projekt_id]
