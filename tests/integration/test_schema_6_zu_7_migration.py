"""Integrationstests der additiven Migration für Mappingtabellen M."""

import sqlite3
from pathlib import Path

from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema


def test_migration_6_zu_7_ergaenzt_mappingtabellen_ohne_bestandsverlust(
    tmp_path: Path,
) -> None:
    db = tmp_path / "migration.sqlite"
    with sqlite3.connect(db) as verbindung:
        verbindung.execute("CREATE TABLE bestand (wert TEXT NOT NULL)")
        verbindung.execute("INSERT INTO bestand VALUES ('unveraendert')")
        verbindung.execute("PRAGMA user_version = 6")
        verbindung.commit()

        initialisiere_schema(verbindung)

        assert verbindung.execute("PRAGMA user_version").fetchone()[0] == 7
        assert verbindung.execute("SELECT wert FROM bestand").fetchone()[0] == "unveraendert"
        spalten = {
            zeile[1]
            for zeile in verbindung.execute("PRAGMA table_info(mappingtabellen)").fetchall()
        }
        indizes = {
            zeile[1]
            for zeile in verbindung.execute("PRAGMA index_list(mappingtabellen)").fetchall()
        }
    assert {
        "mapping_id",
        "projekt_id",
        "zwischendatensatz_id",
        "mapping_json",
        "status",
        "relativer_mapping_pfad",
        "sha256",
    } <= spalten
    assert {
        "idx_mappingtabellen_projekt_id",
        "idx_mappingtabellen_datensatz_id",
    } <= indizes
