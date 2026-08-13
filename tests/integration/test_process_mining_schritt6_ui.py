"""Streamlit-Integrationstests des auf Algorithmus 6 begrenzten Schritt 6."""

from streamlit.testing.v1 import AppTest

APP = r"""
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pandas as pd
import streamlit as st

from framework_mvp.application.process_mining.pm4py_adapter import GraphvizStatus
from framework_mvp.application.process_mining_service import ProcessMiningVorschau
from framework_mvp.domain.models import (
    DfgErgebnis, DfgKante, DiscoveryErgebnisse, Freigabestatus, Mappingzustand,
    MinerVariante, ModellStatistik, Qualitaetsfreigabe, Prozessnotation,
)
from framework_mvp.ui.pages.process_mining import zeige_process_mining_seite

P = UUID("11111111-1111-1111-1111-111111111111")
F = UUID("22222222-2222-2222-2222-222222222222")
E = UUID("33333333-3333-3333-3333-333333333333")
A = UUID("44444444-4444-4444-4444-444444444444")
JETZT = datetime(2025, 1, 1, tzinfo=UTC)
DATEN = pd.DataFrame({
    "case_id": ["1", "1", "2", "2"],
    "activity": ["A", "B", "A", "C"],
    "timestamp": pd.to_datetime(
        ["2025-01-01", "2025-01-02", "2025-01-01", "2025-01-03"], utc=True
    ),
})
FREIGABE = Qualitaetsfreigabe(
    F, P, E, "a" * 64, UUID(int=5), "b" * 64, UUID(int=6), None, "",
    Mappingzustand.NICHT_VORHANDEN, (), "c" * 64, "d" * 64, "e" * 64,
    "q.release.json", "f" * 64, Freigabestatus.FREIGEGEBEN, JETZT,
)

class Projekte:
    def projekt_laden(self, projekt_id):
        return SimpleNamespace(projekt_id=projekt_id, bezeichnung="Discovery-Projekt")

class Qualitaet:
    def freigabe_laden(self, freigabe_id):
        if freigabe_id != F: raise RuntimeError("fremde Freigabe")
        return FREIGABE, DATEN.copy(deep=True)

class ProcessMining:
    def grundlage_laden(self, freigabe_id, projekt_id=None):
        assert freigabe_id == F and projekt_id == P
        return FREIGABE, DATEN.copy(deep=True)
    def analysen_fuer_freigabe(self, projekt_id, freigabe_id): return []
    def graphviz_status(self): return GraphvizStatus(False, "", "", False)
    def vorschau(self, freigabe_id, konfiguration):
        st.session_state["test_vorschau_aufrufe"] = (
            st.session_state.get("test_vorschau_aufrufe", 0) + 1
        )
        dfg = DfgErgebnis(
            ("A", "B", "C"), (("A", 2), ("B", 1), ("C", 1)),
            (DfgKante("A", "B", 1, 0.5), DfgKante("A", "C", 1, 0.5)),
            (("A", 2),), (("B", 1), ("C", 1)),
        )
        discovery = DiscoveryErgebnisse(
            konfiguration.prozessnotation, konfiguration.miner_variante,
            ModellStatistik(3, 1, 4, 5), b"<?xml version='1.0'?><model/>",
            b"<?xml version='1.0'?><ptml/>", None, None, (),
        )
        return ProcessMiningVorschau(
            F, P, E, "a" * 64, konfiguration, dfg, discovery, None, "2.7.23.3", "x" * 64
        )
    def speichern(self, analyse_id, freigabe_id, konfiguration, vorschau):
        return SimpleNamespace(
            analyse_id=A, projekt_id=P, qualitaetspruefung_id=F, event_log_id=E,
            relativer_ergebnis_pfad="analysis.discovery.json",
        )
    def uebergabe_laden(self, analyse_id, projekt_id, freigabe_id):
        analyse = SimpleNamespace(
            analyse_id=A, projekt_id=P, qualitaetspruefung_id=F, event_log_id=E,
            relativer_ergebnis_pfad="analysis.discovery.json",
        )
        ad = {
            "miner_variante": "inductive_miner_infrequent",
            "schwellwert_k": 0.2,
            "prozessnotation": "bpmn",
            "prozessmodell_p": {
                "relativer_pfad": "analysis.model.bpmn", "mime_type": "application/xml"
            },
            "prozessmodell_bytes": b"<?xml version='1.0'?><model/>",
            "dfg_daten": {
                "kanten": [
                    {"quelle": "A", "ziel": "B", "haeufigkeit": 1, "anteil": 0.5},
                    {"quelle": "A", "ziel": "C", "haeufigkeit": 1, "anteil": 0.5},
                ]
            },
            "svg_texte": {},
        }
        return analyse, ad, ad["prozessmodell_bytes"]

zeige_process_mining_seite(Projekte(), Qualitaet(), ProcessMining())
"""


