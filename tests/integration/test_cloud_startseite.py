"""Streamlit-AppTests für öffentlichen Einstieg und isolierten Gastmodus."""

import hashlib
import sqlite3
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from framework_mvp.application.autorisierung import AutorisierungsService
from framework_mvp.application.mandanten_projekt_service import MandantenProjektService
from framework_mvp.bootstrap import (
    DATENBANKPFAD_UMGEBUNGSVARIABLE,
    erstelle_projekt_service,
    erstelle_zugriffs_repository,
)
from framework_mvp.domain.models import Systemtyp, Untersuchungsauftrag
from framework_mvp.domain.models.zugriff import Zugriffskontext
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


def _demo_starten(app: AppTest) -> AppTest:
    return (
        next(button for button in app.button if button.label == "Demoprojekt öffnen")
        .click()
        .run(timeout=120)
    )


def _gastprojekt_starten(app: AppTest, tmp_path: Path) -> AppTest:
    next(button for button in app.button if button.label == "Neues Projekt").click().run()
    geheimnis = str(app.session_state["gast_geheimnis"])
    datenbank = tmp_path / "cloud.sqlite"
    repository = erstelle_zugriffs_repository(datenbank)
    service = MandantenProjektService(
        erstelle_projekt_service(datenbank),
        repository,
        AutorisierungsService(repository),
    )
    projekt = service.projekt_anlegen(
        Zugriffskontext.gast(geheimnis),
        bezeichnung="Temporäres Testprojekt",
        untersuchungsauftrag=Untersuchungsauftrag(
            "Testproblem", "Testzweck", Systemtyp.PRODUKTION, "Testsystem"
        ),
    )
    app.session_state["gast_projekt_id"] = str(projekt.projekt_id)
    app.session_state["aktuelles_projekt_id"] = str(projekt.projekt_id)
    app.session_state["ausgewaehlte_projekt_id"] = projekt.projekt_id
    return app.run()


def test_startseite_zeigt_beide_wege_und_keine_stille_adminfreigabe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _oeffentlich_starten(tmp_path, monkeypatch)
    assert not app.exception
    buttons = {element.label: element for element in app.button}
    assert "Neues Projekt" in buttons
    assert "Demoprojekt öffnen" in buttons
    assert "Anmelden / Kursgruppe öffnen" in buttons
    assert buttons["Anmelden / Kursgruppe öffnen"].disabled
    assert not any("Systemadministration" in element.value for element in app.markdown)


def test_neues_gastprojekt_startet_leer_ohne_vorbelegte_projektzeile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _oeffentlich_starten(tmp_path, monkeypatch)
    next(button for button in app.button if button.label == "Neues Projekt").click().run()
    assert not app.exception
    assert any("nur temporär gespeichert" in warnung.value for warnung in app.warning)
    labels = {button.label for button in app.button}
    assert "Projekt exportieren" in labels
    assert "Projekt importieren" in labels
    assert "Temporäres Projekt löschen" not in labels
    assert "aktuelles_projekt_id" not in app.session_state
    assert "gast_projekt_id" not in app.session_state
    with sqlite3.connect(tmp_path / "cloud.sqlite") as verbindung:
        assert verbindung.execute("SELECT COUNT(*) FROM projekte").fetchone() == (0,)
    archivaktionen = [
        button
        for button in app.sidebar.button
        if button.label in {"Projekt importieren", "Projekt exportieren"}
    ]
    assert len(archivaktionen) == 2
    assert all(button.proto.type == "primary" for button in archivaktionen)
    assert next(
        button for button in archivaktionen if button.label == "Projekt exportieren"
    ).disabled
    assert len(app.get("progress")) == 1
    assert not any("Kursgruppen" in element.value for element in app.markdown)


def test_gastprojekt_loeschung_oeffnet_den_kompakten_dialog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _oeffentlich_starten(tmp_path, monkeypatch)
    _gastprojekt_starten(app, tmp_path)

    next(
        button for button in app.sidebar.button if button.label == "Temporäres Projekt löschen"
    ).click().run()
    assert len(app.get("dialog")) == 1
    assert not app.exception
    assert {button.label for button in app.button} >= {"Endgültig löschen", "Abbrechen"}
    assert any("Andere Projekte bleiben unverändert" in warning.value for warning in app.warning)


