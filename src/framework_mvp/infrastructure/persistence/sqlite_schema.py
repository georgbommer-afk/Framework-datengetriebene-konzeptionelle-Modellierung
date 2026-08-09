"""Gemeinsamer SQLite-Schemavertrag und vollständige Migrationskette."""

import json
import sqlite3
from typing import Any

from framework_mvp.infrastructure.exceptions import NichtUnterstuetzteSchemaversion

SCHEMAVERSION = 7

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

WEITERE_ETL_TABELLEN_SCHEMA_VERSION_4 = """
CREATE TABLE IF NOT EXISTS transformationsplaene (
    transformationsplan_id TEXT PRIMARY KEY NOT NULL,
    projekt_id TEXT NOT NULL,
    import_ids_json TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    erstellt_am_utc TEXT NOT NULL,
    geaendert_am_utc TEXT NOT NULL,
    FOREIGN KEY (projekt_id) REFERENCES projekte(projekt_id)
);
CREATE INDEX IF NOT EXISTS idx_transformationsplaene_projekt_id
    ON transformationsplaene(projekt_id);
CREATE TABLE IF NOT EXISTS zwischendatensaetze (
    zwischendatensatz_id TEXT PRIMARY KEY NOT NULL,
    projekt_id TEXT NOT NULL,
    transformationsplan_id TEXT NOT NULL,
    import_ids_json TEXT NOT NULL,
    relativer_daten_pfad TEXT NOT NULL,
    relativer_schema_pfad TEXT NOT NULL,
    relativer_transformation_pfad TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    zeilenanzahl INTEGER NOT NULL,
    spaltenanzahl INTEGER NOT NULL,
    erstellt_am_utc TEXT NOT NULL,
    FOREIGN KEY (projekt_id) REFERENCES projekte(projekt_id),
    FOREIGN KEY (transformationsplan_id)
        REFERENCES transformationsplaene(transformationsplan_id)
);
CREATE INDEX IF NOT EXISTS idx_zwischendatensaetze_projekt_id
    ON zwischendatensaetze(projekt_id);
CREATE INDEX IF NOT EXISTS idx_zwischendatensaetze_plan_id
    ON zwischendatensaetze(transformationsplan_id);
CREATE TABLE IF NOT EXISTS semantische_mappings (
    mapping_id TEXT PRIMARY KEY NOT NULL,
    projekt_id TEXT NOT NULL,
    zwischendatensatz_id TEXT NOT NULL,
    mapping_json TEXT NOT NULL,
    validierung_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('entwurf', 'validiert', 'ungueltig')),
    relativer_mapping_pfad TEXT NOT NULL,
    erstellt_am_utc TEXT NOT NULL,
    geaendert_am_utc TEXT NOT NULL,
    FOREIGN KEY (projekt_id) REFERENCES projekte(projekt_id),
    FOREIGN KEY (zwischendatensatz_id)
        REFERENCES zwischendatensaetze(zwischendatensatz_id)
);
CREATE INDEX IF NOT EXISTS idx_semantische_mappings_projekt_id
    ON semantische_mappings(projekt_id);
CREATE INDEX IF NOT EXISTS idx_semantische_mappings_datensatz_id
    ON semantische_mappings(zwischendatensatz_id);
"""

EVENT_LOG_QUALITAET_SCHEMA_VERSION_5 = """
CREATE TABLE IF NOT EXISTS event_logs (
    event_log_id TEXT PRIMARY KEY NOT NULL,
    projekt_id TEXT NOT NULL,
    zwischendatensatz_id TEXT NOT NULL,
    mapping_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('entwurf', 'erzeugt', 'ungueltig')),
    ereignisanzahl INTEGER NOT NULL,
    fallanzahl INTEGER NOT NULL,
    aktivitaetsanzahl INTEGER NOT NULL,
    zeitraum_von TEXT,
    zeitraum_bis TEXT,
    relativer_csv_pfad TEXT NOT NULL,
    relativer_schema_pfad TEXT NOT NULL,
    relativer_lineage_pfad TEXT NOT NULL,
    relativer_xes_pfad TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    erstellt_am_utc TEXT NOT NULL,
    FOREIGN KEY (projekt_id) REFERENCES projekte(projekt_id),
    FOREIGN KEY (zwischendatensatz_id)
        REFERENCES zwischendatensaetze(zwischendatensatz_id),
    FOREIGN KEY (mapping_id) REFERENCES semantische_mappings(mapping_id)
);
CREATE INDEX IF NOT EXISTS idx_event_logs_projekt_id ON event_logs(projekt_id);
CREATE TABLE IF NOT EXISTS qualitaetspruefungen (
    quality_run_id TEXT PRIMARY KEY NOT NULL,
    projekt_id TEXT NOT NULL,
    event_log_id TEXT NOT NULL,
    report_json TEXT NOT NULL,
    vergleich_json TEXT NOT NULL,
    relativer_report_pfad TEXT NOT NULL,
    relativer_massnahmen_pfad TEXT NOT NULL,
    relativer_csv_pfad TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    erstellt_am_utc TEXT NOT NULL,
    FOREIGN KEY (projekt_id) REFERENCES projekte(projekt_id),
    FOREIGN KEY (event_log_id) REFERENCES event_logs(event_log_id)
);
CREATE INDEX IF NOT EXISTS idx_qualitaetspruefungen_projekt_id
    ON qualitaetspruefungen(projekt_id);
CREATE TABLE IF NOT EXISTS qualitaetsregeln (
    quality_run_id TEXT NOT NULL,
    regel_id TEXT NOT NULL,
    regel_json TEXT NOT NULL,
    PRIMARY KEY (quality_run_id, regel_id),
    FOREIGN KEY (quality_run_id) REFERENCES qualitaetspruefungen(quality_run_id)
);
CREATE TABLE IF NOT EXISTS qualitaetsmassnahmen (
    quality_run_id TEXT NOT NULL,
    massnahme_id TEXT NOT NULL,
    massnahme_json TEXT NOT NULL,
    reihenfolge INTEGER NOT NULL,
    PRIMARY KEY (quality_run_id, massnahme_id),
    FOREIGN KEY (quality_run_id) REFERENCES qualitaetspruefungen(quality_run_id)
);
"""

