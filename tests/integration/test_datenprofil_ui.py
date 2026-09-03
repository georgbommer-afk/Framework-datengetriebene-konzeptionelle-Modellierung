"""AppTest-Tests der getrennten Datenprofilvisualisierung."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

ANWENDUNGSPFAD = Path(__file__).parents[1] / "streamlit_datenprofil_app.py"

PLATZHALTER_APP = r"""
from uuid import UUID

import pandas as pd
import streamlit as st

from framework_mvp.application.datenimport_service import DatenimportService, bereite_vorschau_auf
from framework_mvp.domain.models import CsvImportparameter, DateiMetadaten, Dateityp
from framework_mvp.ui.pages.etl import _datenprofil_und_bestaetigung

zustand = st.session_state.setdefault("zustand", {})
if not zustand:
    daten = pd.DataFrame({"Status": ["A", "B", "A", "unbekannt", None]})
    zustand.update({
        "vorschau": bereite_vorschau_auf(
            daten, CsvImportparameter(erkanntes_trennzeichen=",")
        ),
        "vorschau_schluessel": "vorschau-1",
        "datei_metadaten": DateiMetadaten(
            "daten.csv", "daten.csv", 10, Dateityp.CSV, "a" * 64
        ),
    })

_datenprofil_und_bestaetigung(
    datenimport_service=DatenimportService(),
    importvorgang_service=object(),
    projekt_id=UUID("11111111-1111-1111-1111-111111111111"),
    zustand=zustand,
)
"""

NUMERISCH_APP = r"""
from uuid import UUID

import pandas as pd
import streamlit as st

from framework_mvp.application.datenimport_service import DatenimportService, bereite_vorschau_auf
from framework_mvp.domain.models import CsvImportparameter, DateiMetadaten, Dateityp
from framework_mvp.ui.pages.etl import _datenprofil_und_bestaetigung

zustand = st.session_state.setdefault("zustand", {})
if not zustand:
    daten = pd.DataFrame({"Wert": [1, 5, 10, 15]})
    zustand.update({
        "vorschau": bereite_vorschau_auf(
            daten, CsvImportparameter(erkanntes_trennzeichen=",")
        ),
        "vorschau_schluessel": "vorschau-1",
        "datei_metadaten": DateiMetadaten(
            "daten.csv", "daten.csv", 10, Dateityp.CSV, "b" * 64
        ),
    })

