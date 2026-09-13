"""Streamlit-Verträge der gezielten O-Behandlung und Schritt-10-Ausgabe."""

from pathlib import Path
from typing import Any, cast

import pytest
from streamlit.testing.v1 import AppTest

from framework_mvp.domain.models import Offenheitskategorie
from framework_mvp.ui.pages.modellausgabe import _html_link
from framework_mvp.ui.pages.modellvalidierung import _entscheidungsoptionen

P = "11111111-1111-1111-1111-111111111111"
M = "22222222-2222-2222-2222-222222222222"
K = "33333333-3333-3333-3333-333333333333"
O_ID = "44444444-4444-4444-4444-444444444444"
PRAEFIX = f"schritt9_{P}_{M}"

SCHRITT_9_APP = r"""
from types import SimpleNamespace
from uuid import UUID

import streamlit as st

from framework_mvp.application.modellableitung import MODELLBESTANDTEILE
from framework_mvp.application.modellvalidierung_service import Validierungsarbeitsfassung
from framework_mvp.ui.pages.modellvalidierung import zeige_modellvalidierung_seite

P = UUID("11111111-1111-1111-1111-111111111111")
M = UUID("22222222-2222-2222-2222-222222222222")
K = UUID("33333333-3333-3333-3333-333333333333")
O = UUID("44444444-4444-4444-4444-444444444444")

def informationen(bestandteil_id):
    if bestandteil_id == "aktivitaeten":
        return [{
            "herkunftsartefakt": "P", "strukturreferenz": "sichtbare_aktivitaeten",
            "wert": ["Fräsen", "Lackieren"],
        }]
    if bestandteil_id == "ressourcen":
        return [{
            "herkunftsartefakt": "A_G",
            "strukturreferenz": "strukturierte_ergebnisse.ressourcen",
            "wert": {"zuordnungen": [{
                "aktivitaet": "Fräsen", "ressourcen": ["Maschine M01"], "offen": False,
            }]},
        }]
    if bestandteil_id == "problemstellung":
        return [{
            "herkunftsartefakt": "U", "strukturreferenz": "untersuchungsauftrag.problemstellung",
            "wert": "Durchlaufzeit ist zu hoch.",
        }]
    return []

OFFENE = [
    {
        "offener_eintrag_id": "problemstellung:unsicher:1",
        "bestandteil_id": "problemstellung",
        "kategorie": "fachlich_unsicher",
        "begruendung": "Automatisch zugeordnete Problemstellung fachlich prüfen.",
        "anwenderhinweis": "Kontext aus Schritt 8 bleibt nur ein Hinweis.",
    },
    {
        "offener_eintrag_id": "eingaben:offen:1",
        "bestandteil_id": "eingaben",
        "kategorie": "fehlend",
        "begruendung": "Experimentelle Faktoren mit Wertebereichen fehlen.",
        "anwenderhinweis": "Pausenzeit als möglichen Faktor prüfen.",
    },
    {
        "offener_eintrag_id": "ressourcen:offen:1",
        "bestandteil_id": "ressourcen",
        "kategorie": "nicht_ableitbar",
        "begruendung": "Kapazität der Ressource ist offen.",
        "anwenderhinweis": "",
    },
    {
        "offener_eintrag_id": "vereinfachungen:offen:1",
        "bestandteil_id": "vereinfachungen",
        "kategorie": "fehlend",
        "begruendung": "Eine Vereinfachung ist nicht dokumentiert.",
        "anwenderhinweis": "",
    },
    {
        "offener_eintrag_id": "daten:offen:1",
        "bestandteil_id": "daten",
        "kategorie": "nicht_ableitbar",
        "begruendung": "Pausendaten sind nicht bestimmbar.",
        "anwenderhinweis": "",
    },
]
BESTANDTEILE = [
    {
        "bestandteil_id": wert.bestandteil_id.value,
        "bezeichnung": wert.bezeichnung,
        "status": "teilweise_offen"
        if any(o["bestandteil_id"] == wert.bestandteil_id.value for o in OFFENE)
        else "vollstaendig_zugeordnet",
        "verwendete_quellen": ["U"],
        "informationen": informationen(wert.bestandteil_id.value),
        "offene_eintrag_ids": [
            o["offener_eintrag_id"]
            for o in OFFENE if o["bestandteil_id"] == wert.bestandteil_id.value
        ],
    }
    for wert in MODELLBESTANDTEILE
]
BASIS = SimpleNamespace(
    ableitung=SimpleNamespace(
        modellableitungs_id=M, projekt_id=P, k_id=K, o_id=O,
        k_sha256="c" * 64, o_sha256="d" * 64,
    ),
    k={"modellbestandteile": BESTANDTEILE},
    o={"offene_eintraege": OFFENE},
    eingabefingerabdruck="a" * 64,
)
class Projekte:
    def projekt_laden(self, projekt_id): return object() if projekt_id == P else None
class Service:
    def grundlage_laden(self, projekt_id, modellableitungs_id, **kwargs):
        assert projekt_id == P and modellableitungs_id == M
        assert kwargs["erwartete_k_id"] == K and kwargs["erwartete_o_id"] == O
        return BASIS
    def arbeitsfassung_aus_grundlage(self, basis, **kwargs):
        assert basis is BASIS
        assert kwargs["zusaetzliche_anpassungen"] == ()
        return Validierungsarbeitsfassung(
            BASIS,
            kwargs["behandlungen"], (),
            kwargs["gesamtvalidierungsstatus"], kwargs["validierungsvermerk"],
            kwargs["gesamtpruefung_bestaetigt"],
            "b" * 64, (),
        )
    def speichern(self, arbeitsfassung, validierungslauf_id, k_stern_id):
        assert arbeitsfassung.finalisierbar
        st.session_state["gespeicherte_behandlungen"] = arbeitsfassung.behandlungen
        return SimpleNamespace(
            validierungslauf_id=validierungslauf_id,
            k_stern_id=k_stern_id,
            projekt_id=P,
        )
    def laden(self, validierungslauf_id):
        return (
            SimpleNamespace(
                validierungslauf_id=validierungslauf_id,
                k_stern_id=UUID(st.session_state["aktuelle_k_stern_id"]),
                projekt_id=P,
            ),
            {
                "k_stern_id": st.session_state["aktuelle_k_stern_id"],
                "behandlungen_offener_eintraege": [],
                "gesamtvalidierung": {"menschlich_bestaetigt": True},
            },
        )
    def k_stern_download_laden(self, validierungslauf_id): return b"{}"

zeige_modellvalidierung_seite(Projekte(), Service())
"""

