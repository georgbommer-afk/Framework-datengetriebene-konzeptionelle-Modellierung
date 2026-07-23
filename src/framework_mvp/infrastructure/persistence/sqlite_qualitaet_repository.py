"""SQLite-Persistenz gespeicherter Qualitätsprüfungen."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import UUID

from framework_mvp.domain.models import (
    Qualitaetsmassnahmenplan,
    QualitaetspruefungArtefakt,
    Qualitaetsregel,
)
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    STANDARD_DATENBANKPFAD,
)
from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema


class SQLiteQualitaetRepository:
    """Speichert Prüfung, Regeln und Maßnahmen in einer Transaktion."""

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

    def speichern(
        self,
        artefakt: QualitaetspruefungArtefakt,
        regeln: tuple[Qualitaetsregel, ...],
        plan: Qualitaetsmassnahmenplan,
        report: dict[str, object],
        vergleich: dict[str, object],
    ) -> None:
        """Speichert sämtliche Metadaten einer Qualitätsprüfung atomar."""
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(
                "INSERT OR IGNORE INTO qualitaetspruefungen VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(artefakt.quality_run_id),
                    str(artefakt.projekt_id),
                    str(artefakt.event_log_id),
                    json.dumps(report, ensure_ascii=False, default=str),
                    json.dumps(vergleich, ensure_ascii=False, default=str),
                    artefakt.relativer_report_pfad,
                    artefakt.relativer_massnahmen_pfad,
                    artefakt.relativer_csv_pfad,
                    artefakt.sha256,
                    artefakt.erstellt_am.isoformat(),
                ),
            )
            for regel in regeln:
                verbindung.execute(
                    "INSERT OR IGNORE INTO qualitaetsregeln VALUES (?, ?, ?)",
                    (
                        str(artefakt.quality_run_id),
                        regel.regel_id,
                        json.dumps(asdict(regel), ensure_ascii=False, default=str),
                    ),
                )
            for massnahme in plan.massnahmen:
                verbindung.execute(
                    "INSERT OR IGNORE INTO qualitaetsmassnahmen VALUES (?, ?, ?, ?)",
                    (
                        str(artefakt.quality_run_id),
                        str(massnahme.massnahme_id),
                        json.dumps(asdict(massnahme), ensure_ascii=False, default=str),
                        massnahme.reihenfolge,
                    ),
                )

    def laden(self, quality_run_id: UUID) -> QualitaetspruefungArtefakt | None:
        """Lädt die Artefaktmetadaten einer Qualitätsprüfung."""
        with self._verbindung() as verbindung:
            zeile = verbindung.execute(
                "SELECT * FROM qualitaetspruefungen WHERE quality_run_id=?",
                (str(quality_run_id),),
            ).fetchone()
        return None if zeile is None else self._artefakt(zeile)

    def fuer_projekt(self, projekt_id: UUID) -> list[QualitaetspruefungArtefakt]:
        """Listet Qualitätsprüfungen eines Projekts stabil auf."""
        with self._verbindung() as verbindung:
            zeilen = verbindung.execute(
                "SELECT * FROM qualitaetspruefungen WHERE projekt_id=? "
                "ORDER BY erstellt_am_utc, quality_run_id",
                (str(projekt_id),),
            ).fetchall()
        return [self._artefakt(zeile) for zeile in zeilen]

    @staticmethod
    def _artefakt(zeile: sqlite3.Row) -> QualitaetspruefungArtefakt:
        return QualitaetspruefungArtefakt(
            UUID(zeile["quality_run_id"]),
            UUID(zeile["projekt_id"]),
            UUID(zeile["event_log_id"]),
            zeile["relativer_report_pfad"],
            zeile["relativer_massnahmen_pfad"],
            zeile["relativer_csv_pfad"],
            zeile["sha256"],
            datetime.fromisoformat(zeile["erstellt_am_utc"]),
        )
