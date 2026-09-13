"""Nachweise des persistierten Plans und genau eines finalen T aus Schritt 2."""

import json
from pathlib import Path
from uuid import uuid4

import pandas as pd

from framework_mvp.application.aktive_lineage_service import (
    AktiveLineageService,
    LineageEndpunkt,
)
from framework_mvp.application.datenimport_service import DatenimportService
from framework_mvp.application.datenquelle_service import DatenquelleService
from framework_mvp.application.importvorgang_service import ImportvorgangService
from framework_mvp.application.loesch_service import LoeschService
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
    Wertevergleichsart,
)
from framework_mvp.infrastructure.importartefakte import ImportartefaktSpeicher
from framework_mvp.infrastructure.persistence.sqlite_datenquelle_repository import (
    SQLiteDatenquelleRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_etl_repository import SQLiteETLRepository
from framework_mvp.infrastructure.persistence.sqlite_importvorgang_repository import (
    SQLiteImportvorgangRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_loesch_repository import (
    SQLiteLoeschRepository,
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
        bezeichnung="Finale ETL",
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
    dateiinhalt = b"id;status;von;zu\n1;alt;HRL-04-A;HRL-04-X\n2;alt;B;HRL-04-Y\n3;bleibt;C;D\n"
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
        SQLiteETLRepository(datenbank),
        importe,
        datenimport,
        artefakte,
        AktiveLineageService(datenbank),
        LoeschService(SQLiteLoeschRepository(datenbank), workspace),
    )
    return service, Transformationsplan.neu(projekt.projekt_id, (importvorgang.import_id,))


def _schritt(
    art: Transformationsart,
    spalten: tuple[str, ...],
    parameter: dict[str, object],
    beschreibung: str,
) -> Transformationsschritt:
    return Transformationsschritt.neu(
        typ=art,
        betroffene_spalten=spalten,
        parameter=parameter,
        reihenfolge=1,
        beschreibung=beschreibung,
    )


def test_drei_planoperationen_erzeugen_vorschau_aber_erst_beim_abschluss_ein_t(
    tmp_path: Path,
) -> None:
    service, plan = _vorbereiten(tmp_path)
    schritte = (
        _schritt(
            Transformationsart.WERTE_ERSETZEN,
            ("status",),
            {"gesuchte_werte": ["alt"], "ersatzwert": "neu"},
            "Status ersetzen",
        ),
        _schritt(
            Transformationsart.WERTE_REGELBASIERT_ABSTRAHIEREN,
            ("von", "zu"),
            {
                "vergleichsart": Wertevergleichsart.BEGINNT_MIT.value,
                "suchwert": "HRL-04",
                "ersatzwert": "HRL",
                "zielmodus": "Bestehende Spalte überschreiben",
            },
            "Von und Zu abstrahieren",
        ),
        _schritt(
            Transformationsart.ZEILEN_LOESCHEN,
            ("status",),
            {"operator": "gleich", "wert": "neu"},
            "Neue Statuszeilen löschen",
        ),
    )

    for schritt in schritte:
        plan, ergebnis, datensatz = service.transformation_anwenden(plan, schritt)
        assert datensatz is None

    assert len(plan.schritte) == 3
    assert service.datensaetze_fuer_projekt(plan.projekt_id) == []
    assert ergebnis.daten.to_dict("records") == [
        {"id": 3, "status": "bleibt", "von": "C", "zu": "D"}
    ]

    abschluss = service.zwischendatensatz_abschliessen(plan)

    assert not abschluss.datensatz_wiederverwendet
    assert len(service.datensaetze_fuer_projekt(plan.projekt_id)) == 1
    assert abschluss.datensatz.zeilenanzahl == 1
    lineage = json.loads(
        service._artefakte.lesen(  # noqa: SLF001
            abschluss.datensatz.relativer_transformation_pfad
        )
    )
    assert len(lineage["transformationsplan"]["schritte"]) == 3
    assert len(lineage["transformationshistorie"]) == 3
    fachhistorie = service.fachliche_transformationshistorie_laden(abschluss.datensatz)
    assert len(fachhistorie) == 3
    assert [wert["reihenfolge"] for wert in fachhistorie] == [1, 2, 3]
    assert fachhistorie[0]["eingang"] == "ursprüngliche Datenquelle D"
    assert fachhistorie[-1]["ergebnis"] == "aktiver Zwischendatensatz T"
    assert all(wert["betroffener_datensatz"] == "Zwischendatensatz T" for wert in fachhistorie)
    assert not any("id" in schluessel.lower() for wert in fachhistorie for schluessel in wert)


def test_schritt_entfernen_nummeriert_neu_und_persistiert_kein_t(tmp_path: Path) -> None:
    service, plan = _vorbereiten(tmp_path)
    erster = _schritt(
        Transformationsart.WERTE_ERSETZEN,
        ("status",),
        {"gesuchte_werte": ["alt"], "ersatzwert": "neu"},
        "Status ersetzen",
    )
    zweiter = _schritt(
        Transformationsart.WERTE_ERSETZEN,
        ("von",),
        {"gesuchte_werte": ["B"], "ersatzwert": "entfernt"},
        "Zwischenschritt",
    )
    dritter = _schritt(
        Transformationsart.ZEILEN_LOESCHEN,
        ("status",),
        {"operator": "gleich", "wert": "bleibt"},
        "Restzeile löschen",
    )
    for schritt in (erster, zweiter, dritter):
        plan, _, _ = service.transformation_anwenden(plan, schritt)

    plan, ergebnis = service.schritt_entfernen_und_vorschau(
        plan, plan.schritte[1].transformationsschritt_id
    )

    assert [wert.reihenfolge for wert in plan.schritte] == [1, 2]
    assert [wert.beschreibung for wert in plan.schritte] == [
        "Status ersetzen",
        "Restzeile löschen",
    ]
    assert ergebnis.daten["status"].tolist() == ["neu", "neu"]
    assert service.datensaetze_fuer_projekt(plan.projekt_id) == []


def test_plan_und_vorschau_bleiben_ueber_neue_serviceinstanz_reproduzierbar(
    tmp_path: Path,
) -> None:
    service, plan = _vorbereiten(tmp_path)
    plan, erwartet, _ = service.transformation_anwenden(
        plan,
        _schritt(
            Transformationsart.ZEILEN_LOESCHEN,
            ("status",),
            {"operator": "enthält", "wert": "alt"},
            "Status enthält alt",
        ),
    )

    geladen = service.plan_laden(plan.transformationsplan_id)
    assert geladen == plan
    assert geladen is not None
    assert service.arbeitsstand_laden(geladen)[0] is None
    pd.testing.assert_frame_equal(service.vorschau(geladen).daten, erwartet.daten)
    assert len(service.transformationshistorie(geladen)) == 1


def test_identisches_finales_ergebnis_behaelt_t_und_downstream_lineage(tmp_path: Path) -> None:
    service, plan = _vorbereiten(tmp_path)
    erster_abschluss = service.zwischendatensatz_abschliessen(plan)
    historischer_plan = Transformationsplan.neu(plan.projekt_id, plan.import_ids)
    historischer_datensatz = service.zwischendatensatz_erzeugen(
        historischer_plan,
        service.vorschau(historischer_plan),
        uuid4(),
        aktivieren=False,
    )
    assert service._aktive_lineage is not None  # noqa: SLF001
    mapping_id = uuid4()
    service._aktive_lineage.aktivieren(  # noqa: SLF001
        plan.projekt_id,
        LineageEndpunkt.M,
        {"aktuelle_mappingtabelle_id": mapping_id},
    )
    plan, _, _ = service.transformation_anwenden(
        plan,
        _schritt(
            Transformationsart.WERTE_ERSETZEN,
            ("status",),
            {"gesuchte_werte": ["kommt nicht vor"], "ersatzwert": "neu"},
            "Wirkungslose Ersetzung",
        ),
    )

    abschluss = service.zwischendatensatz_abschliessen(
        plan,
        bisheriger_datensatz_id=erster_abschluss.datensatz.zwischendatensatz_id,
    )
    checkpoint = service._aktive_lineage.laden(plan.projekt_id)  # noqa: SLF001

    assert abschluss.datensatz_wiederverwendet
    assert abschluss.datensatz.zwischendatensatz_id == (
        erster_abschluss.datensatz.zwischendatensatz_id
    )
    assert len(service.datensaetze_fuer_projekt(plan.projekt_id)) == 1
    assert checkpoint is not None and checkpoint.endpunkt is LineageEndpunkt.M
    assert checkpoint.referenzen["aktuelle_mappingtabelle_id"] == str(mapping_id)
    assert abschluss.datensatz.transformationsplan_id == plan.transformationsplan_id
    assert not service._artefakte.pfad(  # noqa: SLF001
        historischer_datensatz.relativer_daten_pfad
    ).exists()


def test_geaendertes_finales_ergebnis_ersetzt_t_und_invalidiert_downstream(
    tmp_path: Path,
) -> None:
    service, plan = _vorbereiten(tmp_path)
    erster_abschluss = service.zwischendatensatz_abschliessen(plan)
    historischer_plan = Transformationsplan.neu(plan.projekt_id, plan.import_ids)
    historischer_datensatz = service.zwischendatensatz_erzeugen(
        historischer_plan,
        service.vorschau(historischer_plan),
        uuid4(),
        aktivieren=False,
    )
    assert service._aktive_lineage is not None  # noqa: SLF001
    service._aktive_lineage.aktivieren(  # noqa: SLF001
        plan.projekt_id,
        LineageEndpunkt.M,
        {"aktuelle_mappingtabelle_id": uuid4()},
    )
    plan, _, _ = service.transformation_anwenden(
        plan,
        _schritt(
            Transformationsart.ZEILEN_LOESCHEN,
            ("status",),
            {"operator": "gleich", "wert": "alt"},
            "Alte Statuszeilen löschen",
        ),
    )

    abschluss = service.zwischendatensatz_abschliessen(
        plan,
        bisheriger_datensatz_id=erster_abschluss.datensatz.zwischendatensatz_id,
    )
    checkpoint = service._aktive_lineage.laden(plan.projekt_id)  # noqa: SLF001

    assert abschluss.daten_geaendert
    assert abschluss.datensatz.zwischendatensatz_id != (
        erster_abschluss.datensatz.zwischendatensatz_id
    )
    assert [
        wert.zwischendatensatz_id for wert in service.datensaetze_fuer_projekt(plan.projekt_id)
    ] == [abschluss.datensatz.zwischendatensatz_id]
    assert checkpoint is not None and checkpoint.endpunkt is LineageEndpunkt.T
    assert "aktuelle_mappingtabelle_id" not in checkpoint.referenzen
    assert not service._artefakte.pfad(  # noqa: SLF001
        erster_abschluss.datensatz.relativer_daten_pfad
    ).exists()
    assert not service._artefakte.pfad(  # noqa: SLF001
        historischer_datensatz.relativer_daten_pfad
    ).exists()
