"""Streamlit-Integrationstests des fachlichen Schritt-4-Ablaufs."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from streamlit.testing.v1 import AppTest

from framework_mvp.domain.models import MappingModus

APP = r"""
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pandas as pd
import streamlit as st

from framework_mvp.application.mapping import validiere_mapping
from framework_mvp.domain.models import (
    Mappingeintrag, Mappingstatus, Mappingtabelle, Zwischendatensatz,
)
from framework_mvp.ui.pages.event_log import zeige_event_log_seite

P = UUID("11111111-1111-1111-1111-111111111111")
T = UUID("22222222-2222-2222-2222-222222222222")
DATENSATZ = Zwischendatensatz(
    T, P, UUID("33333333-3333-3333-3333-333333333333"),
    (UUID("44444444-4444-4444-4444-444444444444"),),
    "T.csv.gz", "T.schema.json", "T.transformation.json", "a" * 64,
    2, 6, datetime.now(UTC),
)
DATEN = pd.DataFrame({
    "auftrag": ["A", "A"],
    "aktion": ["Start", "Ende"],
    "zeit": ["2025-01-02", "2025-01-01"],
    "startzeit": ["2025-01-01", None],
    "endzeit": ["2025-01-02", "2025-01-03"],
    "ressource": ["R1", "R2"],
})
MAPPING = replace(
    Mappingtabelle.neu(P, T),
    mapping_id=UUID("55555555-5555-5555-5555-555555555555"),
).eintrag_hinzufuegen(
    Mappingeintrag.fuer_spalte("auftrag", "Produktionsauftrag")
).bestaetigen()

class Projekte:
    def projekt_laden(self, projekt_id):
        return SimpleNamespace(projekt_id=projekt_id, bezeichnung="E-Projekt")

class Transformationen:
    def datensaetze_fuer_projekt(self, projekt_id): return [DATENSATZ]
    def zwischendatensatz_laden(self, datensatz_id): return DATENSATZ, DATEN.copy(deep=True)
    def plan_laden(self, plan_id): return None
    def importe_fuer_projekt(self, projekt_id): return []

class Mappingtabellen:
    def fuer_datensatz(self, projekt_id, datensatz_id):
        return None if st.session_state.get("ohne_m") else MAPPING
    def laden(self, mapping_id):
        return MAPPING if mapping_id == MAPPING.mapping_id else None

class Konfigurationen:
    def fuer_projekt(self, projekt_id):
        wert = st.session_state.get("test_konfiguration")
        return [wert] if wert is not None else []
    def validieren(self, mapping, daten):
        ergebnis = validiere_mapping(daten, mapping)
        mapping = replace(
            mapping, validierung=ergebnis.validierung, status=Mappingstatus.VALIDIERT
        )
        return mapping, ergebnis
    def speichern(self, mapping):
        st.session_state["test_konfiguration"] = mapping
        return "konfiguration.json"
    def laden(self, mapping_id):
        return st.session_state.get("test_konfiguration")

class EventLogs:
    def speichern(self, event_log_id, konfigurations_id):
        st.session_state["test_event_log_id"] = event_log_id
        return SimpleNamespace(
            relativer_csv_pfad="E.csv.gz",
            relativer_schema_pfad="E.schema.json",
            relativer_lineage_pfad="E.lineage.json",
        )

