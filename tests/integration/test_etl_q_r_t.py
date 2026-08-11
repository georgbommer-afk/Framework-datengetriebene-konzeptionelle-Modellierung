"""End-to-End-Nachweis der drei persistenten Ausgaben Q, R und T aus Schritt 2."""

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


def test_mehrere_datensaetze_erzeugen_wiederladbare_q_r_und_t(tmp_path: Path) -> None:
    datenbank = tmp_path / "framework.sqlite"
    artefakte = ImportartefaktSpeicher(WorkspaceKonfiguration.ermitteln(tmp_path / "workspace"))
    projekt_repository = SQLiteProjektRepository(datenbank)
    quellen_repository = SQLiteDatenquelleRepository(datenbank)
    import_repository = SQLiteImportvorgangRepository(datenbank)
    etl_repository = SQLiteETLRepository(datenbank)
    projekt = ProjektService(projekt_repository).projekt_anlegen(
        bezeichnung="Q-R-T-Projekt",
        untersuchungsauftrag=Untersuchungsauftrag("", "", Systemtyp.KOMBINIERT, ""),
    )
    quellen_service = DatenquelleService(quellen_repository)
    linke_quelle = quellen_service.datenquelle_anlegen(
        projekt_id=projekt.projekt_id,
        bezeichnung="ERP-Aufträge",
        quellsystemtyp=Quellsystemtyp.ERP_SYSTEM,
        quellenart=Quellenart.CSV,
        bekannte_schluesselattribute=("id",),
    )
    rechte_quelle = quellen_service.datenquelle_anlegen(
        projekt_id=projekt.projekt_id,
        bezeichnung="WM-Status",
        quellsystemtyp=Quellsystemtyp.WM_SYSTEM,
        quellenart=Quellenart.CSV,
        bekannte_schluesselattribute=("id",),
    )
    import_service = ImportvorgangService(
        import_repository,
        projekt_repository,
        quellen_repository,
        artefakte,
    )
    datenimport = DatenimportService()
    parameter = CsvImportparameter(trennzeichenwahl=Trennzeichenwahl.SEMIKOLON)

    def bestaetigen(quelle_id, dateiname: str, inhalt: bytes, platzhalter=()):  # type: ignore[no-untyped-def]
        metadaten = datenimport.datei_pruefen(dateiname, inhalt)
        vorschau = datenimport.vorschau_erstellen(inhalt, parameter)
        profil = datenimport.profil_erstellen(vorschau.vollstaendige_tabelle, platzhalter).profil
        return import_service.import_bestaetigen(
            import_id=uuid4(),
            projekt_id=projekt.projekt_id,
            datenquellen_id=quelle_id,
            datei_metadaten=metadaten,
            dateiinhalt=inhalt,
            importparameter=parameter,
            tabellenbezeichnung=dateiname.removesuffix(".csv"),
            profil=profil,
        )

    linke_bytes = b"id;wert\n1;10\n2;100\n"
    rechte_bytes = b"id;status\n2;alt\n3;alt\n"
    linker_import = bestaetigen(linke_quelle.datenquellen_id, "auftraege.csv", linke_bytes)
    rechter_import = bestaetigen(
        rechte_quelle.datenquellen_id,
        "status.csv",
        rechte_bytes,
        ("nicht gepflegt",),
    )
    transformationen = TransformationsService(
        etl_repository,
        import_service,
        datenimport,
        artefakte,
    )

    rechter_schritt = Transformationsschritt.neu(
        typ=Transformationsart.WERTE_ERSETZEN,
        betroffene_spalten=("status",),
        parameter={"gesuchte_werte": ["alt"], "ersatzwert": "neu"},
        reihenfolge=1,
        beschreibung="Statuswert ersetzen",
    )
    rechter_plan = Transformationsplan.neu(projekt.projekt_id, (rechter_import.import_id,))
    rechter_plan = transformationen.schritt_hinzufuegen(rechter_plan, rechter_schritt)
    rechtes_ergebnis = transformationen.vorschau(rechter_plan)
    rechter_datensatz = transformationen.zwischendatensatz_erzeugen(
        rechter_plan, rechtes_ergebnis, uuid4()
    )

    linker_schritt = Transformationsschritt.neu(
        typ=Transformationsart.WERTE_ERSETZEN,
        betroffene_spalten=("wert",),
        parameter={"gesuchte_werte": [100], "ersatzwert": 55},
        reihenfolge=1,
        beschreibung="Ausreißer durch bestätigten Wert ersetzen",
    )
    join_schritt = Transformationsschritt.neu(
        typ=Transformationsart.TABELLEN_JOIN,
        betroffene_spalten=("id",),
        parameter={
            "rechter_zwischendatensatz_id": str(rechter_datensatz.zwischendatensatz_id),
            "linke_schluessel": ["id"],
            "rechte_schluessel": ["id"],
            "join_art": "OUTER",
            "suffixe": ["_links", "_rechts"],
            "nm_bestaetigt": False,
        },
        reihenfolge=2,
        beschreibung="OUTER-Verknüpfung",
    )
    linker_plan = Transformationsplan.neu(
        projekt.projekt_id,
        (linker_import.import_id, rechter_import.import_id),
    )
    linker_plan = transformationen.schritt_hinzufuegen(linker_plan, linker_schritt)
    linker_plan = transformationen.schritt_hinzufuegen(linker_plan, join_schritt)
    ergebnis = transformationen.vorschau(linker_plan)
    sortiert = ergebnis.daten.sort_values("id").reset_index(drop=True)
    assert sortiert["id"].tolist() == [1, 2, 3]
    assert sortiert.loc[0, "wert"] == 10
    assert sortiert.loc[1, "wert"] == 55
    assert pd.isna(sortiert.loc[2, "wert"])
    assert pd.isna(sortiert.loc[0, "status"])
    assert sortiert["status"].iloc[1:].tolist() == ["neu", "neu"]

    finaler_datensatz = transformationen.zwischendatensatz_erzeugen(linker_plan, ergebnis, uuid4())
    wieder_geladen, t_daten = transformationen.zwischendatensatz_laden(
        finaler_datensatz.zwischendatensatz_id
    )
    assert wieder_geladen == finaler_datensatz
    assert t_daten["status"].dropna().tolist() == ["neu", "neu"]
    assert len(import_service.importe_fuer_projekt(projekt.projekt_id)) == 2

    q_links = quellen_service.datenquelle_laden(linke_quelle.datenquellen_id)
    q_rechts = quellen_service.datenquelle_laden(rechte_quelle.datenquellen_id)
    assert q_links is not None and q_links.bekannte_schluesselattribute == ("id",)
    assert q_rechts is not None and q_rechts.bekannte_schluesselattribute == ("id",)
    r_rechts = import_service.import_laden(rechter_import.import_id)
    assert r_rechts is not None
    assert r_rechts.profil.gesamtprofil["bestaetigte_zusaetzliche_platzhalter"] == [
        "nicht gepflegt"
    ]
    assert import_service.originaldatei_laden(linker_import.import_id)[1] == linke_bytes
    assert import_service.originaldatei_laden(rechter_import.import_id)[1] == rechte_bytes

    herkunft = json.loads(artefakte.lesen(finaler_datensatz.relativer_transformation_pfad))
    assert {wert["import_id"] for wert in herkunft["ausgangsimporte"]} == {
        str(linker_import.import_id),
        str(rechter_import.import_id),
    }
    assert [wert["aktion"] for wert in herkunft["transformationshistorie"]] == [
        "Ausreißer durch bestätigten Wert ersetzen",
        "OUTER-Verknüpfung",
    ]