PROCESS_MINING_SCHEMA_VERSION_6 = """
CREATE TABLE IF NOT EXISTS process_mining_analysen (
    analyse_id TEXT PRIMARY KEY NOT NULL,
    projekt_id TEXT NOT NULL,
    qualitaetspruefung_id TEXT NOT NULL,
    event_log_id TEXT NOT NULL,
    konfiguration_json TEXT NOT NULL,
    filter_json TEXT NOT NULL,
    discovery_verfahren TEXT NOT NULL
        CHECK (discovery_verfahren IN ('inductive_miner', 'heuristics_miner')),
    parameter_json TEXT NOT NULL,
    ereignisanzahl_vorher INTEGER NOT NULL,
    fallanzahl_vorher INTEGER NOT NULL,
    aktivitaetsanzahl_vorher INTEGER NOT NULL,
    variantenanzahl_vorher INTEGER NOT NULL,
    ereignisanzahl_nachher INTEGER NOT NULL,
    fallanzahl_nachher INTEGER NOT NULL,
    aktivitaetsanzahl_nachher INTEGER NOT NULL,
    variantenanzahl_nachher INTEGER NOT NULL,
    modellstatistik_json TEXT NOT NULL,
    warnungen_json TEXT NOT NULL,
    pm4py_version TEXT NOT NULL,
    relativer_ergebnis_pfad TEXT NOT NULL,
    relativer_varianten_pfad TEXT NOT NULL,
    relativer_dfg_pfad TEXT NOT NULL,
    relativer_modell_pfad TEXT NOT NULL,
    relativer_visualisierung_pfad TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('entwurf', 'ausgefuehrt', 'fehlgeschlagen')),
    erstellt_am_utc TEXT NOT NULL,
    geaendert_am_utc TEXT NOT NULL,
    FOREIGN KEY (projekt_id) REFERENCES projekte(projekt_id),
    FOREIGN KEY (event_log_id) REFERENCES event_logs(event_log_id),
    FOREIGN KEY (qualitaetspruefung_id)
        REFERENCES qualitaetspruefungen(quality_run_id)
);
CREATE INDEX IF NOT EXISTS idx_process_mining_projekt_id
    ON process_mining_analysen(projekt_id);
CREATE INDEX IF NOT EXISTS idx_process_mining_event_log_id
    ON process_mining_analysen(event_log_id);
CREATE INDEX IF NOT EXISTS idx_process_mining_qualitaetspruefung_id
    ON process_mining_analysen(qualitaetspruefung_id);
"""

MAPPINGTABELLEN_SCHEMA_VERSION_7 = """
CREATE TABLE IF NOT EXISTS mappingtabellen (
    mapping_id TEXT PRIMARY KEY NOT NULL,
    projekt_id TEXT NOT NULL,
    zwischendatensatz_id TEXT NOT NULL UNIQUE,
    mapping_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('entwurf', 'bestaetigt')),
    relativer_mapping_pfad TEXT NOT NULL,
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    erstellt_am_utc TEXT NOT NULL,
    geaendert_am_utc TEXT NOT NULL,
    FOREIGN KEY (projekt_id) REFERENCES projekte(projekt_id),
    FOREIGN KEY (zwischendatensatz_id)
        REFERENCES zwischendatensaetze(zwischendatensatz_id)
);
CREATE INDEX IF NOT EXISTS idx_mappingtabellen_projekt_id
    ON mappingtabellen(projekt_id);
CREATE INDEX IF NOT EXISTS idx_mappingtabellen_datensatz_id
    ON mappingtabellen(zwischendatensatz_id);
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
    """Initialisiert oder migriert die gemeinsame Datenbank atomar auf Version 7."""
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
        for anweisung in WEITERE_ETL_TABELLEN_SCHEMA_VERSION_4.split(";"):
            if anweisung.strip():
                verbindung.execute(anweisung)
        for anweisung in EVENT_LOG_QUALITAET_SCHEMA_VERSION_5.split(";"):
            if anweisung.strip():
                verbindung.execute(anweisung)
        for anweisung in PROCESS_MINING_SCHEMA_VERSION_6.split(";"):
            if anweisung.strip():
                verbindung.execute(anweisung)
        for anweisung in MAPPINGTABELLEN_SCHEMA_VERSION_7.split(";"):
            if anweisung.strip():
                verbindung.execute(anweisung)
        if version < SCHEMAVERSION:
            verbindung.execute(f"PRAGMA user_version = {SCHEMAVERSION}")
    except Exception:
        verbindung.rollback()
        raise
    else:
        verbindung.commit()
