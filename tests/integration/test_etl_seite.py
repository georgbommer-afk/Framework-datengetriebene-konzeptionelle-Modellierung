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
    projekt = _projekt_anlegen()
    anwendung = AppTest.from_file(ANWENDUNGSPFAD).run()
    anwendung.session_state["aktuelles_projekt_id"] = str(projekt.projekt_id)
    anwendung.radio[0].set_value("2 ETL durchführen").run()
    return anwendung


def test_etl_seite_startet_und_markiert_schritt_zwei(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ETL-Seite, Projektkontext und alle fünf Abschnitte werden angezeigt."""
    anwendung = _etl_starten(tmp_path, monkeypatch)
    assert not anwendung.exception
    assert any(element.value == "2 ETL durchführen" for element in anwendung.header)
    assert anwendung.get("progress")
    assert any("Schritt 1 von 5" in element.value for element in anwendung.caption)
    assert sum("Noch nicht verfügbar" in element.value for element in anwendung.caption) == 0
    assert any("4 Transformation" in element.value for element in anwendung.markdown)
    assert any(element.label == "Alle Schritte anzeigen" for element in anwendung.expander)
    assert not any(element.label == "Aktuelles Projekt" for element in anwendung.selectbox)
    assert any("Aktuelles Projekt: ETL-Projekt" in element.value for element in anwendung.markdown)


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

    auswahl = next(e for e in anwendung.selectbox if e.label == "Datenquelle")
    auswahl.select_index(1).run()
    assert (
        next(e for e in anwendung.text_input if e.label == "Bezeichnung der Datenquelle").value
        == "ERP Tagesexport"
    )


def test_upload_ist_im_ersten_abschnitt_integriert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Datenquelle und Upload werden ohne technischen Zwischenschritt zusammen angezeigt."""
    anwendung = _etl_starten(tmp_path, monkeypatch)
    next(e for e in anwendung.text_input if e.label == "Bezeichnung der Datenquelle").set_value(
        "CSV-Quelle"
    )
    next(e for e in anwendung.button if e.label == "Datenquelle speichern").click().run()
    assert not anwendung.exception
    assert anwendung.get("file_uploader")


def test_projektwechsel_fuehrt_zu_schritt_eins_und_bewahrt_projekt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Der Projektwechsel öffnet die zentrale Auswahl ohne lokalen Dropdown."""
    anwendung = _etl_starten(tmp_path, monkeypatch)
    projekt_id = anwendung.session_state["aktuelles_projekt_id"]
    next(e for e in anwendung.button if e.label == "Projekt wechseln").click().run()
    assert not anwendung.exception
    assert anwendung.radio[0].value == "1 Projekt und Untersuchungsauftrag"
    assert anwendung.session_state["aktuelles_projekt_id"] == projekt_id
