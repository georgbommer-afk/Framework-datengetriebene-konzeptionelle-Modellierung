"""Integrationstests des SQLite-Repositorys für Importvorgänge."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from framework_mvp.application.datenquelle_service import DatenquelleService
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.models import (
    CsvImportparameter,
    Dateityp,
    Importstatus,
    Importvorgang,
    Profilzusammenfassung,
    Quellenart,
    Quellsystemtyp,
    Systemtyp,
    Trennzeichenwahl,
    Untersuchungsauftrag,
)
from framework_mvp.infrastructure.persistence.sqlite_datenquelle_repository import (
    SQLiteDatenquelleRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_importvorgang_repository import (
    SQLiteImportvorgangRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    SQLiteProjektRepository,
)


def _umgebung(pfad: Path):  # type: ignore[no-untyped-def]
    projekt_repository = SQLiteProjektRepository(pfad)
    projekt = ProjektService(projekt_repository).projekt_anlegen(
        bezeichnung="Importprojekt",
        untersuchungsauftrag=Untersuchungsauftrag("", "", Systemtyp.KOMBINIERT, ""),
    )
    quelle_repository = SQLiteDatenquelleRepository(pfad)
    quelle = DatenquelleService(quelle_repository).datenquelle_anlegen(
        projekt_id=projekt.projekt_id,
        bezeichnung="CSV",
        quellsystemtyp=Quellsystemtyp.DATEI_EXPORT,
        quellenart=Quellenart.CSV,
    )
    return projekt, quelle


def _import(projekt_id, datenquellen_id, sha: str = "a" * 64) -> Importvorgang:  # type: ignore[no-untyped-def]
    zeitpunkt = datetime.now(UTC)
    import_id = uuid4()
    return Importvorgang(
        import_id,
        projekt_id,
        datenquellen_id,
        "daten.csv",
        "daten.csv",
        Dateityp.CSV,
        12,
        sha,
        CsvImportparameter(trennzeichenwahl=Trennzeichenwahl.SEMIKOLON),
        "daten",
        2,
        2,
        1,
        f"projects/{projekt_id}/raw/{sha}/daten.csv",
        f"projects/{projekt_id}/profiles/{import_id}.json",
        Profilzusammenfassung(1, 2, 3, 4),
        ("Warnung eins", "Warnung zwei"),
        Importstatus.BESTAETIGT,
        zeitpunkt,
        zeitpunkt,
    )


def test_import_speichern_und_einzeln_laden(tmp_path: Path) -> None:
    """Alle skalaren und JSON-Felder werden vollständig wiederhergestellt."""
    pfad = tmp_path / "import.sqlite"
    projekt, quelle = _umgebung(pfad)
    repository = SQLiteImportvorgangRepository(pfad)
    erwartet = _import(projekt.projekt_id, quelle.datenquellen_id)
    repository.speichern(erwartet)
    assert repository.laden(erwartet.import_id) == erwartet


def test_importe_projekt_und_datenquellenbezogen_auflisten(tmp_path: Path) -> None:
    """Beide fachlichen Sichten liefern die zugehörigen Importe."""
    pfad = tmp_path / "import.sqlite"
    projekt, quelle = _umgebung(pfad)
    repository = SQLiteImportvorgangRepository(pfad)
    importe = [_import(projekt.projekt_id, quelle.datenquellen_id) for _ in range(2)]
    for importvorgang in importe:
        repository.speichern(importvorgang)
    assert {wert.import_id for wert in repository.fuer_projekt_auflisten(projekt.projekt_id)} == {
        wert.import_id for wert in importe
    }
    assert {
        wert.import_id for wert in repository.fuer_datenquelle_auflisten(quelle.datenquellen_id)
    } == {wert.import_id for wert in importe}


def test_mehrere_importe_derselben_datei_sind_moeglich(tmp_path: Path) -> None:
    """Dieselbe Prüfsumme darf bewusst mehreren Import-IDs zugeordnet werden."""
    pfad = tmp_path / "import.sqlite"
    projekt, quelle = _umgebung(pfad)
    repository = SQLiteImportvorgangRepository(pfad)
    erster = _import(projekt.projekt_id, quelle.datenquellen_id)
    zweiter = _import(projekt.projekt_id, quelle.datenquellen_id)
    repository.speichern(erster)
    repository.speichern(zweiter)
    assert len(repository.fuer_projekt_auflisten(projekt.projekt_id)) == 2
