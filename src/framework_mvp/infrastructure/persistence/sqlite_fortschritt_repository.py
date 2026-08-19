"""SQLite-Lesemodell für den zuletzt erfolgreich gespeicherten Framework-Schritt."""

import sqlite3
from pathlib import Path
from uuid import UUID

from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    STANDARD_DATENBANKPFAD,
)
from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema

_ARTEFAKTE = (
    (2, "zwischendatensaetze"),
    (3, "mappingtabellen"),
    (4, "event_logs"),
    (5, "qualitaetspruefungen"),
    (6, "process_mining_analysen"),
    (7, "ergebnisaggregationen"),
    (8, "modellableitungen"),
    (9, "modellvalidierungen"),
)


class SQLiteFortschrittRepository:
    def __init__(self, datenbankpfad: Path | str = STANDARD_DATENBANKPFAD) -> None:
        self._datenbankpfad = Path(datenbankpfad)

    def hoechster_gespeicherter_schritt(self, projekt_id: UUID) -> int:
        verbindung = sqlite3.connect(self._datenbankpfad, timeout=5.0)
        try:
            initialisiere_schema(verbindung)
            projekt = verbindung.execute(
                "SELECT 1 FROM projekte WHERE projekt_id = ?", (str(projekt_id),)
            ).fetchone()
            if projekt is None:
                return 0
            schritt = 1
            for nummer, tabelle in _ARTEFAKTE:
                if verbindung.execute(
                    f"SELECT 1 FROM {tabelle} WHERE projekt_id = ? LIMIT 1",
                    (str(projekt_id),),
                ).fetchone():
                    schritt = max(schritt, nummer)
            gespeichert = verbindung.execute(
                "SELECT framework_schritt FROM projektfortschritt WHERE projekt_id = ?",
                (str(projekt_id),),
            ).fetchone()
            if gespeichert is not None:
                schritt = max(schritt, int(gespeichert[0]))
            return schritt
        finally:
            verbindung.close()
