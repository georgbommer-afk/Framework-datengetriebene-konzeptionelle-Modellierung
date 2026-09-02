"""Gemeinsamer SQLite-Schemavertrag und vollständige Migrationskette."""

import json
import sqlite3
from typing import Any

from framework_mvp.infrastructure.exceptions import NichtUnterstuetzteSchemaversion

SCHEMAVERSION = 12

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

ERGEBNISAGGREGATION_SCHEMA_VERSION_8 = """
CREATE TABLE IF NOT EXISTS ergebnisaggregationen (
    aggregations_id TEXT PRIMARY KEY NOT NULL,
    projekt_id TEXT NOT NULL,
    spezifikations_id TEXT NOT NULL,
    freigabe_id TEXT NOT NULL,
    event_log_id TEXT NOT NULL,
    analyse_id TEXT NOT NULL,
    eingabefingerabdruck TEXT NOT NULL CHECK (length(eingabefingerabdruck) = 64),
    konfigurationsfingerabdruck TEXT NOT NULL CHECK (length(konfigurationsfingerabdruck) = 64),
    relativer_aggregations_pfad TEXT NOT NULL,
    aggregations_sha256 TEXT NOT NULL CHECK (length(aggregations_sha256) = 64),
    status TEXT NOT NULL CHECK (status IN ('gespeichert')),
    erstellt_am_utc TEXT NOT NULL,
    FOREIGN KEY (projekt_id) REFERENCES projekte(projekt_id),
    FOREIGN KEY (freigabe_id) REFERENCES qualitaetspruefungen(quality_run_id),
    FOREIGN KEY (event_log_id) REFERENCES event_logs(event_log_id),
    FOREIGN KEY (analyse_id) REFERENCES process_mining_analysen(analyse_id)
);
CREATE INDEX IF NOT EXISTS idx_ergebnisaggregationen_projekt_id
    ON ergebnisaggregationen(projekt_id);
CREATE INDEX IF NOT EXISTS idx_ergebnisaggregationen_freigabe_id
    ON ergebnisaggregationen(freigabe_id);
CREATE INDEX IF NOT EXISTS idx_ergebnisaggregationen_analyse_id
    ON ergebnisaggregationen(analyse_id);
"""

MODELLABLEITUNG_SCHEMA_VERSION_9 = """
CREATE TABLE IF NOT EXISTS modellableitungen (
    modellableitungs_id TEXT PRIMARY KEY NOT NULL,
    k_id TEXT UNIQUE NOT NULL,
    o_id TEXT UNIQUE NOT NULL,
    projekt_id TEXT NOT NULL,
    aggregations_id TEXT NOT NULL,
    analyse_id TEXT NOT NULL,
    event_log_id TEXT NOT NULL,
    eingabefingerabdruck TEXT NOT NULL CHECK (length(eingabefingerabdruck) = 64),
    mappingversion INTEGER NOT NULL CHECK (mappingversion > 0),
    unsicherheitsfingerabdruck TEXT NOT NULL CHECK (length(unsicherheitsfingerabdruck) = 64),
    relativer_k_pfad TEXT NOT NULL,
    k_sha256 TEXT NOT NULL CHECK (length(k_sha256) = 64),
    relativer_o_pfad TEXT NOT NULL,
    o_sha256 TEXT NOT NULL CHECK (length(o_sha256) = 64),
    status TEXT NOT NULL CHECK (status IN ('gespeichert')),
    erstellt_am_utc TEXT NOT NULL,
    UNIQUE (
        projekt_id, aggregations_id, eingabefingerabdruck,
        mappingversion, unsicherheitsfingerabdruck
    ),
    FOREIGN KEY (projekt_id) REFERENCES projekte(projekt_id),
    FOREIGN KEY (aggregations_id) REFERENCES ergebnisaggregationen(aggregations_id),
    FOREIGN KEY (analyse_id) REFERENCES process_mining_analysen(analyse_id),
    FOREIGN KEY (event_log_id) REFERENCES event_logs(event_log_id)
);
CREATE INDEX IF NOT EXISTS idx_modellableitungen_projekt_id
    ON modellableitungen(projekt_id);
CREATE INDEX IF NOT EXISTS idx_modellableitungen_aggregations_id
    ON modellableitungen(aggregations_id);
"""

