"""AppTests für die auf M begrenzte Bedienoberfläche von Schritt 3."""

from streamlit.testing.v1 import AppTest

SCHRITT_DREI_APP = r"""
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pandas as pd
import streamlit as st

from framework_mvp.domain.models import Zwischendatensatz
from framework_mvp.ui.pages.semantisches_mapping import zeige_semantisches_mapping

PROJEKT_ID = UUID("11111111-1111-1111-1111-111111111111")
DATENSATZ_ID = UUID("22222222-2222-2222-2222-222222222222")
PLAN_ID = UUID("33333333-3333-3333-3333-333333333333")
IMPORT_ID = UUID("44444444-4444-4444-4444-444444444444")
DATENSATZ = Zwischendatensatz(
    DATENSATZ_ID, PROJEKT_ID, PLAN_ID, (IMPORT_ID,),
    "T.csv.gz", "T.schema.json", "T.transformation.json", "a" * 64,
    2, 3, datetime.now(UTC),
)
DATEN = pd.DataFrame({
    "t_pdno": [1001, 1002],
    "transaction": ["ticst0201m000", "tisfc001"],
    "status": [1, 2],
})

class Projekte:
    def projekt_laden(self, projekt_id):
        return SimpleNamespace(projekt_id=projekt_id, bezeichnung="M-Projekt")

class Transformationen:
    def datensaetze_fuer_projekt(self, projekt_id):
        return [DATENSATZ]
    def zwischendatensatz_laden(self, datensatz_id):
        return DATENSATZ, DATEN.copy(deep=True)
    def plan_laden(self, plan_id):
        return None
    def importe_fuer_projekt(self, projekt_id):
        return []

class Mappingtabellen:
    def fuer_datensatz(self, projekt_id, datensatz_id):
        return None
    def speichern(self, mapping):
        st.session_state["test_gespeichertes_m"] = mapping
        return f"projects/{mapping.projekt_id}/mapping_tables/{mapping.mapping_id}.json"

zeige_semantisches_mapping(Projekte(), Transformationen(), Mappingtabellen())
"""


def _aktive_anwendung() -> AppTest:
    app = AppTest.from_string(SCHRITT_DREI_APP)
    app.session_state["aktuelles_projekt_id"] = "11111111-1111-1111-1111-111111111111"
    app.session_state["aktueller_zwischendatensatz_id"] = "22222222-2222-2222-2222-222222222222"
    return app.run()


def _button(app: AppTest, label: str):  # type: ignore[no-untyped-def]
    return next(wert for wert in app.button if wert.label == label)


def test_schritt_drei_zeigt_nur_m_und_keine_event_log_rollen() -> None:
    app = _aktive_anwendung()
    assert not app.exception
    labels = {
        wert.label
        for wert in (
            *app.selectbox,
            *app.multiselect,
            *app.text_input,
            *app.radio,
        )
    }
    assert {
        "Ist eine Interpretation technischer Bezeichnungen erforderlich?",
        "Art der technischen Bezeichnung",
        "Technische Spaltenbezeichnung",
        "Fachliche Spaltenbezeichnung",
    } <= labels
    assert (
        not {
            "Fall-ID",
            "Aktivitätsspalte",
            "Ereigniszeitstempel",
            "Datenstruktur",
            "Ressource",
            "Lifecycle",
        }
        & labels
    )
    assert any("Unveränderte Vorschau" in wert.value for wert in app.markdown)
    assert any("Mappingtabelle (M)" in wert.value for wert in app.markdown)
    assert not any(wert.label == "Projekt" for wert in app.selectbox)
    assert not any(wert.label == "Zwischendatensatz" for wert in app.selectbox)


def test_spaltenzuordnung_kann_erfasst_bearbeitet_und_gespeichert_werden() -> None:
    app = _aktive_anwendung()
    next(wert for wert in app.text_input if wert.label == "Fachliche Spaltenbezeichnung").set_value(
        "Produktionsauftrag"
    )
    _button(app, "Spaltenzuordnung hinzufügen").click().run()
    mapping = app.session_state["mappingtabelle_zustaende"]["11111111-1111-1111-1111-111111111111"][
        "mappingtabelle"
    ]
    assert mapping.eintraege[0].fachliche_bezeichnung == "Produktionsauftrag"
    assert any(
        {"Art", "Technische Bezeichnung", "Fachliche Bezeichnung"} <= set(wert.value.columns)
        for wert in app.dataframe
    )
    _button(app, "Mappingtabelle M bestätigen und speichern").click().run()
    assert not app.exception
    assert any("wurde gespeichert" in wert.value for wert in app.success)
    gespeichert = app.session_state["test_gespeichertes_m"]
    assert gespeichert.eintraege[0].technische_bezeichnung == "t_pdno"
    assert gespeichert.eintraege[0].fachliche_bezeichnung == "Produktionsauftrag"
    assert "event_log_id" not in app.session_state


def test_wertzuordnung_verwendet_nur_vorhandene_werte_und_ihre_quellspalte() -> None:
    app = _aktive_anwendung()
    next(wert for wert in app.radio if wert.label == "Art der technischen Bezeichnung").set_value(
        "Technischer Wert"
    ).run()
    next(
        wert for wert in app.selectbox if wert.label == "Technische Quellspalte für Wert"
    ).set_value("transaction").run()
    next(wert for wert in app.selectbox if wert.label == "Technischer Wert").select_index(0)
    next(wert for wert in app.text_input if wert.label == "Fachliche Wertbezeichnung").set_value(
        "Produktionsauftrag abschließen"
    )
    _button(app, "Wertzuordnung hinzufügen").click().run()
    mapping = app.session_state["mappingtabelle_zustaende"]["11111111-1111-1111-1111-111111111111"][
        "mappingtabelle"
    ]
    assert mapping.eintraege[0].technische_quellspalte == "transaction"
    assert mapping.eintraege[0].technische_bezeichnung == "ticst0201m000"


def test_leeres_m_muss_ausdruecklich_gewaehlt_werden_und_wird_gespeichert() -> None:
    app = _aktive_anwendung()
    next(
        wert
        for wert in app.radio
        if wert.label == "Ist eine Interpretation technischer Bezeichnungen erforderlich?"
    ).set_value("Kein semantisches Mapping erforderlich").run()
    _button(app, "Mappingtabelle M bestätigen und speichern").click().run()
    assert not app.exception
    gespeichert = app.session_state["test_gespeichertes_m"]
    assert gespeichert.kein_mapping_erforderlich
    assert gespeichert.eintraege == ()
    assert any("T unverändert" in wert.value for wert in app.success)
