"""Streamlit-Vertrag von Schritt 7 ohne lokale Auswahl vorgelagerter Artefakte."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = r"""
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pandas as pd
import streamlit as st

from framework_mvp.domain.models import (
    Freigabestatus, LogistischeZielgroesse, Mappingzustand, Projekt, Projektstatus,
    Qualitaetsfreigabe, Systemtyp, Untersuchungsauftrag,
)
from framework_mvp.ui.pages.ergebnisaggregation import zeige_ergebnisaggregation_seite

P = UUID("11111111-1111-1111-1111-111111111111")
F = UUID("22222222-2222-2222-2222-222222222222")
E = UUID("33333333-3333-3333-3333-333333333333")
A = UUID("44444444-4444-4444-4444-444444444444")
T = UUID("55555555-5555-5555-5555-555555555555")
AG = UUID("66666666-6666-6666-6666-666666666666")
JETZT = datetime(2026, 1, 1, tzinfo=UTC)
AUFTRAG = Untersuchungsauftrag(
    "Problem", "Leistung bewerten", Systemtyp.KOMBINIERT, "Werk",
    logistische_zielgroessen=(LogistischeZielgroesse.LIEFERFAEHIGKEIT,),
    ausgewaehlte_kpi_ids=("servicegrad",),
)
PROJEKT = Projekt(P, "Aggregation", (), Projektstatus.AKTIV, JETZT, JETZT, AUFTRAG)
FREIGABE = Qualitaetsfreigabe(
    F, P, E, "a" * 64, T, "b" * 64, UUID(int=6), None, "",
    Mappingzustand.NICHT_VORHANDEN, (), "c" * 64, "d" * 64, "e" * 64,
    "release.json", "f" * 64, Freigabestatus.FREIGEGEBEN, JETZT,
)
EVENTS = pd.DataFrame({
    "case_id": ["1", "1"], "activity": ["A", "B"],
    "timestamp": pd.to_datetime(["2026-01-01", "2026-01-02"], utc=True),
})
if st.session_state.get("test_ressourcen_vollstaendig"):
    EVENTS["resource"] = ["M1", "M2"]
TABELLE = pd.DataFrame({"position": ["P1", "P2"], "befriedigt": ["ja", "nein"]})
BASIS = SimpleNamespace(
    projekt=PROJEKT, freigabe=FREIGABE, event_log=EVENTS, zwischendaten=TABELLE,
    analyse=SimpleNamespace(analyse_id=A),
    discovery_ergebnisse={"prozessnotation": "petrinetz"},
    prozessmodell_sha256="1" * 64, discovery_ergebnisse_sha256="2" * 64,
    untersuchungsauftrag_sha256="3" * 64, datenprofil_sha256="4" * 64,
    eingabefingerabdruck="5" * 64,
    zwischendatensatz=SimpleNamespace(sha256="b" * 64),
    profilwerte={"00000000-0000-0000-0000-000000000001:wert:mittelwert": 2.0},
)

class Projekte:
    def projekt_laden(self, projekt_id): return PROJEKT if projekt_id == P else None

class Aggregation:
    def grundlage_laden(self, projekt_id, freigabe_id, analyse_id):
        assert (projekt_id, freigabe_id, analyse_id) == (P, F, A)
        return BASIS
    def konfigurationsfingerabdruck(self, **kwargs): return "6" * 64
    def vorschau(self, **kwargs):
        return SimpleNamespace(
            grundlage=BASIS, kpi_ergebnisse=(), conformance_ergebnis=None,
            zeitvergleich_ergebnis=None, warnungen=(), konfigurationsfingerabdruck="6" * 64,
        )
    def speichern(self, aggregations_id, vorschau, menschlich_bestaetigt):
        assert menschlich_bestaetigt
        return SimpleNamespace(aggregations_id=AG)
    def uebergabe_schritt8(self, aggregations_id, projekt_id, freigabe_id, analyse_id):
        assert (aggregations_id, projekt_id, freigabe_id, analyse_id) == (AG, P, F, A)
        st.session_state["test_uebergabe_schritt8"] = True
    def laden(self, aggregations_id):
        return SimpleNamespace(aggregations_id=AG), {}
    def a_g_download_laden(self, aggregations_id): return b"{}"

