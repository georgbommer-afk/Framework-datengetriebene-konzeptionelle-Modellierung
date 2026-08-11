"""SQLite-Persistenz der Metadaten von A_G."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import UUID

from framework_mvp.domain.models import (
    Aggregationsstatus,
    Ergebnisaggregation,
)
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    STANDARD_DATENBANKPFAD,
)
from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema


class SQLiteErgebnisaggregationRepository:
    """Speichert ausschließlich immutable Aggregationsmetadaten."""

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

    def speichern(self, aggregation: Ergebnisaggregation) -> None:
        """Speichert die Metadaten idempotent; Konflikte werden nicht überschrieben."""
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(
                "INSERT OR IGNORE INTO ergebnisaggregationen VALUES "
                f"({','.join('?' for _ in range(12))})",
                (
                    str(aggregation.aggregations_id),
                    str(aggregation.projekt_id),
                    str(aggregation.spezifikations_id),
                    str(aggregation.freigabe_id),
                    str(aggregation.event_log_id),
                    str(aggregation.analyse_id),
                    aggregation.eingabefingerabdruck,
                    aggregation.konfigurationsfingerabdruck,
                    aggregation.relativer_aggregations_pfad,
                    aggregation.aggregations_sha256,
                    aggregation.status.value,
                    aggregation.erstellt_am.isoformat(),
                ),
            )

    def laden(self, aggregations_id: UUID) -> Ergebnisaggregation | None:
        """Lädt Metadaten anhand der Aggregations-ID."""
        with self._verbindung() as verbindung:
            zeile = verbindung.execute(
                "SELECT * FROM ergebnisaggregationen WHERE aggregations_id=?",
                (str(aggregations_id),),
            ).fetchone()
        return None if zeile is None else self._aggregation(zeile)

    def fuer_analyse(self, projekt_id: UUID, analyse_id: UUID) -> list[Ergebnisaggregation]:
        """Listet Läufe nur innerhalb derselben aktiven Artefaktkette."""
        with self._verbindung() as verbindung:
            zeilen = verbindung.execute(
                "SELECT * FROM ergebnisaggregationen WHERE projekt_id=? AND analyse_id=? "
                "ORDER BY erstellt_am_utc, aggregations_id",
                (str(projekt_id), str(analyse_id)),
            ).fetchall()
        return [self._aggregation(zeile) for zeile in zeilen]

    @staticmethod
    def _aggregation(zeile: sqlite3.Row) -> Ergebnisaggregation:
        return Ergebnisaggregation(
            UUID(zeile["aggregations_id"]),
            UUID(zeile["projekt_id"]),
            UUID(zeile["spezifikations_id"]),
            UUID(zeile["freigabe_id"]),
            UUID(zeile["event_log_id"]),
            UUID(zeile["analyse_id"]),
            zeile["eingabefingerabdruck"],
            zeile["konfigurationsfingerabdruck"],
            zeile["relativer_aggregations_pfad"],
            zeile["aggregations_sha256"],
            Aggregationsstatus(zeile["status"]),
            datetime.fromisoformat(zeile["erstellt_am_utc"]),
        )
