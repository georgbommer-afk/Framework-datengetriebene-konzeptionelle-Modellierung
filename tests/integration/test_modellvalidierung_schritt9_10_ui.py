"""Kompakte Streamlit-Verträge der Schritte 9 und 10."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

SCHRITT_9_APP = r"""
from types import SimpleNamespace
from uuid import UUID

from framework_mvp.application.modellableitung import MODELLBESTANDTEILE
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
    ableitung=SimpleNamespace(k_id=K, o_id=O),
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

zeige_modellvalidierung_seite(Projekte(), Service())
"""

SCHRITT_10_APP = r"""
from uuid import UUID

from framework_mvp.application.modellableitung import MODELLBESTANDTEILE
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
    def projekt_laden(self, projekt_id): return object() if projekt_id == P else None
class Validierungen:
    def uebergabe_schritt10(self, validierungslauf_id, projekt_id, k_stern_id):
        assert (validierungslauf_id, projekt_id, k_stern_id) == (V, P, KS)
        return K_STERN
class Ausgaben: pass

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


def test_schritt_9_zeigt_elf_schreibgeschuetzte_bestandteile_und_o_behandlung() -> None:
    app = _schritt_9()
    assert not app.exception
    assert len(app.expander) == 11
    assert app.expander[0].label == "1. Problemstellung"
    assert app.expander[-1].label == "11. Darstellung der Vorgänge des Systems"
    assert any(wert.label == "Fachliche Entscheidung" for wert in app.selectbox)
    assert any(
        wert.label == "Fachliche Ergänzung beziehungsweise Begründung" for wert in app.text_area
    )
    assert any(wert.label == "Status der fachlichen Gesamtvalidierung" for wert in app.radio)
    assert not {"Projekt", "K", "O", "Modellableitung"} & {wert.label for wert in app.selectbox}


def test_schritt_10_verlangt_validiertes_k_stern_und_bietet_ruecknavigation() -> None:
    app = _schritt_10(aktiv=False)
    assert not app.exception
    assert any("fachlich validiertes K*" in wert.value for wert in app.error)
    assert any(
        wert.label == "Zurück zu Schritt 9: Modell ergänzen und validieren" for wert in app.button
    )


def test_schritt_10_zeigt_elf_bestandteile_und_nur_report_excel() -> None:
    app = _schritt_10()
    assert not app.exception
    assert len(app.expander) == 11
    auswahl = next(wert for wert in app.multiselect if wert.label == "Ausgabeformen")
    assert auswahl.options == ["Report", "Excel"]
    assert any(wert.label == "Ausgewählte Dateien erzeugen" for wert in app.button)
    assert not app.text_input
    assert not app.text_area


def test_seiten_dokumentieren_die_verbindlichen_vertraege() -> None:
    schritt_9 = Path("src/framework_mvp/ui/pages/modellvalidierung.py").read_text(encoding="utf-8")
    schritt_10 = Path("src/framework_mvp/ui/pages/modellausgabe.py").read_text(encoding="utf-8")
    for titel in (
        "1. Validierte Eingaben K und O",
        "2. Übersicht der elf Modellbestandteile",
        "3. Offene oder fachlich unsichere Punkte bearbeiten",
        "4. Fachliche Gesamtvalidierung",
        "5. Speicherung von K* und Übergabe an Schritt 10",
    ):
        assert titel in schritt_9
    assert "Schritt 10 verändert dieses Modell nicht" in schritt_10
    assert "framework_bereich_oeffnen(schritt=10" in schritt_9
