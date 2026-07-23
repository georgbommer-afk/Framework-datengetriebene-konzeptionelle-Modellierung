"""Integrationstest der Event-Log- und Qualitätsartefakte."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pandas as pd

from framework_mvp.application.datenqualitaet import standardregeln
from framework_mvp.application.datenqualitaet_service import DatenqualitaetService
from framework_mvp.application.event_log_service import EventLogService
from framework_mvp.domain.models import (
    Attributrolle,
    MappingModus,
    Mappingstatus,
    Projekt,
    Qualitaetsmassnahmenplan,
    SemantischesMapping,
    Spaltenzuordnung,
    Systemtyp,
    Transformationsplan,
    Untersuchungsauftrag,
    ZusammengesetzteFallId,
    Zwischendatensatz,
)
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


class _MappingService:
    def __init__(self, mapping: SemantischesMapping) -> None:
        self.mapping = mapping

    def laden(self, mapping_id: UUID) -> SemantischesMapping | None:
        return self.mapping if mapping_id == self.mapping.mapping_id else None


class _TransformationService:
    def __init__(
        self,
        datensatz: Zwischendatensatz,
        daten: pd.DataFrame,
        plan: Transformationsplan,
    ) -> None:
        self.datensatz = datensatz
        self.daten = daten
        self.plan = plan

    def zwischendatensatz_laden(self, datensatz_id: UUID) -> tuple[Zwischendatensatz, pd.DataFrame]:
        assert datensatz_id == self.datensatz.zwischendatensatz_id
        return self.datensatz, self.daten.copy(deep=True)

    def plan_laden(self, plan_id: UUID) -> Transformationsplan | None:
        return self.plan if plan_id == self.plan.transformationsplan_id else None


def test_event_log_und_qualitaetsartefakte_speichern_und_laden(tmp_path: Path) -> None:
    """CSV.GZ, Schema, Lineage, Bericht und Maßnahmen bleiben projektbezogen ladbar."""
    db = tmp_path / "framework.sqlite"
    workspace = WorkspaceKonfiguration.ermitteln(tmp_path / "workspace")
    speicher = ImportartefaktSpeicher(workspace)
    projekt = Projekt.neu("Artefakte", Untersuchungsauftrag("", "", Systemtyp.KOMBINIERT, ""))
    SQLiteProjektRepository(db).speichern(projekt)
    jetzt = datetime.now(UTC)
    plan = Transformationsplan(uuid4(), projekt.projekt_id, (uuid4(),), (), jetzt, jetzt)
    etl_repo = SQLiteETLRepository(db)
    etl_repo.plan_speichern(plan)
    datensatz = Zwischendatensatz(
        uuid4(),
        projekt.projekt_id,
        plan.transformationsplan_id,
        plan.import_ids,
        "projects/x/interim/x.csv.gz",
        "projects/x/interim/x.schema.json",
        "projects/x/interim/x.transformation.json",
        "a" * 64,
        2,
        4,
        jetzt,
    )
    etl_repo.datensatz_speichern(datensatz)
    mapping = SemantischesMapping(
        uuid4(),
        projekt.projekt_id,
        datensatz.zwischendatensatz_id,
        MappingModus.EREIGNISORIENTIERT,
        ZusammengesetzteFallId(("fall",)),
        "aktivitaet",
        "zeit",
        "",
        "",
        "",
        "",
        (Spaltenzuordnung("attribut", Attributrolle.EREIGNISATTRIBUT),),
        (),
        None,
        jetzt,
        jetzt,
        Mappingstatus.VALIDIERT,
    )
    mapping_pfad = f"projects/{projekt.projekt_id}/mappings/{mapping.mapping_id}.json"
    SQLiteMappingRepository(db).speichern(mapping, mapping_pfad)
    daten = pd.DataFrame(
        {
            "fall": ["A", "A"],
            "aktivitaet": ["Start", "Ende"],
            "zeit": ["2025-01-01", "2025-01-02"],
            "attribut": ["x", "y"],
        }
    )
    event_service = EventLogService(
        SQLiteEventLogRepository(db),
        _MappingService(mapping),  # type: ignore[arg-type]
        _TransformationService(datensatz, daten, plan),  # type: ignore[arg-type]
        speicher,
    )
    event_log = event_service.speichern(uuid4(), mapping.mapping_id)
    geladen, tabelle = event_service.laden(event_log.event_log_id)
    assert geladen == event_log
    assert tabelle["event_id"].is_unique
    assert event_log.relativer_xes_pfad == ""
    assert not list(workspace.basisverzeichnis.rglob("*.xes"))
    assert (workspace.basisverzeichnis / event_log.relativer_csv_pfad).is_file()
    schema = json.loads((workspace.basisverzeichnis / event_log.relativer_schema_pfad).read_text())
    lineage = json.loads(
        (workspace.basisverzeichnis / event_log.relativer_lineage_pfad).read_text()
    )
    assert schema["artefaktversion"] == 1
    assert lineage["mapping_id"] == str(mapping.mapping_id)

    qualitaet = DatenqualitaetService(SQLiteQualitaetRepository(db), event_service, speicher)
    qualitaetsartefakt = qualitaet.speichern(
        uuid4(), event_log.event_log_id, standardregeln(), Qualitaetsmassnahmenplan(())
    )
    assert (workspace.basisverzeichnis / qualitaetsartefakt.relativer_report_pfad).is_file()
    assert (workspace.basisverzeichnis / qualitaetsartefakt.relativer_massnahmen_pfad).is_file()
    assert (workspace.basisverzeichnis / qualitaetsartefakt.relativer_csv_pfad).is_file()
    erneut, qualitaetsdaten = qualitaet.laden(qualitaetsartefakt.quality_run_id)
    assert erneut == qualitaetsartefakt
    assert len(qualitaetsdaten) == 2
