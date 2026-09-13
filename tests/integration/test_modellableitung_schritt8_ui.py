"""Streamlit-Vertrag der vereinfachten Gesamtbestätigung in Schritt 8."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = r"""
import json
from dataclasses import asdict
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pandas as pd
import streamlit as st

from framework_mvp.domain.models import (
    AbgeleiteterModellbestandteil, Bestandteilstatus, Eingangsartefakt,
    Informationseintrag, Kennzeichnungsherkunft, OffenerEintrag,
    Offenheitskategorie, Projekt, Projektstatus, Systemtyp,
    Uebernahmeart, Untersuchungsauftrag,
)
from framework_mvp.application.modellableitung import (
    MODELLBESTANDTEILE, wende_pruefhinweise_an,
)
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
    aggregation=SimpleNamespace(
        aggregations_id=AG, aggregations_sha256="a" * 64,
        analyse_id=A, event_log_id=E,
    ),
    analyse=SimpleNamespace(analyse_id=A),
    freigabe=SimpleNamespace(freigabe_id=F, event_log_id=E, event_log_sha256="b" * 64),
    event_log=EVENTS,
    prozessnotation=SimpleNamespace(bezeichnung="Petrinetz"),
    discovery_ergebnisse={"svg_texte": {}},
    quellreferenzen=REFERENZEN,
    lineage={"artefakte": {wert.value: referenz for wert, referenz in REFERENZEN.items()}},
    a_g={"strukturierte_ergebnisse": {"zeitbezogene_datenauswahl": {
        "umfang_e_stern": {"ereignisanzahl": 2, "fallanzahl": 1, "aktivitaetsanzahl": 2}
    }}},
    eingabefingerabdruck="c" * 64,
)

def information(definition):
    return Informationseintrag(
        f"{definition.bestandteil_id.value}:information:1",
        definition.bestandteil_id, Eingangsartefakt.UNTERSUCHUNGSAUFTRAG_U,
        "id-U", "a" * 64, "fachwert", f"Information für {definition.bezeichnung}",
        Uebernahmeart.DIREKTE_UEBERNAHME,
    )

SYSTEMATISCH_OFFEN = (
    OffenerEintrag(
        "eingaben:offen:1", MODELLBESTANDTEILE[3].bestandteil_id,
        Offenheitskategorie.FEHLEND,
        "Keine konkreten experimentellen Faktoren mit Wertebereichen ableitbar.", (),
        Kennzeichnungsherkunft.SYSTEMATISCH_ERKANNT,
    ),
    OffenerEintrag(
        "ressourcen:offen:1", MODELLBESTANDTEILE[10].bestandteil_id,
        Offenheitskategorie.NICHT_ABLEITBAR,
        "Eine Ressourcenbeziehung ist fachlich offen.", (),
        Kennzeichnungsherkunft.SYSTEMATISCH_ERKANNT,
    ),
)
VORGESCHLAGEN = tuple(
    AbgeleiteterModellbestandteil(
        definition.bestandteil_id,
        definition.bezeichnung,
        Bestandteilstatus.OFFEN
        if definition.bestandteil_id == MODELLBESTANDTEILE[3].bestandteil_id
        else Bestandteilstatus.TEILWEISE_OFFEN
        if definition.bestandteil_id == MODELLBESTANDTEILE[10].bestandteil_id
        else Bestandteilstatus.VOLLSTAENDIG_ZUGEORDNET,
        () if definition.bestandteil_id == MODELLBESTANDTEILE[3].bestandteil_id
        else (Eingangsartefakt.UNTERSUCHUNGSAUFTRAG_U,),
        () if definition.bestandteil_id == MODELLBESTANDTEILE[3].bestandteil_id
        else (information(definition),),
        tuple(
            wert.offener_eintrag_id
            for wert in SYSTEMATISCH_OFFEN
            if wert.bestandteil_id == definition.bestandteil_id
        ),
    )
    for definition in MODELLBESTANDTEILE
)

class Projekte:
    def projekt_laden(self, projekt_id): return PROJEKT if projekt_id == P else None