SCHRITT_10_APP = r"""
from types import SimpleNamespace
from uuid import UUID

from framework_mvp.application.modellableitung import MODELLBESTANDTEILE
from framework_mvp.application.modellausgabe_service import StrukturierteModellausgabe
from framework_mvp.ui.pages.modellausgabe import zeige_modellausgabe_seite

P = UUID("11111111-1111-1111-1111-111111111111")
V = UUID("55555555-5555-5555-5555-555555555555")
KS = UUID("66666666-6666-6666-6666-666666666666")
K_STERN = {
    "k_stern_id": str(KS), "validierungslauf_id": str(V), "projekt_id": str(P),
    "erstellt_am": "2026-01-01T00:00:00+00:00",
    "modellbestandteile": [
        {
            "bestandteil_id": wert.bestandteil_id.value,
            "bezeichnung": wert.bezeichnung,
            "urspruenglicher_bestandteil": {"informationen": []},
            "menschliche_eintraege": [],
        }
        for wert in MODELLBESTANDTEILE
    ],
}
class Projekte:
    def projekt_laden(self, projekt_id):
        return SimpleNamespace(
            projekt_id=P, bezeichnung="Fördertechnik / Ost: ÄÖÜ"
        ) if projekt_id == P else None
class Validierungen:
    def uebergabe_schritt10(self, validierungslauf_id, projekt_id, k_stern_id):
        assert (validierungslauf_id, projekt_id, k_stern_id) == (V, P, KS)
        return K_STERN
class Ausgaben:
    def persistierte_ausgabe_laden(self, **kwargs): return None
    def erzeugen(self, **kwargs):
        assert "excel" not in kwargs and "report" not in kwargs
        return StrukturierteModellausgabe(
            b"<!DOCTYPE html><style></style>" if kwargs["html"] else None,
            "modell.html" if kwargs["html"] else None,
            b"%PDF-1.7" if kwargs["pdf"] else None,
            "modell.pdf" if kwargs["pdf"] else None,
            b"PK-xlsx" if kwargs["xlsx"] else None,
            "modell.xlsx" if kwargs["xlsx"] else None,
        )

zeige_modellausgabe_seite(Projekte(), Validierungen(), Ausgaben())
"""


def _schritt_9(*, aktiv: bool = True, zustand: dict[str, Any] | None = None) -> AppTest:
    app = AppTest.from_string(SCHRITT_9_APP, default_timeout=10)
    if aktiv:
        app.session_state["aktuelles_projekt_id"] = P
        app.session_state["aktuelle_modellableitungs_id"] = M
        app.session_state["aktuelle_k_id"] = K
        app.session_state["aktuelle_o_id"] = O_ID
    for key, wert in (zustand or {}).items():
        app.session_state[key] = wert
    return app.run()


