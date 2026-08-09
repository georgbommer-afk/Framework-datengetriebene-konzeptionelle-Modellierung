"""SQLite-Metadatenrepository für die eigenständige Mappingtabelle M."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from uuid import UUID

from framework_mvp.domain.models import Mappingtabelle, mappingtabelle_aus_dict
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    STANDARD_DATENBANKPFAD,
)
from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema


class SQLiteMappingtabelleRepository:
    """Speichert M-Metadaten getrennt von Event-Log-Konfigurationen."""

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

    def speichern(self, mapping: Mappingtabelle, relativer_pfad: str, sha256: str) -> None:
        """Speichert oder aktualisiert eine Mappingtabelle transaktional."""
        mapping_json = json.dumps(asdict(mapping), ensure_ascii=False, sort_keys=True, default=str)
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(
                """
                INSERT INTO mappingtabellen VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mapping_id) DO UPDATE SET
                    mapping_json=excluded.mapping_json,
                    status=excluded.status,
                    relativer_mapping_pfad=excluded.relativer_mapping_pfad,
                    sha256=excluded.sha256,
                    geaendert_am_utc=excluded.geaendert_am_utc
                """,
                (
                    str(mapping.mapping_id),
                    str(mapping.projekt_id),
                    str(mapping.zwischendatensatz_id),
                    mapping_json,
                    mapping.status.value,
                    relativer_pfad,
                    sha256,
                    mapping.erstellt_am.isoformat(),
                    mapping.geaendert_am.isoformat(),
                ),
            )

    def laden(self, mapping_id: UUID) -> tuple[Mappingtabelle, str, str] | None:
        """Lädt M mit Artefaktpfad und gespeicherter Prüfsumme."""
        with self._verbindung() as verbindung:
            zeile = verbindung.execute(
                "SELECT * FROM mappingtabellen WHERE mapping_id=?", (str(mapping_id),)
            ).fetchone()
        return None if zeile is None else self._mapping(zeile)

    def fuer_datensatz(
        self, projekt_id: UUID, zwischendatensatz_id: UUID
    ) -> tuple[Mappingtabelle, str, str] | None:
        """Lädt ausschließlich M des angegebenen Projekts und Zwischendatensatzes."""
        with self._verbindung() as verbindung:
            zeile = verbindung.execute(
                "SELECT * FROM mappingtabellen WHERE projekt_id=? AND zwischendatensatz_id=?",
                (str(projekt_id), str(zwischendatensatz_id)),
            ).fetchone()
        return None if zeile is None else self._mapping(zeile)

    def fuer_projekt(self, projekt_id: UUID) -> list[tuple[Mappingtabelle, str, str]]:
        """Listet M eines Projekts stabil auf."""
        with self._verbindung() as verbindung:
            zeilen = verbindung.execute(
                "SELECT * FROM mappingtabellen WHERE projekt_id=? "
                "ORDER BY erstellt_am_utc, mapping_id",
                (str(projekt_id),),
            ).fetchall()
        return [self._mapping(zeile) for zeile in zeilen]

    @staticmethod
    def _mapping(zeile: sqlite3.Row) -> tuple[Mappingtabelle, str, str]:
        mapping = mappingtabelle_aus_dict(json.loads(zeile["mapping_json"]))
        return mapping, zeile["relativer_mapping_pfad"], zeile["sha256"]
