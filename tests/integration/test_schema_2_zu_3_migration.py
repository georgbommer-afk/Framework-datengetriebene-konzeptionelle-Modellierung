"""Realistische Regressionstests der Migration von Schema 2 auf Schema 3."""

import sqlite3
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.bootstrap import DATENBANKPFAD_UMGEBUNGSVARIABLE
from framework_mvp.domain.models import (
    BeteiligtePerson,
    Betrachtungszeitraum,
    BetrachtungszeitraumModus,
    Erzeugnisstrukturtyp,
    GestaltDerGueter,
    Intralogistikklassifikation,
    LogistischeZielgroesse,
    Materialflusskontinuitaet,
    Produktionsklassifikation,
    Projekt,
    Projektstatus,
    Rahmenbedingungen,
    Systemklassifikation,
    Systemtyp,
    Untersuchungsauftrag,
)
from framework_mvp.infrastructure.persistence import sqlite_schema
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    SQLiteProjektRepository,
)

ANWENDUNGSPFAD = Path(__file__).parents[2] / "streamlit_app.py"


def _vollstaendiges_projekt() -> Projekt:
    produktion = Produktionsklassifikation(
        auftragsabwicklungsstrategie="Make-to-Order (MTO)",
        auflagegroesse="Serienproduktion",
        produktionsstueckzahl="mittel (101-10 000 Stück)",
        produktvielfalt="mittel (11-100 Var.)",
        organisationstyp="Inselfertigung",
        anzahl_arbeitsgaenge="mehrstufig",
        ressourcen=("Maschinen", "Personal"),
    )
    intralogistik = Intralogistikklassifikation(
        handlingvorgaenge=("Einlagerung", "Auslagerung"),
        transportorganisation="gebündelter Rundlauf (“Milk-Run”)",
        lagerplatzzuordnung="Zonenzuordnung",
        materialbereitstellungsprinzip="Vorratshaltung",
        ressourcen=("Gabelstapler", "Routenzüge"),
    )
    klassifikation = Systemklassifikation(
        bereich="Werk 1",
        objekte_gueter="Montageaufträge",
        gestalt_der_gueter=GestaltDerGueter.STUECKGUT,
        erzeugnisstrukturtyp=Erzeugnisstrukturtyp.KONVERGIEREND,
        materialflusskontinuitaet=Materialflusskontinuitaet.DISKONTINUIERLICH,
        kapazitaetsgrenzen="Zwei Schichten",
        input_beschreibung="Material und Auftrag",
        transformation_beschreibung="Transport und Montage",
        output_beschreibung="Fertigprodukt",
        produktion=produktion,
        intralogistik=intralogistik,
    )
    auftrag = Untersuchungsauftrag(
        problemstellung="Lange und variable Durchlaufzeiten",
        untersuchungszweck="System analysieren",
        systemtyp=Systemtyp.KOMBINIERT,
        systemgrenze="Wareneingang bis Versand",
        individuelles_ziel="Engpässe nachvollziehen",
        logistische_zielgroessen=(
            LogistischeZielgroesse.DURCHLAUFZEIT,
            LogistischeZielgroesse.WARTEZEIT,
        ),
        ausgewaehlte_kpi_ids=("gesamtdurchlaufzeit", "wartezeit_aktivitaet"),
        systemklassifikation=klassifikation,
        detaillierungsgrad="Arbeitsgang",
        rahmenbedingungen=Rahmenbedingungen(
            "Personenbezogene Daten pseudonymisieren",
            "Nur lokale Verarbeitung",
            "Zeitstempel sind vollständig",
            "Störungsdaten ausgenommen",
            "Fallstudienzeitraum",
        ),
        betrachtungszeitraum=Betrachtungszeitraum(
            BetrachtungszeitraumModus.MANUELL,
            date(2026, 1, 1),
            date(2026, 6, 30),
        ),
        anmerkungen="Vollständiger Version-2-Regressionsdatensatz",
        legacy_leistungskennzahlen=("Historische Kennzahl",),
    )
    return Projekt.neu(
        "Strukturiertes Bestandsprojekt",
        auftrag,
        Projektstatus.AKTIV,
        (BeteiligtePerson("Ada", "Lovelace", "Fachexpert:in"),),
    )


