"""Persistenz-, Integritäts- und Legacy-Tests der unveränderten E*-Freigabe."""

import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pandas as pd
import pytest

from framework_mvp.application.datenqualitaet_service import DatenqualitaetService
from framework_mvp.application.event_log_service import EventLogKontext
from framework_mvp.domain.models import (
    Aktivitaetsbildungsart,
    Aktivitaetsdefinition,
    CsvImportparameter,
    Dateityp,
    Datenquelle,
    EventLogArtefakt,
    EventLogStatus,
    FachlicheEntscheidung,
    Importvorgang,
    MappingModus,
    Mappingstatus,
    Profilzusammenfassung,
    Projekt,
    Qualitaetsmassnahmenplan,
    QualitaetspruefungArtefakt,
    Quellenart,
    Quellsystemtyp,
    SemantischesMapping,
    Systemtyp,
    Transformationsplan,
    Untersuchungsauftrag,
    ZusammengesetzteFallId,
    Zwischendatensatz,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.infrastructure.importartefakte import ImportartefaktSpeicher
from framework_mvp.infrastructure.persistence.sqlite_etl_repository import SQLiteETLRepository
from framework_mvp.infrastructure.persistence.sqlite_event_log_repository import (
    SQLiteEventLogRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_mapping_repository import (
    SQLiteMappingRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    SQLiteProjektRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_qualitaet_repository import (
    SQLiteQualitaetRepository,
)
from framework_mvp.workspace import WorkspaceKonfiguration


class _EventLogs:
    def __init__(self, kontext: EventLogKontext) -> None:
        self.kontext = kontext

    def kontext_laden(self, event_log_id: UUID) -> EventLogKontext:
        assert event_log_id == self.kontext.artefakt.event_log_id
        return replace(
            self.kontext,
            ereignisse=self.kontext.ereignisse.copy(deep=True),
            zwischendaten=self.kontext.zwischendaten.copy(deep=True),
        )


class _Transformationen:
    def __init__(self, importvorgang: Importvorgang) -> None:
        self.importvorgang = importvorgang

    def import_laden(self, import_id: UUID) -> SimpleNamespace | None:
        if import_id != self.importvorgang.import_id:
            return None
        return SimpleNamespace(importvorgang=self.importvorgang)


class _Datenquellen:
    def __init__(self, quelle: Datenquelle) -> None:
        self.quelle = quelle

    def datenquelle_laden(self, datenquellen_id: UUID) -> Datenquelle | None:
        return self.quelle if datenquellen_id == self.quelle.datenquellen_id else None


def _umgebung(
    tmp_path: Path,
) -> tuple[
    DatenqualitaetService,
    _EventLogs,
    _Datenquellen,
    SQLiteQualitaetRepository,
    ImportartefaktSpeicher,
]:
    projekt_id, t_id, config_id, event_id, import_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    jetzt = datetime.now(UTC)
    plan_id = uuid4()
    t_daten = pd.DataFrame(
        {
            "fall": ["A", "A"],
            "aktion": ["Start", "Ende"],
            "zeit": ["2025-01-01", "2025-01-02"],
        }
    )
    e_daten = pd.DataFrame(
        {
            "case_id": ["A", "A"],
            "activity": ["Start", "Ende"],
            "timestamp": pd.to_datetime(["2025-01-01", "2025-01-02"], utc=True),
            "event_id": ["e1", "e2"],
            "_source_row": [0, 1],
            "_source_case_id_raw": ["A", "A"],
            "_source_activity_raw": ["Start", "Ende"],
            "_source_timestamp_raw": ["2025-01-01", "2025-01-02"],
            "_source_timestamp_column": ["zeit", "zeit"],
        }
    )
    datensatz = Zwischendatensatz(
        t_id,
        projekt_id,
        plan_id,
        (import_id,),
        "projects/p/interim/t.csv.gz",
        "projects/p/interim/t.schema.json",
        "projects/p/interim/t.transformation.json",
        "a" * 64,
        2,
        3,
        jetzt,
    )
    config = SemantischesMapping(
        config_id,
        projekt_id,
        t_id,
        MappingModus.EREIGNISORIENTIERT,
        ZusammengesetzteFallId(("fall",)),
        "aktion",
        "zeit",
        "",
        "",
        "",
        "",
        (),
        (),
        None,
        jetzt,
        jetzt,
        Mappingstatus.VALIDIERT,
        Aktivitaetsdefinition(Aktivitaetsbildungsart.VORHANDENE_SPALTE, ("aktion",)),
        None,
        2,
    )
    artefakt = EventLogArtefakt(
        event_id,
        projekt_id,
        t_id,
        config_id,
        EventLogStatus.ERZEUGT,
        2,
        1,
        2,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 1, 2, tzinfo=UTC),
        "projects/p/event_logs/e.csv.gz",
        "projects/p/event_logs/e.schema.json",
        "projects/p/event_logs/e.lineage.json",
        "",
        "b" * 64,
        jetzt,
    )
    event_logs = _EventLogs(
        EventLogKontext(
            artefakt,
            e_daten,
            config,
            datensatz,
            t_daten,
            None,
            {"sha256": artefakt.sha256},
            {
                "projekt_id": str(projekt_id),
                "zwischendatensatz_id": str(t_id),
                "mapping_id": str(config_id),
                "mappingtabelle_id": None,
                "herkunft_standardspalten": {
                    "case_id": "fall",
                    "activity": "aktion",
                    "timestamp": "zeit",
                },
                "angewandte_fachliche_zuordnungen": [],
            },
        )
    )
    quelle = Datenquelle.neu(
        projekt_id=projekt_id,
        bezeichnung="ERP-Export",
        quellsystemtyp=Quellsystemtyp.ERP_SYSTEM,
        quellenart=Quellenart.CSV,
        konkretes_quellsystem="ERP Produktivsystem",
        fachliche_beschreibung="Produktionsaufträge",
        herkunft_oder_verantwortungsbereich="Produktionsplanung",
    )
    importvorgang = Importvorgang.bestaetigt(
        projekt_id=projekt_id,
        datenquellen_id=quelle.datenquellen_id,
        originaldateiname="auftrag.csv",
        sicherer_dateiname="auftrag.csv",
        dateityp=Dateityp.CSV,
        dateigroesse_bytes=10,
        sha256="c" * 64,
        importparameter=CsvImportparameter(erkanntes_trennzeichen=","),
        tabellenbezeichnung="auftrag.csv",
        zeilenanzahl=2,
        spaltenanzahl=3,
        profil_version=1,
        relativer_raw_pfad="projects/p/raw/c/auftrag.csv",
        relativer_profil_pfad="projects/p/profiles/i.json",
        profilzusammenfassung=Profilzusammenfassung(0, 0, 0, 0),
        import_id=import_id,
    )
    datenquellen = _Datenquellen(quelle)
    db = tmp_path / "framework.sqlite"
    projekt = replace(
        Projekt.neu(
            "Schritt 5",
            Untersuchungsauftrag("", "", Systemtyp.KOMBINIERT, ""),
        ),
        projekt_id=projekt_id,
    )
    SQLiteProjektRepository(db).speichern(projekt)
    etl_repository = SQLiteETLRepository(db)
    etl_repository.plan_speichern(
        Transformationsplan(plan_id, projekt_id, (import_id,), (), jetzt, jetzt)
    )
    etl_repository.datensatz_speichern(datensatz)
    SQLiteMappingRepository(db).speichern(config, "projects/p/mappings/config.json")
    SQLiteEventLogRepository(db).speichern(artefakt)
    repository = SQLiteQualitaetRepository(db)
    speicher = ImportartefaktSpeicher(WorkspaceKonfiguration.ermitteln(tmp_path / "workspace"))
    service = DatenqualitaetService(
        repository,
        event_logs,  # type: ignore[arg-type]
        speicher,
        _Transformationen(importvorgang),  # type: ignore[arg-type]
        datenquellen,  # type: ignore[arg-type]
    )
    return service, event_logs, datenquellen, repository, speicher


def _entscheidungen() -> tuple[FachlicheEntscheidung, ...]:
    return (
        FachlicheEntscheidung("q_nachvollziehbar", False, ""),
        FachlicheEntscheidung("t_verwendbar", False, ""),
        FachlicheEntscheidung("m_verstaendlich", False, ""),
        FachlicheEntscheidung("e_interpretierbar", False, ""),
    )


def test_e_wird_idempotent_ohne_qualitaets_csv_als_identische_referenz_freigegeben(
    tmp_path: Path,
) -> None:
    service, event_logs, _, repository, speicher = _umgebung(tmp_path)
    projekt_id = event_logs.kontext.artefakt.projekt_id
    event_id = event_logs.kontext.artefakt.event_log_id
    original = event_logs.kontext.ereignisse.copy(deep=True)
    freigabe_id = uuid4()

    freigabe = service.freigeben(freigabe_id, projekt_id, event_id, _entscheidungen())
    assert service.freigeben(freigabe_id, projekt_id, event_id, _entscheidungen()) == freigabe
    erneut, e_stern = service.freigabe_laden(freigabe_id)

    assert erneut.event_log_id == event_id
    assert erneut.event_log_sha256 == event_logs.kontext.artefakt.sha256
    pd.testing.assert_frame_equal(e_stern, original, check_dtype=True)
    pd.testing.assert_frame_equal(event_logs.kontext.ereignisse, original, check_dtype=True)
    qualitaetsordner = tmp_path / "workspace" / "projects" / str(projekt_id) / "quality"
    assert [wert.suffix for wert in qualitaetsordner.iterdir()] == [".json"]
    report = json.loads(speicher.lesen(freigabe.relativer_report_pfad))
    assert report["artefaktversion"] == 3
    assert report["artefaktart"] == "quality_gate_freigabe_e_stern"
    assert report["bedeutung"].startswith("E* verweist unverändert auf E")
    assert len(report["quality_gate_ergebnis"]["entscheidungen"]) == 4
    assert all(
        not wert["begruendung"] for wert in report["quality_gate_ergebnis"]["entscheidungen"]
    )
    assert repository.fuer_projekt(projekt_id) == []
    assert repository.freigaben_fuer_projekt(projekt_id) == [freigabe]


def test_manipulierter_bericht_oder_geaendertes_q_entwertet_freigabe(tmp_path: Path) -> None:
    service, event_logs, datenquellen, _, speicher = _umgebung(tmp_path)
    projekt_id = event_logs.kontext.artefakt.projekt_id
    event_id = event_logs.kontext.artefakt.event_log_id
    erste_id = uuid4()
    erste = service.freigeben(erste_id, projekt_id, event_id, _entscheidungen())
    report = speicher.lesen(erste.relativer_report_pfad)
    speicher.artefakt_ersetzen(erste.relativer_report_pfad, report + b" ")
    with pytest.raises(Importintegritaetsfehler, match="Freigabeberichts"):
        service.freigabe_laden(erste_id)
    speicher.artefakt_ersetzen(erste.relativer_report_pfad, report)

    zweite_id = uuid4()
    service.freigeben(zweite_id, projekt_id, event_id, _entscheidungen())
    datenquellen.quelle = replace(
        datenquellen.quelle,
        fachliche_beschreibung="Nachträglich geänderte Datengrundlage",
    )
    with pytest.raises(Importintegritaetsfehler, match="Artefaktkette wurde"):
        service.freigabe_laden(zweite_id)
    assert service.freigaben_fuer_projekt(projekt_id) == []


def test_v2_freigabe_ohne_neue_t_und_m_bewertungen_bleibt_ladbar(tmp_path: Path) -> None:
    service, event_logs, _, _, speicher = _umgebung(tmp_path)
    projekt_id = event_logs.kontext.artefakt.projekt_id
    event_id = event_logs.kontext.artefakt.event_log_id
    freigabe = service.freigeben(uuid4(), projekt_id, event_id, _entscheidungen())
    report = json.loads(speicher.lesen(freigabe.relativer_report_pfad))
    report["artefaktversion"] = 2
    report["quality_gate_ergebnis"]["entscheidungen"] = [
        wert
        for wert in report["quality_gate_ergebnis"]["entscheidungen"]
        if wert["kriterium_id"] in {"q_nachvollziehbar", "e_interpretierbar"}
    ]
    report["quality_gate_ergebnis"]["befunde"] = [
        wert
        for wert in report["quality_gate_ergebnis"]["befunde"]
        if wert["kriterium_id"] not in {"t_verwendbar", "m_verstaendlich"}
    ]
    report_bytes = json.dumps(
        report, ensure_ascii=False, sort_keys=True, indent=2, default=str
    ).encode("utf-8")
    report_sha256 = hashlib.sha256(report_bytes).hexdigest()
    speicher.artefakt_ersetzen(freigabe.relativer_report_pfad, report_bytes)
    with sqlite3.connect(tmp_path / "framework.sqlite") as verbindung, verbindung:
        verbindung.execute(
            "UPDATE qualitaetspruefungen SET report_json=?, vergleich_json=? "
            "WHERE quality_run_id=?",
            (
                json.dumps(report, ensure_ascii=False, default=str),
                json.dumps(
                    {
                        "artefaktart": "quality_gate_freigabe_e_stern",
                        "report_sha256": report_sha256,
                    },
                    ensure_ascii=False,
                ),
                str(freigabe.freigabe_id),
            ),
        )

    geladen, e_stern = service.freigabe_laden(freigabe.freigabe_id)
    entscheidungen = service.entscheidungen_der_freigabe(freigabe.freigabe_id)

    assert geladen.freigabe_id == freigabe.freigabe_id
    pd.testing.assert_frame_equal(e_stern, event_logs.kontext.ereignisse)
    assert {wert.kriterium_id for wert in entscheidungen} == {
        "q_nachvollziehbar",
        "t_verwendbar",
        "m_verstaendlich",
        "e_interpretierbar",
    }
    assert not next(
        wert for wert in entscheidungen if wert.kriterium_id == "t_verwendbar"
    ).anmerkung


def test_legacy_qualitaetskopie_bleibt_lesbar_aber_ist_keine_e_stern_freigabe(
    tmp_path: Path,
) -> None:
    service, event_logs, _, repository, _ = _umgebung(tmp_path)
    projekt_id = event_logs.kontext.artefakt.projekt_id
    legacy = QualitaetspruefungArtefakt(
        uuid4(),
        projekt_id,
        event_logs.kontext.artefakt.event_log_id,
        "legacy.report.json",
        "legacy.measures.json",
        "legacy.csv.gz",
        "a" * 64,
        datetime.now(UTC),
    )
    repository.speichern(
        legacy,
        (),
        Qualitaetsmassnahmenplan(()),
        {"artefaktversion": 1},
        {},
    )

    assert repository.laden(legacy.quality_run_id) == legacy
    assert repository.fuer_projekt(projekt_id) == [legacy]
    assert repository.freigaben_fuer_projekt(projekt_id) == []
    with pytest.raises(Importintegritaetsfehler, match="Legacy"):
        service.freigabe_laden(legacy.quality_run_id)