def _app(*, aktive_freigabe: bool = True) -> AppTest:
    app = AppTest.from_string(APP)
    app.session_state["aktuelles_projekt_id"] = "11111111-1111-1111-1111-111111111111"
    if aktive_freigabe:
        app.session_state["aktuelle_freigabe_id"] = "22222222-2222-2222-2222-222222222222"
    return app.run()


def _button(app: AppTest, label: str):  # type: ignore[no-untyped-def]
    return next(wert for wert in app.button if wert.label == label)


def _vorschau_aufrufe(app: AppTest) -> int:
    return (
        int(app.session_state["test_vorschau_aufrufe"])
        if "test_vorschau_aufrufe" in app.session_state
        else 0
    )


def test_ohne_aktive_freigabe_ist_process_mining_blockiert_und_schritt_fuenf_erreichbar() -> None:
    app = _app(aktive_freigabe=False)
    assert not app.exception
    assert any("Schritt 5" in wert.value for wert in app.warning)
    _button(app, "Zu Schritt 5: Datenqualität prüfen").click().run()
    assert app.session_state["naechster_framework_bereich"] == "5 Datenqualität prüfen"


def test_aktives_e_stern_wird_ohne_lokale_auswahl_kompakt_angezeigt() -> None:
    app = _app()
    assert not app.exception
    assert not any(
        wert.label in {"Projekt", "Freigegebener Event Log E*", "Qualitätslauf"}
        for wert in app.selectbox
    )
    texte = "\n".join(wert.value for wert in app.markdown)
    assert "Discovery-Projekt" in texte
    assert "22222222-2222-2222-2222-222222222222" not in texte
    assert "33333333-3333-3333-3333-333333333333" not in texte
    assert "aaaaaaaa" not in texte
    assert any(wert.label == "Technische Details" for wert in app.expander)


def test_regulaerer_ablauf_bietet_nur_k_und_notation_und_uebergibt_p_und_a_d() -> None:
    app = _app()
    assert _vorschau_aufrufe(app) == 0
    _button(app, "Weiter").click().run()
    assert _vorschau_aufrufe(app) == 0
    assert {wert.label for wert in app.slider} == {"Schwellwert k"}
    assert {wert.label for wert in app.radio} == {"Prozessnotation für P"}
    alle_labels = {
        wert.label
        for wert in (*app.slider, *app.radio, *app.selectbox, *app.multiselect, *app.number_input)
    }
    assert (
        not {
            "Discovery-Verfahren",
            "Variantenfilter",
            "Aktivitäten der Analysesicht",
            "Minimale dargestellte Kantenhäufigkeit",
            "Dependency Threshold",
        }
        & alle_labels
    )
    app.slider[0].set_value(0.2)
    app.radio[0].set_value("BPMN")
    _button(app, "Modell berechnen").click().run()
    assert app.session_state["test_vorschau_aufrufe"] == 1
    assert any("Inductive Miner – infrequent" in wert.value for wert in app.warning)
    app.run()
    assert app.session_state["test_vorschau_aufrufe"] == 1
    _button(app, "Weiter").click().run()
    _button(app, "P und A_D speichern und zu Schritt 7").click().run()
    assert app.session_state["aktuelle_analyse_id"] == "44444444-4444-4444-4444-444444444444"
    assert app.session_state["aktuelles_prozessmodell_id"] == (
        "44444444-4444-4444-4444-444444444444"
    )
    assert app.session_state["aktuelle_discovery_ergebnisse_id"] == (
        "44444444-4444-4444-4444-444444444444"
    )
    assert app.session_state["naechster_framework_bereich"] == "7 Ergebnisse aggregieren"


def test_zurueck_aus_dem_letzten_abschnitt_bewahrt_vorschau_und_konfiguration() -> None:
    app = _app()
    _button(app, "Weiter").click().run()
    app.slider[0].set_value(0.2)
    app.radio[0].set_value("BPMN")
    _button(app, "Modell berechnen").click().run()
    _button(app, "Weiter").click().run()
    zustand = app.session_state["process_mining_zustaende"][
        "11111111-1111-1111-1111-111111111111"
    ]
    signatur = zustand["vorschau_signatur"]
    analyse_id = zustand["analyse_id"]

    [wert for wert in app.button if wert.label == "Zurück"][-1].click().run()

    zustand = app.session_state["process_mining_zustaende"][
        "11111111-1111-1111-1111-111111111111"
    ]
    assert zustand["schritt"] == 2
    assert zustand["vorschau_signatur"] == signatur
    assert zustand["analyse_id"] == analyse_id
    assert app.slider[0].value == 0.2
    notation = app.radio[0].value
    assert notation is not None
    assert notation.value == "bpmn"
    assert app.session_state["test_vorschau_aufrufe"] == 1
