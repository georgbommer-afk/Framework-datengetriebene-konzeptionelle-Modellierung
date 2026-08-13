"""Streamlit-Vertrag von Schritt 8 ohne lokale Artefaktauswahl oder Ergänzungsfelder."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = r"""
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pandas as pd
import streamlit as st

from framework_mvp.domain.models import (
    Eingangsartefakt, Projekt, Projektstatus, Systemtyp, Untersuchungsauftrag,
)
from framework_mvp.application.modellableitung_service import Modellableitungsvorschau
from framework_mvp.ui.pages.modellableitung import zeige_modellableitung_seite

P = UUID("11111111-1111-1111-1111-111111111111")
AG = UUID("22222222-2222-2222-2222-222222222222")
A = UUID("33333333-3333-3333-3333-333333333333")
F = UUID("44444444-4444-4444-4444-444444444444")
E = UUID("55555555-5555-5555-5555-555555555555")
JETZT = datetime(2026, 1, 1, tzinfo=UTC)
PROJEKT = Projekt(
    P, "Ableitung", (), Projektstatus.AKTIV, JETZT, JETZT,
    Untersuchungsauftrag("Problem", "Leistung bewerten", Systemtyp.PRODUKTION, "Werk"),
)
EVENTS = pd.DataFrame({
    "case_id": ["1", "1"], "activity": ["A", "B"],
    "timestamp": pd.to_datetime(["2026-01-01", "2026-01-02"], utc=True),
})
REFERENZEN = {
    wert: {"id": f"id-{wert.value}", "sha256": wert.value.encode().hex().ljust(64, "0")[:64]}
    for wert in Eingangsartefakt
}
BASIS = SimpleNamespace(
    projekt=PROJEKT,
    aggregation=SimpleNamespace(aggregations_id=AG, aggregations_sha256="a" * 64),
    analyse=SimpleNamespace(analyse_id=A),
    freigabe=SimpleNamespace(freigabe_id=F, event_log_id=E, event_log_sha256="b" * 64),
    event_log=EVENTS,
    prozessnotation=SimpleNamespace(bezeichnung="Petrinetz"),
    discovery_ergebnisse={"svg_texte": {}},
    quellreferenzen=REFERENZEN,
    lineage={
        "artefakte": {wert.value: referenz for wert, referenz in REFERENZEN.items()}
    },
    a_g={"warnungen": []},
    eingabefingerabdruck="c" * 64,
)

class Projekte:
    def projekt_laden(self, projekt_id): return PROJEKT if projekt_id == P else None

class Service:
    def grundlage_laden(self, projekt_id, aggregations_id):
        assert (projekt_id, aggregations_id) == (P, AG)
        return BASIS
    def unsicherheitsfingerabdruck(self, werte): return "d" * 64
    def vorschau(self, **kwargs):
        st.session_state["aufgerufene_unsicherheit"] = sorted(
            wert.value for wert in kwargs["fachlich_unsichere_bestandteile"]
        )
        return Modellableitungsvorschau(
            BASIS,
            kwargs["modellableitungs_id"], kwargs["k_id"], kwargs["o_id"],
            kwargs["fachlich_unsichere_bestandteile"], (), (), "d" * 64,
            {"k_id": str(kwargs["k_id"])}, {"o_id": str(kwargs["o_id"])},
            b"{}", b"{}", "e" * 64, "f" * 64,
        )
    def speichern(self, vorschau, menschlich_bestaetigt):
        assert menschlich_bestaetigt
        return SimpleNamespace(
            modellableitungs_id=vorschau.modellableitungs_id,
            k_id=vorschau.k_id, o_id=vorschau.o_id, projekt_id=P,
        )
    def laden(self, ableitungs_id):
        return (
            SimpleNamespace(
                modellableitungs_id=ableitungs_id, projekt_id=P,
                k_id=st.session_state["aktuelle_k_id"],
                o_id=st.session_state["aktuelle_o_id"],
                k_sha256="e" * 64, o_sha256="f" * 64,
            ),
            {"k_id": st.session_state["aktuelle_k_id"]},
            {"o_id": st.session_state["aktuelle_o_id"]},
        )
    def k_download_laden(self, ableitungs_id): return b"{}"
    def o_download_laden(self, ableitungs_id): return b"{}"

