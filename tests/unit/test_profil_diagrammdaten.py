"""Tests für aggregierte, von Profilkennzahlen getrennte Diagrammdaten."""

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from framework_mvp.application.profiling import erstelle_datenprofil, erstelle_diagrammdaten
from framework_mvp.application.profiling.diagrammdaten import erstelle_histogrammdaten
from framework_mvp.ui.components.datenprofil_visualisierung import histogramm_spezifikation


def test_histogramm_ist_deterministisch_und_zaehlt_endliche_werte() -> None:
    """Gleiche Eingaben liefern gleiche Klassen mit vollständiger Häufigkeitssumme."""
    spalte = pd.Series([1, 2, 2, 3, 4, 100, np.inf])
    erstes = erstelle_histogrammdaten(spalte)
    zweites = erstelle_histogrammdaten(spalte)
    assert erstes == zweites
    assert sum(klasse.anzahl for klasse in erstes.klassen) == 6
    assert erstes.median == 2.5


def test_histogramm_fallback_bei_iqr_null() -> None:
    """Konstante Werte erzeugen genau eine stabile Histogrammklasse."""
    histogramm = erstelle_histogrammdaten(pd.Series([7, 7, 7]))
    assert len(histogramm.klassen) == 1
    assert histogramm.klassen[0].anzahl == 3


def test_histogramm_und_medianlayer_nutzen_den_vollstaendigen_wertebereich() -> None:
    daten = pd.DataFrame({"Kosten_EUR": [1.2, 12.0, 69.33, 691.2]})
    profil = erstelle_datenprofil(daten)
    diagramm = erstelle_diagrammdaten(daten, profil).spalten[0]
    histogramm = diagramm.numerisch.histogramm
    assert histogramm.klassen[0].untergrenze == 1.2
    assert histogramm.klassen[-1].obergrenze == 691.2
    spezifikation = histogramm_spezifikation(profil.spaltenprofile[0], diagramm)
    assert [layer["encoding"]["x"]["scale"]["domain"] for layer in spezifikation["layer"]] == [
        [1.2, 691.2],
        [1.2, 691.2],
    ]


def test_histogramm_mutiert_daten_nicht() -> None:
    """Die Diagrammaggregation verändert die numerische Quelle nicht."""
    spalte = pd.Series([1.0, np.nan, 3.0])
    erwartet = spalte.copy(deep=True)
    erstelle_histogrammdaten(spalte)
    assert_frame_equal(spalte.to_frame(), erwartet.to_frame())


def test_fehlwertdiagramm_enthaelt_alle_spalten_getrennt_und_sortiert() -> None:
    """Je Spalte bleiben echte Fehlwerte und Platzhalter getrennte Einträge."""
    daten = pd.DataFrame({"B": [None, "x"], "A": ["NULL", "x"], "C": ["x", "y"]})
    profil = erstelle_datenprofil(daten)
    diagramme = erstelle_diagrammdaten(daten, profil)
    assert len(diagramme.fehlwerte) == 6
    assert [wert.spaltenname for wert in diagramme.fehlwerte[::2]] == ["A", "B", "C"]
    assert {wert.art for wert in diagramme.fehlwerte} == {
        "Echte Fehlwerte",
        "Textuelle Platzhalter",
    }


def test_boxplotdaten_enthalten_whisker_und_ausreisserzahl() -> None:
    """Der Boxplot überträgt aggregierte Grenzen ohne Roh-Ausreißerpunkte."""
    daten = pd.DataFrame({"x": [1, 2, 3, 4, 100]})
    diagramm = erstelle_diagrammdaten(daten, erstelle_datenprofil(daten)).spalten[0]
    assert diagramm.numerisch is not None
    assert diagramm.numerisch.boxplot.unterer_whisker == 1
    assert diagramm.numerisch.boxplot.oberer_whisker == 4
    assert diagramm.numerisch.boxplot.ausreisser == 1


def test_kategorien_werden_auf_fuenfzehn_plus_weitere_begrenzt() -> None:
    """Weitere reguläre Kategorien werden nachvollziehbar zusammengefasst."""
    daten = pd.DataFrame({"x": [f"Wert {index:02d}" for index in range(20)]})
    diagramm = erstelle_diagrammdaten(daten, erstelle_datenprofil(daten)).spalten[0]
    assert len(diagramm.kategorien) == 16
    assert diagramm.kategorien[-1].bezeichnung == "Weitere"
    assert diagramm.kategorien[-1].anzahl == 5


def test_zeitliche_aggregation_bleibt_transiente_visualisierung() -> None:
    """Eine ergänzende Zeitgrafik bleibt von den fachlichen R-Werten getrennt."""
    daten = pd.DataFrame({"zeit": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-02"])})
    profil = erstelle_datenprofil(daten)
    diagramm = erstelle_diagrammdaten(daten, profil).spalten[0]
    assert sum(wert.anzahl for wert in diagramm.zeitintervalle) == 3