def _vollstaendiger_zustand() -> dict[str, Any]:
    return {
        f"{PRAEFIX}_problemstellung:unsicher:1_entscheidung": "bestätigt",
        f"{PRAEFIX}_eingaben:offen:1_entscheidung": "ergänzt_oder_angepasst",
        f"{PRAEFIX}_eingaben:offen:1_bezugstyp": "ressource",
        f"{PRAEFIX}_eingaben:offen:1_konkreter_bezug": "Maschine M01",
        f"{PRAEFIX}_eingaben:offen:1_bezeichnung": "Pausenzeit",
        f"{PRAEFIX}_eingaben:offen:1_art": "quantitativer_parameter",
        f"{PRAEFIX}_eingaben:offen:1_unterer_wert": 0.0,
        f"{PRAEFIX}_eingaben:offen:1_oberer_wert": 30.0,
        f"{PRAEFIX}_eingaben:offen:1_einheit": "min",
        f"{PRAEFIX}_ressourcen:offen:1_entscheidung": "ergänzt_oder_angepasst",
        f"{PRAEFIX}_ressourcen:offen:1_ressource": "Maschine M01",
        f"{PRAEFIX}_ressourcen:offen:1_kapazitaet": "2 Aufträge",
        f"{PRAEFIX}_vereinfachungen:offen:1_entscheidung": "nicht_anwendbar",
        f"{PRAEFIX}_daten:offen:1_entscheidung": "nicht_bekannt_oder_bestimmbar",
        f"{PRAEFIX}_gesamtbestaetigung": True,
        f"{PRAEFIX}_validierungsvermerk": "Mit Prozesseignerin geprüft.",
    }


def _schritt_10(*, aktiv: bool = True) -> AppTest:
    app = AppTest.from_string(SCHRITT_10_APP, default_timeout=10)
    if aktiv:
        app.session_state["aktuelles_projekt_id"] = P
        app.session_state["aktuelle_validierungslauf_id"] = "55555555-5555-5555-5555-555555555555"
        app.session_state["aktuelle_k_stern_id"] = "66666666-6666-6666-6666-666666666666"
    return app.run()


def test_schritt_9_verlangt_aktives_k_o_paar() -> None:
    app = _schritt_9(aktiv=False)
    assert not app.exception
    assert any("aktive Ergebnisaggregation A_G" in wert.value for wert in app.error)


def test_schritt_9_zeigt_k_schreibgeschuetzt_und_nur_o_editoren() -> None:
    app = _schritt_9()
    assert not app.exception
    assert len(app.dataframe) == 1
    assert len(app.dataframe[0].value) == 16
    assert app.expander[0].label == "Bereits zugeordnete Modellbestandteile anzeigen"
    assert any(wert.label == "Behandlung" for wert in app.selectbox)
    assert not app.radio
    assert not any(
        wert.label == "Anzahl zusätzlicher Modellanpassungen" for wert in app.number_input
    )
    assert any("Hinweis aus Schritt 8:" in wert.value for wert in app.markdown)
    assert any("Kontext aus Schritt 8" in wert.value for wert in app.info)
    assert any(
        wert.label == "Zurück zu Schritt 8 und als fachlich unsicher kennzeichnen"
        for wert in app.button
    )


def test_vier_behandlungen_und_bestaetigung_nur_fuer_fachlich_unsicher() -> None:
    unsicher = _entscheidungsoptionen(Offenheitskategorie.FACHLICH_UNSICHER)
    fehlend = _entscheidungsoptionen(Offenheitskategorie.FEHLEND)
    assert {
        "ergänzt_oder_angepasst",
        "nicht_bekannt_oder_bestimmbar",
        "nicht_anwendbar",
    } <= set(fehlend)
    assert "bestätigt" in unsicher
    assert "bestätigt" not in fehlend


def test_experimenteller_faktor_verwendet_vorhandene_ressource_und_wertebereich() -> None:
    zustand = _vollstaendiger_zustand()
    zustand[f"{PRAEFIX}_gesamtbestaetigung"] = False
    app = _schritt_9(zustand=zustand)
    assert not app.exception
    bezug = next(wert for wert in app.selectbox if wert.label == "Konkreter Bezug")
    assert bezug.options == ["Maschine M01"]
    assert any(wert.label == "Bezeichnung des experimentellen Faktors" for wert in app.text_input)
    assert any(wert.label == "Unterer Wert" and wert.value == 0.0 for wert in app.number_input)
    assert any(wert.label == "Oberer Wert" and wert.value == 30.0 for wert in app.number_input)