def _version_2_datenbank_anlegen(pfad: Path) -> Projekt:
    projekt = _vollstaendiges_projekt()
    SQLiteProjektRepository(pfad).speichern(projekt)
    with sqlite3.connect(pfad) as verbindung:
        verbindung.execute("DROP TABLE datenquellen")
        verbindung.execute("PRAGMA user_version = 2")
    return projekt


def test_vollstaendiges_schema_2_projekt_wird_unveraendert_auf_3_migriert(
    tmp_path: Path,
) -> None:
    """Alle strukturierten Felder überstehen die ausschließlich additive Migration."""
    pfad = tmp_path / "schema-2.sqlite"
    erwartet = _version_2_datenbank_anlegen(pfad)
    service = ProjektService(SQLiteProjektRepository(pfad))

    geladen = service.projekt_laden(erwartet.projekt_id)

    assert geladen == erwartet
    with sqlite3.connect(pfad) as verbindung:
        assert verbindung.execute("PRAGMA user_version").fetchone()[0] == 11
        spalten = {zeile[1] for zeile in verbindung.execute("PRAGMA table_info(projekte)")}
        tabellen = {
            zeile[0]
            for zeile in verbindung.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert spalten == {
        "projekt_id",
        "bezeichnung",
        "beteiligte_personen_json",
        "status",
        "erstellt_am_utc",
        "geaendert_am_utc",
        "untersuchungsauftrag_json",
    }
    assert "datenquellen" in tabellen


def test_fehlgeschlagene_migration_von_2_auf_3_wird_zurueckgerollt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ein DDL-Fehler erhält Version 2 und die unveränderte Projekttabelle."""
    pfad = tmp_path / "rollback.sqlite"
    projekt = _version_2_datenbank_anlegen(pfad)
    monkeypatch.setattr(
        sqlite_schema,
        "DATENQUELLEN_SCHEMA_VERSION_3",
        "CREATE TABL datenquellen (defekt)",
    )
    with pytest.raises(sqlite3.OperationalError):
        SQLiteProjektRepository(pfad).auflisten()
    with sqlite3.connect(pfad) as verbindung:
        assert verbindung.execute("PRAGMA user_version").fetchone()[0] == 2
        assert verbindung.execute("SELECT projekt_id FROM projekte").fetchone()[0] == str(
            projekt.projekt_id
        )
        assert (
            verbindung.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = 'datenquellen'"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize("etl_oeffnen", [False, True])
def test_streamlit_seiten_starten_mit_migrierter_version_2_datenbank(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, etl_oeffnen: bool
) -> None:
    """Projektverwaltung und ETL-Seite starten ohne technischen Traceback."""
    pfad = tmp_path / f"app-{etl_oeffnen}.sqlite"
    _version_2_datenbank_anlegen(pfad)
    monkeypatch.setenv(DATENBANKPFAD_UMGEBUNGSVARIABLE, str(pfad))
    anwendung = AppTest.from_file(ANWENDUNGSPFAD).run()
    if etl_oeffnen:
        anwendung.radio[0].set_value("2 ETL durchführen").run()
    assert not anwendung.exception
    assert any(
        element.value == "Datengetriebene konzeptionelle Modellierung"
        for element in anwendung.title
    )
    if etl_oeffnen:
        assert anwendung.radio[0].value == "1 Projektrahmen definieren"


def test_nicht_unterstuetzte_version_zeigt_fehlermeldung_statt_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ein erwartbarer Migrationsfehler bleibt innerhalb der kontrollierten UI-Fehleranzeige."""
    pfad = tmp_path / "version-6.sqlite"
    with sqlite3.connect(pfad) as verbindung:
        verbindung.execute("PRAGMA user_version = 12")
    monkeypatch.setenv(DATENBANKPFAD_UMGEBUNGSVARIABLE, str(pfad))
    anwendung = AppTest.from_file(ANWENDUNGSPFAD).run()
    assert not anwendung.exception
    assert any("neuere Schemaversion 12" in element.value for element in anwendung.error)
