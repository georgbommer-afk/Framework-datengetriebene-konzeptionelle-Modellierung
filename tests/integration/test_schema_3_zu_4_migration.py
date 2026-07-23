"""Integrationstests der additiven Migration von Schema 3 auf 4."""

import sqlite3
from pathlib import Path

import pytest

from framework_mvp.infrastructure.exceptions import NichtUnterstuetzteSchemaversion
from framework_mvp.infrastructure.persistence import sqlite_schema
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    SQLiteProjektRepository,
)


def _version_drei_anlegen(pfad: Path) -> None:
    SQLiteProjektRepository(pfad).auflisten()
    with sqlite3.connect(pfad) as verbindung:
        verbindung.execute("DROP TABLE importvorgaenge")
        verbindung.execute("PRAGMA user_version = 3")


def test_schema_drei_wird_additiv_auf_vier_migriert(tmp_path: Path) -> None:
    """Die neue Tabelle und ihre drei Suchindizes werden ergänzt."""
    pfad = tmp_path / "migration.sqlite"
    _version_drei_anlegen(pfad)
    SQLiteProjektRepository(pfad).auflisten()
    with sqlite3.connect(pfad) as verbindung:
        assert verbindung.execute("PRAGMA user_version").fetchone()[0] == 4
        tabellen = {zeile[0] for zeile in verbindung.execute("SELECT name FROM sqlite_master")}
    assert {
        "projekte",
        "datenquellen",
        "importvorgaenge",
        "transformationsplaene",
        "zwischendatensaetze",
        "semantische_mappings",
    } <= tabellen
    assert {
        "idx_importvorgaenge_projekt_id",
        "idx_importvorgaenge_datenquellen_id",
        "idx_importvorgaenge_sha256",
    } <= tabellen


def test_migration_erhaelt_projekt_und_datenquellentabelle(tmp_path: Path) -> None:
    """Vorhandene Tabellen werden weder ersetzt noch in ihrer Struktur verändert."""
    pfad = tmp_path / "migration.sqlite"
    _version_drei_anlegen(pfad)
    with sqlite3.connect(pfad) as verbindung:
        vorher = {
            name: tuple(verbindung.execute(f"PRAGMA table_info({name})"))
            for name in ("projekte", "datenquellen")
        }
    SQLiteProjektRepository(pfad).auflisten()
    with sqlite3.connect(pfad) as verbindung:
        nachher = {
            name: tuple(verbindung.execute(f"PRAGMA table_info({name})"))
            for name in ("projekte", "datenquellen")
        }
    assert nachher == vorher


def test_migration_rollt_bei_fehler_zurueck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Eine fehlerhafte Version-4-Anweisung setzt weder Tabelle noch user_version dauerhaft."""
    pfad = tmp_path / "migration.sqlite"
    _version_drei_anlegen(pfad)
    monkeypatch.setattr(sqlite_schema, "IMPORTVORGAENGE_SCHEMA_VERSION_4", "CREATE TABL defekt")
    with sqlite3.connect(pfad) as verbindung, pytest.raises(sqlite3.OperationalError):
        sqlite_schema.initialisiere_schema(verbindung)
    with sqlite3.connect(pfad) as verbindung:
        assert verbindung.execute("PRAGMA user_version").fetchone()[0] == 3
        assert (
            verbindung.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = 'importvorgaenge'"
            ).fetchone()[0]
            == 0
        )


def test_version_fuenf_wird_abgelehnt(tmp_path: Path) -> None:
    """Eine unbekannte neuere Version bleibt unverändert."""
    pfad = tmp_path / "version-fuenf.sqlite"
    with sqlite3.connect(pfad) as verbindung:
        verbindung.execute("PRAGMA user_version = 5")
    with pytest.raises(NichtUnterstuetzteSchemaversion):
        SQLiteProjektRepository(pfad).auflisten()
