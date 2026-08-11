"""Streamlit-Vertrag von Schritt 7 ohne lokale Auswahl vorgelagerter Artefakte."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = r"""
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pandas as pd

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

zeige_ergebnisaggregation_seite(Projekte(), Aggregation())
"""


def _app(*, aktiv: bool = True) -> AppTest:
    app = AppTest.from_string(APP, default_timeout=10)
    if aktiv:
        app.session_state["aktuelles_projekt_id"] = "11111111-1111-1111-1111-111111111111"
        app.session_state["aktuelle_freigabe_id"] = "22222222-2222-2222-2222-222222222222"
        app.session_state["aktuelle_analyse_id"] = "44444444-4444-4444-4444-444444444444"
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


def test_woped_url_iframe_und_fallback_sind_fest_und_bedingt() -> None:
    quelle = Path("src/framework_mvp/ui/pages/ergebnisaggregation.py").read_text(encoding="utf-8")
    assert 'WOPED_NEXT_URL = "https://taminofischer.github.io/woped-next/"' in quelle
    assert "components.iframe(WOPED_NEXT_URL, height=900, scrolling=True)" in quelle
    assert 'st.link_button("WoPeD Next in neuem Tab öffnen", WOPED_NEXT_URL)' in quelle
    assert 'if status == "Sollmodell muss zunächst erstellt werden"' in quelle