MODELLVALIDIERUNG_SCHEMA_VERSION_10 = """
CREATE TABLE IF NOT EXISTS modellvalidierungen (
    validierungslauf_id TEXT PRIMARY KEY NOT NULL,
    k_stern_id TEXT UNIQUE NOT NULL,
    projekt_id TEXT NOT NULL,
    modellableitungs_id TEXT NOT NULL,
    k_id TEXT NOT NULL,
    o_id TEXT NOT NULL,
    eingabefingerabdruck TEXT NOT NULL CHECK (length(eingabefingerabdruck) = 64),
    entscheidungsfingerabdruck TEXT NOT NULL CHECK (length(entscheidungsfingerabdruck) = 64),
    relativer_k_stern_pfad TEXT NOT NULL,
    k_stern_sha256 TEXT NOT NULL CHECK (length(k_stern_sha256) = 64),
    status TEXT NOT NULL CHECK (status IN ('fachlich_validiert')),
    erstellt_am_utc TEXT NOT NULL,
    UNIQUE (
        projekt_id, modellableitungs_id,
        eingabefingerabdruck, entscheidungsfingerabdruck
    ),
    FOREIGN KEY (projekt_id) REFERENCES projekte(projekt_id),
    FOREIGN KEY (modellableitungs_id) REFERENCES modellableitungen(modellableitungs_id),
    FOREIGN KEY (k_id) REFERENCES modellableitungen(k_id),
    FOREIGN KEY (o_id) REFERENCES modellableitungen(o_id)
);
CREATE INDEX IF NOT EXISTS idx_modellvalidierungen_projekt_id
    ON modellvalidierungen(projekt_id);
CREATE INDEX IF NOT EXISTS idx_modellvalidierungen_modellableitungs_id
    ON modellvalidierungen(modellableitungs_id);
"""

