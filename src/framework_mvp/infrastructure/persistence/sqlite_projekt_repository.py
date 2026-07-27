"""SQLite-Persistenz mit transaktionaler Migration auf Schemaversion 2."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from framework_mvp.domain.models import (
    BeteiligtePerson,
    Betrachtungszeitraum,
    BetrachtungszeitraumModus,
    GestaltDerGueter,
    Intralogistikklassifikation,
    LogistischeZielgroesse,
    Materialflussform,
    Materialflusskontinuitaet,
    Produktionsklassifikation,
    Projekt,
    Projektstatus,
    Rahmenbedingungen,
    Systemklassifikation,
    Systemtyp,
    Untersuchungsauftrag,
)
from framework_mvp.infrastructure.persistence.sqlite_schema import initialisiere_schema
from framework_mvp.workspace import STANDARD_WORKSPACE_PFAD

STANDARD_DATENBANKPFAD = STANDARD_WORKSPACE_PFAD / "framework_mvp.sqlite"

_SPALTEN = """
    projekt_id, bezeichnung, beteiligte_personen_json, status,
    erstellt_am_utc, geaendert_am_utc, untersuchungsauftrag_json
"""


class SQLiteProjektRepository:
    """Speichert Projekte und migriert vorhandene Version-1-Daten atomar."""

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

    def speichern(self, projekt: Projekt) -> None:
        """Fügt ein Projekt ein oder aktualisiert es atomar."""
        sql = f"""
            INSERT INTO projekte ({_SPALTEN}) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(projekt_id) DO UPDATE SET
                bezeichnung = excluded.bezeichnung,
                beteiligte_personen_json = excluded.beteiligte_personen_json,
                status = excluded.status,
                geaendert_am_utc = excluded.geaendert_am_utc,
                untersuchungsauftrag_json = excluded.untersuchungsauftrag_json
        """
        with self._verbindung() as verbindung, verbindung:
            verbindung.execute(sql, self._serialisieren(projekt))

    def laden(self, projekt_id: UUID) -> Projekt | None:
        """Lädt ein Projekt anhand seiner UUID."""
        with self._verbindung() as verbindung:
            zeile = verbindung.execute(
                f"SELECT {_SPALTEN} FROM projekte WHERE projekt_id = ?", (str(projekt_id),)
            ).fetchone()
        return None if zeile is None else self._deserialisieren(zeile)

    def auflisten(self) -> list[Projekt]:
        """Lädt alle Projekte in reproduzierbarer Reihenfolge."""
        with self._verbindung() as verbindung:
            zeilen = verbindung.execute(
                f"SELECT {_SPALTEN} FROM projekte ORDER BY erstellt_am_utc, projekt_id"
            ).fetchall()
        return [self._deserialisieren(zeile) for zeile in zeilen]

    @staticmethod
    def _json(wert: Any) -> str:
        return json.dumps(wert, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def _serialisieren(cls, projekt: Projekt) -> tuple[Any, ...]:
        personen = [
            {"vorname": p.vorname, "nachname": p.nachname, "rolle": p.rolle}
            for p in projekt.beteiligte_personen
        ]
        return (
            str(projekt.projekt_id),
            projekt.bezeichnung,
            cls._json(personen),
            projekt.status.value,
            projekt.erstellt_am.isoformat(),
            projekt.geaendert_am.isoformat(),
            cls._json(cls._auftrag_als_dict(projekt.untersuchungsauftrag)),
        )

    @classmethod
    def _auftrag_als_dict(cls, auftrag: Untersuchungsauftrag) -> dict[str, Any]:
        system = auftrag.systemklassifikation
        return {
            "problemstellung": auftrag.problemstellung,
            "untersuchungszweck": auftrag.untersuchungszweck,
            "untersuchungszwecke": list(auftrag.untersuchungszwecke),
            "individuelles_ziel": auftrag.individuelles_ziel,
            "systemtyp": auftrag.systemtyp.value,
            "systemgrenze": auftrag.systemgrenze,
            "logistische_zielgroessen": [z.value for z in auftrag.logistische_zielgroessen],
            "ausgewaehlte_kpi_ids": list(auftrag.ausgewaehlte_kpi_ids),
            "legacy_leistungskennzahlen": list(auftrag.legacy_leistungskennzahlen),
            "migrationsbestand": auftrag.migrationsbestand,
            "detaillierungsgrad": auftrag.detaillierungsgrad,
            "anmerkungen": auftrag.anmerkungen,
            "betrachtungszeitraum": {
                "modus": auftrag.betrachtungszeitraum.modus.value,
                "beginn": cls._datum(auftrag.betrachtungszeitraum.beginn),
                "ende": cls._datum(auftrag.betrachtungszeitraum.ende),
                "migrationsbestand": auftrag.betrachtungszeitraum.migrationsbestand,
            },
            "rahmenbedingungen": {
                feld: getattr(auftrag.rahmenbedingungen, feld)
                for feld in auftrag.rahmenbedingungen.__dataclass_fields__
            },
            "systemklassifikation": cls._system_als_dict(system),
        }

    @staticmethod
    def _system_als_dict(system: Systemklassifikation) -> dict[str, Any]:
        def block(
            objekt: Produktionsklassifikation | Intralogistikklassifikation | None,
        ) -> dict[str, Any] | None:
            if objekt is None:
                return None
            return {
                feld: list(wert) if isinstance(wert, tuple) else wert
                for feld, wert in (
                    (name, getattr(objekt, name)) for name in objekt.__dataclass_fields__
                )
            }

        return {
            "bereich": system.bereich,
            "objekte_gueter": system.objekte_gueter,
            "gestalt_der_gueter": system.gestalt_der_gueter.value,
            "materialflussform": system.materialflussform.value,
            "materialflusskontinuitaet": system.materialflusskontinuitaet.value,
            "kapazitaetsgrenzen": system.kapazitaetsgrenzen,
            "input_beschreibung": system.input_beschreibung,
            "transformation_beschreibung": system.transformation_beschreibung,
            "output_beschreibung": system.output_beschreibung,
            "produktion": block(system.produktion),
            "intralogistik": block(system.intralogistik),
        }

    @staticmethod
    def _datum(wert: date | None) -> str | None:
        return None if wert is None else wert.isoformat()

    @staticmethod
    def _datum_aus_text(wert: str | None) -> date | None:
        return None if wert is None else date.fromisoformat(wert)

    @classmethod
    def _deserialisieren(cls, zeile: sqlite3.Row) -> Projekt:
        daten = json.loads(zeile["untersuchungsauftrag_json"])
        system_daten = daten["systemklassifikation"]
        produktionsdaten = system_daten["produktion"]
        intralogistikdaten = system_daten["intralogistik"]
        if produktionsdaten is not None:
            produktionsdaten["produktionsfaktoren"] = tuple(produktionsdaten["produktionsfaktoren"])
            produktionsdaten["ressourcen"] = tuple(produktionsdaten["ressourcen"])
        if intralogistikdaten is not None:
            for feld in ("hauptfunktionen", "ladungstraeger", "ressourcen"):
                intralogistikdaten[feld] = tuple(intralogistikdaten[feld])
        system = Systemklassifikation(
            bereich=system_daten["bereich"],
            objekte_gueter=system_daten["objekte_gueter"],
            gestalt_der_gueter=GestaltDerGueter(system_daten["gestalt_der_gueter"]),
            materialflussform=Materialflussform(system_daten["materialflussform"]),
            materialflusskontinuitaet=Materialflusskontinuitaet(
                system_daten["materialflusskontinuitaet"]
            ),
            kapazitaetsgrenzen=system_daten["kapazitaetsgrenzen"],
            input_beschreibung=system_daten["input_beschreibung"],
            transformation_beschreibung=system_daten["transformation_beschreibung"],
            output_beschreibung=system_daten["output_beschreibung"],
            produktion=None
            if produktionsdaten is None
            else Produktionsklassifikation(**produktionsdaten),
            intralogistik=None
            if intralogistikdaten is None
            else Intralogistikklassifikation(**intralogistikdaten),
        )
        zeitraum = daten["betrachtungszeitraum"]
        auftrag = Untersuchungsauftrag(
            problemstellung=daten["problemstellung"],
            untersuchungszweck=daten["untersuchungszweck"],
            individuelles_ziel=daten["individuelles_ziel"],
            systemtyp=Systemtyp(daten["systemtyp"]),
            systemgrenze=daten["systemgrenze"],
            logistische_zielgroessen=tuple(
                LogistischeZielgroesse(z) for z in daten["logistische_zielgroessen"]
            ),
            ausgewaehlte_kpi_ids=tuple(daten["ausgewaehlte_kpi_ids"]),
            legacy_leistungskennzahlen=tuple(daten["legacy_leistungskennzahlen"]),
            migrationsbestand=bool(daten.get("migrationsbestand", False)),
            systemklassifikation=system,
            detaillierungsgrad=daten["detaillierungsgrad"],
            rahmenbedingungen=Rahmenbedingungen(**daten["rahmenbedingungen"]),
            betrachtungszeitraum=Betrachtungszeitraum(
                BetrachtungszeitraumModus(zeitraum["modus"]),
                cls._datum_aus_text(zeitraum["beginn"]),
                cls._datum_aus_text(zeitraum["ende"]),
                bool(zeitraum.get("migrationsbestand", False)),
            ),
            anmerkungen=daten["anmerkungen"],
            untersuchungszwecke=tuple(
                daten.get("untersuchungszwecke", (daten["untersuchungszweck"],))
            ),
        )
        personen = tuple(
            BeteiligtePerson(**person) for person in json.loads(zeile["beteiligte_personen_json"])
        )
        return Projekt(
            UUID(zeile["projekt_id"]),
            zeile["bezeichnung"],
            personen,
            Projektstatus(zeile["status"]),
            datetime.fromisoformat(zeile["erstellt_am_utc"]),
            datetime.fromisoformat(zeile["geaendert_am_utc"]),
            auftrag,
        )
