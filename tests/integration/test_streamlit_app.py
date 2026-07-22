"""Bedientests für die Streamlit-Anwendung."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from framework_mvp.bootstrap import DATENBANKPFAD_UMGEBUNGSVARIABLE, erstelle_projekt_service
from framework_mvp.domain.models import (
    BetrachtungszeitraumModus,
    LogistischeZielgroesse,
    Systemtyp,
    Untersuchungsauftrag,
)

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
    assert any(element.label == "Projektstatus" for element in anwendung.selectbox)
    assert anwendung.get("progress")
    assert any("Schritt 1 von 7" in element.value for element in anwendung.caption)
    assert all(
        any(name in element.value for element in anwendung.caption)
        for name in ("Projekt und beteiligte Personen", "Zusammenfassung und Speicherung")
    )


def test_person_kann_hinzugefuegt_und_entfernt_werden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dynamische Personenzeilen lassen sich vor dem Speichern verwalten."""
    anwendung = _anwendung_starten(tmp_path, monkeypatch)
    _schaltflaeche(anwendung, "Person hinzufügen").click().run()
    assert any(element.label == "Vorname" for element in anwendung.text_input)
    _schaltflaeche(anwendung, "Entfernen").click().run()
    assert not any(element.label == "Vorname" for element in anwendung.text_input)


def test_kpi_vorschlaege_reagieren_auf_zielauswahl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gewählte Zielgrößen erzeugen im Auswertungsschritt KPI-Kandidaten."""
    anwendung = _anwendung_starten(tmp_path, monkeypatch)
    anwendung.session_state["wizard_entwurf"]["zielgroessen"] = [
        LogistischeZielgroesse.DURCHLAUFZEIT
    ]
    anwendung.session_state["wizard_schritt"] = 5
    anwendung.run()
    assert any(element.label == "Gesamtdurchlaufzeit" for element in anwendung.checkbox)


def test_neues_entwurfsprojekt_kann_gespeichert_werden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ein neues Projekt mit unvollständigem Auftrag kann als Entwurf gespeichert werden."""
    anwendung = _anwendung_starten(tmp_path, monkeypatch)
    anwendung.text_input[0].set_value("Bedienbares Projekt")

    _schaltflaeche(anwendung, "Entwurf speichern").click().run()

    assert not anwendung.exception
    assert any("Entwurf wurde gespeichert" in element.value for element in anwendung.success)
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
    projektstatus.select_index(1)

    _schaltflaeche(anwendung, "Weiter").click().run()
    _schaltflaeche(anwendung, "Zurück").click().run()
    anwendung.session_state["wizard_schritt"] = 7
    anwendung.run()
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
            untersuchungszweck="Ziel",
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
    _schaltflaeche(anwendung, "Weiter").click().run()
    assert next(e for e in anwendung.text_area if e.label == "Problemstellung").value == "Problem"


@pytest.mark.parametrize("schritt", range(1, 8))
def test_entwurf_kann_aus_jedem_schritt_gespeichert_werden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, schritt: int
) -> None:
    """Jeder Wizard-Schritt bietet eine wirksame Entwurfsspeicherung."""
    anwendung = _anwendung_starten(tmp_path, monkeypatch)
    anwendung.session_state["wizard_entwurf"]["bezeichnung"] = f"Entwurf {schritt}"
    anwendung.session_state["wizard_schritt"] = schritt
    anwendung.run()
    _schaltflaeche(anwendung, "Entwurf speichern").click().run()
    assert not anwendung.exception
    assert any("Entwurf wurde gespeichert" in element.value for element in anwendung.success)


def test_systemtyp_steuert_spezifische_fragen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ein reines Intralogistiksystem zeigt keine Produktionsfragen."""
    anwendung = _anwendung_starten(tmp_path, monkeypatch)
    anwendung.session_state["wizard_entwurf"]["systemtyp"] = Systemtyp.INTRALOGISTIK
    anwendung.session_state["wizard_schritt"] = 4
    anwendung.run()
    assert any(element.label == "Hauptfunktionen" for element in anwendung.multiselect)
    assert not any(element.label == "Produktionsart" for element in anwendung.selectbox)


def test_manueller_zeitraum_zeigt_beide_datumsfelder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Der manuelle Modus zeigt Beginn und Ende zur Eingabe."""
    anwendung = _anwendung_starten(tmp_path, monkeypatch)
    anwendung.session_state["wizard_entwurf"]["zeitraum_modus"] = BetrachtungszeitraumModus.MANUELL
    anwendung.session_state["wizard_schritt"] = 6
    anwendung.run()
    assert {element.label for element in anwendung.date_input} == {"Beginn", "Ende"}