class Service:
    prueffingerabdruck = staticmethod(ModellableitungService.prueffingerabdruck)
    def grundlage_laden(self, projekt_id, aggregations_id):
        assert (projekt_id, aggregations_id) == (P, AG)
        return BASIS
    def vorherige_anwenderhinweise(self, projekt_id, aggregations_id, vorschau):
        return {}
    def vorschau(self, **kwargs):
        st.session_state["vorschau_automatisch"] = True
        hinweise = kwargs.get("anwenderhinweise", ())
        unsicherheiten = kwargs.get("unsicherheitskennzeichnungen", ())
        bestandteile, offene = wende_pruefhinweise_an(
            VORGESCHLAGEN, SYSTEMATISCH_OFFEN, hinweise, unsicherheiten
        )
        fingerprint = self.prueffingerabdruck(hinweise, unsicherheiten)
        bestaetigt_am = kwargs.get("bestaetigt_am")
        k = {
            "modellbestandteile": json.loads(json.dumps(
                [asdict(wert) for wert in bestandteile], default=str
            )),
            "eingangslineage": BASIS.lineage,
            "bestaetigt_am": str(bestaetigt_am) if bestaetigt_am else None,
        }
        o = {"offene_eintraege": json.loads(json.dumps(
            [asdict(wert) for wert in offene], default=str
        ))}
        return Modellableitungsvorschau(
            BASIS, kwargs["modellableitungs_id"], kwargs["k_id"], kwargs["o_id"],
            VORGESCHLAGEN, SYSTEMATISCH_OFFEN, hinweise, unsicherheiten,
            bestandteile, offene, fingerprint, bestaetigt_am,
            k, o, b"{}", b"{}", "e" * 64, "f" * 64,
        )
    def speichern(self, vorschau, *, menschlich_bestaetigt=None):
        assert menschlich_bestaetigt is True
        assert vorschau.bestaetigt_am is not None
        st.session_state["anzahl_gesamtbestaetigungen"] = 1
        st.session_state["gespeichertes_k"] = vorschau.k
        st.session_state["gespeichertes_o"] = vorschau.o
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
                k_sha256="e" * 64, o_sha256="f" * 64, mappingversion=4,
            ),
            st.session_state["gespeichertes_k"],
            st.session_state["gespeichertes_o"],
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


def test_haupttabelle_zeigt_vollstaendig_teilweise_offen_und_offen_ohne_pflichteingaben() -> None:
    app = _app()
    assert not app.exception
    assert app.session_state["vorschau_automatisch"] is True
    assert len(app.dataframe) == 1
    assert list(app.dataframe[0].value.columns) == [
        "Modellbestandteil",
        "Zugeordnete Information",
        "Quelle",
        "Status",
        "Offene Punkte O",
    ]
    assert len(app.dataframe[0].value) == 16
    assert {"Vollständig zugeordnet", "Teilweise offen", "Offen"} <= set(
        app.dataframe[0].value["Status"]
    )
    assert not app.checkbox
    assert not app.radio
    assert not app.text_area
    assert len(app.multiselect) == 1
    assert any(wert.label == "Grundlage der Modellableitung anzeigen" for wert in app.expander)
    assert not {
        "Projekt",
        "Aggregationslauf",
        "Freigabe",
        "Process-Mining-Analyse",
    } & {wert.label for wert in app.selectbox}


def test_anwenderhinweis_erscheint_erst_nach_sekundaeraktion_und_wird_in_o_gespeichert() -> None:
    app = _app()
    hinzufuegen = [wert for wert in app.button if wert.label == "Hinweis für Schritt 9 hinzufügen"]
    assert len(hinzufuegen) == 2
    hinzufuegen[0].click().run()
    assert len(app.text_area) == 1
    app.text_area[0].set_value("Schichtmodell als Faktor prüfen.").run()
    primary = next(
        wert
        for wert in app.button
        if wert.label == "Zuordnungen bestätigen, K und O speichern und zu Schritt 9"
    )
    assert not primary.disabled
    primary.click().run()

    assert app.session_state["anzahl_gesamtbestaetigungen"] == 1
    assert any(
        wert["anwenderhinweis"] == "Schichtmodell als Faktor prüfen." and wert["status"] == "offen"
        for wert in app.session_state["gespeichertes_o"]["offene_eintraege"]
    )
    assert app.session_state["naechster_framework_bereich"] == ("9 Modell ergänzen und validieren")


def test_eine_gesamtbestaetigung_speichert_auch_ohne_hinweis_und_erneutes_oeffnen_ist_lesbar() -> (
    None
):
    app = _app()
    primary_buttons = [
        wert
        for wert in app.button
        if wert.label == "Zuordnungen bestätigen, K und O speichern und zu Schritt 9"
    ]
    assert len(primary_buttons) == 1
    primary_buttons[0].click().run()
    assert app.session_state["aktuelle_modellableitungs_id"]
    assert app.session_state["aktuelle_k_id"]
    assert app.session_state["aktuelle_o_id"]
    assert app.session_state["anzahl_gesamtbestaetigungen"] == 1
    assert not app.exception
    assert len(app.dataframe) == 1
    assert len(app.dataframe[0].value) == 16
    assert len(app.download_button) == 2
    assert any("gespeichert und erneut validiert" in wert.value for wert in app.success)


def test_seite_enthaelt_keine_fachliche_bearbeitung_von_o() -> None:
    quelle = Path("src/framework_mvp/ui/pages/modellableitung.py").read_text(encoding="utf-8")
    assert "Vorschlag nicht übernehmen" not in quelle
    assert "Fachliche Entscheidung" not in quelle
    assert "Pflichtbegründung" not in quelle
    assert "Vorschau von K und O erzeugen" not in quelle
    assert "schritt_abschliessen_und_weiter(aktueller_schritt=8" in quelle
