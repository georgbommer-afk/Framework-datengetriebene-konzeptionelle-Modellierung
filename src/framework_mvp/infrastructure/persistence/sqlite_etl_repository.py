"""SQLite-Ablage für Transformationspläne und Zwischendatensätze."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import UUID

from framework_mvp.domain.models import (
    Transformationsart,
    Transformationsplan,
    Transformationsschritt,
    Zwischendatensatz,
)
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    STANDARD_DATENBANKPFAD,
)
from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema


class SQLiteETLRepository:
    """Speichert kleine ETL-Metadaten, jedoch keine vollständigen Tabellen."""

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

    def plan_speichern(self, plan: Transformationsplan) -> None:
        """Speichert oder aktualisiert einen vollständigen Plan transaktional."""
        plan_json = json.dumps(asdict(plan), ensure_ascii=False, default=str, sort_keys=True)
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(
                """
                INSERT INTO transformationsplaene VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(transformationsplan_id) DO UPDATE SET
                    import_ids_json=excluded.import_ids_json,
                    plan_json=excluded.plan_json,
                    geaendert_am_utc=excluded.geaendert_am_utc
                """,
                (
                    str(plan.transformationsplan_id),
                    str(plan.projekt_id),
                    json.dumps([str(wert) for wert in plan.import_ids]),
                    plan_json,
                    plan.erstellt_am.isoformat(),
                    plan.geaendert_am.isoformat(),
                ),
            )

    def plan_laden(self, plan_id: UUID) -> Transformationsplan | None:
        """Lädt einen Transformationsplan mit typisierten Schritten."""
        with self._verbindung() as verbindung:
            zeile = verbindung.execute(
                "SELECT * FROM transformationsplaene WHERE transformationsplan_id=?",
                (str(plan_id),),
            ).fetchone()
        if zeile is None:
            return None
        struktur = json.loads(zeile["plan_json"])
        schritte = tuple(
            Transformationsschritt(
                UUID(wert["transformationsschritt_id"]),
                Transformationsart(wert["typ"]),
                tuple(wert["betroffene_spalten"]),
                wert["parameter_json"],
                wert["reihenfolge"],
                wert["beschreibung"],
                wert["aktiviert"],
                datetime.fromisoformat(wert["erstellt_am"]),
                wert["fachliche_begruendung"],
            )
            for wert in struktur["schritte"]
        )
        return Transformationsplan(
            UUID(zeile["transformationsplan_id"]),
            UUID(zeile["projekt_id"]),
            tuple(UUID(wert) for wert in json.loads(zeile["import_ids_json"])),
            schritte,
            datetime.fromisoformat(zeile["erstellt_am_utc"]),
            datetime.fromisoformat(zeile["geaendert_am_utc"]),
        )

    def datensatz_speichern(self, datensatz: Zwischendatensatz) -> None:
        """Speichert Metadaten eines erzeugten Zwischendatensatzes."""
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(
                "INSERT INTO zwischendatensaetze VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(datensatz.zwischendatensatz_id),
                    str(datensatz.projekt_id),
                    str(datensatz.transformationsplan_id),
                    json.dumps([str(wert) for wert in datensatz.import_ids]),
                    datensatz.relativer_daten_pfad,
                    datensatz.relativer_schema_pfad,
                    datensatz.relativer_transformation_pfad,
                    datensatz.sha256,
                    datensatz.zeilenanzahl,
                    datensatz.spaltenanzahl,
                    datensatz.erstellt_am.isoformat(),
                ),
            )

    def datensatz_laden(self, datensatz_id: UUID) -> Zwischendatensatz | None:
        """Lädt die Metadaten eines Zwischendatensatzes."""
        with self._verbindung() as verbindung:
            zeile = verbindung.execute(
                "SELECT * FROM zwischendatensaetze WHERE zwischendatensatz_id=?",
                (str(datensatz_id),),
            ).fetchone()
        return None if zeile is None else self._datensatz(zeile)

    def datensaetze_fuer_projekt(self, projekt_id: UUID) -> list[Zwischendatensatz]:
        """Listet projektbezogene Zwischendatensätze stabil auf."""
        with self._verbindung() as verbindung:
            zeilen = verbindung.execute(
                "SELECT * FROM zwischendatensaetze WHERE projekt_id=? "
                "ORDER BY erstellt_am_utc, zwischendatensatz_id",
                (str(projekt_id),),
            ).fetchall()
        return [self._datensatz(zeile) for zeile in zeilen]

    @staticmethod
    def _datensatz(zeile: sqlite3.Row) -> Zwischendatensatz:
        return Zwischendatensatz(
            UUID(zeile["zwischendatensatz_id"]),
            UUID(zeile["projekt_id"]),
            UUID(zeile["transformationsplan_id"]),
            tuple(UUID(wert) for wert in json.loads(zeile["import_ids_json"])),
            zeile["relativer_daten_pfad"],
            zeile["relativer_schema_pfad"],
            zeile["relativer_transformation_pfad"],
            zeile["sha256"],
            zeile["zeilenanzahl"],
            zeile["spaltenanzahl"],
            datetime.fromisoformat(zeile["erstellt_am_utc"]),
        )