PORTABILITAET_UND_MANDANTEN_SCHEMA_VERSION_11 = """
CREATE TABLE IF NOT EXISTS benutzer (
    benutzer_id TEXT PRIMARY KEY NOT NULL,
    oidc_issuer TEXT NOT NULL,
    oidc_subject TEXT NOT NULL,
    email TEXT NOT NULL DEFAULT '',
    anzeigename TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'aktiv' CHECK (status IN ('aktiv', 'deaktiviert')),
    erstellt_am_utc TEXT NOT NULL,
    zuletzt_angemeldet_am_utc TEXT NOT NULL,
    UNIQUE (oidc_issuer, oidc_subject)
);
CREATE TABLE IF NOT EXISTS globale_rollen (
    benutzer_id TEXT NOT NULL,
    rolle TEXT NOT NULL CHECK (rolle IN ('gruppenleitung', 'systemadmin')),
    vergeben_am_utc TEXT NOT NULL,
    vergeben_von_benutzer_id TEXT,
    PRIMARY KEY (benutzer_id, rolle),
    FOREIGN KEY (benutzer_id) REFERENCES benutzer(benutzer_id),
    FOREIGN KEY (vergeben_von_benutzer_id) REFERENCES benutzer(benutzer_id)
);
CREATE TABLE IF NOT EXISTS kursgruppen (
    gruppen_id TEXT PRIMARY KEY NOT NULL,
    bezeichnung TEXT NOT NULL CHECK (length(trim(bezeichnung)) > 0),
    beschreibung TEXT NOT NULL DEFAULT '',
    gruppenleitung_benutzer_id TEXT NOT NULL,
    beginn_am TEXT,
    ende_am TEXT,
    maximale_teilnehmende INTEGER NOT NULL DEFAULT 100
        CHECK (maximale_teilnehmende BETWEEN 1 AND 10000),
    maximale_projekte INTEGER NOT NULL DEFAULT 15
        CHECK (maximale_projekte BETWEEN 1 AND 10000),
    speicherlimit_pro_projekt_bytes INTEGER NOT NULL DEFAULT 209715200
        CHECK (speicherlimit_pro_projekt_bytes > 0),
    aufbewahrung_bis_utc TEXT,
    status TEXT NOT NULL DEFAULT 'aktiv'
        CHECK (status IN ('aktiv', 'abgelaufen', 'gesperrt', 'geloescht')),
    erstellt_am_utc TEXT NOT NULL,
    geaendert_am_utc TEXT NOT NULL,
    FOREIGN KEY (gruppenleitung_benutzer_id) REFERENCES benutzer(benutzer_id)
);
CREATE TABLE IF NOT EXISTS gruppenmitgliedschaften (
    gruppen_id TEXT NOT NULL,
    benutzer_id TEXT NOT NULL,
    rolle TEXT NOT NULL CHECK (rolle IN ('teilnehmer', 'gruppenleitung', 'gruppenassistenz')),
    status TEXT NOT NULL DEFAULT 'aktiv'
        CHECK (status IN ('aktiv', 'entfernt', 'gesperrt')),
    berechtigungen_json TEXT NOT NULL DEFAULT '[]',
    beigetreten_am_utc TEXT NOT NULL,
    geaendert_am_utc TEXT NOT NULL,
    PRIMARY KEY (gruppen_id, benutzer_id),
    FOREIGN KEY (gruppen_id) REFERENCES kursgruppen(gruppen_id),
    FOREIGN KEY (benutzer_id) REFERENCES benutzer(benutzer_id)
);
CREATE INDEX IF NOT EXISTS idx_gruppenmitgliedschaften_benutzer
    ON gruppenmitgliedschaften(benutzer_id, status);
CREATE TABLE IF NOT EXISTS gruppeneinladungen (
    einladungs_id TEXT PRIMARY KEY NOT NULL,
    gruppen_id TEXT NOT NULL,
    token_sha256 TEXT UNIQUE NOT NULL CHECK (length(token_sha256) = 64),
    laeuft_ab_am_utc TEXT NOT NULL,
    maximale_nutzungen INTEGER NOT NULL CHECK (maximale_nutzungen > 0),
    anzahl_nutzungen INTEGER NOT NULL DEFAULT 0 CHECK (anzahl_nutzungen >= 0),
    erlaubte_email_domain TEXT NOT NULL DEFAULT '',
    erlaubte_emails_json TEXT NOT NULL DEFAULT '[]',
    widerrufen_am_utc TEXT,
    erstellt_von_benutzer_id TEXT NOT NULL,
    erstellt_am_utc TEXT NOT NULL,
    FOREIGN KEY (gruppen_id) REFERENCES kursgruppen(gruppen_id),
    FOREIGN KEY (erstellt_von_benutzer_id) REFERENCES benutzer(benutzer_id)
);
CREATE INDEX IF NOT EXISTS idx_gruppeneinladungen_gruppe
    ON gruppeneinladungen(gruppen_id);
CREATE TABLE IF NOT EXISTS projektzugehoerigkeiten (
    projekt_id TEXT PRIMARY KEY NOT NULL,
    zugriffsart TEXT NOT NULL
        CHECK (zugriffsart IN ('gast', 'kursgruppe', 'legacy_unassigned')),
    gruppen_id TEXT,
    gast_geheimnis_sha256 TEXT,
    gast_ablauf_am_utc TEXT,
    zuletzt_aktiv_am_utc TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
    erstellt_am_utc TEXT NOT NULL,
    CHECK (
        (zugriffsart = 'gast' AND gruppen_id IS NULL
            AND length(gast_geheimnis_sha256) = 64 AND gast_ablauf_am_utc IS NOT NULL)
        OR (zugriffsart = 'kursgruppe' AND gruppen_id IS NOT NULL
            AND gast_geheimnis_sha256 IS NULL AND gast_ablauf_am_utc IS NULL)
        OR (zugriffsart = 'legacy_unassigned' AND gruppen_id IS NULL
            AND gast_geheimnis_sha256 IS NULL AND gast_ablauf_am_utc IS NULL)
    ),
    FOREIGN KEY (projekt_id) REFERENCES projekte(projekt_id) ON DELETE CASCADE,
    FOREIGN KEY (gruppen_id) REFERENCES kursgruppen(gruppen_id)
);
CREATE INDEX IF NOT EXISTS idx_projektzugehoerigkeiten_gruppe
    ON projektzugehoerigkeiten(gruppen_id);
CREATE INDEX IF NOT EXISTS idx_projektzugehoerigkeiten_gast_ablauf
    ON projektzugehoerigkeiten(gast_ablauf_am_utc);
CREATE TABLE IF NOT EXISTS projektmitglieder (
    projekt_id TEXT NOT NULL,
    benutzer_id TEXT NOT NULL,
    darf_bearbeiten INTEGER NOT NULL DEFAULT 1 CHECK (darf_bearbeiten IN (0, 1)),
    status TEXT NOT NULL DEFAULT 'aktiv' CHECK (status IN ('aktiv', 'entfernt')),
    zugewiesen_am_utc TEXT NOT NULL,
    PRIMARY KEY (projekt_id, benutzer_id),
    FOREIGN KEY (projekt_id) REFERENCES projekte(projekt_id) ON DELETE CASCADE,
    FOREIGN KEY (benutzer_id) REFERENCES benutzer(benutzer_id)
);
CREATE INDEX IF NOT EXISTS idx_projektmitglieder_benutzer
    ON projektmitglieder(benutzer_id, status);
CREATE TABLE IF NOT EXISTS projektfortschritt (
    projekt_id TEXT PRIMARY KEY NOT NULL,
    framework_schritt INTEGER NOT NULL CHECK (framework_schritt BETWEEN 1 AND 10),
    fachlicher_unterschritt TEXT NOT NULL DEFAULT '',
    fortschritt_zaehler INTEGER NOT NULL CHECK (fortschritt_zaehler >= 0),
    fortschritt_nenner INTEGER NOT NULL CHECK (fortschritt_nenner > 0),
    phase INTEGER NOT NULL CHECK (phase BETWEEN 1 AND 3),
    status TEXT NOT NULL DEFAULT 'in_bearbeitung'
        CHECK (status IN ('in_bearbeitung', 'abgeschlossen', 'blockiert')),
    gespeichert_am_utc TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
    FOREIGN KEY (projekt_id) REFERENCES projekte(projekt_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS archivmetadaten (
    archiv_id TEXT PRIMARY KEY NOT NULL,
    projekt_id TEXT,
    gruppen_id TEXT,
    archivtyp TEXT NOT NULL
        CHECK (archivtyp IN ('projekt_export', 'projekt_import', 'kurs_export', 'kurs_import')),
    archivversion INTEGER NOT NULL CHECK (archivversion > 0),
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    groesse_bytes INTEGER NOT NULL CHECK (groesse_bytes >= 0),
    erstellt_von_benutzer_id TEXT,
    erstellt_am_utc TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('erfolgreich', 'abgelehnt', 'fehlgeschlagen')),
    details_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (projekt_id) REFERENCES projekte(projekt_id) ON DELETE SET NULL,
    FOREIGN KEY (gruppen_id) REFERENCES kursgruppen(gruppen_id) ON DELETE SET NULL,
    FOREIGN KEY (erstellt_von_benutzer_id) REFERENCES benutzer(benutzer_id)
);
CREATE TABLE IF NOT EXISTS bereinigungsprotokoll (
    eintrag_id TEXT PRIMARY KEY NOT NULL,
    projekt_id TEXT,
    gruppen_id TEXT,
    aktion TEXT NOT NULL,
    ergebnis TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    erstellt_am_utc TEXT NOT NULL
);
"""

