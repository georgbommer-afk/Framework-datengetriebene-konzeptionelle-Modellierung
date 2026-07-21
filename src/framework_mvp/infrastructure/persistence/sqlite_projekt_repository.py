"""SQLite-Implementierung der Projektablage."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from framework_mvp.domain.models import (
    Projekt,
    Projektstatus,
    Systemtyp,
    Untersuchungsauftrag,
)
from framework_mvp.infrastructure.exceptions import NichtUnterstuetzteSchemaversion

STANDARD_DATENBANKPFAD = Path("workspace/framework_mvp.sqlite")
SCHEMAVERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projekte (
    projekt_id TEXT PRIMARY KEY NOT NULL,
    bezeichnung TEXT NOT NULL CHECK (length(trim(bezeichnung)) > 0),
    beteiligte_personen_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('entwurf', 'aktiv', 'abgeschlossen')),
    erstellt_am_utc TEXT NOT NULL,
    geaendert_am_utc TEXT NOT NULL,
    problemstellung TEXT NOT NULL,
    zielsetzung TEXT NOT NULL,
    systemtyp TEXT NOT NULL
        CHECK (systemtyp IN ('produktion', 'intralogistik', 'kombiniert')),
    systemgrenze TEXT NOT NULL,
    input_beschreibung TEXT NOT NULL,
    transformation_beschreibung TEXT NOT NULL,
    output_beschreibung TEXT NOT NULL,
    detaillierungsgrad TEXT NOT NULL,
    leistungskennzahlen_json TEXT NOT NULL,
    rahmenbedingungen TEXT NOT NULL,
    betrachtungszeitraum_beginn TEXT,
    betrachtungszeitraum_ende TEXT,
    anmerkungen TEXT NOT NULL,
    CHECK (
        betrachtungszeitraum_beginn IS NULL
        OR betrachtungszeitraum_ende IS NULL
        OR betrachtungszeitraum_ende >= betrachtungszeitraum_beginn
    )
);
"""

_SPALTEN = """
    projekt_id, bezeichnung, beteiligte_personen_json, status,
    erstellt_am_utc, geaendert_am_utc, problemstellung, zielsetzung,
    systemtyp, systemgrenze, input_beschreibung, transformation_beschreibung,
    output_beschreibung, detaillierungsgrad, leistungskennzahlen_json,
    rahmenbedingungen, betrachtungszeitraum_beginn,
    betrachtungszeitraum_ende, anmerkungen
"""


