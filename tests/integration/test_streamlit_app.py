"""Bedientests für die Streamlit-Anwendung."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from framework_mvp.bootstrap import DATENBANKPFAD_UMGEBUNGSVARIABLE, erstelle_projekt_service
from framework_mvp.domain.models import Systemtyp, Untersuchungsauftrag

ANWENDUNGSPFAD = Path(__file__).parents[2] / "streamlit_app.py"


def _anwendung_starten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    datenbankpfad = tmp_path / "streamlit.sqlite"
    monkeypatch.setenv(DATENBANKPFAD_UMGEBUNGSVARIABLE, str(datenbankpfad))
    return AppTest.from_file(ANWENDUNGSPFAD).run()


def _schaltflaeche(anwendung: AppTest, beschriftung: str):  # type: ignore[no-untyped-def]
    return next(element for element in anwendung.button if element.label == beschriftung)


def test_anwendung_startet_und_zeigt_formular(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Die Anwendung startet ohne Ausnahme und zeigt zentrale Eingaben."""
    anwendung = _anwendung_starten(tmp_path, monkeypatch)

    assert not anwendung.exception
    assert anwendung.title[0].value == "Datengetriebene konzeptionelle Modellierung"
    assert any(element.label == "Projektbezeichnung" for element in anwendung.text_input)
    assert any(element.label == "Problemstellung" for element in anwendung.text_area)
    assert any(element.label == "Projektstatus" for element in anwendung.selectbox)


def test_neues_entwurfsprojekt_kann_gespeichert_werden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ein neues Projekt mit unvollständigem Auftrag kann als Entwurf gespeichert werden."""
    anwendung = _anwendung_starten(tmp_path, monkeypatch)
    anwendung.text_input[0].set_value("Bedienbares Projekt")

    _schaltflaeche(anwendung, "Projekt speichern").click().run()

    assert not anwendung.exception
    assert any("erfolgreich gespeichert" in element.value for element in anwendung.success)
    service = erstelle_projekt_service()
    assert [projekt.bezeichnung for projekt in service.projekte_auflisten()] == [
        "Bedienbares Projekt"
    ]


def test_unvollstaendiges_aktives_projekt_zeigt_fachlichen_fehler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Die Statusinvariante wird als verständliche Fehlermeldung angezeigt."""
    anwendung = _anwendung_starten(tmp_path, monkeypatch)
    anwendung.text_input[0].set_value("Unvollständiges Projekt")
    projektstatus = next(
        element for element in anwendung.selectbox if element.label == "Projektstatus"
    )
    projektstatus.select("aktiv")

    _schaltflaeche(anwendung, "Projekt speichern").click().run()

    assert not anwendung.exception
    assert any("nur als Entwurf" in element.value for element in anwendung.error)


def test_gespeichertes_projekt_wird_erneut_geladen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Persistierte Projektwerte werden beim Start in das Formular geladen."""
    datenbankpfad = tmp_path / "streamlit.sqlite"
    monkeypatch.setenv(DATENBANKPFAD_UMGEBUNGSVARIABLE, str(datenbankpfad))
    service = erstelle_projekt_service()
    service.projekt_anlegen(
        bezeichnung="Bereits gespeichert",
        untersuchungsauftrag=Untersuchungsauftrag(
            problemstellung="Problem",
            zielsetzung="Ziel",
            systemtyp=Systemtyp.PRODUKTION,
            systemgrenze="Grenze",
        ),
    )

    anwendung = AppTest.from_file(ANWENDUNGSPFAD).run()
    projektauswahl = next(
        element
        for element in anwendung.selectbox
        if element.label == "Vorhandenes Projekt auswählen"
    )
    projektauswahl.select_index(1).run()

    assert not anwendung.exception
    assert anwendung.text_input[0].value == "Bereits gespeichert"
    problemstellung = next(
        element for element in anwendung.text_area if element.label == "Problemstellung"
    )
    assert problemstellung.value == "Problem"
