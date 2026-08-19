"""Nachweise der sofort persistierten, inkrementellen Transformationskette."""

import json
from pathlib import Path
from uuid import uuid4

import pandas as pd

from framework_mvp.application.datenimport_service import DatenimportService
from framework_mvp.application.datenquelle_service import DatenquelleService
from framework_mvp.application.importvorgang_service import ImportvorgangService
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.application.transformations_service import TransformationsService
from framework_mvp.domain.models import (
    CsvImportparameter,
    Quellenart,
    Quellsystemtyp,
    Systemtyp,
    Transformationsart,
    Transformationsplan,
    Transformationsschritt,
    Trennzeichenwahl,
    Untersuchungsauftrag,
)
from framework_mvp.infrastructure.importartefakte import ImportartefaktSpeicher
from framework_mvp.infrastructure.persistence.sqlite_datenquelle_repository import (
    SQLiteDatenquelleRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_etl_repository import SQLiteETLRepository
from framework_mvp.infrastructure.persistence.sqlite_importvorgang_repository import (
    SQLiteImportvorgangRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    SQLiteProjektRepository,
)
from framework_mvp.workspace import WorkspaceKonfiguration


def _vorbereiten(tmp_path: Path) -> tuple[TransformationsService, Transformationsplan]:
    datenbank = tmp_path / "framework.sqlite"
    workspace = WorkspaceKonfiguration.ermitteln(tmp_path / "workspace")
    projekt_repository = SQLiteProjektRepository(datenbank)
    projekt = ProjektService(projekt_repository).projekt_anlegen(
        bezeichnung="Inkrementelle ETL",
        untersuchungsauftrag=Untersuchungsauftrag("", "", Systemtyp.KOMBINIERT, ""),
    )
    quellen_repository = SQLiteDatenquelleRepository(datenbank)
    quelle = DatenquelleService(quellen_repository).datenquelle_anlegen(
        projekt_id=projekt.projekt_id,
        bezeichnung="ERP",
        quellsystemtyp=Quellsystemtyp.ERP_SYSTEM,
        quellenart=Quellenart.CSV,
    )
    datenimport = DatenimportService()
    artefakte = ImportartefaktSpeicher(workspace)
    importe = ImportvorgangService(
        SQLiteImportvorgangRepository(datenbank),
        projekt_repository,
        quellen_repository,
        artefakte,
    )
    dateiinhalt = b"id;status\n1;alt\n2;alt\n3;bleibt\n"
    parameter = CsvImportparameter(trennzeichenwahl=Trennzeichenwahl.SEMIKOLON)
    metadaten = datenimport.datei_pruefen("status.csv", dateiinhalt)
    vorschau = datenimport.vorschau_erstellen(dateiinhalt, parameter)
    importvorgang = importe.import_bestaetigen(
        import_id=uuid4(),
        projekt_id=projekt.projekt_id,
        datenquellen_id=quelle.datenquellen_id,
        datei_metadaten=metadaten,
        dateiinhalt=dateiinhalt,
        importparameter=parameter,
        tabellenbezeichnung="Status",
        profil=datenimport.profil_erstellen(vorschau.vollstaendige_tabelle).profil,
    )
    service = TransformationsService(
        SQLiteETLRepository(datenbank), importe, datenimport, artefakte
    )
    return service, Transformationsplan.neu(projekt.projekt_id, (importvorgang.import_id,))


def test_jede_aktion_baut_auf_letztem_zwischenstand_auf_und_speichert_lineage(
    tmp_path: Path,
) -> None:
    service, plan = _vorbereiten(tmp_path)
    ersetzen = Transformationsschritt.neu(
        typ=Transformationsart.WERTE_ERSETZEN,
        betroffene_spalten=("status",),
        parameter={"gesuchte_werte": ["alt"], "ersatzwert": "neu"},
        reihenfolge=1,
        beschreibung="Status alt durch neu ersetzen",
    )
    plan, erstes_ergebnis, erster_datensatz = service.transformation_anwenden(
        plan, ersetzen, uuid4()
    )
    assert erstes_ergebnis.daten["status"].tolist() == ["neu", "neu", "bleibt"]

    rohzugriffe = 0
    original_laden = service.import_dataframe_laden

    def mit_zaehler(import_id):  # type: ignore[no-untyped-def]
        nonlocal rohzugriffe
        rohzugriffe += 1
        return original_laden(import_id)

    service.import_dataframe_laden = mit_zaehler  # type: ignore[method-assign]
    loeschen = Transformationsschritt.neu(
        typ=Transformationsart.ZEILEN_LOESCHEN,
        betroffene_spalten=("status",),
        parameter={"operator": "gleich", "wert": "neu"},
        reihenfolge=2,
        beschreibung="Zeilen mit Status neu löschen",
    )
    plan, zweites_ergebnis, zweiter_datensatz = service.transformation_anwenden(
        plan, loeschen, uuid4()
    )

    assert rohzugriffe == 0
    assert zweites_ergebnis.daten.to_dict("records") == [{"id": 3, "status": "bleibt"}]
    assert zweiter_datensatz.zeilenanzahl == 1
    assert zweiter_datensatz.spaltenanzahl == 2
    assert service.neuester_plan_fuer_import(plan.projekt_id, plan.import_ids[0]) == plan
    assert service.arbeitsstand_laden(plan)[0] == zweiter_datensatz

    historie = service.transformationshistorie(plan)
    assert [wert["reihenfolge"] for wert in historie] == [1, 2]
    assert [wert["zeilen_nachher"] for wert in historie] == [3, 1]
    assert all("id" not in " ".join(wert) for wert in historie)

    lineage = json.loads(
        service._artefakte.lesen(zweiter_datensatz.relativer_transformation_pfad)  # noqa: SLF001
    )
    assert lineage["inkrementelle_lineage"]["eingabe_zwischendatensatz_id"] == str(
        erster_datensatz.zwischendatensatz_id
    )
    assert len(lineage["transformationshistorie"]) == 2
    assert lineage["ergebnisprofil"]["zeilen"] == 1


def test_arbeitsstand_bleibt_ueber_neue_serviceinstanz_vollstaendig(tmp_path: Path) -> None:
    service, plan = _vorbereiten(tmp_path)
    schritt = Transformationsschritt.neu(
        typ=Transformationsart.ZEILEN_LOESCHEN,
        betroffene_spalten=("status",),
        parameter={"operator": "enthält", "wert": "alt"},
        reihenfolge=1,
        beschreibung="Status enthält alt",
    )
    plan, _, datensatz = service.transformation_anwenden(plan, schritt, uuid4())

    neu_geladener_plan = service.plan_laden(plan.transformationsplan_id)
    assert neu_geladener_plan == plan
    assert neu_geladener_plan is not None
    geladen, daten = service.arbeitsstand_laden(neu_geladener_plan)
    assert geladen == datensatz
    pd.testing.assert_frame_equal(
        daten.reset_index(drop=True),
        pd.DataFrame({"id": [3], "status": ["bleibt"]}),
        check_dtype=False,
    )
    assert len(service.transformationshistorie(neu_geladener_plan)) == 1


def test_neuer_schritt_ergaenzt_auch_einen_legacy_gesamtstand_in_der_historie(
    tmp_path: Path,
) -> None:
    service, plan = _vorbereiten(tmp_path)
    erster_schritt = Transformationsschritt.neu(
        typ=Transformationsart.ZEILEN_LOESCHEN,
        betroffene_spalten=("status",),
        parameter={"operator": "gleich", "wert": "alt"},
        reihenfolge=1,
        beschreibung="Status ist alt",
    )
    plan = service.schritt_hinzufuegen(plan, erster_schritt)
    legacy_ergebnis = service.vorschau(plan)
    service.zwischendatensatz_erzeugen(plan, legacy_ergebnis, uuid4())

    zweiter_schritt = Transformationsschritt.neu(
        typ=Transformationsart.TEXT_BEREINIGEN,
        betroffene_spalten=("status",),
        parameter={
            "art": "Festen Präfix entfernen",
            "praefix": "b",
            "nichttreffer": "Originalwert beibehalten",
        },
        reihenfolge=2,
        beschreibung="Präfix aus Status entfernen",
    )
    plan, _, _ = service.transformation_anwenden(plan, zweiter_schritt, uuid4())

    historie = service.transformationshistorie(plan)
    assert [eintrag["reihenfolge"] for eintrag in historie] == [1, 2]
    assert [eintrag["transformationsart"] for eintrag in historie] == [
        "Zeilen anhand einer Bedingung löschen",
        "Text bereinigen oder extrahieren",
    ]
