"""AppTest-Integrationstests der ETL-Hauptseite."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from framework_mvp.bootstrap import (
    DATENBANKPFAD_UMGEBUNGSVARIABLE,
    erstelle_datenquelle_service,
    erstelle_projekt_service,
)
from framework_mvp.domain.models import Projekt, Systemtyp, Untersuchungsauftrag
from framework_mvp.workspace import WORKSPACE_UMGEBUNGSVARIABLE

ANWENDUNGSPFAD = Path(__file__).parents[2] / "streamlit_app.py"

TRANSFORMATIONS_APP = r"""
from uuid import UUID

import pandas as pd

from framework_mvp.domain.models import Transformationsplan
from framework_mvp.ui.components.transformation import zeige_transformationseditor

plan = Transformationsplan.neu(
    UUID("11111111-1111-1111-1111-111111111111"),
    (UUID("22222222-2222-2222-2222-222222222222"),),
)
zeige_transformationseditor(
    object(),
    plan,
    pd.DataFrame({"Text": ["RS TX (abc)", "ohne Treffer"], "Wert": [1, 2]}),
    {"spaltenprofile": []},
)
"""

ETL_NAVIGATION_APP = r"""
import streamlit as st

from framework_mvp.ui.pages.etl import _navigation

zustand = st.session_state.setdefault(
    "zustand",
    {
        "schritt": 5,
        "transformationsplan": "plan-bleibt-erhalten",
        "zwischendatensatz_id": "datensatz-bleibt-erhalten",
    },
)
_navigation(zustand)
"""


def _projekt_anlegen() -> Projekt:
    return erstelle_projekt_service().projekt_anlegen(
        bezeichnung="ETL-Projekt",
        untersuchungsauftrag=Untersuchungsauftrag("", "", Systemtyp.KOMBINIERT, ""),
    )


def _etl_starten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv(DATENBANKPFAD_UMGEBUNGSVARIABLE, str(tmp_path / "app.sqlite"))
    monkeypatch.setenv(WORKSPACE_UMGEBUNGSVARIABLE, str(tmp_path / "workspace"))
    projekt = _projekt_anlegen()
    anwendung = AppTest.from_file(ANWENDUNGSPFAD).run()
    anwendung.session_state["aktuelles_projekt_id"] = str(projekt.projekt_id)
    anwendung.radio[0].set_value("2 ETL durchführen").run()
    return anwendung


def _neue_datenquelle_waehlen(anwendung: AppTest) -> None:
    auswahl = next(e for e in anwendung.selectbox if e.label == "Datenquelle")
    assert auswahl.value is None
    assert auswahl.proto.placeholder == "Choose an option"
    auswahl.set_value("Neue Datenquelle anlegen").run()
    next(e for e in anwendung.selectbox if e.label == "Quellsystemtyp").set_value("ERP-System")


def test_etl_seite_startet_und_markiert_schritt_zwei(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ETL-Seite, Projektkontext und alle fünf Abschnitte werden angezeigt."""
    anwendung = _etl_starten(tmp_path, monkeypatch)
    assert not anwendung.exception
    assert any(element.value == "Schritt 2: ETL durchführen" for element in anwendung.header)
    einleitung = "\n".join(element.value for element in anwendung.markdown)
    assert "bereitgestellten Datensätze (D)" in einleitung
    assert "Datenquellenkatalog (Q)" in einleitung
    assert "Datenprofil (R)" in einleitung
    assert "Zwischendatensatz (T)" in einleitung
    assert len(anwendung.get("progress")) == 1
    assert any("Phase 1 – Aufbereitung der Datenbasis" in wert.value for wert in anwendung.caption)
    assert any(
        "Unterschritt 1/5" in wert.value and "Datenquelle und Datei" in wert.value
        for wert in anwendung.markdown
    )
    assert not any(element.label == "Alle Schritte anzeigen" for element in anwendung.expander)
    assert not any(element.label == "Aktuelles Projekt" for element in anwendung.selectbox)
    assert any("Aktuelles Projekt: ETL-Projekt" in element.value for element in anwendung.markdown)


def test_datenquelle_kann_angelegt_und_erneut_geladen_werden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Der aktive Teilschritt speichert und öffnet einen Katalogeintrag."""
    anwendung = _etl_starten(tmp_path, monkeypatch)
    _neue_datenquelle_waehlen(anwendung)
    bezeichnung = next(e for e in anwendung.text_input if e.label == "Bezeichnung der Datenquelle")
    bezeichnung.set_value("ERP Tagesexport")
    speichern = next(e for e in anwendung.button if e.label == "Datenquelle speichern")
    speichern.click().run()
    assert not anwendung.exception
    assert any("erfolgreich gespeichert" in e.value for e in anwendung.success)
    projekt = erstelle_projekt_service().projekte_auflisten()[0]
    datenquellen = erstelle_datenquelle_service().datenquellen_fuer_projekt(projekt.projekt_id)
    assert [quelle.bezeichnung for quelle in datenquellen] == ["ERP Tagesexport"]
    assert (tmp_path / "workspace" / "projects" / str(projekt.projekt_id) / "raw").is_dir()

    auswahl = next(e for e in anwendung.selectbox if e.label == "Datenquelle")
    assert auswahl.value == anwendung.session_state["aktuelle_datenquellen_id"]
    assert (
        next(e for e in anwendung.text_input if e.label == "Bezeichnung der Datenquelle").value
        == "ERP Tagesexport"
    )


def test_upload_ist_im_ersten_abschnitt_integriert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Datenquelle und Upload werden ohne technischen Zwischenschritt zusammen angezeigt."""
    anwendung = _etl_starten(tmp_path, monkeypatch)
    _neue_datenquelle_waehlen(anwendung)
    next(e for e in anwendung.text_input if e.label == "Bezeichnung der Datenquelle").set_value(
        "CSV-Quelle"
    )
    next(e for e in anwendung.button if e.label == "Datenquelle speichern").click().run()
    assert not anwendung.exception
    assert anwendung.get("file_uploader")


