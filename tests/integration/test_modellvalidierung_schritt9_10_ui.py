"""Kompakte Streamlit-Verträge der Schritte 9 und 10."""

from pathlib import Path
from typing import Any, cast

import pytest
from streamlit.testing.v1 import AppTest

from framework_mvp.domain.models import Offenheitskategorie
from framework_mvp.ui.pages.modellausgabe import _html_link
from framework_mvp.ui.pages.modellvalidierung import _entscheidungsoptionen

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
BESTANDTEILE = [
    {
        "bestandteil_id": wert.bestandteil_id.value,
        "bezeichnung": wert.bezeichnung,
        "status": "teilweise_offen" if index == 0 else "vollstaendig_zugeordnet",
        "verwendete_quellen": ["U"],
        "informationen": [],
        "offene_eintrag_ids": ["offen-1"] if index == 0 else [],
    }
    for index, wert in enumerate(MODELLBESTANDTEILE)
]
BASIS = SimpleNamespace(
    ableitung=SimpleNamespace(
        modellableitungs_id=M, projekt_id=P, k_id=K, o_id=O,
        k_sha256="c" * 64, o_sha256="d" * 64,
    ),
    k={"modellbestandteile": BESTANDTEILE},
    o={"offene_eintraege": [{
        "offener_eintrag_id": "offen-1",
        "bestandteil_id": "problemstellung",
        "kategorie": "fachlich_unsicher",
        "begruendung": "Problemstellung fachlich prüfen.",
    }]},
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
        return Validierungsarbeitsfassung(
            BASIS,
            kwargs["behandlungen"], kwargs["zusaetzliche_anpassungen"],
            kwargs["gesamtvalidierungsstatus"], kwargs["validierungsvermerk"],
            kwargs["gesamtpruefung_bestaetigt"],
            "b" * 64, (),
        )
    def speichern(self, arbeitsfassung, validierungslauf_id, k_stern_id):
        assert arbeitsfassung.finalisierbar
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
            {"k_stern_id": st.session_state["aktuelle_k_stern_id"]},
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
    def erzeugen(self, **kwargs):
        assert kwargs["html"] is True and kwargs["pdf"] is True
        assert "excel" not in kwargs and "report" not in kwargs
        return StrukturierteModellausgabe(
            b"<!DOCTYPE html><style></style>", "modell.html",
            b"%PDF-1.7", "modell.pdf",
        )

zeige_modellausgabe_seite(Projekte(), Validierungen(), Ausgaben())
"""


def _schritt_9(*, aktiv: bool = True) -> AppTest:
    app = AppTest.from_string(SCHRITT_9_APP, default_timeout=10)
    if aktiv:
        app.session_state["aktuelles_projekt_id"] = "11111111-1111-1111-1111-111111111111"
        app.session_state["aktuelle_modellableitungs_id"] = "22222222-2222-2222-2222-222222222222"
        app.session_state["aktuelle_k_id"] = "33333333-3333-3333-3333-333333333333"
        app.session_state["aktuelle_o_id"] = "44444444-4444-4444-4444-444444444444"
    return app.run()


def _schritt_10(*, aktiv: bool = True) -> AppTest:
    app = AppTest.from_string(SCHRITT_10_APP, default_timeout=10)
    if aktiv:
        app.session_state["aktuelles_projekt_id"] = "11111111-1111-1111-1111-111111111111"
        app.session_state["aktuelle_validierungslauf_id"] = "55555555-5555-5555-5555-555555555555"
        app.session_state["aktuelle_k_stern_id"] = "66666666-6666-6666-6666-666666666666"
    return app.run()


def test_schritt_9_verlangt_aktives_k_o_paar() -> None:
    app = _schritt_9(aktiv=False)
    assert not app.exception
    assert any("aktiven IDs des gespeicherten K/O-Paars" in wert.value for wert in app.error)
    assert any(
        wert.label == "Zurück zu Schritt 8: Modellbestandteile ableiten" for wert in app.button
    )


def test_schritt_9_zeigt_16_schreibgeschuetzte_bestandteile_und_o_behandlung() -> None:
    app = _schritt_9()
    assert not app.exception
    assert len(app.dataframe) == 2
    assert app.expander[0].label == "Schreibgeschützte Details aus K"
    assert app.expander[1].label == "Problemstellung · 1 offene Punkte"
    assert app.expander[-1].label == "Technische Details"
    assert any(wert.label == "Fachliche Entscheidung" for wert in app.selectbox)
    assert any(wert.label == "Status der fachlichen Gesamtvalidierung" for wert in app.radio)
    assert any("K*-Vorschau" in wert.value for wert in app.caption)
    assert any("vollständige konzeptionelle Modell" in wert.label for wert in app.checkbox)
    assert not {"Projekt", "K", "O", "Modellableitung"} & {wert.label for wert in app.selectbox}


def test_k_stern_speichern_setzt_ids_und_oeffnet_schritt_zehn() -> None:
    app = _schritt_9()
    next(wert for wert in app.selectbox if wert.label == "Fachliche Entscheidung").set_value(
        "bestätigt"
    ).run()
    next(
        wert for wert in app.text_area if wert.label == "Begründung der fachlichen Entscheidung"
    ).set_value("Fachlich geprüft und bestätigt.")
    next(
        wert for wert in app.radio if wert.label == "Status der fachlichen Gesamtvalidierung"
    ).set_value("fachlich validiert")
    next(
        wert for wert in app.checkbox if "vollständige konzeptionelle Modell" in wert.label
    ).check().run()
    next(
        wert for wert in app.button if wert.label == "K* fachlich validieren und zu Schritt 10"
    ).click().run()

    assert app.session_state["aktuelle_validierungslauf_id"]
    assert app.session_state["aktuelle_k_stern_id"]
    assert app.session_state["naechster_framework_bereich"] == (
        "10 Konzeptionelles Modell ausgeben"
    )
    assert not app.exception


def test_schritt_9_benennt_fehlende_pflichtfelder_konkret() -> None:
    app = _schritt_9()
    final = next(
        wert for wert in app.button if wert.label == "K* fachlich validieren und zu Schritt 10"
    )
    assert final.disabled
    ausgabe = "\n".join(wert.value for wert in app.markdown)
    assert "Offener Punkt 1 (problemstellung): Fachliche Entscheidung" in ausgabe
    assert "Status der fachlichen Gesamtvalidierung" in ausgabe
    assert "Ausdrückliche fachliche Gesamtbestätigung" in ausgabe


def test_schritt_9_zeigt_entscheidungsspezifische_felder_und_optionen() -> None:
    assert "bestätigt" in _entscheidungsoptionen(Offenheitskategorie.FACHLICH_UNSICHER)
    assert "bestätigt" not in _entscheidungsoptionen(Offenheitskategorie.FEHLEND)
    assert "bestätigt" not in _entscheidungsoptionen(Offenheitskategorie.NICHT_ABLEITBAR)

    app = _schritt_9()
    entscheidung = next(wert for wert in app.selectbox if wert.label == "Fachliche Entscheidung")
    entscheidung.set_value("ergänzt_oder_angepasst").run()
    assert any(wert.label == "Fachlicher Inhalt für K*" for wert in app.text_area)
    assert any(wert.label == "Begründung der fachlichen Entscheidung" for wert in app.text_area)

    entscheidung = next(wert for wert in app.selectbox if wert.label == "Fachliche Entscheidung")
    entscheidung.set_value("nicht_anwendbar").run()
    assert not any(wert.label == "Fachlicher Inhalt für K*" for wert in app.text_area)
    assert any(wert.label == "Begründung der fachlichen Entscheidung" for wert in app.text_area)


def test_schritt_9_erlaubt_mehrere_zusaetzliche_anpassungen() -> None:
    app = _schritt_9()
    next(
        wert for wert in app.number_input if wert.label == "Anzahl zusätzlicher Modellanpassungen"
    ).set_value(2).run()
    assert sum(wert.label == "Modellbestandteil" for wert in app.selectbox) == 2
    assert sum(wert.label == "Fachlicher Inhalt" for wert in app.text_area) == 2
    assert sum(wert.label == "Begründung" for wert in app.text_area) == 2


def test_schritt_10_verlangt_validiertes_k_stern_und_bietet_ruecknavigation() -> None:
    app = _schritt_10(aktiv=False)
    assert not app.exception
    assert any("fachlich validiertes K*" in wert.value for wert in app.error)
    assert any(
        wert.label == "Zurück zu Schritt 9: Modell ergänzen und validieren" for wert in app.button
    )


def test_schritt_10_bietet_html_pdf_und_nur_deaktivierten_xlsx_dummy() -> None:
    app = _schritt_10()
    assert not app.exception
    assert len(app.expander) == 17
    dummy = next(
        wert for wert in app.button if wert.label.endswith(".xlsx – noch nicht implementiert")
    )
    assert dummy.disabled
    assert "Fördertechnik Ost ÄÖÜ.xlsx" in dummy.label
    next(wert for wert in app.button if wert.label == "HTML und PDF erzeugen").click().run()
    downloads = cast(list[Any], app.get("download_button"))
    assert {wert.label for wert in downloads} == {
        "HTML-Report herunterladen",
        "PDF-Report herunterladen",
    }
    assert not any("Excel-Ausgabe herunterladen" == wert.label for wert in downloads)
    link = next(
        wert.value
        for wert in app.markdown
        if "Konzeptionelles Modell in neuem Tab öffnen" in wert.value
    )
    assert 'target="_blank"' in link
    assert 'rel="noopener noreferrer"' in link
    assert 'href="/mock/media/' in link
    assert link.split('href="', 1)[1].split('"', 1)[0].endswith(".html")
    assert "data:" not in link
    assert not app.text_input
    assert not app.text_area


def test_html_link_akzeptiert_nur_streamlit_medienressource() -> None:
    link = _html_link("/media/bericht.html")
    assert 'href="/media/bericht.html"' in link
    assert 'target="_blank"' in link
    assert 'rel="noopener noreferrer"' in link
    with pytest.raises(ValueError):
        _html_link("data:text/html;base64,PGh0bWw+")


def test_seiten_dokumentieren_die_verbindlichen_vertraege() -> None:
    schritt_9 = Path("src/framework_mvp/ui/pages/modellvalidierung.py").read_text(encoding="utf-8")
    schritt_10 = Path("src/framework_mvp/ui/pages/modellausgabe.py").read_text(encoding="utf-8")
    for titel in (
        "1. Validierte Eingaben K und O",
        "2. Übersicht der 16 Modellbestandteile",
        "3. Offene und fachlich unsichere Punkte bearbeiten",
        "4. Fachliche Gesamtvalidierung",
        "5. K* speichern und zu Schritt 10",
    ):
        assert titel in schritt_9
    assert "Schritt 10 verändert dieses Modell nicht" in schritt_10
    assert "framework_bereich_oeffnen(schritt=10" in schritt_9
