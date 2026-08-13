"""Additive Migration der Modellableitung auf Schemaversion 9."""

import sqlite3
from pathlib import Path

from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema


def test_migration_8_zu_9_ergaenzt_k_und_o_ohne_bestandsverlust(tmp_path: Path) -> None:
    db = tmp_path / "migration.sqlite"
    with sqlite3.connect(db) as verbindung:
        verbindung.execute("CREATE TABLE bestand (wert TEXT NOT NULL)")
        verbindung.execute("INSERT INTO bestand VALUES ('unveraendert')")
        verbindung.execute("PRAGMA user_version = 8")
        verbindung.commit()
        initialisiere_schema(verbindung)

        assert verbindung.execute("PRAGMA user_version").fetchone()[0] == 11
        assert verbindung.execute("SELECT wert FROM bestand").fetchone()[0] == "unveraendert"
        spalten = {
            wert[1]
            for wert in verbindung.execute("PRAGMA table_info(modellableitungen)").fetchall()
        }
        assert spalten == {
            "modellableitungs_id",
            "k_id",
            "o_id",
            "projekt_id",
            "aggregations_id",
            "analyse_id",
            "event_log_id",
            "eingabefingerabdruck",
            "mappingversion",
            "unsicherheitsfingerabdruck",
            "relativer_k_pfad",
            "k_sha256",
            "relativer_o_pfad",
            "o_sha256",
            "status",
            "erstellt_am_utc",
        }
