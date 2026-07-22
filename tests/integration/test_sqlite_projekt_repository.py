"""Integrationstests für das SQLite-Projektrepository."""

import sqlite3
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from framework_mvp.domain.models import (
    BeteiligtePerson,
    Betrachtungszeitraum,
    BetrachtungszeitraumModus,
    Projekt,
    Projektstatus,
    Systemtyp,
    Untersuchungsauftrag,
)
from framework_mvp.infrastructure.exceptions import NichtUnterstuetzteSchemaversion
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    SQLiteProjektRepository,
)


def _projekt(bezeichnung: str) -> Projekt:
    auftrag = Untersuchungsauftrag(
        problemstellung="Material wartet zu lange",
        untersuchungszweck="System analysieren",
        systemtyp=Systemtyp.KOMBINIERT,
        systemgrenze="Wareneingang bis Montage",
        detaillierungsgrad="Arbeitsstation",
        legacy_leistungskennzahlen=("Durchlaufzeit", "Bestand"),
        betrachtungszeitraum=Betrachtungszeitraum(
            BetrachtungszeitraumModus.MANUELL,
            date(2026, 1, 1),
            date(2026, 3, 31),
        ),
        anmerkungen="Erste Untersuchung",
    )
    return Projekt.neu(
        bezeichnung,
        auftrag,
        status=Projektstatus.AKTIV,
        beteiligte_personen=(
            BeteiligtePerson("Ada", "Lovelace"),
            BeteiligtePerson("Grace", "Hopper"),
        ),
    )


def test_speichern_und_laden_mit_automatischer_anlage(tmp_path: Path) -> None:
    """Ein vollständiges Projekt übersteht den SQLite-Rundlauf unverändert."""
    datenbankpfad = tmp_path / "unterordner" / "projekte.sqlite"
    repository = SQLiteProjektRepository(datenbankpfad)
    projekt = _projekt("Analyse A")

    assert not datenbankpfad.exists()
    repository.speichern(projekt)

    assert datenbankpfad.exists()
    assert repository.laden(projekt.projekt_id) == projekt


def test_aktualisieren_eines_bestehenden_projekts(tmp_path: Path) -> None:
    """Ein Upsert aktualisiert den Datensatz und erhält dessen Erstellungszeitpunkt."""
    repository = SQLiteProjektRepository(tmp_path / "projekte.sqlite")
    ursprung = _projekt("Analyse A")
    repository.speichern(ursprung)
    aktualisiert = ursprung.aktualisiert(
        bezeichnung="Analyse B",
        untersuchungsauftrag=ursprung.untersuchungsauftrag,
        status=Projektstatus.ABGESCHLOSSEN,
        beteiligte_personen=(BeteiligtePerson("Ada", "Lovelace"),),
    )

    repository.speichern(aktualisiert)
    geladen = repository.laden(ursprung.projekt_id)

    assert geladen == aktualisiert
    assert geladen is not None
    assert geladen.erstellt_am == ursprung.erstellt_am
    assert len(repository.auflisten()) == 1


def test_auflisten_mehrerer_projekte(tmp_path: Path) -> None:
    """Alle Projekte werden auch bei gleichen Zeitstempeln stabil sortiert."""
    repository = SQLiteProjektRepository(tmp_path / "projekte.sqlite")
    projekt_a = _projekt("Analyse A")
    projekt_b = replace(
        _projekt("Analyse B"),
        erstellt_am=projekt_a.erstellt_am,
        geaendert_am=projekt_a.geaendert_am,
    )
    repository.speichern(projekt_a)
    repository.speichern(projekt_b)

    erwartet = sorted(
        [projekt_a, projekt_b],
        key=lambda projekt: (projekt.erstellt_am, str(projekt.projekt_id)),
    )
    assert repository.auflisten() == erwartet


def test_laden_eines_unbekannten_projekts(tmp_path: Path) -> None:
    """Ein nicht gespeichertes Projekt wird nicht erfunden."""
    projekt = _projekt("Nicht gespeichert")
    repository = SQLiteProjektRepository(tmp_path / "projekte.sqlite")

    assert repository.laden(projekt.projekt_id) is None


def test_schemaversion_ist_drei(tmp_path: Path) -> None:
    """Nach der Schemaerstellung ist die SQLite-Schemaversion gesetzt."""
    datenbankpfad = tmp_path / "projekte.sqlite"
    repository = SQLiteProjektRepository(datenbankpfad)
    repository.auflisten()

    with sqlite3.connect(datenbankpfad) as verbindung:
        schemaversion = verbindung.execute("PRAGMA user_version").fetchone()[0]

    assert schemaversion == 3


def test_neuere_schemaversion_wird_abgelehnt_und_nicht_zurueckgesetzt(
    tmp_path: Path,
) -> None:
    """Eine neuere Datenbankversion bleibt unverändert und verhindert den Zugriff."""
    datenbankpfad = tmp_path / "projekte.sqlite"
    with sqlite3.connect(datenbankpfad) as verbindung:
        verbindung.execute("PRAGMA user_version = 4")
    repository = SQLiteProjektRepository(datenbankpfad)

    with pytest.raises(NichtUnterstuetzteSchemaversion):
        repository.auflisten()

    with sqlite3.connect(datenbankpfad) as verbindung:
        schemaversion = verbindung.execute("PRAGMA user_version").fetchone()[0]

    assert schemaversion == 4


def test_upsert_erhaelt_urspruenglichen_erstellungszeitpunkt(tmp_path: Path) -> None:
    """Ein Upsert übernimmt Fachwerte, aber keinen abweichenden Erstellungszeitpunkt."""
    repository = SQLiteProjektRepository(tmp_path / "projekte.sqlite")
    ursprung = _projekt("Analyse A")
    repository.speichern(ursprung)
    abweichender_zeitpunkt = ursprung.erstellt_am - timedelta(days=1)
    aktualisiert = replace(
        ursprung,
        bezeichnung="Analyse mit neuen Fachwerten",
        beteiligte_personen=(BeteiligtePerson("Neue", "Person"),),
        erstellt_am=abweichender_zeitpunkt,
    )

    repository.speichern(aktualisiert)
    geladen = repository.laden(ursprung.projekt_id)

    assert geladen is not None
    assert geladen.erstellt_am == ursprung.erstellt_am
    assert geladen.bezeichnung == aktualisiert.bezeichnung
    assert geladen.beteiligte_personen == aktualisiert.beteiligte_personen
    assert len(repository.auflisten()) == 1
