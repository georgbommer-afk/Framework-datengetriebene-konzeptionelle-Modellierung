"""Tests der reinen Vorschauaufbereitung und Cache-Schlüssel."""

import pandas as pd
from pandas.testing import assert_frame_equal

from framework_mvp.application.datenimport_service import (
    DatenimportService,
    bereite_vorschau_auf,
)
from framework_mvp.domain.models import (
    CsvImportparameter,
    DateiMetadaten,
    Dateityp,
    Trennzeichenwahl,
)


def _parameter() -> CsvImportparameter:
    return CsvImportparameter(trennzeichenwahl=Trennzeichenwahl.KOMMA)


def test_vorschau_ist_auf_200_zeilen_begrenzt() -> None:
    """Die Vorschautabelle wird begrenzt, die Gesamtzahl jedoch nicht."""
    vorschau = bereite_vorschau_auf(pd.DataFrame({"a": range(250)}), _parameter())
    assert len(vorschau.tabelle) == 200
    assert vorschau.gesamtzeilen == 250


def test_spaltenzahl_namen_und_datentypen_bleiben_korrekt() -> None:
    """Strukturinformationen stammen aus dem vollständigen DataFrame."""
    vorschau = bereite_vorschau_auf(pd.DataFrame({"Nummer": [1], "Text": ["a"]}), _parameter())
    assert vorschau.gesamtspalten == 2
    assert vorschau.spaltennamen == ("Nummer", "Text")
    assert vorschau.pandas_datentypen == ("int64", "str")


def test_leere_und_nicht_leere_werte_werden_gezaehlt() -> None:
    """Die Spaltenstatistik zählt echte Pandas-Fehlwerte auf allen Zeilen."""
    vorschau = bereite_vorschau_auf(pd.DataFrame({"a": [1, None, 3, None]}), _parameter())
    statistik = vorschau.spaltenuebersicht[0]
    assert statistik.nicht_leere_werte == 2
    assert statistik.leere_werte == 2
    assert statistik.anteil_leerer_werte == 0.5


def test_quelldaten_werden_nicht_veraendert() -> None:
    """Weder Berechnung noch spätere Vorschauänderung mutieren den Ursprung."""
    daten = pd.DataFrame({"a": [1, 2]})
    erwartet = daten.copy(deep=True)
    vorschau = bereite_vorschau_auf(daten, _parameter())
    vorschau.tabelle.iloc[0, 0] = 99
    assert_frame_equal(daten, erwartet)


def test_cache_schluessel_beruecksichtigt_pruefsumme_und_parameter() -> None:
    """Datei- oder Parameteränderungen erzeugen verschiedene Schlüssel."""
    service = DatenimportService()
    metadaten = DateiMetadaten("a.csv", "a.csv", 1, Dateityp.CSV, "abc")
    komma = _parameter()
    semikolon = CsvImportparameter(trennzeichenwahl=Trennzeichenwahl.SEMIKOLON)
    assert service.cache_schluessel(metadaten, komma) != service.cache_schluessel(
        metadaten, semikolon
    )
    andere_datei = DateiMetadaten("b.csv", "b.csv", 1, Dateityp.CSV, "def")
    assert service.cache_schluessel(metadaten, komma) != service.cache_schluessel(
        andere_datei, komma
    )
