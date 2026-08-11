"""Additive Migration der Ergebnisaggregation auf Schemaversion 8."""

import sqlite3
from pathlib import Path

from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema


def test_migration_7_zu_8_ergaenzt_a_g_ohne_bestandsverlust(tmp_path: Path) -> None:
    db = tmp_path / "migration.sqlite"
    with sqlite3.connect(db) as verbindung:
        verbindung.execute("CREATE TABLE bestand (wert TEXT NOT NULL)")
        verbindung.execute("INSERT INTO bestand VALUES ('unveraendert')")
        verbindung.execute("PRAGMA user_version = 7")
        verbindung.commit()
        initialisiere_schema(verbindung)
        assert verbindung.execute("PRAGMA user_version").fetchone()[0] == 10
        assert verbindung.execute("SELECT wert FROM bestand").fetchone()[0] == "unveraendert"
        spalten = {
            wert[1]
            for wert in verbindung.execute("PRAGMA table_info(ergebnisaggregationen)").fetchall()
        }
        assert {
            "aggregations_id",
            "projekt_id",
            "spezifikations_id",
            "freigabe_id",
            "event_log_id",
            "analyse_id",
            "eingabefingerabdruck",
            "konfigurationsfingerabdruck",
            "relativer_aggregations_pfad",
            "aggregations_sha256",
            "status",
            "erstellt_am_utc",
        } == spalten
