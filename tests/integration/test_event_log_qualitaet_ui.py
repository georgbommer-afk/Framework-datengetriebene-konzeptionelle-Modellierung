"""AppTest der neuen Framework-Seiten 4 und 5."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from framework_mvp.bootstrap import DATENBANKPFAD_UMGEBUNGSVARIABLE, erstelle_projekt_service
from framework_mvp.domain.models import Systemtyp, Untersuchungsauftrag
from framework_mvp.workspace import WORKSPACE_UMGEBUNGSVARIABLE

ANWENDUNGSPFAD = Path(__file__).parents[2] / "streamlit_app.py"


def _app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv(DATENBANKPFAD_UMGEBUNGSVARIABLE, str(tmp_path / "app.sqlite"))
    monkeypatch.setenv(WORKSPACE_UMGEBUNGSVARIABLE, str(tmp_path / "workspace"))
    projekt = erstelle_projekt_service().projekt_anlegen(
        bezeichnung="Framework 4 und 5",
        untersuchungsauftrag=Untersuchungsauftrag("", "", Systemtyp.KOMBINIERT, ""),
    )
    anwendung = AppTest.from_file(ANWENDUNGSPFAD)
    anwendung.session_state["aktuelles_projekt_id"] = str(projekt.projekt_id)
    return anwendung.run()


@pytest.mark.parametrize(
    ("seite", "titel", "voraussetzungswarnung"),
    (
        ("4 Event Log aufbauen", "4 Event Log aufbauen", "kein konsistenter T"),
        (
            "5 Datenqualität prüfen",
            "5 Datenqualität prüfen",
            "erzeugen und speichern Sie zuerst in Schritt 4 einen Event Log E",
        ),
    ),
)
def test_neue_seiten_nutzen_kompakten_wizard_ohne_framework_grafik(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seite: str,
    titel: str,
    voraussetzungswarnung: str,
) -> None:
    """Navigation, Überschrift und kompakter Wizard starten ohne produktiven Workspace."""
    anwendung = _app(tmp_path, monkeypatch)
    anwendung.radio[0].set_value(seite).run()
    assert not anwendung.exception
    assert any(wert.value == titel for wert in anwendung.header)
    assert any(voraussetzungswarnung in wert.value for wert in anwendung.warning)
    assert not any("Schritt 1 von" in wert.value for wert in anwendung.caption)
    assert not any("<svg" in wert.value for wert in anwendung.markdown)
    assert not (tmp_path / "workspace").exists()
