"""Gemeinsamer SQLite-Schemavertrag und vollständige Migrationskette."""

import json
import sqlite3
from typing import Any

from framework_mvp.infrastructure.exceptions import NichtUnterstuetzteSchemaversion

SCHEMAVERSION = 4

PROJEKT_SCHEMA_VERSION_2 = """
CREATE TABLE IF NOT EXISTS projekte (
    projekt_id TEXT PRIMARY KEY NOT NULL,
    bezeichnung TEXT NOT NULL CHECK (length(trim(bezeichnung)) > 0),
    beteiligte_personen_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('entwurf', 'aktiv', 'abgeschlossen')),
    erstellt_am_utc TEXT NOT NULL,
    geaendert_am_utc TEXT NOT NULL,
    untersuchungsauftrag_json TEXT NOT NULL
)
"""

DATENQUELLEN_SCHEMA_VERSION_3 = """
CREATE TABLE IF NOT EXISTS datenquellen (
    datenquellen_id TEXT PRIMARY KEY NOT NULL,
    projekt_id TEXT NOT NULL,
    bezeichnung TEXT NOT NULL CHECK (length(trim(bezeichnung)) > 0),
    quellsystemtyp TEXT NOT NULL,
    konkretes_quellsystem TEXT NOT NULL,
    fachliche_beschreibung TEXT NOT NULL,
    herkunft_oder_verantwortungsbereich TEXT NOT NULL,
    quellenart TEXT NOT NULL CHECK (quellenart IN ('csv', 'excel', 'datenbank')),
    erwartete_tabellen_oder_blaetter_json TEXT NOT NULL,
    bekannte_schluesselattribute_json TEXT NOT NULL,
    erstellt_am_utc TEXT NOT NULL,
    geaendert_am_utc TEXT NOT NULL,
    FOREIGN KEY (projekt_id) REFERENCES projekte(projekt_id)
)
"""

IMPORTVORGAENGE_SCHEMA_VERSION_4 = """
CREATE TABLE IF NOT EXISTS importvorgaenge (
    import_id TEXT PRIMARY KEY NOT NULL,
    projekt_id TEXT NOT NULL,
    datenquellen_id TEXT NOT NULL,
    originaldateiname TEXT NOT NULL,
    sicherer_dateiname TEXT NOT NULL,
    dateityp TEXT NOT NULL CHECK (dateityp IN ('CSV', 'XLSX')),
    dateigroesse_bytes INTEGER NOT NULL CHECK (dateigroesse_bytes >= 0),
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    importparameter_json TEXT NOT NULL,
    tabellenbezeichnung TEXT NOT NULL,
    zeilenanzahl INTEGER NOT NULL CHECK (zeilenanzahl >= 0),
    spaltenanzahl INTEGER NOT NULL CHECK (spaltenanzahl >= 0),
    profil_version INTEGER NOT NULL CHECK (profil_version >= 1),
    relativer_raw_pfad TEXT NOT NULL,
    relativer_profil_pfad TEXT NOT NULL,
    profilzusammenfassung_json TEXT NOT NULL,
    warnungen_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('entwurf', 'bestaetigt', 'fehlgeschlagen')),
    erstellt_am_utc TEXT NOT NULL,
    bestaetigt_am_utc TEXT,
    FOREIGN KEY (projekt_id) REFERENCES projekte(projekt_id),
    FOREIGN KEY (datenquellen_id) REFERENCES datenquellen(datenquellen_id)
);
CREATE INDEX IF NOT EXISTS idx_importvorgaenge_projekt_id
    ON importvorgaenge(projekt_id);
CREATE INDEX IF NOT EXISTS idx_importvorgaenge_datenquellen_id
    ON importvorgaenge(datenquellen_id);
CREATE INDEX IF NOT EXISTS idx_importvorgaenge_sha256
    ON importvorgaenge(sha256);
"""

_PROJEKTSPALTEN_VERSION_2 = """
    projekt_id, bezeichnung, beteiligte_personen_json, status,
    erstellt_am_utc, geaendert_am_utc, untersuchungsauftrag_json
"""


