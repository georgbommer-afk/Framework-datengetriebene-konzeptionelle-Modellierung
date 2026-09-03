"""Integrationstests für das SQLite-Projektrepository."""

import json
import sqlite3
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

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
    Systemklassifikation,
    Systemtyp,
    Untersuchungsauftrag,
)
from framework_mvp.infrastructure.exceptions import NichtUnterstuetzteSchemaversion
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    SQLiteProjektRepository,
)


def test_mehrere_untersuchungszwecke_werden_additiv_persistiert(tmp_path: Path) -> None:
    """Der JSON-Vertrag bewahrt mehrere Zwecke ohne Änderung des SQLite-Schemas."""
    repository = SQLiteProjektRepository(tmp_path / "zwecke.sqlite")
    projekt = Projekt.neu(
        "Mehrere Zwecke",
        Untersuchungsauftrag(
            "Problem",
            "System analysieren",
            Systemtyp.PRODUKTION,
            "Grenze",
            untersuchungszwecke=(
                "System analysieren",
                "Materialfluss erklären",
                "Bestände verstehen",
            ),
        ),
    )
    repository.speichern(projekt)
    geladen = repository.laden(projekt.projekt_id)
    assert geladen is not None
    assert geladen.untersuchungsauftrag.untersuchungszwecke == (
        "System analysieren",
        "Materialfluss erklären",
        "Bestände verstehen",
    )


@pytest.mark.parametrize(
    ("systemtyp", "produktion", "intralogistik"),
    [
        (
            Systemtyp.PRODUKTION,
            Produktionsklassifikation(
                auftragsabwicklungsstrategie="Make-to-Order (MTO)",
                auflagegroesse="Massenproduktion (ggfs. mit Sorten)",
                produktionsstueckzahl="hoch (mehr als 10 000 Stück)",
                produktvielfalt="mittel (11-100 Var.)",
                organisationstyp="Fließproduktion",
                anzahl_arbeitsgaenge="mehrstufig",
                ressourcen=("Maschinen", "Informationssysteme"),
            ),
            None,
        ),
        (
            Systemtyp.INTRALOGISTIK,
            None,
            Intralogistikklassifikation(
                handlingvorgaenge=("Einlagerung", "Sortierung", "Verteilung"),
                transportorganisation="gebündelter Rundlauf (“Milk-Run”)",
                lagerplatzzuordnung="Zonenzuordnung",
                materialbereitstellungsprinzip="einsatzsynchrone Bereitstellung",
                ressourcen=("Routenzüge", "Personal"),
            ),
        ),
    ],
)
def test_vollstaendiges_u_und_s_werden_unveraendert_persistiert(
    tmp_path: Path,
    systemtyp: Systemtyp,
    produktion: Produktionsklassifikation | None,
    intralogistik: Intralogistikklassifikation | None,
) -> None:
    """Der JSON-Rundlauf bewahrt alle in U und S ausgegebenen Fachwerte."""
    repository = SQLiteProjektRepository(tmp_path / f"u-s-{systemtyp.value}.sqlite")
    auftrag = Untersuchungsauftrag(
        problemstellung="Fehlende Transparenz",
        untersuchungszweck="System analysieren",
        untersuchungszwecke=("System analysieren", "Materialfluss erklären"),
        individuelles_ziel="Materialfluss erklären",
        systemtyp=systemtyp,
        systemgrenze="Wareneingang bis Versand",
        logistische_zielgroessen=(
            LogistischeZielgroesse.LIEFERZEIT,
            LogistischeZielgroesse.PROZESSSICHERHEIT,
        ),
        ausgewaehlte_kpi_ids=(
            "mittlere_dlz_warenausgang",
            "anteil_regulaer_abgeschlossener_faelle",
        ),
        systemklassifikation=Systemklassifikation(
            gestalt_der_gueter=GestaltDerGueter.STUECKGUT,
            erzeugnisstrukturtyp=Erzeugnisstrukturtyp.KONVERGIEREND,
            materialflusskontinuitaet=Materialflusskontinuitaet.DISKONTINUIERLICH,
            produktion=produktion,
            intralogistik=intralogistik,
        ),
    )
    projekt = Projekt.neu("Vollständiger Projektrahmen", auftrag)

    repository.speichern(projekt)

    assert repository.laden(projekt.projekt_id) == projekt


