"""Integrationstests der neuen SQLite-Persistenz für ETL und Mapping."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from framework_mvp.domain.models import (
    Aktivitaetsbildungsart,
    Aktivitaetsdefinition,
    MappingModus,
    Mappingstatus,
    Projekt,
    SemantischesMapping,
    Systemtyp,
    Transformationsplan,
    Untersuchungsauftrag,
    ZusammengesetzteFallId,
    Zwischendatensatz,
)
from framework_mvp.infrastructure.persistence.sqlite_etl_repository import SQLiteETLRepository
from framework_mvp.infrastructure.persistence.sqlite_mapping_repository import (
    SQLiteMappingRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    SQLiteProjektRepository,
)


def test_plan_datensatz_und_mapping_werden_projektbezogen_persistiert(
    tmp_path: Path,
) -> None:
    """Die neuen Metadaten bleiben über unabhängige Repositoryinstanzen ladbar."""
    pfad = tmp_path / "etl.sqlite"
    projekt = Projekt.neu(
        "Persistenz",
        Untersuchungsauftrag("", "", Systemtyp.KOMBINIERT, ""),
    )
    SQLiteProjektRepository(pfad).speichern(projekt)
    jetzt = datetime.now(UTC)
    plan = Transformationsplan(uuid4(), projekt.projekt_id, (uuid4(),), (), jetzt, jetzt)
    etl = SQLiteETLRepository(pfad)
    etl.plan_speichern(plan)
    datensatz = Zwischendatensatz(
        uuid4(),
        projekt.projekt_id,
        plan.transformationsplan_id,
        plan.import_ids,
        f"projects/{projekt.projekt_id}/interim/daten.csv.gz",
        f"projects/{projekt.projekt_id}/interim/schema.json",
        f"projects/{projekt.projekt_id}/interim/transformation.json",
        "a" * 64,
        2,
        3,
        jetzt,
    )
    etl.datensatz_speichern(datensatz)
    assert SQLiteETLRepository(pfad).plan_laden(plan.transformationsplan_id) == plan
    assert SQLiteETLRepository(pfad).datensatz_laden(datensatz.zwischendatensatz_id) == datensatz

    mapping = SemantischesMapping(
        uuid4(),
        projekt.projekt_id,
        datensatz.zwischendatensatz_id,
        MappingModus.EREIGNISORIENTIERT,
        ZusammengesetzteFallId(("id",)),
        "activity",
        "time",
        "",
        "",
        "",
        "",
        (),
        (),
        None,
        jetzt,
        jetzt,
        Mappingstatus.ENTWURF,
        Aktivitaetsdefinition(
            Aktivitaetsbildungsart.ZUSAMMENGESETZT,
            ("von", "zu"),
            " → ",
        ),
    )
    mapping_pfad = f"projects/{projekt.projekt_id}/mappings/{mapping.mapping_id}.json"
    SQLiteMappingRepository(pfad).speichern(mapping, mapping_pfad)
    geladen = SQLiteMappingRepository(pfad).laden(mapping.mapping_id)
    assert geladen == (mapping, mapping_pfad)
    assert SQLiteMappingRepository(pfad).fuer_projekt(projekt.projekt_id) == [
        (mapping, mapping_pfad)
    ]
