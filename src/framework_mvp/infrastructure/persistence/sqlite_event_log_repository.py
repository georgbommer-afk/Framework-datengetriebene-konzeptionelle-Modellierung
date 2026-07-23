"""SQLite-Persistenz kanonischer Event-Log-Metadaten."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import UUID

from framework_mvp.domain.models import EventLogArtefakt, EventLogStatus
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    STANDARD_DATENBANKPFAD,
)
from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema


class SQLiteEventLogRepository:
    """Speichert Event-Log-Metadaten transaktional."""

    def __init__(self, datenbankpfad: Path | str = STANDARD_DATENBANKPFAD) -> None:
        self._datenbankpfad = Path(datenbankpfad)

    @contextmanager
    def _verbindung(self) -> Iterator[sqlite3.Connection]:
        self._datenbankpfad.parent.mkdir(parents=True, exist_ok=True)
        verbindung = sqlite3.connect(self._datenbankpfad)
        verbindung.row_factory = sqlite3.Row
        verbindung.execute("PRAGMA foreign_keys = ON")
        try:
            initialisiere_schema(verbindung)
            yield verbindung
        finally:
            verbindung.close()

    def speichern(self, artefakt: EventLogArtefakt) -> None:
        """Speichert ein erzeugtes Event Log unveränderlich."""
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(
                "INSERT OR IGNORE INTO event_logs VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(artefakt.event_log_id),
                    str(artefakt.projekt_id),
                    str(artefakt.zwischendatensatz_id),
                    str(artefakt.mapping_id),
                    artefakt.status.value,
                    artefakt.ereignisanzahl,
                    artefakt.fallanzahl,
                    artefakt.aktivitaetsanzahl,
                    artefakt.zeitraum_von.isoformat() if artefakt.zeitraum_von else None,
                    artefakt.zeitraum_bis.isoformat() if artefakt.zeitraum_bis else None,
                    artefakt.relativer_csv_pfad,
                    artefakt.relativer_schema_pfad,
                    artefakt.relativer_lineage_pfad,
                    artefakt.relativer_xes_pfad,
                    artefakt.sha256,
                    artefakt.erstellt_am.isoformat(),
                ),
            )

    def laden(self, event_log_id: UUID) -> EventLogArtefakt | None:
        """Lädt ein Event Log anhand seiner ID."""
        with self._verbindung() as verbindung:
            zeile = verbindung.execute(
                "SELECT * FROM event_logs WHERE event_log_id=?", (str(event_log_id),)
            ).fetchone()
        return None if zeile is None else self._artefakt(zeile)

    def fuer_projekt(self, projekt_id: UUID) -> list[EventLogArtefakt]:
        """Listet Event Logs eines Projekts stabil auf."""
        with self._verbindung() as verbindung:
            zeilen = verbindung.execute(
                "SELECT * FROM event_logs WHERE projekt_id=? "
                "ORDER BY erstellt_am_utc, event_log_id",
                (str(projekt_id),),
            ).fetchall()
        return [self._artefakt(zeile) for zeile in zeilen]

    @staticmethod
    def _artefakt(zeile: sqlite3.Row) -> EventLogArtefakt:
        return EventLogArtefakt(
            UUID(zeile["event_log_id"]),
            UUID(zeile["projekt_id"]),
            UUID(zeile["zwischendatensatz_id"]),
            UUID(zeile["mapping_id"]),
            EventLogStatus(zeile["status"]),
            zeile["ereignisanzahl"],
            zeile["fallanzahl"],
            zeile["aktivitaetsanzahl"],
            datetime.fromisoformat(zeile["zeitraum_von"]) if zeile["zeitraum_von"] else None,
            datetime.fromisoformat(zeile["zeitraum_bis"]) if zeile["zeitraum_bis"] else None,
            zeile["relativer_csv_pfad"],
            zeile["relativer_schema_pfad"],
            zeile["relativer_lineage_pfad"],
            zeile["relativer_xes_pfad"],
            zeile["sha256"],
            datetime.fromisoformat(zeile["erstellt_am_utc"]),
        )