_datenprofil_und_bestaetigung(
    datenimport_service=DatenimportService(),
    importvorgang_service=object(),
    projekt_id=UUID("22222222-2222-2222-2222-222222222222"),
    zustand=zustand,
)
"""


def _starten() -> AppTest:
    return AppTest.from_file(ANWENDUNGSPFAD).run()


def test_kennzahlen_spaltenuebersicht_und_fehlwertdiagramm() -> None:
    """Gesamtkennzahlen, Tabellen und das getrennte Fehlwertdiagramm werden angezeigt."""
    anwendung = _starten()
    assert not anwendung.exception
    labels = {wert.label for wert in anwendung.metric}
    assert {"Zeilen", "Spalten", "Echte Fehlwerte", "Textuelle Platzhalter"} <= labels
    assert len(anwendung.dataframe) == 1
    assert anwendung.get("vega_lite_chart")


def test_numerische_detailspalte_zeigt_histogramm_median_und_boxplot() -> None:
    """Die numerische Standardauswahl zeigt aggregierte Diagramme und Median."""
    anwendung = _starten()
    assert any(wert.label == "Median" for wert in anwendung.metric)
    assert {
        "Minimum",
        "Maximum",
        "Mittelwert",
        "Median",
        "Q1",
        "Q3",
        "IQR",
    } <= {wert.label for wert in anwendung.metric}
    assert any("IQR-Regel" in wert.value for wert in anwendung.caption)
    assert any("aggregierte Histogrammklassen" in wert.value for wert in anwendung.caption)
    assert len(anwendung.get("vega_lite_chart")) >= 3


def test_kategoriale_detailspalte_zeigt_haeufigkeiten() -> None:
    """Eine geänderte Detailauswahl zeigt kategoriale Häufigkeiten."""
    anwendung = _starten()
    next(
        wert for wert in anwendung.selectbox if wert.label == "Spalte für Detailanalyse"
    ).set_value("Kategorie").run()
    assert not anwendung.exception
    assert any(wert.label == "Eindeutige reguläre Ausprägungen" for wert in anwendung.metric)
    assert any(wert.label == "Häufigster Wert (Modus)" for wert in anwendung.metric)
    assert not any(
        wert.value in {"Histogramm", "Kompakter Boxplot"} for wert in anwendung.subheader
    )
    assert any(wert.value == "Häufigkeitsverteilung" for wert in anwendung.subheader)


def test_zeitspalte_zeigt_zeitraum_und_aggregation() -> None:
    """Eine erkannte Zeitspalte zeigt Zeitraum, Quote und Granularität."""
    anwendung = _starten()
    next(
        wert for wert in anwendung.selectbox if wert.label == "Spalte für Detailanalyse"
    ).set_value("Zeit").run()
    assert not anwendung.exception
    assert any(wert.label == "Frühester Zeitpunkt" for wert in anwendung.metric)
    assert any("aggregiert" in wert.value for wert in anwendung.caption)


def test_vollstaendig_leere_spalte_zeigt_hinweis() -> None:
    """Eine vollständig leere Detailspalte erzeugt keinen leeren Chart."""
    anwendung = _starten()
    next(
        wert for wert in anwendung.selectbox if wert.label == "Spalte für Detailanalyse"
    ).set_value("Leer").run()
    assert not anwendung.exception
    assert any("vollständig leer" in wert.value for wert in anwendung.info)


def test_fehlwertplatzhalter_bleiben_ueber_reruns_erhalten() -> None:
    anwendung = AppTest.from_string(PLATZHALTER_APP).run()
    assert any(wert.label == "Spalte" for wert in anwendung.selectbox)
    eingabe = next(
        wert
        for wert in anwendung.text_input
        if wert.label.startswith("Bestätigte domänenspezifische Fehlwertplatzhalter")
    )

    eingabe.set_value("-, n/a, unbekannt").run()
    anwendung.run()

    assert anwendung.session_state["zustand"]["zusaetzliche_platzhalter"] == (
        "-",
        "n/a",
        "unbekannt",
    )
    assert (
        next(
            wert
            for wert in anwendung.text_input
            if wert.label.startswith("Bestätigte domänenspezifische Fehlwertplatzhalter")
        ).value
        == "-, n/a, unbekannt"
    )


def test_indikatorbedingung_wird_hinzugefuegt_angezeigt_und_entfernt() -> None:
    anwendung = AppTest.from_string(PLATZHALTER_APP).run()
    next(wert for wert in anwendung.text_input if wert.label == "Vergleichswert").set_value("A")
    next(wert for wert in anwendung.button if wert.label == "Bedingung hinzufügen").click().run()

    bedingungen = anwendung.session_state["zustand"]["indikatorbedingungen"]
    assert len(bedingungen) == 1
    assert bedingungen[0].vergleichswert == "A"
    assert any("2 Beobachtungen" in wert.value for wert in anwendung.markdown)

    next(wert for wert in anwendung.button if wert.label == "Entfernen").click().run()
    assert anwendung.session_state["zustand"]["indikatorbedingungen"] == ()


def test_mehrere_indikatorbedingungen_sind_in_der_zentralen_kachel_sichtbar() -> None:
    anwendung = AppTest.from_string(PLATZHALTER_APP).run()
    for vergleichswert in ("A", "B"):
        next(wert for wert in anwendung.text_input if wert.label == "Vergleichswert").set_value(
            vergleichswert
        )
        next(
            wert for wert in anwendung.button if wert.label == "Bedingung hinzufügen"
        ).click().run()
    assert len(anwendung.session_state["zustand"]["indikatorbedingungen"]) == 2
    assert sum(wert.label == "Entfernen" for wert in anwendung.button) == 2


def test_ungueltiger_indikatorvergleichswert_wird_verstaendlich_abgelehnt() -> None:
    anwendung = AppTest.from_string(NUMERISCH_APP).run()
    next(wert for wert in anwendung.text_input if wert.label == "Vergleichswert").set_value("abc")
    next(wert for wert in anwendung.button if wert.label == "Bedingung hinzufügen").click().run()

    assert any("kein gültiger Wert" in wert.value for wert in anwendung.error)
    assert "indikatorbedingungen" not in anwendung.session_state["zustand"]