def test_alte_klassifikationswerte_werden_robust_auf_den_neuen_katalog_geladen(
    tmp_path: Path,
) -> None:
    """Umbenannte Felder und alte Werte verursachen keinen Ladefehler und werden bereinigt."""
    datenbankpfad = tmp_path / "altwerte.sqlite"
    repository = SQLiteProjektRepository(datenbankpfad)
    projekt = Projekt.neu(
        "Altbestand",
        Untersuchungsauftrag(
            "Problem",
            "System analysieren",
            Systemtyp.KOMBINIERT,
            "Grenze",
            logistische_zielgroessen=(
                LogistischeZielgroesse.DURCHLAUFZEIT,
                LogistischeZielgroesse.WARTEZEIT,
            ),
            systemklassifikation=Systemklassifikation(
                produktion=Produktionsklassifikation(),
                intralogistik=Intralogistikklassifikation(),
            ),
        ),
    )
    repository.speichern(projekt)
    with sqlite3.connect(datenbankpfad) as verbindung:
        text = verbindung.execute(
            "SELECT untersuchungsauftrag_json FROM projekte WHERE projekt_id = ?",
            (str(projekt.projekt_id),),
        ).fetchone()[0]
        daten = json.loads(text)
        system = daten["systemklassifikation"]
        system["materialflussform"] = "gemischt"
        system.pop("erzeugnisstrukturtyp")
        system["gestalt_der_gueter"] = "fliessgut"
        system["produktion"] = {
            "auftragsabwicklungsstrategie": "MTO – Make-to-Order",
            "produktionsart": "Sortenproduktion",
            "produktionsstueckzahl": "mittel (101–10.000 Stück)",
            "produktvielfalt": "mittel (11–100 Varianten)",
            "organisationstyp": "Inselfertigung",
            "anzahl_arbeitsgaenge": "mehrstufig",
            "produktionsfaktoren": ["anlagenintensiv"],
            "ressourcen": ["Maschinen", "Fördertechnik"],
        }
        system["intralogistik"] = {
            "hauptfunktionen": ["Lagerung", "Kommissionierung"],
            "transportorganisation": "Linien- beziehungsweise Routenzugverkehr",
            "lagerprinzip": "Supermarktprinzip",
            "ressourcen": ["Stapler", "AMR"],
        }
        daten["ausgewaehlte_kpi_ids"] = ["gesamtdurchlaufzeit", "wartezeit_aktivitaet"]
        verbindung.execute(
            "UPDATE projekte SET untersuchungsauftrag_json = ? WHERE projekt_id = ?",
            (json.dumps(daten), str(projekt.projekt_id)),
        )

    geladen = repository.laden(projekt.projekt_id)

    assert geladen is not None
    auftrag = geladen.untersuchungsauftrag
    assert auftrag.ausgewaehlte_kpi_ids == (
        "mittlere_dlz_wareneingang",
        "tatsaechliche_wartezeit_aqt",
    )
    assert auftrag.systemklassifikation.gestalt_der_gueter is (
        GestaltDerGueter.GEFORMT_UNGEFORMTES_FLIESSGUT
    )
    assert auftrag.systemklassifikation.erzeugnisstrukturtyp is Erzeugnisstrukturtyp.GENERELL
    assert auftrag.systemklassifikation.produktion == Produktionsklassifikation(
        auftragsabwicklungsstrategie="Make-to-Order (MTO)",
        auflagegroesse="Massenproduktion (ggfs. mit Sorten)",
        produktionsstueckzahl="mittel (101-10 000 Stück)",
        produktvielfalt="mittel (11-100 Var.)",
        organisationstyp="Inselfertigung",
        anzahl_arbeitsgaenge="mehrstufig",
        ressourcen=("Maschinen",),
    )
    assert auftrag.systemklassifikation.intralogistik == Intralogistikklassifikation(
        handlingvorgaenge=("Einlagerung", "Auslagerung", "Kommissionierung"),
        transportorganisation="gebündelter Rundlauf (“Milk-Run”)",
        materialbereitstellungsprinzip="Vorratshaltung",
        ressourcen=("Gabelstapler",),
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


def test_schemaversion_ist_fuenf(tmp_path: Path) -> None:
    """Nach der Schemaerstellung ist die SQLite-Schemaversion gesetzt."""
    datenbankpfad = tmp_path / "projekte.sqlite"
    repository = SQLiteProjektRepository(datenbankpfad)
    repository.auflisten()

    with sqlite3.connect(datenbankpfad) as verbindung:
        schemaversion = verbindung.execute("PRAGMA user_version").fetchone()[0]

    assert schemaversion == 12


def test_neuere_schemaversion_wird_abgelehnt_und_nicht_zurueckgesetzt(
    tmp_path: Path,
) -> None:
    """Eine neuere Datenbankversion bleibt unverändert und verhindert den Zugriff."""
    datenbankpfad = tmp_path / "projekte.sqlite"
    with sqlite3.connect(datenbankpfad) as verbindung:
        verbindung.execute("PRAGMA user_version = 13")
    repository = SQLiteProjektRepository(datenbankpfad)

    with pytest.raises(NichtUnterstuetzteSchemaversion):
        repository.auflisten()

    with sqlite3.connect(datenbankpfad) as verbindung:
        schemaversion = verbindung.execute("PRAGMA user_version").fetchone()[0]

        assert schemaversion == 13


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
