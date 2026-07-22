"""SQLite-Implementierung des Repositorys für Importvorgänge."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from framework_mvp.domain.models import (
    CsvImportparameter,
    Dateityp,
    Dezimaltrennzeichen,
    ExcelImportparameter,
    Importstatus,
    Importvorgang,
    Kopfzeileneinstellung,
    Kopfzeilenmodus,
    Profilzusammenfassung,
    Tausendertrennzeichen,
    Trennzeichenwahl,
    Zeichenkodierung,
)
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    STANDARD_DATENBANKPFAD,
)
from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema

_SPALTEN = """
    import_id, projekt_id, datenquellen_id, originaldateiname, sicherer_dateiname,
    dateityp, dateigroesse_bytes, sha256, importparameter_json, tabellenbezeichnung,
    zeilenanzahl, spaltenanzahl, profil_version, relativer_raw_pfad,
    relativer_profil_pfad, profilzusammenfassung_json, warnungen_json, status,
    erstellt_am_utc, bestaetigt_am_utc
"""


def _json(wert: Any) -> str:
    return json.dumps(wert, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def serialisiere_importparameter(
    parameter: CsvImportparameter | ExcelImportparameter,
) -> dict[str, Any]:
    """Überführt typisierte Importparameter in eine stabile JSON-Struktur."""
    if isinstance(parameter, CsvImportparameter):
        return {"typ": "csv", "werte": asdict(parameter)}
    return {"typ": "excel", "werte": asdict(parameter)}


def deserialisiere_importparameter(
    struktur: dict[str, Any],
) -> CsvImportparameter | ExcelImportparameter:
    """Stellt typisierte Importparameter aus der gespeicherten Struktur wieder her."""
    werte = struktur["werte"]
    kopf = werte["kopfzeile"]
    kopfzeile = Kopfzeileneinstellung(Kopfzeilenmodus(kopf["modus"]), kopf["zeilennummer"])
    if struktur["typ"] == "csv":
        return CsvImportparameter(
            trennzeichenwahl=Trennzeichenwahl(werte["trennzeichenwahl"]),
            benutzerdefiniertes_trennzeichen=werte["benutzerdefiniertes_trennzeichen"],
            erkanntes_trennzeichen=werte["erkanntes_trennzeichen"],
            zeichenkodierung=Zeichenkodierung(werte["zeichenkodierung"]),
            dezimaltrennzeichen=Dezimaltrennzeichen(werte["dezimaltrennzeichen"]),
            tausendertrennzeichen=Tausendertrennzeichen(werte["tausendertrennzeichen"]),
            kopfzeile=kopfzeile,
        )
    return ExcelImportparameter(werte["tabellenblatt"], kopfzeile)


class SQLiteImportvorgangRepository:
    """Speichert ausschließlich Importmetadaten in der gemeinsamen SQLite-Datei."""

    def __init__(self, datenbankpfad: Path | str = STANDARD_DATENBANKPFAD) -> None:
        """Konfiguriert den Datenbankpfad ohne sofortigen Zugriff."""
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

    def speichern(self, importvorgang: Importvorgang) -> None:
        """Speichert einen Import genau einmal innerhalb einer SQLite-Transaktion."""
        platzhalter = ", ".join("?" for _ in range(20))
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(
                f"INSERT INTO importvorgaenge ({_SPALTEN}) VALUES ({platzhalter})",
                self._serialisieren(importvorgang),
            )

    def laden(self, import_id: UUID) -> Importvorgang | None:
        """Lädt einen Importvorgang anhand seiner UUID."""
        with self._verbindung() as verbindung:
            zeile = verbindung.execute(
                f"SELECT {_SPALTEN} FROM importvorgaenge WHERE import_id = ?", (str(import_id),)
            ).fetchone()
        return None if zeile is None else self._deserialisieren(zeile)

    def fuer_projekt_auflisten(self, projekt_id: UUID) -> list[Importvorgang]:
        """Lädt Projektimporte in stabiler zeitlicher Reihenfolge."""
        return self._auflisten("projekt_id", projekt_id)

    def fuer_datenquelle_auflisten(self, datenquellen_id: UUID) -> list[Importvorgang]:
        """Lädt Datenquellenimporte in stabiler zeitlicher Reihenfolge."""
        return self._auflisten("datenquellen_id", datenquellen_id)

    def _auflisten(self, spalte: str, wert: UUID) -> list[Importvorgang]:
        with self._verbindung() as verbindung:
            zeilen = verbindung.execute(
                f"SELECT {_SPALTEN} FROM importvorgaenge WHERE {spalte} = ? "
                "ORDER BY erstellt_am_utc, import_id",
                (str(wert),),
            ).fetchall()
        return [self._deserialisieren(zeile) for zeile in zeilen]

    @staticmethod
    def _serialisieren(importvorgang: Importvorgang) -> tuple[Any, ...]:
        return (
            str(importvorgang.import_id),
            str(importvorgang.projekt_id),
            str(importvorgang.datenquellen_id),
            importvorgang.originaldateiname,
            importvorgang.sicherer_dateiname,
            importvorgang.dateityp.value,
            importvorgang.dateigroesse_bytes,
            importvorgang.sha256,
            _json(serialisiere_importparameter(importvorgang.importparameter)),
            importvorgang.tabellenbezeichnung,
            importvorgang.zeilenanzahl,
            importvorgang.spaltenanzahl,
            importvorgang.profil_version,
            importvorgang.relativer_raw_pfad,
            importvorgang.relativer_profil_pfad,
            _json(asdict(importvorgang.profilzusammenfassung)),
            _json(importvorgang.warnungen),
            importvorgang.status.value,
            importvorgang.erstellt_am.isoformat(),
            importvorgang.bestaetigt_am.isoformat() if importvorgang.bestaetigt_am else None,
        )

    @staticmethod
    def _deserialisieren(zeile: sqlite3.Row) -> Importvorgang:
        return Importvorgang(
            import_id=UUID(zeile["import_id"]),
            projekt_id=UUID(zeile["projekt_id"]),
            datenquellen_id=UUID(zeile["datenquellen_id"]),
            originaldateiname=zeile["originaldateiname"],
            sicherer_dateiname=zeile["sicherer_dateiname"],
            dateityp=Dateityp(zeile["dateityp"]),
            dateigroesse_bytes=zeile["dateigroesse_bytes"],
            sha256=zeile["sha256"],
            importparameter=deserialisiere_importparameter(
                json.loads(zeile["importparameter_json"])
            ),
            tabellenbezeichnung=zeile["tabellenbezeichnung"],
            zeilenanzahl=zeile["zeilenanzahl"],
            spaltenanzahl=zeile["spaltenanzahl"],
            profil_version=zeile["profil_version"],
            relativer_raw_pfad=zeile["relativer_raw_pfad"],
            relativer_profil_pfad=zeile["relativer_profil_pfad"],
            profilzusammenfassung=Profilzusammenfassung(
                **json.loads(zeile["profilzusammenfassung_json"])
            ),
            warnungen=tuple(json.loads(zeile["warnungen_json"])),
            status=Importstatus(zeile["status"]),
            erstellt_am=datetime.fromisoformat(zeile["erstellt_am_utc"]),
            bestaetigt_am=(
                datetime.fromisoformat(zeile["bestaetigt_am_utc"])
                if zeile["bestaetigt_am_utc"]
                else None
            ),
        )
