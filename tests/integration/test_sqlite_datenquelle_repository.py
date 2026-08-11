"""Integrationstests des SQLite-Datenquellenrepositorys."""

import sqlite3
from pathlib import Path

from framework_mvp.domain.models import (
    Datenquelle,
    Projekt,
    Quellenart,
    Quellsystemtyp,
    Systemtyp,
    Untersuchungsauftrag,
)
from framework_mvp.infrastructure.persistence.sqlite_datenquelle_repository import (
    SQLiteDatenquelleRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    SQLiteProjektRepository,
)


def _projekt(repository: SQLiteProjektRepository, bezeichnung: str = "Projekt") -> Projekt:
    projekt = Projekt.neu(
        bezeichnung,
        Untersuchungsauftrag("", "", Systemtyp.KOMBINIERT, ""),
    )
    repository.speichern(projekt)
    return projekt


def _quelle(projekt: Projekt, bezeichnung: str = "ERP-Export") -> Datenquelle:
    return Datenquelle.neu(
        projekt_id=projekt.projekt_id,
        bezeichnung=bezeichnung,
        quellsystemtyp=Quellsystemtyp.ERP_SYSTEM,
        quellenart=Quellenart.CSV,
        erwartete_tabellen_oder_blaetter=("Aufträge",),
        bekannte_schluesselattribute=("Auftrags-ID",),
    )


def test_speichern_laden_und_aktualisieren(tmp_path: Path) -> None:
    """Eine Datenquelle kann vollständig gespeichert, geladen und aktualisiert werden."""
    pfad = tmp_path / "katalog.sqlite"
    projekt = _projekt(SQLiteProjektRepository(pfad))
    repository = SQLiteDatenquelleRepository(pfad)
    quelle = _quelle(projekt)
    repository.speichern(quelle)
    assert repository.laden(quelle.datenquellen_id) == quelle

    aktualisiert = quelle.aktualisiert(
        bezeichnung="ERP-Export neu",
        quellsystemtyp=Quellsystemtyp.ERP_SYSTEM,
        quellenart=Quellenart.EXCEL,
    )
    repository.speichern(aktualisiert)
    geladen = repository.laden(quelle.datenquellen_id)
    assert geladen == aktualisiert
    assert geladen is not None
    assert geladen.erstellt_am == quelle.erstellt_am


def test_projektbezogenes_auflisten(tmp_path: Path) -> None:
    """Der Katalog liefert ausschließlich Datenquellen des angeforderten Projekts."""
    pfad = tmp_path / "katalog.sqlite"
    projekt_repository = SQLiteProjektRepository(pfad)
    projekt_a = _projekt(projekt_repository, "A")
    projekt_b = _projekt(projekt_repository, "B")
    repository = SQLiteDatenquelleRepository(pfad)
    quelle_a = _quelle(projekt_a, "Quelle A")
    quelle_b = _quelle(projekt_b, "Quelle B")
    repository.speichern(quelle_a)
    repository.speichern(quelle_b)
    assert repository.fuer_projekt_auflisten(projekt_a.projekt_id) == [quelle_a]


def test_schema_zwei_wird_ohne_projektverlust_migriert(tmp_path: Path) -> None:
    """Die Migration ergänzt nur den Katalog und erhält vorhandene Projekte."""
    pfad = tmp_path / "migration.sqlite"
    projekt_repository = SQLiteProjektRepository(pfad)
    projekt = _projekt(projekt_repository)
    with sqlite3.connect(pfad) as verbindung:
        verbindung.execute("DROP TABLE datenquellen")
        verbindung.execute("PRAGMA user_version = 2")

    SQLiteDatenquelleRepository(pfad).fuer_projekt_auflisten(projekt.projekt_id)

    assert projekt_repository.laden(projekt.projekt_id) == projekt
    with sqlite3.connect(pfad) as verbindung:
        assert verbindung.execute("PRAGMA user_version").fetchone()[0] == 10
        tabellen = {zeile[0] for zeile in verbindung.execute("SELECT name FROM sqlite_master")}
    assert "datenquellen" in tabellen
