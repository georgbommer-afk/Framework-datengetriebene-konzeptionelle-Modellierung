"""Reproduzierbare Persistenz der Schritt-4-Konfiguration und des Event Logs E."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pandas as pd
import pytest

from framework_mvp.application.event_log_service import EventLogService
from framework_mvp.application.mapping_service import MappingService
from framework_mvp.application.mappingtabelle_service import MappingtabelleService
from framework_mvp.domain.models import (
    Aktivitaetsbildungsart,
    Aktivitaetsdefinition,
    Attributrolle,
    Mappingeintrag,
    MappingModus,
    Mappingstatus,
    Mappingtabelle,
    Projekt,
    SemantischesMapping,
    Spaltenzuordnung,
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
from framework_mvp.infrastructure.persistence.sqlite_mappingtabelle_repository import (
    SQLiteMappingtabelleRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    SQLiteProjektRepository,
)
from framework_mvp.workspace import WorkspaceKonfiguration


class _Transformationen:
    def __init__(
        self, datensatz: Zwischendatensatz, daten: pd.DataFrame, plan: Transformationsplan
    ) -> None:
        self.datensatz = datensatz
        self.daten = daten
        self.plan = plan

    def zwischendatensatz_laden(self, datensatz_id: UUID) -> tuple[Zwischendatensatz, pd.DataFrame]:
        if datensatz_id != self.datensatz.zwischendatensatz_id:
            raise AssertionError("Unerwarteter Zwischendatensatz")
        return self.datensatz, self.daten.copy(deep=True)

    def plan_laden(self, plan_id: UUID) -> Transformationsplan | None:
        return self.plan if plan_id == self.plan.transformationsplan_id else None


def test_konfiguration_m_und_e_bleiben_vollstaendig_reproduzierbar(tmp_path: Path) -> None:
    db = tmp_path / "framework.sqlite"
    workspace = WorkspaceKonfiguration.ermitteln(tmp_path / "workspace")
    speicher = ImportartefaktSpeicher(workspace)
    projekt = Projekt.neu("Schritt 4", Untersuchungsauftrag("", "", Systemtyp.KOMBINIERT, ""))
    SQLiteProjektRepository(db).speichern(projekt)
    jetzt = datetime.now(UTC)
    plan = Transformationsplan(uuid4(), projekt.projekt_id, (uuid4(),), (), jetzt, jetzt)
    etl_repository = SQLiteETLRepository(db)
    etl_repository.plan_speichern(plan)
    datensatz = Zwischendatensatz(
        uuid4(),
        projekt.projekt_id,
        plan.transformationsplan_id,
        plan.import_ids,
        "projects/x/interim/T.csv.gz",
        "projects/x/interim/T.schema.json",
        "projects/x/interim/T.transformation.json",
        "a" * 64,
        2,
        5,
        jetzt,
    )
    etl_repository.datensatz_speichern(datensatz)
    daten = pd.DataFrame(
        {
            "fall": ["A", "A"],
            "aktion": ["S", "E"],
            "zeit": ["2025-01-02", "2025-01-01"],
            "ende": ["2025-01-03", "2025-01-02"],
            "ressource": ["R1", "R2"],
        }
    )
    transformationen = _Transformationen(datensatz, daten, plan)
    mappingtabelle_service = MappingtabelleService(
        SQLiteMappingtabelleRepository(db),
        transformationen,  # type: ignore[arg-type]
        speicher,
    )
    mappingtabelle = Mappingtabelle.neu(projekt.projekt_id, datensatz.zwischendatensatz_id)
    mappingtabelle = mappingtabelle.eintrag_hinzufuegen(
        Mappingeintrag.fuer_wert("aktion", "S", "Start")
    )
    mappingtabelle = mappingtabelle.eintrag_hinzufuegen(
        Mappingeintrag.fuer_spalte("ressource", "Ausführende Ressource")
    ).bestaetigen()
    unveraendertes_m = mappingtabelle
    unveraendertes_t = daten.copy(deep=True)
    mappingtabelle_service.speichern(mappingtabelle)

    konfigurations_service = MappingService(
        SQLiteMappingRepository(db),
        transformationen,  # type: ignore[arg-type]
        speicher,
    )
    konfiguration = SemantischesMapping(
        uuid4(),
        projekt.projekt_id,
        datensatz.zwischendatensatz_id,
        MappingModus.EREIGNISORIENTIERT,
        ZusammengesetzteFallId(("fall",)),
        "aktion",
        "zeit",
        "",
        "",
        "",
        "",
        (Spaltenzuordnung("ressource", Attributrolle.EREIGNISATTRIBUT),),
        (),
        None,
        jetzt,
        jetzt,
        Mappingstatus.ENTWURF,
        Aktivitaetsdefinition(Aktivitaetsbildungsart.VORHANDENE_SPALTE, ("aktion",)),
        mappingtabelle.mapping_id,
        2,
    )
    konfiguration, validierung = konfigurations_service.validieren(konfiguration, daten)
    assert validierung.validierung.gueltig
    konfigurationspfad = konfigurations_service.speichern(konfiguration)
    assert konfigurations_service.laden(konfiguration.mapping_id) == konfiguration
    struktur = json.loads(speicher.lesen(konfigurationspfad))
    assert struktur["artefakt_version"] == 2
    assert struktur["mapping"]["mappingtabelle_id"] == str(mappingtabelle.mapping_id)
    assert struktur["mapping"]["konfigurationsversion"] == 2

    event_service = EventLogService(
        SQLiteEventLogRepository(db),
        konfigurations_service,
        transformationen,  # type: ignore[arg-type]
        speicher,
        mappingtabelle_service,
    )
    version_drei = replace(
        konfiguration,
        mapping_id=uuid4(),
        ressourcen_spalte="ressource",
        spaltenzuordnungen=(),
        validierung=None,
        status=Mappingstatus.ENTWURF,
        konfigurationsversion=3,
    )
    version_drei, pruefung_drei = konfigurations_service.validieren(version_drei, daten)
    assert pruefung_drei.validierung.gueltig
    pfad_drei = konfigurations_service.speichern(version_drei)
    assert konfigurations_service.laden(version_drei.mapping_id) == version_drei
    struktur_drei = json.loads(speicher.lesen(pfad_drei))
    assert struktur_drei["artefakt_version"] == 2
    assert struktur_drei["mapping"]["konfigurationsversion"] == 3
    assert event_service.vorschau(version_drei.mapping_id).ereignisse["resource"].tolist() == [
        "R2",
        "R1",
    ]

    version_vier = replace(
        version_drei,
        mapping_id=uuid4(),
        startzeitstempelspalte="zeit",
        endzeitstempelspalte="ende",
        validierung=None,
        status=Mappingstatus.ENTWURF,
        konfigurationsversion=4,
    )
    version_vier, pruefung_vier = konfigurations_service.validieren(version_vier, daten)
    assert pruefung_vier.validierung.gueltig
    pfad_vier = konfigurations_service.speichern(version_vier)
    assert konfigurations_service.laden(version_vier.mapping_id) == version_vier
    struktur_vier = json.loads(speicher.lesen(pfad_vier))
    assert struktur_vier["mapping"]["konfigurationsversion"] == 4
    assert struktur_vier["mapping"]["zeitstempelspalte"] == "zeit"
    assert struktur_vier["mapping"]["startzeitstempelspalte"] == "zeit"
    assert struktur_vier["mapping"]["endzeitstempelspalte"] == "ende"
    vorschau_vier = event_service.vorschau(version_vier.mapping_id)
    assert vorschau_vier.herkunft_standardspalten["timestamp"] == "zeit"
    assert vorschau_vier.herkunft_standardspalten["start_timestamp"] == "zeit"
    assert vorschau_vier.herkunft_standardspalten["end_timestamp"] == "ende"
    artefakt_vier = event_service.speichern(uuid4(), version_vier.mapping_id)
    lineage_vier = json.loads(speicher.lesen(artefakt_vier.relativer_lineage_pfad))
    assert lineage_vier["event_log_konfiguration"]["konfigurationsversion"] == 4
    assert lineage_vier["herkunft_standardspalten"]["timestamp"] == "zeit"
    assert lineage_vier["herkunft_standardspalten"]["start_timestamp"] == "zeit"
    assert lineage_vier["herkunft_standardspalten"]["end_timestamp"] == "ende"

    event_log_id = uuid4()
    event_service.vorschau(konfiguration.mapping_id)
    artefakt = event_service.speichern(event_log_id, konfiguration.mapping_id)
    assert event_service.speichern(event_log_id, konfiguration.mapping_id) == artefakt
    geladenes_artefakt, ereignisse = event_service.laden(event_log_id)
    assert geladenes_artefakt == artefakt
    assert ereignisse["activity"].tolist() == ["E", "Start"]
    assert ereignisse["Ausführende Ressource"].tolist() == ["R2", "R1"]
    lineage = json.loads(speicher.lesen(artefakt.relativer_lineage_pfad))
    assert lineage["mappingtabelle_id"] == str(mappingtabelle.mapping_id)
    assert len(lineage["angewandte_fachliche_zuordnungen"]) == 2
    assert lineage["event_log_konfiguration"]["mapping_id"] == str(konfiguration.mapping_id)
    pd.testing.assert_frame_equal(daten, unveraendertes_t)
    assert mappingtabelle_service.laden(mappingtabelle.mapping_id) == unveraendertes_m
    assert artefakt.status.value == "erzeugt"

    schema_bytes = speicher.lesen(artefakt.relativer_schema_pfad)
    schema = json.loads(schema_bytes)
    schema["sha256"] = "0" * 64
    speicher.artefakt_ersetzen(
        artefakt.relativer_schema_pfad,
        json.dumps(schema, ensure_ascii=False).encode("utf-8"),
    )
    with pytest.raises(Importintegritaetsfehler, match="Schema und CSV.GZ"):
        event_service.laden(event_log_id)
    speicher.artefakt_ersetzen(artefakt.relativer_schema_pfad, schema_bytes)

    manipuliert = struktur
    manipuliert["mapping"]["zeitstempelspalte"] = "andere_spalte"
    speicher.artefakt_ersetzen(
        konfigurationspfad,
        json.dumps(manipuliert, ensure_ascii=False, default=str).encode("utf-8"),
    )
    with pytest.raises(Importintegritaetsfehler, match="inkonsistent"):
        konfigurations_service.laden(konfiguration.mapping_id)
