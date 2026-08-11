"""Additive gemeinsame Migration für Schritt 9 und 10 auf Schemaversion 10."""

import sqlite3
from pathlib import Path

from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema


def test_migration_9_zu_10_ergaenzt_k_stern_ohne_bestandsverlust(tmp_path: Path) -> None:
    db = tmp_path / "migration.sqlite"
    with sqlite3.connect(db) as verbindung:
        verbindung.execute("CREATE TABLE bestand (wert TEXT NOT NULL)")
        verbindung.execute("INSERT INTO bestand VALUES ('unveraendert')")
        verbindung.execute("PRAGMA user_version = 9")
        verbindung.commit()
        initialisiere_schema(verbindung)

        assert verbindung.execute("PRAGMA user_version").fetchone()[0] == 10
        assert verbindung.execute("SELECT wert FROM bestand").fetchone()[0] == "unveraendert"
        spalten = {
            wert[1]
            for wert in verbindung.execute("PRAGMA table_info(modellvalidierungen)").fetchall()
        }
        assert spalten == {
            "validierungslauf_id",
            "k_stern_id",
            "projekt_id",
            "modellableitungs_id",
            "k_id",
            "o_id",
            "eingabefingerabdruck",
            "entscheidungsfingerabdruck",
            "relativer_k_stern_pfad",
            "k_stern_sha256",
            "status",
            "erstellt_am_utc",
        }