def test_eine_gesamtbestaetigung_erzeugt_k_stern_mit_strukturierten_behandlungen() -> None:
    app = _schritt_9(zustand=_vollstaendiger_zustand())
    assert not app.exception
    assert not app.radio
    globale = [wert for wert in app.checkbox if "vollständige konzeptionelle Modell" in wert.label]
    assert len(globale) == 1 and globale[0].value is True
    final = next(
        wert
        for wert in app.button
        if wert.label == "Gesamtmodell fachlich validieren und K* erzeugen"
    )
    assert not final.disabled
    final.click().run()
    behandlungen = app.session_state["gespeicherte_behandlungen"]
    assert len(behandlungen) == 5
    faktor = next(wert for wert in behandlungen if wert.bestandteil_id.value == "eingaben")
    assert faktor.strukturierter_inhalt["konkreter_bezug"] == "Maschine M01"
    assert faktor.strukturierter_inhalt["oberer_wert"] == 30.0
    unbekannt = next(wert for wert in behandlungen if wert.bestandteil_id.value == "daten")
    assert unbekannt.entscheidung.value == "nicht_bekannt_oder_bestimmbar"
    assert unbekannt.strukturierter_inhalt == {}
    assert app.session_state["aktuelle_validierungslauf_id"]
    assert app.session_state["aktuelle_k_stern_id"]
    assert app.session_state["naechster_framework_bereich"] == (
        "10 Konzeptionelles Modell ausgeben"
    )


def test_unbehandelter_o_punkt_blockiert_gesamtvalidierung() -> None:
    app = _schritt_9()
    final = next(
        wert
        for wert in app.button
        if wert.label == "Gesamtmodell fachlich validieren und K* erzeugen"
    )
    assert final.disabled
    assert next(
        wert for wert in app.checkbox if "vollständige konzeptionelle Modell" in wert.label
    ).disabled
    ausgabe = "\n".join(wert.value for wert in app.markdown)
    assert "Offener Punkt 1 (problemstellung): Behandlung auswählen" in ausgabe


def test_schritt_10_verlangt_validiertes_k_stern_und_bietet_ruecknavigation() -> None:
    app = _schritt_10(aktiv=False)
    assert not app.exception
    assert any("fachlich validiertes K*" in wert.value for wert in app.error)


def test_schritt_10_bietet_html_pdf_und_funktionalen_xlsx_download() -> None:
    app = _schritt_10()
    assert not app.exception
    assert len(app.expander) == 17
    assert {wert.label for wert in app.checkbox} == {
        "PDF – kompakte statische Dokumentation und Informationsweitergabe",
        "HTML – interaktive beziehungsweise erweiterte Betrachtung des konzeptionellen Modells",
        "XLSX – strukturierte Weiterverarbeitung der Modellinformationen, insbesondere als "
        "Grundlage für weitere DES-Arbeiten",
    }
    assert next(wert for wert in app.checkbox if wert.label.startswith("PDF")).value is True
    next(wert for wert in app.checkbox if wert.label.startswith("HTML")).check().run()
    next(wert for wert in app.checkbox if wert.label.startswith("XLSX")).check().run()
    next(wert for wert in app.button if wert.label == "Gewählte Ausgabe erzeugen").click().run()
    downloads = cast(list[Any], app.get("download_button"))
    assert {wert.label for wert in downloads} == {
        "HTML-Report herunterladen",
        "PDF-Report herunterladen",
        "Excel-Ausgabe herunterladen",
    }
    link = next(
        wert.value
        for wert in app.markdown
        if "Konzeptionelles Modell in neuem Tab öffnen" in wert.value
    )
    assert 'target="_blank"' in link
    assert 'rel="noopener noreferrer"' in link
    assert 'href="/mock/media/' in link
    assert "data:" not in link


def test_schritt_10_verlangt_mindestens_eine_ausgabeform() -> None:
    app = _schritt_10()
    next(wert for wert in app.checkbox if wert.label.startswith("PDF")).uncheck().run()

    assert any("mindestens PDF, HTML oder XLSX" in wert.value for wert in app.warning)
    erzeugen = next(wert for wert in app.button if wert.label == "Gewählte Ausgabe erzeugen")
    assert erzeugen.disabled


def test_html_link_akzeptiert_nur_streamlit_medienressource() -> None:
    link = _html_link("/media/bericht.html")
    assert 'href="/media/bericht.html"' in link
    with pytest.raises(ValueError):
        _html_link("data:text/html;base64,PGh0bWw+")


def test_seite_dokumentiert_neue_hauptstruktur_ohne_generische_alte_editoren() -> None:
    schritt_9 = Path("src/framework_mvp/ui/pages/modellvalidierung.py").read_text(encoding="utf-8")
    for titel in (
        "1. Vorläufiges Modell K",
        "2. Offene Inhalte aus O ergänzen",
        "3. Gesamtübersicht",
        "4. Fachliche Gesamtvalidierung",
    ):
        assert titel in schritt_9
    assert "Anzahl zusätzlicher Modellanpassungen" not in schritt_9
    assert "Status der fachlichen Gesamtvalidierung" not in schritt_9
    assert "Gesamtmodell fachlich validieren und K* erzeugen" in schritt_9
