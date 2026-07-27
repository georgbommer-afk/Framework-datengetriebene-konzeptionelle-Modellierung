"""Regressionstest der vollständigen UI-Ausgabe von ETL-Schritt 9."""

import sqlite3
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from framework_mvp.bootstrap import DATENBANKPFAD_UMGEBUNGSVARIABLE
from framework_mvp.workspace import WORKSPACE_UMGEBUNGSVARIABLE

ANWENDUNG = """
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4
import pandas as pd
import streamlit as st
from framework_mvp.application.datenimport_service import DatenimportService
from framework_mvp.application.transformation import Transformationsergebnis
from framework_mvp.application.transformations_service import TransformationsService
from framework_mvp.domain.models import (
    Projekt,
    Systemtyp,
    Transformationsplan,
    Untersuchungsauftrag,
)
from framework_mvp.infrastructure.importartefakte import ImportartefaktSpeicher
from framework_mvp.infrastructure.persistence.sqlite_etl_repository import SQLiteETLRepository
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    SQLiteProjektRepository,
)
from framework_mvp.ui.pages.etl import _zwischendatensatz
from framework_mvp.workspace import WorkspaceKonfiguration
from framework_mvp.bootstrap import ermittle_datenbankpfad

if "regressionsplan" not in st.session_state:
    projekt = Projekt.neu(
        "Regression",
        Untersuchungsauftrag("", "", Systemtyp.KOMBINIERT, ""),
    )
    SQLiteProjektRepository(ermittle_datenbankpfad()).speichern(projekt)
    st.session_state.regressionsplan = Transformationsplan.neu(
        projekt.projekt_id, (uuid4(),)
    )
plan = st.session_state.regressionsplan
service = TransformationsService(
    SQLiteETLRepository(ermittle_datenbankpfad()),
    None,
    None,
    ImportartefaktSpeicher(WorkspaceKonfiguration.ermitteln()),
)
ergebnis = Transformationsergebnis(
    pd.DataFrame({"id": [1, 2], "wert": ["a", "b"]}),
    pd.DataFrame({"id": [1, 2], "wert": ["a", "b"]}),
    (),
    (),
)
service.vorschau = lambda aktueller_plan: ergebnis
profil = DatenimportService().profil_erstellen(ergebnis.daten).profil
service.ausgangsprofil_laden = lambda import_id: SimpleNamespace(
    profil_version=1,
    gesamtprofil=__import__("dataclasses").asdict(profil),
)
service.import_dataframe_laden = lambda import_id: ergebnis.daten
zustand = st.session_state.setdefault("schritt_neun", {"transformationsplan": plan})
zustand.setdefault(
    "bestaetigter_import",
    SimpleNamespace(
        import_id=plan.import_ids[0],
        datenquellen_id=uuid4(),
        originaldateiname="regression.csv",
        tabellenbezeichnung="Regression",
    ),
)
class DatenquelleService:
    def datenquelle_laden(self, datenquellen_id):
        return SimpleNamespace(bezeichnung="Regression")
_zwischendatensatz(service, DatenquelleService(), plan.projekt_id, zustand)
"""


def test_schritt_neun_zeigt_alle_artefaktpfade_ohne_attributfehler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Erzeugung und anschließendes Rendern verwenden das bestehende Domänenattribut."""
    datenbank = tmp_path / "framework.sqlite"
    workspace = tmp_path / "workspace"
    monkeypatch.setenv(DATENBANKPFAD_UMGEBUNGSVARIABLE, str(datenbank))
    monkeypatch.setenv(WORKSPACE_UMGEBUNGSVARIABLE, str(workspace))
    anwendung = AppTest.from_string(ANWENDUNG).run()
    next(
        wert
        for wert in anwendung.button
        if wert.label == "Zwischendatensatz erstellen und mit dem semantischen Mapping fortfahren"
    ).click().run()
    assert not anwendung.exception
    ausgabe = "\n".join(wert.value for wert in anwendung.markdown)
    assert ".csv.gz" in ausgabe
    assert ".schema.json" in ausgabe
    assert ".transformation.json" in ausgabe
    with sqlite3.connect(datenbank) as verbindung:
        zeile = verbindung.execute(
            "SELECT relativer_daten_pfad, relativer_schema_pfad, "
            "relativer_transformation_pfad FROM zwischendatensaetze"
        ).fetchone()
        assert verbindung.execute("SELECT COUNT(*) FROM zwischendatensaetze").fetchone()[0] == 1
    assert zeile is not None
    assert all((workspace / pfad).is_file() for pfad in zeile)
