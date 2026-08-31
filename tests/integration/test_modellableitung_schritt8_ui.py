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
    AbgeleiteterModellbestandteil, Bestandteilstatus, Eingangsartefakt,
    Projekt, Projektstatus, Systemtyp, Untersuchungsauftrag,
)
from framework_mvp.application.modellableitung import MODELLBESTANDTEILE
from framework_mvp.application.modellableitung_service import (
    ModellableitungService, Modellableitungsvorschau,
)
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
    entscheidungsfingerabdruck = staticmethod(ModellableitungService.entscheidungsfingerabdruck)
    def grundlage_laden(self, projekt_id, aggregations_id):
        assert (projekt_id, aggregations_id) == (P, AG)
        return BASIS
    def vorschau(self, **kwargs):
        st.session_state["vorschau_automatisch"] = True
        entscheidungen = kwargs.get("entscheidungen", ())
        st.session_state["aufgerufene_entscheidungen"] = len(entscheidungen)
        bestandteile = tuple(
            AbgeleiteterModellbestandteil(
                definition.bestandteil_id, definition.bezeichnung,
                Bestandteilstatus.VOLLSTAENDIG_ZUGEORDNET, (), (), (),
            )
            for definition in MODELLBESTANDTEILE
        )
        return Modellableitungsvorschau(
            BASIS,
            kwargs["modellableitungs_id"], kwargs["k_id"], kwargs["o_id"],
            bestandteile, (), entscheidungen, bestandteile, (),
            self.entscheidungsfingerabdruck(entscheidungen),
            {"k_id": str(kwargs["k_id"])}, {"o_id": str(kwargs["o_id"])},
            b"{}", b"{}", "e" * 64, "f" * 64,
        )
    def speichern(self, vorschau):
        assert len(vorschau.entscheidungen) == 16
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


def test_haupttabelle_hat_sechzehn_bestandteile_und_fuenf_spalten() -> None:
    app = _app()
    assert not app.exception
    assert app.session_state["vorschau_automatisch"] is True
    assert len(app.dataframe) == 1
    assert list(app.dataframe[0].value.columns) == [
        "Bestandteil",
        "Vorgeschlagene Information",
        "Quelle/Schritt",
        "Status",
        "Fachliche Entscheidung",
    ]
    assert len(app.dataframe[0].value) == 16
    assert len(app.expander) == 17
    assert app.expander[0].label.startswith("1. Problemstellung")
    assert app.expander[-2].label.startswith("16. Darstellung der Vorgänge des Systems")
    assert app.expander[-1].label == "Technische Details"
    assert not app.checkbox
    assert len(app.radio) == 16
    assert not app.text_area
    assert not {
        "Projekt",
        "Aggregationslauf",
        "Freigabe",
        "Process-Mining-Analyse",
    } & {wert.label for wert in app.selectbox}


def test_vorschau_entsteht_ohne_vorschauknopf_und_speichern_ist_zunaechst_gesperrt() -> None:
    app = _app()
    assert app.session_state["aufgerufene_entscheidungen"] == 0
    assert not any(wert.label == "Vorschau von K und O erzeugen" for wert in app.button)
    speichern = next(
        wert for wert in app.button if wert.label == "K und O speichern und zu Schritt 9"
    )
    assert speichern.disabled
    assert any("Bitte prüfen Sie noch 16" in wert.value for wert in app.warning)


def test_speichern_setzt_k_o_ids_und_oeffnet_schritt_neun() -> None:
    app = _app()
    for radio in app.radio:
        radio.set_value("Vorschlag übernehmen")
    app.run()
    next(
        wert for wert in app.button if wert.label == "K und O speichern und zu Schritt 9"
    ).click().run()

    assert app.session_state["aktuelle_modellableitungs_id"]
    assert app.session_state["aktuelle_k_id"]
    assert app.session_state["aktuelle_o_id"]
    assert app.session_state["naechster_framework_bereich"] == ("9 Modell ergänzen und validieren")


def test_seite_trennt_fachliche_und_technische_details_und_uebergibt_an_schritt_neun() -> None:
    quelle = Path("src/framework_mvp/ui/pages/modellableitung.py").read_text(encoding="utf-8")
    for titel in (
        "Zuordnung der Ergebnisse aus Schritt 1 bis 7",
        "Fachliche Vorschläge und Übernahmeentscheidungen",
        "Technische Details",
    ):
        assert titel in quelle
    assert "Vorschlag nicht übernehmen" in quelle
    assert "Vorschau von K und O erzeugen" not in quelle
    assert "framework_bereich_oeffnen(schritt=9" in quelle
