"""Integrationstest der Process-Mining-Metadatenpersistenz."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from framework_mvp.domain.models import (
    DiscoveryVerfahren,
    ProcessMiningAnalyse,
    ProcessMiningStatus,
)
from framework_mvp.infrastructure.persistence.sqlite_process_mining_repository import (
    SQLiteProcessMiningRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema


def test_analyse_speichern_laden_und_projektbezogen_auflisten(tmp_path: Path) -> None:
    """JSON-Felder und relative Artefaktpfade bleiben vollständig erhalten."""
    db = tmp_path / "repository.sqlite"
    projekt_id = uuid4()
    event_log_id = uuid4()
    quality_id = uuid4()
    with sqlite3.connect(db) as verbindung:
        initialisiere_schema(verbindung)
        # Der Repositorytest setzt nachfolgend bewusst minimale Fremdartefakte ein.
        verbindung.execute("PRAGMA foreign_keys = OFF")
        verbindung.execute(
            "INSERT INTO projekte VALUES (?, 'P', '[]', 'entwurf', ?, ?, '{}')",
            (str(projekt_id), datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat()),
        )
        verbindung.execute(
            "INSERT INTO event_logs VALUES "
            "(?, ?, ?, ?, 'erzeugt', 1, 1, 1, NULL, NULL, 'e.csv.gz', "
            "'e.schema.json', 'e.lineage.json', '', ?, ?)",
            (
                str(event_log_id),
                str(projekt_id),
                str(uuid4()),
                str(uuid4()),
                "a" * 64,
                datetime.now(UTC).isoformat(),
            ),
        )
        verbindung.execute(
            "INSERT INTO qualitaetspruefungen VALUES "
            "(?, ?, ?, '{}', '{}', 'q.report.json', 'q.measures.json', "
            "'q.csv.gz', ?, ?)",
            (
                str(quality_id),
                str(projekt_id),
                str(event_log_id),
                "b" * 64,
                datetime.now(UTC).isoformat(),
            ),
        )
        verbindung.commit()
    jetzt = datetime.now(UTC)
    analyse = ProcessMiningAnalyse(
        uuid4(),
        projekt_id,
        quality_id,
        event_log_id,
        '{"konfiguration":true}',
        '[{"filter":"keiner"}]',
        DiscoveryVerfahren.INDUCTIVE_MINER,
        '{"noise_threshold":0.0}',
        5,
        2,
        3,
        2,
        4,
        2,
        3,
        1,
        '{"stellen":4}',
        "[]",
        "2.7.23.3",
        f"projects/{projekt_id}/process_mining/a.summary.json",
        f"projects/{projekt_id}/process_mining/a.variants.csv.gz",
        f"projects/{projekt_id}/process_mining/a.dfg.json",
        f"projects/{projekt_id}/process_mining/a.model.pnml",
        "",
        ProcessMiningStatus.AUSGEFUEHRT,
        jetzt,
        jetzt,
    )
    repository = SQLiteProcessMiningRepository(db)
    repository.speichern(analyse)
    assert repository.laden(analyse.analyse_id) == analyse
    assert repository.fuer_projekt(projekt_id) == [analyse]
    repository.speichern(analyse)
    with sqlite3.connect(db) as verbindung:
        assert verbindung.execute("SELECT count(*) FROM process_mining_analysen").fetchone()[0] == 1
