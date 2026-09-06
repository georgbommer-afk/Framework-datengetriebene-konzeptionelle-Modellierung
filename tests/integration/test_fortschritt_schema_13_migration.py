"""Migration trennt alte Navigationspositionen konservativ vom Abschlussstand."""

import sqlite3
from pathlib import Path

from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.models import Systemtyp, Untersuchungsauftrag
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    SQLiteProjektRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema


def test_schema_12_migriert_position_ohne_scheinfortschritt(tmp_path: Path) -> None:
    db = tmp_path / "schema-12.sqlite"
    service = ProjektService(SQLiteProjektRepository(db))
    projekte = [
        service.projekt_anlegen(
            bezeichnung=name,
            untersuchungsauftrag=Untersuchungsauftrag(
                "Problem", "Zweck", Systemtyp.PRODUKTION, "Grenze"
            ),
        )
        for name in ("Teilstand", "Abgeschlossen")
    ]
    with sqlite3.connect(db) as verbindung:
        verbindung.execute(
            "ALTER TABLE projektfortschritt DROP COLUMN abgeschlossene_unterschritte_json"
        )
        for projekt, status in zip(projekte, ("in_bearbeitung", "abgeschlossen"), strict=True):
            verbindung.execute(
                """
                INSERT INTO projektfortschritt (
                    projekt_id, framework_schritt, fachlicher_unterschritt,
                    fortschritt_zaehler, fortschritt_nenner, phase, status,
                    gespeichert_am_utc, revision
                ) VALUES (?, 4, 'Semantische Rollen und Attribute auswählen',
                          16, 28, 1, ?, '2026-09-06T00:00:00+00:00', 3)
                """,
                (str(projekt.projekt_id), status),
            )
        verbindung.execute("PRAGMA user_version = 12")

    with sqlite3.connect(db) as verbindung:
        initialisiere_schema(verbindung)
        zeilen = verbindung.execute(
            "SELECT status, abgeschlossene_unterschritte_json "
            "FROM projektfortschritt ORDER BY status DESC"
        ).fetchall()
        assert verbindung.execute("PRAGMA user_version").fetchone()[0] == 13

    nach_status = dict(zeilen)
    assert nach_status["in_bearbeitung"] == "[0,0,0,0,0,0,0,0,0,0]"
    assert nach_status["abgeschlossen"] == "[5,5,3,4,4,3,1,1,1,1]"
