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
    erstelle_projekt_service().projekt_anlegen(
        bezeichnung="Framework 4 und 5",
        untersuchungsauftrag=Untersuchungsauftrag("", "", Systemtyp.KOMBINIERT, ""),
    )
    return AppTest.from_file(ANWENDUNGSPFAD).run()


@pytest.mark.parametrize(
    ("seite", "titel", "schritte"),
    (
        ("4 Event Log aufbauen", "4 Event Log aufbauen", 5),
        ("5 Datenqualität prüfen", "5 Datenqualität prüfen", 6),
    ),
)
def test_neue_seiten_nutzen_kompakten_wizard_ohne_framework_grafik(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seite: str,
    titel: str,
    schritte: int,
) -> None:
    """Navigation, Überschrift und kompakter Wizard starten ohne produktiven Workspace."""
    anwendung = _app(tmp_path, monkeypatch)
    anwendung.radio[0].set_value(seite).run()
    assert not anwendung.exception
    assert any(wert.value == titel for wert in anwendung.header)
    assert any(f"Schritt 1 von {schritte}" in wert.value for wert in anwendung.caption)
    assert any(wert.label == "Alle Schritte anzeigen" for wert in anwendung.expander)
    assert not any("<svg" in wert.value for wert in anwendung.markdown)
    assert not (tmp_path / "workspace").exists()
