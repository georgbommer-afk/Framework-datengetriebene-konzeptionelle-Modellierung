"""AppTest für den Einstieg in Framework-Schritt 3."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from framework_mvp.bootstrap import DATENBANKPFAD_UMGEBUNGSVARIABLE, erstelle_projekt_service
from framework_mvp.domain.models import Systemtyp, Untersuchungsauftrag
from framework_mvp.workspace import WORKSPACE_UMGEBUNGSVARIABLE

ANWENDUNGSPFAD = Path(__file__).parents[2] / "streamlit_app.py"


def test_mapping_seite_startet_und_verlangt_zwischendatensatz(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Framework-Schritt 3 startet projektbezogen mit sechs sichtbaren Teilschritten."""
    monkeypatch.setenv(DATENBANKPFAD_UMGEBUNGSVARIABLE, str(tmp_path / "app.sqlite"))
    monkeypatch.setenv(WORKSPACE_UMGEBUNGSVARIABLE, str(tmp_path / "workspace"))
    erstelle_projekt_service().projekt_anlegen(
        bezeichnung="Mapping-Projekt",
        untersuchungsauftrag=Untersuchungsauftrag("", "", Systemtyp.KOMBINIERT, ""),
    )
    anwendung = AppTest.from_file(ANWENDUNGSPFAD).run()
    anwendung.radio[0].set_value("3 Semantisches Mapping").run()
    assert not anwendung.exception
    assert any(element.value == "3 Semantisches Mapping" for element in anwendung.header)
    assert any("Schritt 1 von 6" in element.value for element in anwendung.caption)
    assert any("Zwischendatensatz erzeugt" in element.value for element in anwendung.warning)
