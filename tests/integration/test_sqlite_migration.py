"""Integrationstests der transaktionalen SQLite-Migration."""

import json
import sqlite3
from pathlib import Path
from uuid import UUID

import pytest

from framework_mvp.domain.models import BetrachtungszeitraumModus
from framework_mvp.infrastructure.exceptions import NichtUnterstuetzteSchemaversion
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    SQLiteProjektRepository,
)

_SCHEMA_V1 = """
CREATE TABLE projekte (
 projekt_id TEXT PRIMARY KEY, bezeichnung TEXT NOT NULL,
 beteiligte_personen_json TEXT NOT NULL, status TEXT NOT NULL,
 erstellt_am_utc TEXT NOT NULL, geaendert_am_utc TEXT NOT NULL,
 problemstellung TEXT NOT NULL, zielsetzung TEXT NOT NULL, systemtyp TEXT NOT NULL,
 systemgrenze TEXT NOT NULL, input_beschreibung TEXT NOT NULL,
 transformation_beschreibung TEXT NOT NULL, output_beschreibung TEXT NOT NULL,
 detaillierungsgrad TEXT NOT NULL, leistungskennzahlen_json TEXT NOT NULL,
 rahmenbedingungen TEXT NOT NULL, betrachtungszeitraum_beginn TEXT,
 betrachtungszeitraum_ende TEXT, anmerkungen TEXT NOT NULL
)
"""


def _version_1_anlegen(
    pfad: Path,
    personen_json: str = '["Ada Lovelace"]',
    mit_datum: bool = True,
    status: str = "entwurf",
) -> str:
    projekt_id = "12345678-1234-5678-1234-567812345678"
    with sqlite3.connect(pfad) as verbindung:
        verbindung.execute(_SCHEMA_V1)
        verbindung.execute(
            "INSERT INTO projekte VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                projekt_id,
                "Altprojekt",
                personen_json,
                status,
                "2026-01-01T10:00:00+00:00",
                "2026-01-02T10:00:00+00:00",
                "Altes Problem",
                "Altes Ziel",
                "produktion",
                "Alte Grenze",
                "Alter Input",
                "Alte Transformation",
                "Alter Output",
                "Alt-Detail",
                json.dumps(["Alt-KPI"]),
                "Alter Rahmen",
                "2026-01-01" if mit_datum else None,
                "2026-01-31" if mit_datum else None,
                "Alte Anmerkung",
            ),
        )
        verbindung.execute("PRAGMA user_version = 1")
    return projekt_id


@pytest.mark.parametrize(
    ("mit_datum", "modus"),
    [(True, BetrachtungszeitraumModus.MANUELL), (False, BetrachtungszeitraumModus.OFFEN)],
)
def test_version_1_wird_vollstaendig_migriert(
    tmp_path: Path, mit_datum: bool, modus: BetrachtungszeitraumModus
) -> None:
    """Fachwerte, Personen, Altziel, Legacy-KPI und Zeitraum bleiben erhalten."""
    pfad = tmp_path / "migration.sqlite"
    projekt_id = _version_1_anlegen(pfad, mit_datum=mit_datum)
    projekt = SQLiteProjektRepository(pfad).laden(UUID(projekt_id))
    assert projekt is not None
    assert projekt.bezeichnung == "Altprojekt"
    assert projekt.beteiligte_personen[0].nachname == "Ada Lovelace"
    assert projekt.beteiligte_personen[0].rolle == "Sonstige"
    assert projekt.untersuchungsauftrag.individuelles_ziel == "Altes Ziel"
    assert projekt.untersuchungsauftrag.untersuchungszweck == ""
    assert projekt.untersuchungsauftrag.legacy_leistungskennzahlen == ("Alt-KPI",)
    assert projekt.untersuchungsauftrag.betrachtungszeitraum.modus is modus


def test_aktiver_migrationsbestand_behaelt_seinen_status(tmp_path: Path) -> None:
    """Ein alter aktiver Status bleibt trotz des neuen leeren Zwecks lesbar."""
    pfad = tmp_path / "aktiv.sqlite"
    projekt_id = _version_1_anlegen(pfad, status="aktiv")
    projekt = SQLiteProjektRepository(pfad).laden(UUID(projekt_id))
    assert projekt is not None
    assert projekt.status.value == "aktiv"
    assert projekt.untersuchungsauftrag.migrationsbestand


def test_fehlgeschlagene_migration_wird_zurueckgerollt(tmp_path: Path) -> None:
    """Ungültiges JSON lässt Version und alte Tabelle unverändert."""
    pfad = tmp_path / "defekt.sqlite"
    _version_1_anlegen(pfad, personen_json="kein-json")
    with pytest.raises(json.JSONDecodeError):
        SQLiteProjektRepository(pfad).auflisten()
    with sqlite3.connect(pfad) as verbindung:
        assert verbindung.execute("PRAGMA user_version").fetchone()[0] == 1
        assert verbindung.execute("SELECT COUNT(*) FROM projekte").fetchone()[0] == 1


def test_version_groesser_fuenf_wird_abgelehnt(tmp_path: Path) -> None:
    """Eine unbekannte neuere Schemaversion bleibt unangetastet."""
    pfad = tmp_path / "neu.sqlite"
    with sqlite3.connect(pfad) as verbindung:
        verbindung.execute("PRAGMA user_version = 6")
    with pytest.raises(NichtUnterstuetzteSchemaversion):
        SQLiteProjektRepository(pfad).auflisten()