zeige_ergebnisaggregation_seite(Projekte(), Aggregation())
"""


def _app(*, aktiv: bool = True, ressourcen_vollstaendig: bool = False) -> AppTest:
    app = AppTest.from_string(APP, default_timeout=10)
    if aktiv:
        app.session_state["aktuelles_projekt_id"] = "11111111-1111-1111-1111-111111111111"
        app.session_state["aktuelle_freigabe_id"] = "22222222-2222-2222-2222-222222222222"
        app.session_state["aktuelle_analyse_id"] = "44444444-4444-4444-4444-444444444444"
    if ressourcen_vollstaendig:
        app.session_state["test_ressourcen_vollstaendig"] = True
    return app.run()


def test_fehlende_aktive_kette_blockiert_und_verweist_auf_schritt_sechs() -> None:
    app = _app(aktiv=False)
    assert not app.exception
    assert any("U, R, T, E*, P und A_D" in wert.value for wert in app.error)
    assert any(
        wert.label == "Zurück zu Schritt 6: Process Mining durchführen" for wert in app.button
    )


def test_aktive_kette_hat_keine_lokale_auswahl_und_nur_kpis_aus_u() -> None:
    app = _app()
    assert not app.exception
    assert not {
        "Projekt",
        "Freigegebener Event Log E*",
        "Process-Mining-Analyse",
        "Qualitätslauf",
    } & {wert.label for wert in app.selectbox}
    expander = "\n".join(wert.label for wert in app.expander)
    assert "Servicegrad" in expander
    assert "Liefertreue" not in expander
    untertitel = "\n".join(wert.value for wert in app.subheader)
    assert "Validierte Eingangsartefakte" in untertitel
    assert any(wert.label == "Sollmodellpfad" for wert in app.radio)
    assert any(
        wert.label == "Direkte zeitbezogene Soll-Ist-Auswertung durchführen"
        for wert in app.checkbox
    )
    assert any(wert.label == "Ressourcenentscheidung" for wert in app.radio)
    assert any(wert.label == "Explizite Ankunftszeitspalte (optional)" for wert in app.selectbox)


def test_vollstaendige_ressourcenspalte_zeigt_automatische_schreibgeschuetzte_zuordnung() -> None:
    app = _app(ressourcen_vollstaendig=True)
    assert not app.exception
    assert any("kanonische Spalte resource" in wert.value for wert in app.success)
    assert not any(wert.label == "Ressourcenentscheidung" for wert in app.radio)
    assert any(
        "Die eindeutigen Zuordnungen werden automatisch übernommen" in wert.value
        for wert in app.success
    )


def test_unvollstaendige_ressourcen_zeigen_kompakte_manuelle_tabelle() -> None:
    app = _app()
    auswahl = next(wert for wert in app.radio if wert.label == "Ressourcenentscheidung")
    app = auswahl.set_value("Manuell je Aktivität zuordnen").run()

    assert not app.exception
    assert len(app.dataframe) == 1
    assert app.dataframe[0].key == "ag_ressourcen_tabelle"
    assert list(app.dataframe[0].value.columns) == [
        "Aktivität",
        "Ressourcen (kommagetrennt)",
    ]
    assert any(
        "manuelle Ressourcenzuordnung ist nicht vollständig" in wert.value for wert in app.warning
    )
    assert next(
        wert for wert in app.button if wert.label == "A_G vollständig neu berechnen"
    ).disabled


def test_a_g_speichern_setzt_id_uebergabe_und_schritt_acht() -> None:
    app = _app()
    next(wert for wert in app.button if wert.label == "A_G vollständig neu berechnen").click().run()
    next(
        wert for wert in app.button if wert.label == "A_G speichern und zu Schritt 8"
    ).click().run()

    assert app.session_state["aktuelle_aggregations_id"] == ("66666666-6666-6666-6666-666666666666")
    assert app.session_state["test_uebergabe_schritt8"] is True
    assert app.session_state["naechster_framework_bereich"] == ("8 Modellbestandteile ableiten")


def test_schritt_7_hat_keine_redundante_vorschau_bestaetigung() -> None:
    app = _app()
    next(wert for wert in app.button if wert.label == "A_G vollständig neu berechnen").click().run()
    assert not any("Ich bestätige die Vorschau" in wert.label for wert in app.checkbox)
    assert any(wert.label == "Technische Details" for wert in app.expander)


def test_woped_url_iframe_und_fallback_sind_fest_und_bedingt() -> None:
    quelle = Path("src/framework_mvp/ui/pages/ergebnisaggregation.py").read_text(encoding="utf-8")
    assert 'WOPED_NEXT_URL = "https://taminofischer.github.io/woped-next/"' in quelle
    assert "components.iframe(WOPED_NEXT_URL, height=900, scrolling=True)" in quelle
    assert 'st.link_button("WoPeD Next in neuem Tab öffnen", WOPED_NEXT_URL)' in quelle
    assert 'if status == "Sollmodell muss zunächst erstellt werden"' in quelle