AKTIVE_PROJEKTLINEAGE_SCHEMA_VERSION_12 = """
CREATE TABLE IF NOT EXISTS aktive_projektlineage (
    projekt_id TEXT PRIMARY KEY NOT NULL,
    endpunkt TEXT NOT NULL,
    referenzen_json TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
    aktualisiert_am_utc TEXT NOT NULL,
    FOREIGN KEY (projekt_id) REFERENCES projekte(projekt_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS datenprofil_generationen (
    profil_id TEXT PRIMARY KEY NOT NULL,
    projekt_id TEXT NOT NULL,
    import_id TEXT NOT NULL,
    vorgaenger_profil_id TEXT,
    fachversion INTEGER NOT NULL CHECK (fachversion > 1),
    relativer_profil_pfad TEXT NOT NULL,
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    erstellt_am_utc TEXT NOT NULL,
    UNIQUE (import_id, fachversion),
    FOREIGN KEY (projekt_id) REFERENCES projekte(projekt_id) ON DELETE CASCADE,
    FOREIGN KEY (import_id) REFERENCES importvorgaenge(import_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_datenprofil_generationen_import
    ON datenprofil_generationen(import_id, fachversion)
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
    """Initialisiert oder migriert die gemeinsame Datenbank atomar auf Version 12."""
    verbindung.execute("PRAGMA foreign_keys = ON")
    verbindung.execute("PRAGMA busy_timeout = 5000")
    verbindung.execute("PRAGMA journal_mode = WAL")
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
        for anweisung in ERGEBNISAGGREGATION_SCHEMA_VERSION_8.split(";"):
            if anweisung.strip():
                verbindung.execute(anweisung)
        for anweisung in MODELLABLEITUNG_SCHEMA_VERSION_9.split(";"):
            if anweisung.strip():
                verbindung.execute(anweisung)
        for anweisung in MODELLVALIDIERUNG_SCHEMA_VERSION_10.split(";"):
            if anweisung.strip():
                verbindung.execute(anweisung)
        for anweisung in PORTABILITAET_UND_MANDANTEN_SCHEMA_VERSION_11.split(";"):
            if anweisung.strip():
                verbindung.execute(anweisung)
        for anweisung in AKTIVE_PROJEKTLINEAGE_SCHEMA_VERSION_12.split(";"):
            if anweisung.strip():
                verbindung.execute(anweisung)
        projekt_tabelle = verbindung.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'projekte'"
        ).fetchone()
        if projekt_tabelle is not None:
            zeitpunkt = "1970-01-01T00:00:00+00:00"
            verbindung.execute(
                """
                INSERT OR IGNORE INTO projektzugehoerigkeiten (
                    projekt_id, zugriffsart, gruppen_id, gast_geheimnis_sha256,
                    gast_ablauf_am_utc, zuletzt_aktiv_am_utc, revision, erstellt_am_utc
                )
                SELECT projekt_id, 'legacy_unassigned', NULL, NULL, NULL,
                       COALESCE(geaendert_am_utc, ?), 1, COALESCE(erstellt_am_utc, ?)
                FROM projekte
                """,
                (zeitpunkt, zeitpunkt),
            )
        if version < SCHEMAVERSION:
            verbindung.execute(f"PRAGMA user_version = {SCHEMAVERSION}")
    except Exception:
        verbindung.rollback()
        raise
    else:
        verbindung.commit()
