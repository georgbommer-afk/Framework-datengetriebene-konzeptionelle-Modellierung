"""Strukturtests der kompakten Wizard-Komponente."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

ANWENDUNG = """
from framework_mvp.ui.components.kompakter_wizard import zeige_kompakten_fortschritt
zeige_kompakten_fortschritt(
    schritt=2,
    kurze_namen=("Quelle", "Upload", "Profil"),
    lange_namen=("Datenquelle registrieren", "Datei hochladen", "Datenprofil erstellen"),
)
"""


def test_kompakter_wizard_markiert_status_und_bietet_alle_schritte(tmp_path: Path) -> None:
    """Die Anzeige benötigt keine Karten und hält Langtitel im geschlossenen Expander."""
    anwendung = AppTest.from_string(ANWENDUNG).run()
    assert not anwendung.exception
    assert any("Schritt 2 von 3" in wert.value for wert in anwendung.caption)
    zeile = " ".join(wert.value for wert in anwendung.markdown)
    assert "✓ 1 Quelle" in zeile
    assert "**2 Upload**" in zeile
    assert "3 Profil" in zeile
    assert any(wert.label == "Alle Schritte anzeigen" for wert in anwendung.expander)
    assert not anwendung.get("container")