zeige_event_log_seite(
    Projekte(), Konfigurationen(), Mappingtabellen(), Transformationen(), EventLogs()
)
"""


def _app(*, ohne_m: bool = False) -> AppTest:
    app = AppTest.from_string(APP)
    app.session_state["aktuelles_projekt_id"] = "11111111-1111-1111-1111-111111111111"
    app.session_state["aktueller_zwischendatensatz_id"] = "22222222-2222-2222-2222-222222222222"
    app.session_state["ohne_m"] = ohne_m
    return app.run()


def _button(app: AppTest, label: str):  # type: ignore[no-untyped-def]
    return next(wert for wert in app.button if wert.label == label)


def test_schritt_vier_verwendet_zentralen_kontext_und_zeigt_t_und_m() -> None:
    app = _app()
    assert not app.exception
    assert not any(wert.label == "Projekt" for wert in app.selectbox)
    assert not any(wert.label == "Zwischendatensatz" for wert in app.selectbox)
    assert any("Aktuelles Projekt: E-Projekt" in wert.value for wert in app.markdown)
    assert any("Semantische Sicht" in wert.value for wert in app.markdown)
    assert any("Unveränderte Vorschau" in wert.value for wert in app.markdown)
    assert any(wert.label == "Wie sind die Ereignisse in T dargestellt?" for wert in app.radio)


def test_schritt_vier_ist_auch_ohne_m_zulaessig() -> None:
    app = _app(ohne_m=True)
    assert not app.exception
    assert any("kein M vorhanden" in wert.value for wert in app.info)
    assert any(wert.label == "Weiter" and not wert.disabled for wert in app.button)


def test_regulaere_oberflaeche_hat_genau_eine_fallspalte_und_begrenzte_aktivitaet() -> None:
    app = _app()
    _button(app, "Weiter").click().run()
    assert {wert.label for wert in app.selectbox} >= {
        "Fallidentifikation",
        "Aktivitätsspalte",
        "Ereigniszeitstempel",
    }
    assert not any("Fall-ID-Bestandteil" in wert.label for wert in app.selectbox)
    next(w for w in app.radio if w.label == "Aktivitätsbeschreibung").set_value(
        "Aus mehreren Attributen zusammensetzen"
    ).run()
    next(w for w in app.selectbox if w.label == "1. Bestandteil").select_index(0).run()
    next(w for w in app.selectbox if w.label == "2. Bestandteil").select_index(0).run()
    labels = {wert.label for wert in (*app.text_input, *app.selectbox, *app.number_input)}
    assert "Verknüpfungselement (optional)" in labels
    assert "1. Bestandteil" in labels and "2. Bestandteil" in labels
    assert not {"Präfix (optional)", "Suffix (optional)", "Verhalten bei leeren Werten"} & labels


def test_breite_oberflaeche_erfasst_beschreibung_je_zeitstempelspalte() -> None:
    app = _app()
    next(w for w in app.radio if w.label == "Wie sind die Ereignisse in T dargestellt?").set_value(
        "breiter_zeitstempeldatensatz"
    ).run()
    _button(app, "Weiter").click().run()
    next(w for w in app.multiselect if w.label == "Relevante Zeitstempelspalten").set_value(
        ["startzeit", "endzeit"]
    ).run()
    labels = {wert.label for wert in app.text_input}
    assert any("startzeit" in wert for wert in labels)
    assert any("endzeit" in wert for wert in labels)


def test_ereignisorientierter_ablauf_speichert_e_und_setzt_aktiven_kontext() -> None:
    app = AppTest.from_string(APP)
    projekt_id = UUID("11111111-1111-1111-1111-111111111111")
    datensatz_id = UUID("22222222-2222-2222-2222-222222222222")
    app.session_state["aktuelles_projekt_id"] = str(projekt_id)
    app.session_state["aktueller_zwischendatensatz_id"] = str(datensatz_id)
    app.session_state["event_log_zustaende"] = {
        str(projekt_id): {
            "schritt": 4,
            "datensatz_id": str(datensatz_id),
            "konfigurations_id": uuid4(),
            "erstellt_am": datetime.now(UTC),
            "mapping_modus": MappingModus.EREIGNISORIENTIERT,
            "fall_id": "auftrag",
            "aktivitaetsquellen": ("aktion",),
            "zeitstempelspalte": "zeit",
            "zeitstempelzuordnungen": (),
            "zusaetzliche_attribute": ("ressource",),
        }
    }
    app = app.run()
    assert not app.exception
    assert any("Fallbezogener Event Log (E)" in wert.value for wert in app.markdown)
    _button(app, "Weiter").click().run()
    _button(app, "Fallbezogenen Event Log speichern").click().run()
    assert not app.exception
    assert app.session_state["aktuelles_event_log_id"] == str(
        app.session_state["test_event_log_id"]
    )
    assert any("wurde gespeichert" in wert.value for wert in app.success)
