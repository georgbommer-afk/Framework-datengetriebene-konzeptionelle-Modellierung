"""AppTest-Tests der getrennten Datenprofilvisualisierung."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

ANWENDUNGSPFAD = Path(__file__).parents[1] / "streamlit_datenprofil_app.py"


def _starten() -> AppTest:
    return AppTest.from_file(ANWENDUNGSPFAD).run()


def test_kennzahlen_spaltenuebersicht_und_fehlwertdiagramm() -> None:
    """Gesamtkennzahlen, Tabellen und das getrennte Fehlwertdiagramm werden angezeigt."""
    anwendung = _starten()
    assert not anwendung.exception
    labels = {wert.label for wert in anwendung.metric}
    assert {"Zeilen", "Spalten", "Echte Fehlwerte", "Textuelle Platzhalter"} <= labels
    assert len(anwendung.dataframe) >= 2
    assert anwendung.get("vega_lite_chart")


def test_numerische_detailspalte_zeigt_histogramm_median_und_boxplot() -> None:
    """Die numerische Standardauswahl zeigt aggregierte Diagramme und Median."""
    anwendung = _starten()
    assert any(wert.label == "Median" for wert in anwendung.metric)
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
