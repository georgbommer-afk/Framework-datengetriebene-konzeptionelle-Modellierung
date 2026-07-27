"""End-to-End-Tests für Import, Profil, Bestätigung und erneutes Laden."""

from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import pandas as pd
import pytest

from framework_mvp.application.datenimport_service import DatenimportService
from framework_mvp.application.datenquelle_service import DatenquelleService
from framework_mvp.application.importvorgang_service import ImportvorgangService
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.models import (
    CsvImportparameter,
    ExcelImportparameter,
    Importvorgang,
    Quellenart,
    Quellsystemtyp,
    Systemtyp,
    Trennzeichenwahl,
    Untersuchungsauftrag,
)
from framework_mvp.infrastructure.importartefakte import ImportartefaktSpeicher
from framework_mvp.infrastructure.persistence.sqlite_datenquelle_repository import (
    SQLiteDatenquelleRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_importvorgang_repository import (
    SQLiteImportvorgangRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    SQLiteProjektRepository,
)
from framework_mvp.ui.pages.etl import _gespeicherten_import_wiederherstellen
from framework_mvp.workspace import WorkspaceKonfiguration


def _services(tmp_path: Path, quellenart: Quellenart):  # type: ignore[no-untyped-def]
    datenbankpfad = tmp_path / "framework.sqlite"
    projekt_repository = SQLiteProjektRepository(datenbankpfad)
    datenquelle_repository = SQLiteDatenquelleRepository(datenbankpfad)
    import_repository = SQLiteImportvorgangRepository(datenbankpfad)
    projekt = ProjektService(projekt_repository).projekt_anlegen(
        bezeichnung="E2E-Projekt",
        untersuchungsauftrag=Untersuchungsauftrag("", "", Systemtyp.KOMBINIERT, ""),
    )
    datenquelle = DatenquelleService(datenquelle_repository).datenquelle_anlegen(
        projekt_id=projekt.projekt_id,
        bezeichnung="Quelldatei",
        quellsystemtyp=Quellsystemtyp.DATEI_EXPORT,
        quellenart=quellenart,
    )
    service = ImportvorgangService(
        import_repository,
        projekt_repository,
        datenquelle_repository,
        ImportartefaktSpeicher(WorkspaceKonfiguration.ermitteln(tmp_path / "workspace")),
    )
    return projekt, datenquelle, service, import_repository


def test_csv_import_profil_bestaetigung_laden_und_platzhalter(tmp_path: Path) -> None:
    """CSV-Texte bleiben Platzhalter, während technisch leere Felder echte Fehlwerte werden."""
    projekt, quelle, service, repository = _services(tmp_path, Quellenart.CSV)
    inhalt = b"id;wert\n1;NULL\n2;N/A\n3;NA\n4;NaN\n5;-\n6;\n"
    import_service = DatenimportService()
    metadaten = import_service.datei_pruefen("platzhalter.csv", inhalt)
    parameter = CsvImportparameter(trennzeichenwahl=Trennzeichenwahl.SEMIKOLON)
    vorschau = import_service.vorschau_erstellen(inhalt, parameter)
    profilierung = import_service.profil_erstellen(vorschau.vollstaendige_tabelle)
    wertprofil = next(
        wert for wert in profilierung.profil.spaltenprofile if wert.spaltenname == "wert"
    )
    assert wertprofil.fehlwerte.platzhalter == 5
    assert wertprofil.fehlwerte.echte_fehlwerte == 1
    import_id = uuid4()
    bestaetigt = service.import_bestaetigen(
        import_id=import_id,
        projekt_id=projekt.projekt_id,
        datenquellen_id=quelle.datenquellen_id,
        datei_metadaten=metadaten,
        dateiinhalt=inhalt,
        importparameter=parameter,
        tabellenbezeichnung="platzhalter",
        profil=profilierung.profil,
    )
    geladen = service.import_laden(import_id)
    assert geladen is not None and geladen.importvorgang == bestaetigt
    assert repository.laden(import_id) == bestaetigt
    assert vorschau.vollstaendige_tabelle.loc[0, "wert"] == "NULL"


def test_excel_import_blatt_profil_bestaetigung_laden_und_platzhalter(tmp_path: Path) -> None:
    """Auch der Excel-Importer erhält textuelle Platzhalter getrennt von einer leeren Zelle."""
    projekt, quelle, service, _ = _services(tmp_path, Quellenart.EXCEL)
    puffer = BytesIO()
    pd.DataFrame({"wert": ["NULL", "N/A", "NA", "NaN", "-", None, "Regulär"]}).to_excel(
        puffer, sheet_name="Daten", index=False
    )
    inhalt = puffer.getvalue()
    import_service = DatenimportService()
    metadaten = import_service.datei_pruefen("platzhalter.xlsx", inhalt)
    parameter = ExcelImportparameter("Daten")
    vorschau = import_service.vorschau_erstellen(inhalt, parameter)
    profil = import_service.profil_erstellen(vorschau.vollstaendige_tabelle).profil
    wertprofil = profil.spaltenprofile[0].fehlwerte
    assert wertprofil.platzhalter == 5
    assert wertprofil.echte_fehlwerte == 1
    import_id = uuid4()
    service.import_bestaetigen(
        import_id=import_id,
        projekt_id=projekt.projekt_id,
        datenquellen_id=quelle.datenquellen_id,
        datei_metadaten=metadaten,
        dateiinhalt=inhalt,
        importparameter=parameter,
        tabellenbezeichnung="Daten",
        profil=profil,
    )
    assert service.import_laden(import_id) is not None


def test_gespeicherter_import_stellt_raw_parameter_vorschau_und_profil_wieder_her(
    tmp_path: Path,
) -> None:
    """Ein bestätigter Import kann ohne erneuten Upload vollständig fortgesetzt werden."""
    projekt, quelle, service, _ = _services(tmp_path, Quellenart.CSV)
    inhalt = b"id;wert\n1;A\n2;B\n"
    datenimport = DatenimportService()
    metadaten = datenimport.datei_pruefen("wiederaufnahme.csv", inhalt)
    parameter = CsvImportparameter(trennzeichenwahl=Trennzeichenwahl.SEMIKOLON)
    vorschau = datenimport.vorschau_erstellen(inhalt, parameter)
    profil = datenimport.profil_erstellen(vorschau.vollstaendige_tabelle).profil
    bestaetigt = service.import_bestaetigen(
        import_id=uuid4(),
        projekt_id=projekt.projekt_id,
        datenquellen_id=quelle.datenquellen_id,
        datei_metadaten=metadaten,
        dateiinhalt=inhalt,
        importparameter=parameter,
        tabellenbezeichnung="wiederaufnahme",
        profil=profil,
    )
    zustand: dict[str, object] = {}
    wiederhergestellt = _gespeicherten_import_wiederherstellen(
        importvorgang_service=service,
        datenimport_service=datenimport,
        import_id=bestaetigt.import_id,
        zustand=zustand,
    )
    assert wiederhergestellt == bestaetigt
    assert zustand["dateiinhalt"] == inhalt
    assert zustand["csv_parameter"] == parameter
    assert zustand["bestaetigter_import"] == bestaetigt
    assert zustand["vorschau"].gesamtzeilen == 2  # type: ignore[union-attr]
    assert zustand["profil"].profil.zeilen == 2  # type: ignore[union-attr]


def test_doppelte_ausfuehrung_erzeugt_keinen_zweiten_import(tmp_path: Path) -> None:
    """Eine stabile Import-ID macht wiederholte Bestätigung idempotent."""
    projekt, quelle, service, repository = _services(tmp_path, Quellenart.CSV)
    inhalt = b"a,b\n1,2\n"
    import_service = DatenimportService()
    metadaten = import_service.datei_pruefen("daten.csv", inhalt)
    parameter = CsvImportparameter(trennzeichenwahl=Trennzeichenwahl.KOMMA)
    vorschau = import_service.vorschau_erstellen(inhalt, parameter)
    profil = import_service.profil_erstellen(vorschau.vollstaendige_tabelle).profil
    import_id = uuid4()
    argumente = {
        "import_id": import_id,
        "projekt_id": projekt.projekt_id,
        "datenquellen_id": quelle.datenquellen_id,
        "datei_metadaten": metadaten,
        "dateiinhalt": inhalt,
        "importparameter": parameter,
        "tabellenbezeichnung": "daten",
        "profil": profil,
    }
    assert service.import_bestaetigen(**argumente) == service.import_bestaetigen(**argumente)
    assert len(repository.fuer_projekt_auflisten(projekt.projekt_id)) == 1


class _FehlerRepository:
    def laden(self, import_id: UUID) -> Importvorgang | None:
        return None

    def speichern(self, importvorgang: Importvorgang) -> None:
        raise RuntimeError("Erzwungener SQLite-Fehler")

    def fuer_projekt_auflisten(self, projekt_id: UUID) -> list[Importvorgang]:
        return []

    def fuer_datenquelle_auflisten(self, datenquellen_id: UUID) -> list[Importvorgang]:
        return []


def test_fehler_nach_dateierzeugung_kompensiert_neue_artefakte(tmp_path: Path) -> None:
    """Ein SQLite-Fehler entfernt neu erzeugtes Profil und neu erzeugte Raw-Datei."""
    projekt, quelle, _, _ = _services(tmp_path, Quellenart.CSV)
    datenbankpfad = tmp_path / "framework.sqlite"
    artefakte = ImportartefaktSpeicher(WorkspaceKonfiguration.ermitteln(tmp_path / "kompensation"))
    service = ImportvorgangService(
        _FehlerRepository(),
        SQLiteProjektRepository(datenbankpfad),
        SQLiteDatenquelleRepository(datenbankpfad),
        artefakte,
    )
    inhalt = b"a\n1\n"
    import_service = DatenimportService()
    metadaten = import_service.datei_pruefen("daten.csv", inhalt)
    parameter = CsvImportparameter(trennzeichenwahl=Trennzeichenwahl.KOMMA)
    vorschau = import_service.vorschau_erstellen(inhalt, parameter)
    profil = import_service.profil_erstellen(vorschau.vollstaendige_tabelle).profil
    with pytest.raises(RuntimeError, match="SQLite"):
        service.import_bestaetigen(
            import_id=uuid4(),
            projekt_id=projekt.projekt_id,
            datenquellen_id=quelle.datenquellen_id,
            datei_metadaten=metadaten,
            dateiinhalt=inhalt,
            importparameter=parameter,
            tabellenbezeichnung="daten",
            profil=profil,
        )
    assert not list((tmp_path / "kompensation").rglob("*.csv"))
    assert not list((tmp_path / "kompensation").rglob("*.json"))


def test_bestehende_raw_datei_wird_bei_fehler_nicht_entfernt(tmp_path: Path) -> None:
    """Die Kompensation löscht niemals eine vor dem Ablauf vorhandene inhaltsgleiche Raw-Datei."""
    projekt, quelle, _, _ = _services(tmp_path, Quellenart.CSV)
    datenbankpfad = tmp_path / "framework.sqlite"
    artefakte = ImportartefaktSpeicher(
        WorkspaceKonfiguration.ermitteln(tmp_path / "wiederverwendung")
    )
    inhalt = b"a\n1\n"
    import_service = DatenimportService()
    metadaten = import_service.datei_pruefen("daten.csv", inhalt)
    vorhanden = artefakte.raw_speichern(
        projekt.projekt_id, metadaten.sha256, metadaten.sicherer_dateiname, inhalt
    )
    service = ImportvorgangService(
        _FehlerRepository(),
        SQLiteProjektRepository(datenbankpfad),
        SQLiteDatenquelleRepository(datenbankpfad),
        artefakte,
    )
    parameter = CsvImportparameter(trennzeichenwahl=Trennzeichenwahl.KOMMA)
    vorschau = import_service.vorschau_erstellen(inhalt, parameter)
    profil = import_service.profil_erstellen(vorschau.vollstaendige_tabelle).profil
    with pytest.raises(RuntimeError):
        service.import_bestaetigen(
            import_id=uuid4(),
            projekt_id=projekt.projekt_id,
            datenquellen_id=quelle.datenquellen_id,
            datei_metadaten=metadaten,
            dateiinhalt=inhalt,
            importparameter=parameter,
            tabellenbezeichnung="daten",
            profil=profil,
        )
    assert artefakte.lesen(vorhanden.relativer_pfad) == inhalt


def test_fehler_vor_artefakterzeugung_hinterlaesst_keine_datei(tmp_path: Path) -> None:
    """Eine abweichende Uploadprüfsumme stoppt den Ablauf vor dem ersten Schreibzugriff."""
    projekt, quelle, service, _ = _services(tmp_path, Quellenart.CSV)
    inhalt = b"a\n1\n"
    import_service = DatenimportService()
    metadaten = import_service.datei_pruefen("daten.csv", inhalt)
    parameter = CsvImportparameter(trennzeichenwahl=Trennzeichenwahl.KOMMA)
    vorschau = import_service.vorschau_erstellen(inhalt, parameter)
    profil = import_service.profil_erstellen(vorschau.vollstaendige_tabelle).profil
    with pytest.raises(Exception, match="Prüfsumme"):
        service.import_bestaetigen(
            import_id=uuid4(),
            projekt_id=projekt.projekt_id,
            datenquellen_id=quelle.datenquellen_id,
            datei_metadaten=metadaten,
            dateiinhalt=b"abweichend",
            importparameter=parameter,
            tabellenbezeichnung="daten",
            profil=profil,
        )
    assert not list((tmp_path / "workspace").rglob("*.csv"))