zeige_modellableitung_seite(Projekte(), Service())
"""


def _app(*, aktiv: bool = True) -> AppTest:
    app = AppTest.from_string(APP, default_timeout=10)
    if aktiv:
        app.session_state["aktuelles_projekt_id"] = "11111111-1111-1111-1111-111111111111"
        app.session_state["aktuelle_aggregations_id"] = "22222222-2222-2222-2222-222222222222"
    return app.run()


def test_fehlende_aktive_aggregation_blockiert_und_verweist_auf_schritt_sieben() -> None:
    app = _app(aktiv=False)
    assert not app.exception
    assert any("aktive, gespeicherte Aggregation A_G" in wert.value for wert in app.error)
    assert any(wert.label == "Zurück zu Schritt 7: Ergebnisse aggregieren" for wert in app.button)


def test_alle_elf_bestandteile_quellen_und_unsicherheitsmarkierungen_sind_sichtbar() -> None:
    app = _app()
    assert not app.exception
    assert len(app.expander) == 11
    assert app.expander[0].label == "1. Problemstellung"
    assert app.expander[-1].label == "11. Darstellung der Vorgänge des Systems"
    assert (
        len(
            [
                wert
                for wert in app.checkbox
                if wert.label == "Vorhandene Zuordnung als fachlich unsicher kennzeichnen"
            ]
        )
        == 11
    )
    assert sum("teilweise offen" in wert.value for wert in app.warning) == 3
    assert not app.text_input
    assert not app.text_area
    assert not {
        "Projekt",
        "Aggregationslauf",
        "Freigabe",
        "Process-Mining-Analyse",
    } & {wert.label for wert in app.selectbox}


def test_unsicherheit_wird_menschlich_markiert_ohne_ersatzwert() -> None:
    app = _app()
    aktivitaeten = next(
        wert for wert in app.checkbox if wert.key == "modellableitung_unsicher_aktivitaeten"
    )
    aktivitaeten.check().run()
    next(wert for wert in app.button if wert.label == "Vorschau von K und O erzeugen").click().run()
    assert app.session_state["aufgerufene_unsicherheit"] == ["aktivitaeten"]
    assert not app.text_input
    assert not app.text_area


def test_speichern_setzt_k_o_ids_und_oeffnet_schritt_neun() -> None:
    app = _app()
    next(wert for wert in app.button if wert.label == "Vorschau von K und O erzeugen").click().run()
    next(
        wert for wert in app.checkbox if wert.label.startswith("Ich bestätige ausschließlich")
    ).check().run()
    next(
        wert for wert in app.button if wert.label == "K und O speichern und zu Schritt 9"
    ).click().run()

    assert app.session_state["aktuelle_modellableitungs_id"]
    assert app.session_state["aktuelle_k_id"]
    assert app.session_state["aktuelle_o_id"]
    assert app.session_state["naechster_framework_bereich"] == ("9 Modell ergänzen und validieren")


def test_seite_enthaelt_fuenf_abschnitte_und_validierte_schritt_neun_uebergabe() -> None:
    quelle = Path("src/framework_mvp/ui/pages/modellableitung.py").read_text(encoding="utf-8")
    for titel in (
        "1. Validierte Eingangsartefakte",
        "2. Zuordnung gemäß Tabelle 3.15",
        "3. Vorschau des vorläufigen konzeptionellen Modells (K)",
        "4. Offene Bestandteile (O)",
        "5. Bestätigung, Speicherung und Übergabe an Schritt 9",
    ):
        assert titel in quelle
    assert "keine fachliche Validierung von K" in quelle
    assert "framework_bereich_oeffnen(schritt=9" in quelle
