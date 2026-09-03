"""SQLite-Metadatenpersistenz für gemeinsam erzeugte Artefakte K und O."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import UUID

from framework_mvp.domain.models import Modellableitung, Modellableitungsstatus
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    STANDARD_DATENBANKPFAD,
)
from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema


class SQLiteModellableitungRepository:
    """Speichert immutable K/O-Metadaten transaktional und konfliktfrei."""

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

    def speichern(self, ableitung: Modellableitung) -> None:
        """Speichert einen neuen Lauf; widersprüchliche Identitäten werden nicht ignoriert."""
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(
                f"INSERT INTO modellableitungen VALUES ({','.join('?' for _ in range(16))})",
                (
                    str(ableitung.modellableitungs_id),
                    str(ableitung.k_id),
                    str(ableitung.o_id),
                    str(ableitung.projekt_id),
                    str(ableitung.aggregations_id),
                    str(ableitung.analyse_id),
                    str(ableitung.event_log_id),
                    ableitung.eingabefingerabdruck,
                    ableitung.mappingversion,
                    ableitung.unsicherheitsfingerabdruck,
                    ableitung.relativer_k_pfad,
                    ableitung.k_sha256,
                    ableitung.relativer_o_pfad,
                    ableitung.o_sha256,
                    ableitung.status.value,
                    ableitung.erstellt_am.isoformat(),
                ),
            )

    def laden(self, modellableitungs_id: UUID) -> Modellableitung | None:
        """Lädt Metadaten über die Modellableitungs-ID."""
        with self._verbindung() as verbindung:
            zeile = verbindung.execute(
                "SELECT * FROM modellableitungen WHERE modellableitungs_id=?",
                (str(modellableitungs_id),),
            ).fetchone()
        return None if zeile is None else self._ableitung(zeile)

    def finde_identisch(
        self,
        projekt_id: UUID,
        aggregations_id: UUID,
        eingabefingerabdruck: str,
        mappingversion: int,
        unsicherheitsfingerabdruck: str,
    ) -> Modellableitung | None:
        """Findet den bereits gespeicherten identischen Algorithmus-8-Lauf."""
        with self._verbindung() as verbindung:
            zeile = verbindung.execute(
                "SELECT * FROM modellableitungen WHERE projekt_id=? AND aggregations_id=? "
                "AND eingabefingerabdruck=? AND mappingversion=? "
                "AND unsicherheitsfingerabdruck=?",
                (
                    str(projekt_id),
                    str(aggregations_id),
                    eingabefingerabdruck,
                    mappingversion,
                    unsicherheitsfingerabdruck,
                ),
            ).fetchone()
        return None if zeile is None else self._ableitung(zeile)

    def neueste_vorgaengerin(
        self,
        projekt_id: UUID,
        analyse_id: UUID,
        event_log_id: UUID,
        aktuelle_aggregations_id: UUID,
    ) -> Modellableitung | None:
        """Findet nur eine nachvollziehbare Vorgängerableitung derselben Eingangslineage."""
        with self._verbindung() as verbindung:
            zeile = verbindung.execute(
                "SELECT * FROM modellableitungen WHERE projekt_id=? AND analyse_id=? "
                "AND event_log_id=? AND aggregations_id<>? "
                "ORDER BY erstellt_am_utc DESC, rowid DESC LIMIT 1",
                (
                    str(projekt_id),
                    str(analyse_id),
                    str(event_log_id),
                    str(aktuelle_aggregations_id),
                ),
            ).fetchone()
        return None if zeile is None else self._ableitung(zeile)

    @staticmethod
    def _ableitung(zeile: sqlite3.Row) -> Modellableitung:
        return Modellableitung(
            UUID(zeile["modellableitungs_id"]),
            UUID(zeile["k_id"]),
            UUID(zeile["o_id"]),
            UUID(zeile["projekt_id"]),
            UUID(zeile["aggregations_id"]),
            UUID(zeile["analyse_id"]),
            UUID(zeile["event_log_id"]),
            zeile["eingabefingerabdruck"],
            zeile["mappingversion"],
            zeile["unsicherheitsfingerabdruck"],
            zeile["relativer_k_pfad"],
            zeile["k_sha256"],
            zeile["relativer_o_pfad"],
            zeile["o_sha256"],
            Modellableitungsstatus(zeile["status"]),
            datetime.fromisoformat(zeile["erstellt_am_utc"]),
        )
