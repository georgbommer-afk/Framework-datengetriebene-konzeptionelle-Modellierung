"""Streamlit-AppTests für öffentlichen Einstieg und isolierten Gastmodus."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from framework_mvp.bootstrap import DATENBANKPFAD_UMGEBUNGSVARIABLE
from framework_mvp.ui.oidc import (
    LOKALER_TESTADMIN_UMGEBUNGSVARIABLE,
    LOKALER_TESTMODUS_UMGEBUNGSVARIABLE,
)
from framework_mvp.workspace import WORKSPACE_UMGEBUNGSVARIABLE

APP = Path(__file__).parents[2] / "streamlit_app.py"


def _oeffentlich_starten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.delenv(LOKALER_TESTMODUS_UMGEBUNGSVARIABLE, raising=False)
    monkeypatch.delenv(LOKALER_TESTADMIN_UMGEBUNGSVARIABLE, raising=False)
    monkeypatch.setenv(DATENBANKPFAD_UMGEBUNGSVARIABLE, str(tmp_path / "cloud.sqlite"))
    monkeypatch.setenv(WORKSPACE_UMGEBUNGSVARIABLE, str(tmp_path / "workspace"))
    return AppTest.from_file(APP).run()


def test_startseite_zeigt_beide_wege_und_keine_stille_adminfreigabe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _oeffentlich_starten(tmp_path, monkeypatch)
    assert not app.exception
    buttons = {element.label: element for element in app.button}
    assert "Ohne Anmeldung testen" in buttons
    assert "Anmelden / Kursgruppe öffnen" in buttons
    assert buttons["Anmelden / Kursgruppe öffnen"].disabled
    assert not any("Systemadministration" in element.value for element in app.markdown)


def test_gastmodus_zeigt_warnung_projektaktionen_und_genau_einen_fortschrittsbalken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _oeffentlich_starten(tmp_path, monkeypatch)
    next(button for button in app.button if button.label == "Ohne Anmeldung testen").click().run()
    assert not app.exception
    assert any("nur temporär gespeichert" in warnung.value for warnung in app.warning)
    labels = {button.label for button in app.button}
    assert "Projekt exportieren" in labels
    assert "Projekt importieren" in labels
    assert "Demo beenden und Daten löschen" in labels
    archivaktionen = [
        button
        for button in app.sidebar.button
        if button.label in {"Projekt importieren", "Projekt exportieren"}
    ]
    assert len(archivaktionen) == 2
    assert all(button.proto.type == "primary" for button in archivaktionen)
    assert len(app.get("progress")) == 1
    assert not any("Kursgruppen" in element.value for element in app.markdown)


def test_gastprojekt_loeschung_oeffnet_den_kompakten_dialog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _oeffentlich_starten(tmp_path, monkeypatch)
    next(button for button in app.button if button.label == "Ohne Anmeldung testen").click().run()

    next(
        button for button in app.sidebar.button if button.label == "Demo beenden und Daten löschen"
    ).click().run()
    assert len(app.get("dialog")) == 1
    assert not app.exception
    assert {button.label for button in app.button} >= {"Endgültig löschen", "Abbrechen"}
    assert any("Andere Projekte bleiben unverändert" in warning.value for warning in app.warning)


def test_loeschaktionen_bleiben_auch_in_spaeterem_frameworkschritt_sichtbar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _oeffentlich_starten(tmp_path, monkeypatch)
    next(button for button in app.button if button.label == "Ohne Anmeldung testen").click().run()

    app.radio[0].set_value("7 Ergebnisse aggregieren").run()

    assert not app.exception
    assert any(button.label == "Demo beenden und Daten löschen" for button in app.sidebar.button)


def test_projektimport_oeffnet_lokal_begrenzten_zip_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _oeffentlich_starten(tmp_path, monkeypatch)
    next(button for button in app.button if button.label == "Ohne Anmeldung testen").click().run()
    next(
        button for button in app.sidebar.button if button.label == "Projekt importieren"
    ).click().run()

    assert not app.exception
    upload = next(wert for wert in app.file_uploader if wert.label == "ZIP-Projektarchiv auswählen")
    assert list(upload.proto.type) == [".zip"]
    quelle = APP.read_text(encoding="utf-8")
    assert ".st-key-projektimport_bereich" in quelle
    assert '[data-testid="stFileUploaderDropzoneInstructions"]' in quelle
