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
    ProfilkennzahlReferenz, Profilkennzahltyp, Qualitaetsfreigabe, Systemtyp,
    Untersuchungsauftrag,
)
from framework_mvp.ui.pages.ergebnisaggregation import zeige_ergebnisaggregation_seite

P = UUID("11111111-1111-1111-1111-111111111111")
F = UUID("22222222-2222-2222-2222-222222222222")
E = UUID("33333333-3333-3333-3333-333333333333")
A = UUID("44444444-4444-4444-4444-444444444444")
T = UUID("55555555-5555-5555-5555-555555555555")
AG = UUID("66666666-6666-6666-6666-666666666666")
ALTES_AG = UUID("77777777-7777-7777-7777-777777777777")
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
    profilkennzahlen=(
        ProfilkennzahlReferenz(
            "profilkennzahl:befriedigt-ja", "00000000-0000-0000-0000-000000000001",
            "quelle-1", "Produktionsdaten", "produktion.csv", "Aufträge", "befriedigt",
            Profilkennzahltyp.ABSOLUTE_HAEUFIGKEIT_INDIKATOR, 1.0,
            "gleich", "ja", 2, 2, 3, "4" * 64,
        ),
        ProfilkennzahlReferenz(
            "profilkennzahl:zeilen", "00000000-0000-0000-0000-000000000001",
            "quelle-1", "Produktionsdaten", "produktion.csv", "Aufträge", "",
            Profilkennzahltyp.ZEILENANZAHL, 2.0,
            auswertbare_beobachtungen=2, grundgesamtheit=2, profilversion=3,
            profil_sha256="4" * 64,
        ),
    ),
)

class Projekte:
    def projekt_laden(self, projekt_id): return PROJEKT if projekt_id == P else None

class Aggregation:
    def grundlage_laden(self, projekt_id, freigabe_id, analyse_id):
        assert (projekt_id, freigabe_id, analyse_id) == (P, F, A)
        return BASIS
    def konfigurationsfingerabdruck(self, **kwargs):
        return str(st.session_state.get("test_konfigurationsfingerabdruck", "6" * 64))
    def vorschau(self, **kwargs):
        return SimpleNamespace(
            grundlage=BASIS, kpi_ergebnisse=(), conformance_ergebnis=None,
            zeitvergleich_ergebnis=None, warnungen=(),
            konfigurationsfingerabdruck=self.konfigurationsfingerabdruck(),
        )
    def speichern(self, aggregations_id, vorschau, menschlich_bestaetigt):
        assert menschlich_bestaetigt
        st.session_state["test_speicheraufrufe"] = int(
            st.session_state.get("test_speicheraufrufe", 0)
        ) + 1
        return SimpleNamespace(aggregations_id=AG)
    def uebergabe_schritt8(self, aggregations_id, projekt_id, freigabe_id, analyse_id):
        assert aggregations_id in {AG, ALTES_AG}
        assert (projekt_id, freigabe_id, analyse_id) == (P, F, A)
        st.session_state["test_uebergabe_schritt8"] = True
    def laden(self, aggregations_id):
        return SimpleNamespace(
            aggregations_id=aggregations_id,
            projekt_id=P,
            freigabe_id=F,
            analyse_id=A,
            eingabefingerabdruck="5" * 64,
            konfigurationsfingerabdruck="6" * 64,
        ), {}
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
    assert any("aktuellen Projektstand" in wert.value for wert in app.error)
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
    checkboxen = {wert.label for wert in app.checkbox}
    assert "A. Termin-/Fertigstellungsabweichung dT – Gleichung 3.1" in checkboxen
    assert "B. Bearbeitungszeitabweichung dB – Gleichung 3.2" in checkboxen
    assert "C. Ressourcenbezogene Busy Ratio – Gleichungen 3.3 bis 3.5" in checkboxen
    assert "Ressourcen, Entitäten, Warteschlangen und Zeitgrößen" in untertitel
    assert any(wert.label == "Anzahl bestätigter Ankunftsströme q" for wert in app.number_input)
    assert not any("erster gültiger Ereigniszeitstempel" in wert.label for wert in app.selectbox)


def test_r_profilkennzahlen_werden_fachlich_statt_als_technische_ids_angezeigt() -> None:
    app = _app()
    auswahl = next(wert for wert in app.selectbox if wert.label == "Exakte Profilkennzahl aus R")
    optionen = "\n".join(str(wert) for wert in auswahl.options)
    assert "Datensatz: Produktionsdaten" in optionen
    assert "Spalte: befriedigt" in optionen
    assert "Absolute Häufigkeit eines Indikators" in optionen
    assert "befriedigt = ja" in optionen
    assert "Wert: 1" in optionen
    assert "profilkennzahl:befriedigt-ja" not in optionen


def test_vollstaendige_ressourcenspalte_zeigt_automatische_schreibgeschuetzte_zuordnung() -> None:
    app = _app(ressourcen_vollstaendig=True)
    assert not app.exception
    assert any("kanonischen Spalte resource" in wert.value for wert in app.success)
    assert any("automatisch übernommen" in wert.value for wert in app.success)


def test_unvollstaendige_ressourcen_zeigen_kompakte_manuelle_tabelle() -> None:
    app = _app()
    assert not app.exception
    tabelle = next(wert for wert in app.dataframe if wert.key == "ag_ressourcen_tabelle")
    assert list(tabelle.value.columns) == [
        "Aktivität",
        "Manuelle Ressourcen (kommagetrennt)",
        "Offen / nicht bekannt",
    ]
    assert not next(
        wert
        for wert in app.button
        if wert.label
        == "Ergebnisaggregation berechnen und weiter zu Schritt 8: Modellbestandteile ableiten"
    ).disabled


