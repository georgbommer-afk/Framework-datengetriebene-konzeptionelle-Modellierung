"""SQLite-Implementierung des Datenquellenrepositorys."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from framework_mvp.domain.models import Datenquelle, Quellenart, Quellsystemtyp
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    STANDARD_DATENBANKPFAD,
)
from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema

_SPALTEN = """
    datenquellen_id, projekt_id, bezeichnung, quellsystemtyp, konkretes_quellsystem,
    fachliche_beschreibung, herkunft_oder_verantwortungsbereich, quellenart,
    erwartete_tabellen_oder_blaetter_json, bekannte_schluesselattribute_json,
    erstellt_am_utc, geaendert_am_utc
"""


class SQLiteDatenquelleRepository:
    """Speichert Datenquellen in der gemeinsamen lokalen Projektdatenbank."""

    def __init__(self, datenbankpfad: Path | str = STANDARD_DATENBANKPFAD) -> None:
        """Konfiguriert den Datenbankpfad ohne sofortigen Dateizugriff."""
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

    def speichern(self, datenquelle: Datenquelle) -> None:
        """Fügt eine Datenquelle ein oder aktualisiert sie atomar."""
        platzhalter = ", ".join("?" for _ in range(12))
        sql = f"""
            INSERT INTO datenquellen ({_SPALTEN}) VALUES ({platzhalter})
            ON CONFLICT(datenquellen_id) DO UPDATE SET
                bezeichnung = excluded.bezeichnung,
                quellsystemtyp = excluded.quellsystemtyp,
                konkretes_quellsystem = excluded.konkretes_quellsystem,
                fachliche_beschreibung = excluded.fachliche_beschreibung,
                herkunft_oder_verantwortungsbereich = excluded.herkunft_oder_verantwortungsbereich,
                quellenart = excluded.quellenart,
                erwartete_tabellen_oder_blaetter_json =
                    excluded.erwartete_tabellen_oder_blaetter_json,
                bekannte_schluesselattribute_json =
                    excluded.bekannte_schluesselattribute_json,
                geaendert_am_utc = excluded.geaendert_am_utc
        """
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(sql, self._serialisieren(datenquelle))

    def laden(self, datenquellen_id: UUID) -> Datenquelle | None:
        """Lädt eine Datenquelle anhand ihrer UUID."""
        with self._verbindung() as verbindung:
            zeile = verbindung.execute(
                f"SELECT {_SPALTEN} FROM datenquellen WHERE datenquellen_id = ?",
                (str(datenquellen_id),),
            ).fetchone()
        return None if zeile is None else self._deserialisieren(zeile)

    def fuer_projekt_auflisten(self, projekt_id: UUID) -> list[Datenquelle]:
        """Lädt Datenquellen eines Projekts in stabiler Reihenfolge."""
        with self._verbindung() as verbindung:
            zeilen = verbindung.execute(
                f"SELECT {_SPALTEN} FROM datenquellen WHERE projekt_id = ? "
                "ORDER BY erstellt_am_utc, datenquellen_id",
                (str(projekt_id),),
            ).fetchall()
        return [self._deserialisieren(zeile) for zeile in zeilen]

    @staticmethod
    def _json(werte: tuple[str, ...]) -> str:
        return json.dumps(werte, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def _serialisieren(cls, datenquelle: Datenquelle) -> tuple[Any, ...]:
        return (
            str(datenquelle.datenquellen_id),
            str(datenquelle.projekt_id),
            datenquelle.bezeichnung,
            datenquelle.quellsystemtyp.value,
            datenquelle.konkretes_quellsystem,
            datenquelle.fachliche_beschreibung,
            datenquelle.herkunft_oder_verantwortungsbereich,
            datenquelle.quellenart.value,
            cls._json(datenquelle.erwartete_tabellen_oder_blaetter),
            cls._json(datenquelle.bekannte_schluesselattribute),
            datenquelle.erstellt_am.isoformat(),
            datenquelle.geaendert_am.isoformat(),
        )

    @staticmethod
    def _deserialisieren(zeile: sqlite3.Row) -> Datenquelle:
        return Datenquelle(
            datenquellen_id=UUID(zeile["datenquellen_id"]),
            projekt_id=UUID(zeile["projekt_id"]),
            bezeichnung=zeile["bezeichnung"],
            quellsystemtyp=Quellsystemtyp(zeile["quellsystemtyp"]),
            konkretes_quellsystem=zeile["konkretes_quellsystem"],
            fachliche_beschreibung=zeile["fachliche_beschreibung"],
            herkunft_oder_verantwortungsbereich=zeile["herkunft_oder_verantwortungsbereich"],
            quellenart=Quellenart(zeile["quellenart"]),
            erwartete_tabellen_oder_blaetter=tuple(
                json.loads(zeile["erwartete_tabellen_oder_blaetter_json"])
            ),
            bekannte_schluesselattribute=tuple(
                json.loads(zeile["bekannte_schluesselattribute_json"])
            ),
            erstellt_am=datetime.fromisoformat(zeile["erstellt_am_utc"]),
            geaendert_am=datetime.fromisoformat(zeile["geaendert_am_utc"]),
        )
