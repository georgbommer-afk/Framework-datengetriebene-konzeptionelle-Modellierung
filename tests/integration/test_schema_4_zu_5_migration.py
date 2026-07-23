"""Integrationstests der additiven Migration auf Event Log und Qualität."""

import sqlite3
from pathlib import Path

import pytest

from framework_mvp.domain.models import Projekt, Systemtyp, Untersuchungsauftrag
from framework_mvp.infrastructure.persistence import sqlite_schema
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    SQLiteProjektRepository,
)


def _version_vier(pfad: Path) -> None:
    SQLiteProjektRepository(pfad).auflisten()
    with sqlite3.connect(pfad) as verbindung:
        for name in (
            "qualitaetsmassnahmen",
            "qualitaetsregeln",
            "qualitaetspruefungen",
            "event_logs",
        ):
            verbindung.execute(f"DROP TABLE {name}")
        verbindung.execute("PRAGMA user_version = 4")


def test_version_vier_wird_additiv_auf_fuenf_migriert(tmp_path: Path) -> None:
    """Alle vier neuen Tabellen werden ergänzt und vorhandene Tabellen bleiben bestehen."""
    pfad = tmp_path / "migration.sqlite"
    projekt = Projekt.neu("Bestand", Untersuchungsauftrag("", "", Systemtyp.KOMBINIERT, ""))
    SQLiteProjektRepository(pfad).speichern(projekt)
    _version_vier(pfad)
    with sqlite3.connect(pfad) as verbindung:
        vorher = verbindung.execute(
            "SELECT * FROM projekte WHERE projekt_id=?", (str(projekt.projekt_id),)
        ).fetchone()
    SQLiteProjektRepository(pfad).auflisten()
    with sqlite3.connect(pfad) as verbindung:
        assert verbindung.execute("PRAGMA user_version").fetchone()[0] == 6
        tabellen = {
            wert[0]
            for wert in verbindung.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        nachher = verbindung.execute(
            "SELECT * FROM projekte WHERE projekt_id=?", (str(projekt.projekt_id),)
        ).fetchone()
    assert {
        "event_logs",
        "qualitaetspruefungen",
        "qualitaetsregeln",
        "qualitaetsmassnahmen",
        "projekte",
        "zwischendatensaetze",
    } <= tabellen
    assert nachher == vorher


def test_migration_auf_fuenf_rollt_bei_fehler_zurueck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fehlerhafte DDL hinterlässt weder Tabellen noch eine erhöhte Version."""
    pfad = tmp_path / "rollback.sqlite"
    _version_vier(pfad)
    monkeypatch.setattr(
        sqlite_schema,
        "EVENT_LOG_QUALITAET_SCHEMA_VERSION_5",
        "CREATE TABLE event_logs_neu (id TEXT); CREATE TABL defekt",
    )
    with sqlite3.connect(pfad) as verbindung, pytest.raises(sqlite3.OperationalError):
        sqlite_schema.initialisiere_schema(verbindung)
    with sqlite3.connect(pfad) as verbindung:
        assert verbindung.execute("PRAGMA user_version").fetchone()[0] == 4
        assert (
            verbindung.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name='event_logs_neu'"
            ).fetchone()[0]
            == 0
        )