def test_a_g_speichern_setzt_id_uebergabe_und_schritt_acht() -> None:
    app = _app()
    next(
        wert
        for wert in app.button
        if wert.label
        == "Ergebnisaggregation berechnen und weiter zu Schritt 8: Modellbestandteile ableiten"
    ).click().run()

    assert app.session_state["aktuelle_aggregations_id"] == ("66666666-6666-6666-6666-666666666666")
    assert app.session_state["test_uebergabe_schritt8"] is True
    assert app.session_state["naechster_framework_bereich"] == ("8 Modellbestandteile ableiten")


def test_unveraenderte_a_g_konfiguration_bewahrt_aktive_folgeartefakte() -> None:
    app = _app()
    projekt_id = "11111111-1111-1111-1111-111111111111"
    alte_ag = "77777777-7777-7777-7777-777777777777"
    app.session_state["aktuelle_aggregations_id"] = alte_ag
    app.session_state[f"ag_konfiguration_bearbeiten_{projekt_id}"] = True
    app.session_state["aktuelle_modellableitungs_id"] = "8" * 32
    app.session_state["aktuelle_k_id"] = "9" * 32
    app.session_state["aktuelle_o_id"] = "a" * 32
    app.session_state["aktuelle_validierungslauf_id"] = "b" * 32
    app.session_state["aktuelle_k_stern_id"] = "c" * 32
    app = app.run()

    next(
        wert
        for wert in app.button
        if wert.label
        == "Ergebnisaggregation berechnen und weiter zu Schritt 8: Modellbestandteile ableiten"
    ).click().run()

    assert app.session_state["aktuelle_aggregations_id"] == alte_ag
    assert (
        app.session_state["test_speicheraufrufe"]
        if "test_speicheraufrufe" in app.session_state
        else 0
    ) == 0
    assert app.session_state["aktuelle_modellableitungs_id"] == "8" * 32
    assert app.session_state["aktuelle_validierungslauf_id"] == "b" * 32
    assert app.session_state["aktuelle_k_stern_id"] == "c" * 32
    assert app.session_state["naechster_framework_bereich"] == "8 Modellbestandteile ableiten"


def test_geaenderte_a_g_konfiguration_loest_folgeartefakte_und_oeffnet_schritt_acht() -> None:
    app = _app()
    projekt_id = "11111111-1111-1111-1111-111111111111"
    app.session_state["aktuelle_aggregations_id"] = "77777777-7777-7777-7777-777777777777"
    app.session_state[f"ag_konfiguration_bearbeiten_{projekt_id}"] = True
    app.session_state["test_konfigurationsfingerabdruck"] = "7" * 64
    app.session_state["aktuelle_modellableitungs_id"] = "8" * 32
    app.session_state["aktuelle_validierungslauf_id"] = "b" * 32
    app.session_state["aktuelle_k_stern_id"] = "c" * 32
    app = app.run()

    next(
        wert
        for wert in app.button
        if wert.label
        == "Ergebnisaggregation berechnen und weiter zu Schritt 8: Modellbestandteile ableiten"
    ).click().run()

    assert app.session_state["aktuelle_aggregations_id"] == ("66666666-6666-6666-6666-666666666666")
    assert app.session_state["test_speicheraufrufe"] == 1
    assert "aktuelle_modellableitungs_id" not in app.session_state
    assert "aktuelle_validierungslauf_id" not in app.session_state
    assert "aktuelle_k_stern_id" not in app.session_state
    assert app.session_state["naechster_framework_bereich"] == "8 Modellbestandteile ableiten"


def test_schritt_7_hat_keine_redundante_vorschau_bestaetigung() -> None:
    app = _app()
    assert not any("Ich bestätige die Vorschau" in wert.label for wert in app.checkbox)
    assert not any(wert.label == "A_G speichern und zu Schritt 8" for wert in app.button)


def test_woped_url_iframe_und_fallback_sind_fest_und_bedingt() -> None:
    quelle = Path("src/framework_mvp/ui/pages/ergebnisaggregation.py").read_text(encoding="utf-8")
    assert 'WOPED_NEXT_URL = "https://taminofischer.github.io/woped-next/"' in quelle
    assert "components.iframe(WOPED_NEXT_URL, height=900, scrolling=True)" in quelle
    assert 'st.link_button("WoPeD Next in neuem Tab öffnen", WOPED_NEXT_URL)' in quelle
    assert 'if status == "Sollmodell muss zunächst erstellt werden"' in quelle


def test_conformance_ergebnisdarstellung_und_mappingbestaetigung_sind_explizit() -> None:
    quelle = Path("src/framework_mvp/ui/pages/ergebnisaggregation.py").read_text(encoding="utf-8")
    assert "Ich bestätige die Zuordnung zwischen den Aktivitäten des Event Logs" in quelle
    assert "Fitness nach Gleichung 3.13" in quelle
    assert "pT · produzierte Tokens" in quelle
    assert "cT · konsumierte Tokens" in quelle
    assert "mT · fehlende Tokens" in quelle
    assert "rT · verbleibende Tokens" in quelle
    assert "PM4Py-Plausibilisierung" in quelle
    assert "fallbezogene Diagnosen" in quelle
