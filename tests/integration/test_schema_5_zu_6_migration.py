"""Integrationstests der additiven Migration auf Schemaversion 6."""

import sqlite3
from pathlib import Path

import pytest

from framework_mvp.infrastructure.exceptions import NichtUnterstuetzteSchemaversion
from framework_mvp.infrastructure.persistence import sqlite_schema
from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema


def test_migration_5_zu_6_ist_additiv_und_indiziert(tmp_path: Path) -> None:
    """Bestehende Daten bleiben erhalten und die neue Tabelle ist vollständig indiziert."""
    db = tmp_path / "migration.sqlite"
    with sqlite3.connect(db) as verbindung:
        verbindung.execute("CREATE TABLE bestand (wert TEXT NOT NULL)")
        verbindung.execute("INSERT INTO bestand VALUES ('unveraendert')")
        verbindung.execute("PRAGMA user_version = 5")
        verbindung.commit()
        initialisiere_schema(verbindung)
        assert verbindung.execute("PRAGMA user_version").fetchone()[0] == 11
        assert verbindung.execute("SELECT wert FROM bestand").fetchone()[0] == "unveraendert"
        indizes = {
            zeile[1]
            for zeile in verbindung.execute("PRAGMA index_list(process_mining_analysen)").fetchall()
        }
    assert {
        "idx_process_mining_projekt_id",
        "idx_process_mining_event_log_id",
        "idx_process_mining_qualitaetspruefung_id",
    } <= indizes


def test_migration_rollback_und_neuere_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fehler setzen Version 5 nicht hoch; eine unbekannte neuere Version bleibt erhalten."""
    db = tmp_path / "rollback.sqlite"
    with sqlite3.connect(db) as verbindung:
        verbindung.execute("PRAGMA user_version = 5")
        verbindung.commit()
        monkeypatch.setattr(
            sqlite_schema,
            "PROCESS_MINING_SCHEMA_VERSION_6",
            "CREATE TABLE teilweise (id TEXT); UNGUELTIGE ANWEISUNG",
        )
        with pytest.raises(sqlite3.OperationalError):
            initialisiere_schema(verbindung)
        assert verbindung.execute("PRAGMA user_version").fetchone()[0] == 5
        assert (
            verbindung.execute("SELECT name FROM sqlite_master WHERE name='teilweise'").fetchone()
            is None
        )
    neuer = tmp_path / "neuer.sqlite"
    with sqlite3.connect(neuer) as verbindung:
        verbindung.execute("PRAGMA user_version = 12")
        with pytest.raises(NichtUnterstuetzteSchemaversion):
            initialisiere_schema(verbindung)
        assert verbindung.execute("PRAGMA user_version").fetchone()[0] == 12