class SQLiteProjektRepository:
    """Speichert Projekte transaktional in einer lokalen SQLite-Datenbank."""

    def __init__(self, datenbankpfad: Path | str = STANDARD_DATENBANKPFAD) -> None:
        """Konfiguriert den Datenbankpfad ohne sofortigen Dateizugriff."""
        self._datenbankpfad = Path(datenbankpfad)

    @contextmanager
    def _verbindung(self) -> Iterator[sqlite3.Connection]:
        self._datenbankpfad.parent.mkdir(parents=True, exist_ok=True)
        verbindung = sqlite3.connect(self._datenbankpfad)
        verbindung.row_factory = sqlite3.Row
        try:
            with verbindung:
                schemaversion = verbindung.execute("PRAGMA user_version").fetchone()[0]
                if schemaversion > SCHEMAVERSION:
                    raise NichtUnterstuetzteSchemaversion(
                        "Die SQLite-Datenbank verwendet die neuere Schemaversion "
                        f"{schemaversion}; unterstützt wird höchstens Version {SCHEMAVERSION}."
                    )
                verbindung.executescript(_SCHEMA)
                if schemaversion == 0:
                    verbindung.execute(f"PRAGMA user_version = {SCHEMAVERSION}")
            yield verbindung
        finally:
            verbindung.close()

    def speichern(self, projekt: Projekt) -> None:
        """Fügt ein Projekt ein oder aktualisiert es atomar."""
        platzhalter = ", ".join("?" for _ in range(19))
        aktualisierungen = """
            bezeichnung = excluded.bezeichnung,
            beteiligte_personen_json = excluded.beteiligte_personen_json,
            status = excluded.status,
            geaendert_am_utc = excluded.geaendert_am_utc,
            problemstellung = excluded.problemstellung,
            zielsetzung = excluded.zielsetzung,
            systemtyp = excluded.systemtyp,
            systemgrenze = excluded.systemgrenze,
            input_beschreibung = excluded.input_beschreibung,
            transformation_beschreibung = excluded.transformation_beschreibung,
            output_beschreibung = excluded.output_beschreibung,
            detaillierungsgrad = excluded.detaillierungsgrad,
            leistungskennzahlen_json = excluded.leistungskennzahlen_json,
            rahmenbedingungen = excluded.rahmenbedingungen,
            betrachtungszeitraum_beginn = excluded.betrachtungszeitraum_beginn,
            betrachtungszeitraum_ende = excluded.betrachtungszeitraum_ende,
            anmerkungen = excluded.anmerkungen
        """
        sql = (
            f"INSERT INTO projekte ({_SPALTEN}) VALUES ({platzhalter}) "
            f"ON CONFLICT(projekt_id) DO UPDATE SET {aktualisierungen}"
        )
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(sql, self._serialisieren(projekt))

    def laden(self, projekt_id: UUID) -> Projekt | None:
        """Lädt ein Projekt anhand seiner UUID."""
        with self._verbindung() as verbindung:
            zeile = verbindung.execute(
                f"SELECT {_SPALTEN} FROM projekte WHERE projekt_id = ?",
                (str(projekt_id),),
            ).fetchone()
        return None if zeile is None else self._deserialisieren(zeile)

    def auflisten(self) -> list[Projekt]:
        """Lädt alle Projekte sortiert nach Erstellungszeit und UUID."""
        with self._verbindung() as verbindung:
            zeilen = verbindung.execute(
                f"SELECT {_SPALTEN} FROM projekte ORDER BY erstellt_am_utc ASC, projekt_id ASC"
            ).fetchall()
        return [self._deserialisieren(zeile) for zeile in zeilen]

    @staticmethod
    def _json_liste(werte: tuple[str, ...]) -> str:
        return json.dumps(werte, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def _serialisieren(cls, projekt: Projekt) -> tuple[Any, ...]:
        auftrag = projekt.untersuchungsauftrag
        return (
            str(projekt.projekt_id),
            projekt.bezeichnung,
            cls._json_liste(projekt.beteiligte_personen),
            projekt.status.value,
            projekt.erstellt_am.isoformat(),
            projekt.geaendert_am.isoformat(),
            auftrag.problemstellung,
            auftrag.zielsetzung,
            auftrag.systemtyp.value,
            auftrag.systemgrenze,
            auftrag.input_beschreibung,
            auftrag.transformation_beschreibung,
            auftrag.output_beschreibung,
            auftrag.detaillierungsgrad,
            cls._json_liste(auftrag.leistungskennzahlen),
            auftrag.rahmenbedingungen,
            cls._datum_als_text(auftrag.betrachtungszeitraum_beginn),
            cls._datum_als_text(auftrag.betrachtungszeitraum_ende),
            auftrag.anmerkungen,
        )

    @staticmethod
    def _datum_als_text(wert: date | None) -> str | None:
        return None if wert is None else wert.isoformat()

    @staticmethod
    def _text_als_datum(wert: str | None) -> date | None:
        return None if wert is None else date.fromisoformat(wert)

    @classmethod
    def _deserialisieren(cls, zeile: sqlite3.Row) -> Projekt:
        auftrag = Untersuchungsauftrag(
            problemstellung=zeile["problemstellung"],
            zielsetzung=zeile["zielsetzung"],
            systemtyp=Systemtyp(zeile["systemtyp"]),
            systemgrenze=zeile["systemgrenze"],
            input_beschreibung=zeile["input_beschreibung"],
            transformation_beschreibung=zeile["transformation_beschreibung"],
            output_beschreibung=zeile["output_beschreibung"],
            detaillierungsgrad=zeile["detaillierungsgrad"],
            leistungskennzahlen=tuple(json.loads(zeile["leistungskennzahlen_json"])),
            rahmenbedingungen=zeile["rahmenbedingungen"],
            betrachtungszeitraum_beginn=cls._text_als_datum(zeile["betrachtungszeitraum_beginn"]),
            betrachtungszeitraum_ende=cls._text_als_datum(zeile["betrachtungszeitraum_ende"]),
            anmerkungen=zeile["anmerkungen"],
        )
        return Projekt(
            projekt_id=UUID(zeile["projekt_id"]),
            bezeichnung=zeile["bezeichnung"],
            beteiligte_personen=tuple(json.loads(zeile["beteiligte_personen_json"])),
            status=Projektstatus(zeile["status"]),
            erstellt_am=datetime.fromisoformat(zeile["erstellt_am_utc"]),
            geaendert_am=datetime.fromisoformat(zeile["geaendert_am_utc"]),
            untersuchungsauftrag=auftrag,
        )