def test_anwendung_beenden_loest_session_ohne_projektloeschung(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _oeffentlich_starten(tmp_path, monkeypatch)
    _gastprojekt_starten(app, tmp_path)
    projekt_id = str(app.session_state["aktuelles_projekt_id"])

    beenden = next(button for button in app.sidebar.button if button.label == "Anwendung beenden")
    assert beenden.proto.type != "primary"
    beenden.click().run()

    assert "gast_geheimnis" not in app.session_state
    assert "aktuelles_projekt_id" not in app.session_state
    assert {button.label for button in app.button} >= {"Neues Projekt", "Demoprojekt öffnen"}
    with sqlite3.connect(tmp_path / "cloud.sqlite") as verbindung:
        assert verbindung.execute(
            "SELECT COUNT(*) FROM projekte WHERE projekt_id=?", (projekt_id,)
        ).fetchone() == (1,)


def test_loeschaktionen_bleiben_auch_in_spaeterem_frameworkschritt_sichtbar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _oeffentlich_starten(tmp_path, monkeypatch)
    _gastprojekt_starten(app, tmp_path)

    app.radio[0].set_value("7 Ergebnisse aggregieren").run()

    assert not app.exception
    assert any(button.label == "Temporäres Projekt löschen" for button in app.sidebar.button)


def test_projektimport_oeffnet_lokal_begrenzten_zip_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _oeffentlich_starten(tmp_path, monkeypatch)
    next(button for button in app.button if button.label == "Neues Projekt").click().run()
    next(
        button for button in app.sidebar.button if button.label == "Projekt importieren"
    ).click().run()

    assert not app.exception
    upload = next(wert for wert in app.file_uploader if wert.label == "ZIP-Projektarchiv auswählen")
    assert list(upload.proto.type) == [".zip"]
    quelle = APP.read_text(encoding="utf-8")
    assert ".st-key-projektimport_bereich" in quelle
    assert '[data-testid="stFileUploaderDropzoneInstructions"]' in quelle


def _gastarchiv_exportieren(app: AppTest) -> bytes:
    app.radio[0].set_value("4 Event Log aufbauen").run()
    next(
        button for button in app.sidebar.button if button.label == "Projekt exportieren"
    ).click().run()
    archivzustand = app.session_state["projektarchiv"]
    assert isinstance(archivzustand, dict)
    archiv = archivzustand["daten"]
    assert isinstance(archiv, bytes)
    return archiv


def _konfliktimport_oeffnen(app: AppTest, archiv: bytes) -> AppTest:
    next(
        button for button in app.sidebar.button if button.label == "Projekt importieren"
    ).click().run()
    next(wert for wert in app.file_uploader if wert.label == "ZIP-Projektarchiv auswählen").upload(
        "projekt.zip", archiv, "application/zip"
    ).run()
    next(button for button in app.button if button.label == "Projektarchiv prüfen").click().run()
    return app


def test_konfliktaktionen_rendern_mit_eindeutigen_stabilen_keys_und_abbruch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _oeffentlich_starten(tmp_path, monkeypatch)
    _demo_starten(app)
    projekt_id = str(app.session_state["aktuelles_projekt_id"])
    archiv = _gastarchiv_exportieren(app)
    archiv_hash = hashlib.sha256(archiv).hexdigest()
    with sqlite3.connect(tmp_path / "cloud.sqlite") as verbindung:
        verbindung.execute(
            "UPDATE projekte SET bezeichnung='Nach Export geändert' WHERE projekt_id=?",
            (projekt_id,),
        )
        verbindung.commit()

    _konfliktimport_oeffnen(app, archiv)

    assert not app.exception
    aktionen = {
        button.label: button.key
        for button in app.button
        if button.label
        in {
            "Projekt importieren",
            "Projekt exportieren",
            "Abbrechen",
            "Vorhandenes Projekt ersetzen",
            "Temporäres Projekt löschen",
        }
    }
    assert aktionen["Vorhandenes Projekt ersetzen"] == (
        f"projektimport_ersetzen_{projekt_id}_{archiv_hash[:16]}"
    )
    assert aktionen["Abbrechen"] == f"projektimport_abbrechen_{projekt_id}_{archiv_hash[:16]}"
    assert aktionen["Projekt exportieren"] == f"projektexport_erstellen_{projekt_id}"
    assert aktionen["Temporäres Projekt löschen"] == (f"projekt_loeschen_oeffnen_{projekt_id}")
    assert len(set(aktionen.values())) == len(aktionen)
    erste_keys = sorted(
        key for key in aktionen.values() if key and key.startswith("projektimport_")
    )

    app.run()
    zweite_keys = sorted(
        button.key
        for button in app.button
        if button.key and button.key.startswith("projektimport_")
    )
    assert erste_keys == zweite_keys

    next(button for button in app.button if button.label == "Abbrechen").click().run()
    assert not app.exception
    assert app.session_state["projektimport_offen"] is False
    assert not list((tmp_path / "workspace" / ".import-staging").glob("upload-*"))
    with sqlite3.connect(tmp_path / "cloud.sqlite") as verbindung:
        assert verbindung.execute(
            "SELECT bezeichnung FROM projekte WHERE projekt_id=?", (projekt_id,)
        ).fetchone() == ("Nach Export geändert",)


def test_neuimport_rendert_zwei_gleich_beschriftete_buttons_ohne_duplicate_element_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    quellpfad = tmp_path / "quelle"
    zielpfad = tmp_path / "ziel"
    quellpfad.mkdir()
    zielpfad.mkdir()
    quelle = _oeffentlich_starten(quellpfad, monkeypatch)
    _gastprojekt_starten(quelle, quellpfad)
    quellprojekt_id = str(quelle.session_state["aktuelles_projekt_id"])
    archiv = _gastarchiv_exportieren(quelle)
    archiv_hash = hashlib.sha256(archiv).hexdigest()

    ziel = _oeffentlich_starten(zielpfad, monkeypatch)
    next(button for button in ziel.button if button.label == "Neues Projekt").click().run()
    _konfliktimport_oeffnen(ziel, archiv)

    importbuttons = [button for button in ziel.button if button.label == "Projekt importieren"]
    assert not ziel.exception
    assert len(importbuttons) == 2
    assert len({button.key for button in importbuttons}) == 2
    assert all(button.key is not None for button in importbuttons)
    assert any((button.key or "").startswith("projektimport_oeffnen_") for button in importbuttons)
    assert any(
        button.key == f"projektimport_ausfuehren_{quellprojekt_id}_{archiv_hash[:16]}"
        for button in importbuttons
    )


def test_bestaetigter_konfliktimport_oeffnet_projekt_mit_importiertem_fortschritt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _oeffentlich_starten(tmp_path, monkeypatch)
    _gastprojekt_starten(app, tmp_path)
    projekt_id = str(app.session_state["aktuelles_projekt_id"])
    archiv = _gastarchiv_exportieren(app)
    with sqlite3.connect(tmp_path / "cloud.sqlite") as verbindung:
        verbindung.execute(
            "UPDATE projekte SET bezeichnung='Zu ersetzender Stand' WHERE projekt_id=?",
            (projekt_id,),
        )
        verbindung.commit()
    _konfliktimport_oeffnen(app, archiv)

    next(
        button for button in app.button if button.label == "Vorhandenes Projekt ersetzen"
    ).click().run()

    assert not app.exception
    assert app.session_state["aktuelles_projekt_id"] == projekt_id
    assert app.session_state["framework_bereich"] == "4 Event Log aufbauen"
    assert "projektimport_zustand" not in app.session_state
    assert app.session_state["projektimport_offen"] is False
    assert any("wurde ersetzt" in erfolg.value for erfolg in app.success)
    assert any("Schritt 4" in wert.value for wert in app.markdown)
    assert not list((tmp_path / "workspace" / ".import-staging").glob("upload-*"))
    with sqlite3.connect(tmp_path / "cloud.sqlite") as verbindung:
        assert verbindung.execute(
            "SELECT bezeichnung FROM projekte WHERE projekt_id=?", (projekt_id,)
        ).fetchone() == ("Temporäres Testprojekt",)
