"""AppTest-Tests für Prüfung, Bestätigung und gespeicherte Importe."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from framework_mvp.bootstrap import (
    DATENBANKPFAD_UMGEBUNGSVARIABLE,
    erstelle_importvorgang_service,
    erstelle_projekt_service,
)
from framework_mvp.workspace import WORKSPACE_UMGEBUNGSVARIABLE

ANWENDUNGSPFAD = Path(__file__).parents[1] / "streamlit_importpruefung_app.py"


def _starten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv(DATENBANKPFAD_UMGEBUNGSVARIABLE, str(tmp_path / "app.sqlite"))
    monkeypatch.setenv(WORKSPACE_UMGEBUNGSVARIABLE, str(tmp_path / "workspace"))
    return AppTest.from_file(ANWENDUNGSPFAD).run()


def test_zusammenfassung_und_bestaetigung_speichern_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Teilschritt sieben zeigt die Zusammenfassung und bestätigt genau einen Import."""
    anwendung = _starten(tmp_path, monkeypatch)
    assert not anwendung.exception
    assert any(
        "Originaldatei wird unverändert gespeichert" in wert.value for wert in anwendung.info
    )
    next(
        wert for wert in anwendung.button if wert.label == "Import verbindlich bestätigen"
    ).click().run()
    assert not anwendung.exception
    assert any("verbindlich bestätigt" in wert.value for wert in anwendung.success)
    projekt = erstelle_projekt_service().projekte_auflisten()[0]
    assert len(erstelle_importvorgang_service().importe_fuer_projekt(projekt.projekt_id)) == 1


def test_gespeicherter_import_kann_geoeffnet_werden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Die Projektübersicht öffnet einen Import nach vollständiger Integritätsprüfung."""
    anwendung = _starten(tmp_path, monkeypatch)
    next(
        wert for wert in anwendung.button if wert.label == "Import verbindlich bestätigen"
    ).click().run()
    auswahl = next(
        wert for wert in anwendung.selectbox if wert.label == "Gespeicherten Import öffnen"
    )
    auswahl.select_index(1).run()
    assert not anwendung.exception
    assert any("konsistent" in wert.value for wert in anwendung.success)


def test_integritaetsfehler_wird_verstaendlich_angezeigt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Eine nachträglich veränderte Raw-Datei wird nicht als fehlerfrei dargestellt."""
    anwendung = _starten(tmp_path, monkeypatch)
    next(
        wert for wert in anwendung.button if wert.label == "Import verbindlich bestätigen"
    ).click().run()
    projekt = erstelle_projekt_service().projekte_auflisten()[0]
    importvorgang = erstelle_importvorgang_service().importe_fuer_projekt(projekt.projekt_id)[0]
    (tmp_path / "workspace" / importvorgang.relativer_raw_pfad).write_bytes(b"manipuliert")
    next(
        wert for wert in anwendung.selectbox if wert.label == "Gespeicherten Import öffnen"
    ).select_index(1).run()
    assert not anwendung.exception
    assert any("Prüfsumme" in wert.value for wert in anwendung.error)
