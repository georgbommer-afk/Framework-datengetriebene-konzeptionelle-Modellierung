"""SQLite-Metadatenpersistenz für Validierungsläufe und K*."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import UUID

from framework_mvp.domain.models import Modellvalidierung, Modellvalidierungsstatus
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    STANDARD_DATENBANKPFAD,
)
from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema


class SQLiteModellvalidierungRepository:
    """Speichert immutable K*-Metadaten transaktional und konfliktfrei."""

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

    def speichern(self, validierung: Modellvalidierung) -> None:
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(
                f"INSERT INTO modellvalidierungen VALUES ({','.join('?' for _ in range(12))})",
                (
                    str(validierung.validierungslauf_id),
                    str(validierung.k_stern_id),
                    str(validierung.projekt_id),
                    str(validierung.modellableitungs_id),
                    str(validierung.k_id),
                    str(validierung.o_id),
                    validierung.eingabefingerabdruck,
                    validierung.entscheidungsfingerabdruck,
                    validierung.relativer_k_stern_pfad,
                    validierung.k_stern_sha256,
                    validierung.status.value,
                    validierung.erstellt_am.isoformat(),
                ),
            )

    def laden(self, validierungslauf_id: UUID) -> Modellvalidierung | None:
        with self._verbindung() as verbindung:
            zeile = verbindung.execute(
                "SELECT * FROM modellvalidierungen WHERE validierungslauf_id=?",
                (str(validierungslauf_id),),
            ).fetchone()
        return None if zeile is None else self._validierung(zeile)

    def finde_identisch(
        self,
        projekt_id: UUID,
        modellableitungs_id: UUID,
        eingabefingerabdruck: str,
        entscheidungsfingerabdruck: str,
    ) -> Modellvalidierung | None:
        with self._verbindung() as verbindung:
            zeile = verbindung.execute(
                "SELECT * FROM modellvalidierungen WHERE projekt_id=? AND modellableitungs_id=? "
                "AND eingabefingerabdruck=? AND entscheidungsfingerabdruck=?",
                (
                    str(projekt_id),
                    str(modellableitungs_id),
                    eingabefingerabdruck,
                    entscheidungsfingerabdruck,
                ),
            ).fetchone()
        return None if zeile is None else self._validierung(zeile)

    @staticmethod
    def _validierung(zeile: sqlite3.Row) -> Modellvalidierung:
        return Modellvalidierung(
            UUID(zeile["validierungslauf_id"]),
            UUID(zeile["k_stern_id"]),
            UUID(zeile["projekt_id"]),
            UUID(zeile["modellableitungs_id"]),
            UUID(zeile["k_id"]),
            UUID(zeile["o_id"]),
            zeile["eingabefingerabdruck"],
            zeile["entscheidungsfingerabdruck"],
            zeile["relativer_k_stern_pfad"],
            zeile["k_stern_sha256"],
            Modellvalidierungsstatus(zeile["status"]),
            datetime.fromisoformat(zeile["erstellt_am_utc"]),
        )