def test_projektwechsel_fuehrt_zu_schritt_eins_und_bewahrt_projekt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Der Projektwechsel öffnet die zentrale Auswahl ohne lokalen Dropdown."""
    anwendung = _etl_starten(tmp_path, monkeypatch)
    projekt_id = anwendung.session_state["aktuelles_projekt_id"]
    next(e for e in anwendung.button if e.label == "Projekt wechseln").click().run()
    assert not anwendung.exception
    assert anwendung.radio[0].value == "Schritt 1: Projektrahmen definieren"
    assert anwendung.session_state["aktuelles_projekt_id"] == projekt_id


def test_transformation_startet_ohne_vorbelegten_typ() -> None:
    anwendung = AppTest.from_string(TRANSFORMATIONS_APP).run()
    auswahl = next(e for e in anwendung.selectbox if e.label == "Transformationsart")

    assert not anwendung.exception
    assert auswahl.value is None
    assert auswahl.proto.placeholder == "Choose an option"
    assert next(
        e for e in anwendung.button if e.label == "Transformation zum Plan hinzufügen"
    ).disabled


def test_zeilen_loeschen_formular_zeigt_bedingung_und_vorschau() -> None:
    anwendung = AppTest.from_string(TRANSFORMATIONS_APP).run()
    next(e for e in anwendung.selectbox if e.label == "Transformationsart").set_value(
        "Zeilen anhand einer Bedingung löschen"
    ).run()
    next(e for e in anwendung.selectbox if e.label == "Spalte für Löschbedingung").set_value(
        "Wert"
    ).run()
    next(e for e in anwendung.selectbox if e.label == "Operator der Löschbedingung").set_value(
        "größer"
    ).run()
    next(e for e in anwendung.text_input if e.label == "Vergleichswert").set_value("1").run()

    assert not anwendung.exception
    assert any("1 von 2 Zeilen werden gelöscht" in wert.value for wert in anwendung.info)
    assert not next(
        e for e in anwendung.button if e.label == "Transformation zum Plan hinzufügen"
    ).disabled


def test_textbereinigungsformular_zeigt_allgemeine_begrenzer_und_sicheren_standard() -> None:
    anwendung = AppTest.from_string(TRANSFORMATIONS_APP).run()
    next(e for e in anwendung.selectbox if e.label == "Transformationsart").set_value(
        "Text bereinigen oder extrahieren"
    ).run()
    next(e for e in anwendung.selectbox if e.label == "Textspalte").set_value("Text").run()
    next(e for e in anwendung.selectbox if e.label == "Textoperation").set_value(
        "Zwischen Begrenzern extrahieren"
    ).run()
    next(e for e in anwendung.text_input if e.label == "Startbegrenzer").set_value("(")
    next(e for e in anwendung.text_input if e.label == "Endbegrenzer").set_value(")").run()

    assert not anwendung.exception
    assert any("Werte ohne Treffer bleiben unverändert" in wert.value for wert in anwendung.caption)
    vorschau = next(
        wert
        for wert in anwendung.dataframe
        if list(wert.value.columns) == ["Originalwert", "Vorschau", "Status"]
    ).value
    assert vorschau.to_dict(orient="records") == [
        {
            "Originalwert": "RS TX (abc)",
            "Vorschau": "abc",
            "Status": "Transformiert",
        },
        {
            "Originalwert": "ohne Treffer",
            "Vorschau": "ohne Treffer",
            "Status": "Unverändert (kein Treffer)",
        },
    ]
    assert not next(
        e for e in anwendung.button if e.label == "Transformation zum Plan hinzufügen"
    ).disabled


def test_zurueck_aus_dem_letzten_etl_abschnitt_bewahrt_den_zustand() -> None:
    anwendung = AppTest.from_string(ETL_NAVIGATION_APP).run()
    next(wert for wert in anwendung.button if wert.label == "Zurück").click().run()

    zustand = anwendung.session_state["zustand"]
    assert zustand["schritt"] == 4
    assert zustand["transformationsplan"] == "plan-bleibt-erhalten"
    assert zustand["zwischendatensatz_id"] == "datensatz-bleibt-erhalten"