def _json(wert: Any) -> str:
    return json.dumps(wert, ensure_ascii=False, separators=(",", ":"))


def _migriere_version_1_auf_2(verbindung: sqlite3.Connection) -> None:
    """Migriert das flache Projektmodell verlustfrei zum strukturierten Auftrag."""
    verbindung.execute("ALTER TABLE projekte RENAME TO projekte_version_1")
    verbindung.execute(PROJEKT_SCHEMA_VERSION_2)
    for zeile in verbindung.execute("SELECT * FROM projekte_version_1").fetchall():
        personen = [
            {"vorname": "", "nachname": str(person), "rolle": "Sonstige"}
            for person in json.loads(zeile["beteiligte_personen_json"])
        ]
        beginn = zeile["betrachtungszeitraum_beginn"]
        ende = zeile["betrachtungszeitraum_ende"]
        auftrag = {
            "problemstellung": zeile["problemstellung"],
            "untersuchungszweck": "",
            "individuelles_ziel": zeile["zielsetzung"],
            "systemtyp": zeile["systemtyp"],
            "systemgrenze": zeile["systemgrenze"],
            "logistische_zielgroessen": [],
            "ausgewaehlte_kpi_ids": [],
            "legacy_leistungskennzahlen": json.loads(zeile["leistungskennzahlen_json"]),
            "migrationsbestand": True,
            "detaillierungsgrad": zeile["detaillierungsgrad"],
            "anmerkungen": zeile["anmerkungen"],
            "betrachtungszeitraum": {
                "modus": "manuell" if beginn is not None or ende is not None else "offen",
                "beginn": beginn,
                "ende": ende,
                "migrationsbestand": True,
            },
            "rahmenbedingungen": {
                "vertraulichkeit_datenschutz": "",
                "technische_einschraenkungen": "",
                "bekannte_annahmen": "",
                "bekannte_ausschluesse": "",
                "sonstige": zeile["rahmenbedingungen"],
            },
            "systemklassifikation": {
                "bereich": zeile["systemgrenze"],
                "objekte_gueter": "",
                "gestalt_der_gueter": "mischform",
                "materialflussform": "gemischt",
                "materialflusskontinuitaet": "gemischt",
                "kapazitaetsgrenzen": "",
                "input_beschreibung": zeile["input_beschreibung"],
                "transformation_beschreibung": zeile["transformation_beschreibung"],
                "output_beschreibung": zeile["output_beschreibung"],
                "produktion": None,
                "intralogistik": None,
            },
        }
        verbindung.execute(
            f"INSERT INTO projekte ({_PROJEKTSPALTEN_VERSION_2}) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                zeile["projekt_id"],
                zeile["bezeichnung"],
                _json(personen),
                zeile["status"],
                zeile["erstellt_am_utc"],
                zeile["geaendert_am_utc"],
                _json(auftrag),
            ),
        )
    verbindung.execute("DROP TABLE projekte_version_1")


def initialisiere_schema(verbindung: sqlite3.Connection) -> None:
    """Initialisiert oder migriert die gemeinsame Datenbank atomar auf Version 4."""
    version = int(verbindung.execute("PRAGMA user_version").fetchone()[0])
    if version > SCHEMAVERSION:
        raise NichtUnterstuetzteSchemaversion(
            "Die SQLite-Datenbank verwendet die neuere Schemaversion "
            f"{version}; unterstützt wird höchstens Version {SCHEMAVERSION}."
        )
    verbindung.execute("BEGIN IMMEDIATE")
    try:
        if version == 0:
            verbindung.execute(PROJEKT_SCHEMA_VERSION_2)
        elif version == 1:
            _migriere_version_1_auf_2(verbindung)
        verbindung.execute(DATENQUELLEN_SCHEMA_VERSION_3)
        for anweisung in IMPORTVORGAENGE_SCHEMA_VERSION_4.split(";"):
            if anweisung.strip():
                verbindung.execute(anweisung)
        if version < SCHEMAVERSION:
            verbindung.execute(f"PRAGMA user_version = {SCHEMAVERSION}")
    except Exception:
        verbindung.rollback()
        raise
    else:
        verbindung.commit()
