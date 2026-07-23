"""AppTest-Integrationstests der ETL-Hauptseite."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from framework_mvp.bootstrap import (
    DATENBANKPFAD_UMGEBUNGSVARIABLE,
    erstelle_datenquelle_service,
    erstelle_projekt_service,
)
from framework_mvp.domain.models import Projekt, Systemtyp, Untersuchungsauftrag
from framework_mvp.workspace import WORKSPACE_UMGEBUNGSVARIABLE

ANWENDUNGSPFAD = Path(__file__).parents[2] / "streamlit_app.py"


def _projekt_anlegen() -> Projekt:
    return erstelle_projekt_service().projekt_anlegen(
        bezeichnung="ETL-Projekt",
        untersuchungsauftrag=Untersuchungsauftrag("", "", Systemtyp.KOMBINIERT, ""),
    )


def _etl_starten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv(DATENBANKPFAD_UMGEBUNGSVARIABLE, str(tmp_path / "app.sqlite"))
    monkeypatch.setenv(WORKSPACE_UMGEBUNGSVARIABLE, str(tmp_path / "workspace"))
    _projekt_anlegen()
    anwendung = AppTest.from_file(ANWENDUNGSPFAD).run()
    anwendung.radio[0].set_value("2 ETL durchführen").run()
    return anwendung


def test_etl_seite_startet_und_markiert_schritt_zwei(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ETL-Seite, Fortschritt und alle neun Teilschritte werden angezeigt."""
    anwendung = _etl_starten(tmp_path, monkeypatch)
    assert not anwendung.exception
    assert any(element.value == "2 ETL durchführen" for element in anwendung.header)
    assert anwendung.get("progress")
    assert any("Schritt 1 von 9" in element.value for element in anwendung.caption)
    assert sum("Noch nicht verfügbar" in element.value for element in anwendung.caption) == 0
    assert any("8 Transformation" in element.value for element in anwendung.markdown)
    assert any(element.label == "Alle Schritte anzeigen" for element in anwendung.expander)


def test_datenquelle_kann_angelegt_und_erneut_geladen_werden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Der aktive Teilschritt speichert und öffnet einen Katalogeintrag."""
    anwendung = _etl_starten(tmp_path, monkeypatch)
    bezeichnung = next(e for e in anwendung.text_input if e.label == "Bezeichnung der Datenquelle")
    bezeichnung.set_value("ERP Tagesexport")
    speichern = next(e for e in anwendung.button if e.label == "Datenquelle speichern")
    speichern.click().run()
    assert not anwendung.exception
    assert any("erfolgreich gespeichert" in e.value for e in anwendung.success)
    projekt = erstelle_projekt_service().projekte_auflisten()[0]
    datenquellen = erstelle_datenquelle_service().datenquellen_fuer_projekt(projekt.projekt_id)
    assert [quelle.bezeichnung for quelle in datenquellen] == ["ERP Tagesexport"]
    assert (tmp_path / "workspace" / "projects" / str(projekt.projekt_id) / "raw").is_dir()

    auswahl = next(e for e in anwendung.selectbox if e.label == "Gespeicherte Datenquelle öffnen")
    auswahl.select_index(1).run()
    assert (
        next(e for e in anwendung.text_input if e.label == "Bezeichnung der Datenquelle").value
        == "ERP Tagesexport"
    )


def test_weiter_fuehrt_nach_registrierung_zum_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Eine gültig gespeicherte Quelle schaltet den zweiten Teilschritt frei."""
    anwendung = _etl_starten(tmp_path, monkeypatch)
    next(e for e in anwendung.text_input if e.label == "Bezeichnung der Datenquelle").set_value(
        "CSV-Quelle"
    )
    next(e for e in anwendung.button if e.label == "Datenquelle speichern").click().run()
    weiter = next(e for e in anwendung.button if e.label == "Weiter")
    assert not weiter.disabled
    weiter.click().run()
    assert not anwendung.exception
    assert any("Schritt 2 von 9" in element.value for element in anwendung.caption)
    assert anwendung.get("file_uploader")
