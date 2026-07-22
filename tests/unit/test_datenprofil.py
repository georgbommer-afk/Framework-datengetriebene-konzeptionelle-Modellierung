"""Tests der technischen Profilberechnung auf vollständigen Tabellen."""

from datetime import UTC

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from framework_mvp.application.profiling import erstelle_datenprofil
from framework_mvp.domain.models import Profiltyp, Spaltenprofil, Zeitgranularitaet


def _spalte(daten: pd.DataFrame, name: str) -> Spaltenprofil:
    return next(
        wert for wert in erstelle_datenprofil(daten).spaltenprofile if wert.spaltenname == name
    )


def test_echte_fehlwerte_und_text_nan_bleiben_getrennt() -> None:
    """Pandas-Fehlwerte werden nicht mit dem Textplatzhalter NaN vermischt."""
    daten = pd.DataFrame({"a": pd.Series([None, np.nan, pd.NA, pd.NaT, "NaN"], dtype="object")})
    profil = _spalte(daten, "a").fehlwerte
    assert profil.echte_fehlwerte == 4
    assert profil.platzhalter == 1
    assert {wert.bezeichnung: wert.anzahl for wert in profil.platzhalterklassen} == {"NaN": 1}


def test_alle_textuellen_platzhalter_und_grossschreibung() -> None:
    """Exakte Platzhalter werden nach strip und ohne Beachtung der Schreibweise erkannt."""
    daten = pd.DataFrame({"a": ["NULL", "null", "N/A", "NA", "-", "", "   ", "nAn"]})
    profil = _spalte(daten, "a").fehlwerte
    assert profil.platzhalter == 8
    klassen = {wert.bezeichnung for wert in profil.platzhalterklassen}
    assert klassen == {"NULL", "N/A", "NA", "-", "Leere Zeichenkette", "Nur Leerzeichen", "NaN"}


def test_aehnliche_regulaere_texte_sind_keine_platzhalter() -> None:
    """Die Erkennung verwendet keine unscharfe Teilzeichensuche."""
    profil = _spalte(pd.DataFrame({"a": ["NULLSTELLE", "N/A-Test", "NANometer"]}), "a")
    assert profil.fehlwerte.platzhalter == 0
    assert profil.fehlwerte.gueltige_regulaere_werte == 3


def test_profil_mutiert_queldaten_nicht() -> None:
    """Auch heterogene Fehlwerte werden im Original nicht ersetzt."""
    daten = pd.DataFrame({"a": [" NULL ", None, "Wert"]})
    erwartet = daten.copy(deep=True)
    erstelle_datenprofil(daten)
    assert_frame_equal(daten, erwartet)


def test_gesamtprofil_enthaelt_struktur_speicher_duplikate_und_summen() -> None:
    """Gesamtkennzahlen beruhen auf der vollständigen Tabelle."""
    daten = pd.DataFrame(
        {"zahl": [1.0, 1.0, np.nan], "text": ["A", "A", "NULL"], "leer": [None] * 3}
    )
    profil = erstelle_datenprofil(daten)
    assert (profil.zeilen, profil.spalten) == (3, 3)
    assert profil.speicherbedarf_bytes >= int(daten.memory_usage(deep=True).sum())
    assert profil.exakte_duplikate == 1
    assert profil.vollstaendig_leere_spalten == 1
    assert profil.echte_fehlwerte == 4
    assert profil.textuelle_platzhalter == 1
    assert profil.numerische_spalten == 1
    assert profil.kategoriale_spalten == 2


def test_numerische_statistik_und_ausreisser() -> None:
    """Median, Quartile, Stichprobenstreuung und IQR-Regel werden vollständig berechnet."""
    profil = _spalte(pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 100.0]}), "x").numerisch
    assert profil is not None
    assert (profil.minimum, profil.maximum, profil.mittelwert, profil.median) == (1, 100, 22, 3)
    assert profil.standardabweichung == pytest.approx(np.std([1, 2, 3, 4, 100], ddof=1))
    assert (profil.q1, profil.q3, profil.interquartilsabstand) == (2, 4, 2)
    assert (profil.untere_ausreissergrenze, profil.obere_ausreissergrenze) == (-1, 7)
    assert profil.potenzielle_ausreisser == 1


def test_konstante_und_einzelne_numerische_werte() -> None:
    """Konstanten haben IQR null; ein Einzelwert hat keine definierte Stichprobenstreuung."""
    konstant = _spalte(pd.DataFrame({"x": [5.0, 5.0, 5.0]}), "x").numerisch
    einzeln = _spalte(pd.DataFrame({"x": [5.0]}), "x").numerisch
    assert konstant is not None and konstant.interquartilsabstand == 0
    assert einzeln is not None and einzeln.standardabweichung is None


def test_vollstaendig_fehlende_numerische_spalte() -> None:
    """Eine numerische NaN-Spalte erhält keine erfundenen Statistiken."""
    profil = _spalte(pd.DataFrame({"x": [np.nan, np.nan]}), "x").numerisch
    assert profil is not None
    assert profil.gueltige_werte == 0
    assert profil.minimum is None


def test_unendliche_werte_werden_separat_gezaehlt() -> None:
    """Positive und negative Unendlichkeit fließen nicht in Kennzahlen ein."""
    profil = _spalte(pd.DataFrame({"x": [1.0, 3.0, np.inf, -np.inf]}), "x").numerisch
    assert profil is not None
    assert profil.unendliche_werte == 2
    assert profil.mittelwert == 2


def test_kategoriale_haeufigkeiten_sind_stabil_sortiert() -> None:
    """Gleiche Häufigkeiten werden nach ihrer Bezeichnung sortiert."""
    profil = _spalte(pd.DataFrame({"x": ["B", "A", "B", "A", "C"]}), "x").kategorial
    assert profil is not None
    assert [(wert.bezeichnung, wert.anzahl) for wert in profil.haeufigste_werte] == [
        ("A", 2),
        ("B", 2),
        ("C", 1),
    ]
    assert profil.eindeutige_auspraegungen == 3


def test_seltene_werte_unter_einem_prozent() -> None:
    """Die zentrale Schwelle zählt Werte mit einem Anteil strikt unter einem Prozent."""
    profil = _spalte(pd.DataFrame({"x": ["häufig"] * 100 + ["selten"]}), "x").kategorial
    assert profil is not None and profil.seltene_werte == 1


@pytest.mark.parametrize(
    ("gueltig", "ungueltig", "erwarteter_typ"),
    [(9, 1, Profiltyp.ZEITBEZOGEN), (8, 2, Profiltyp.KATEGORIAL)],
)
def test_zeitspaltenerkennung_verwendet_neunzig_prozent(
    gueltig: int, ungueltig: int, erwarteter_typ: Profiltyp
) -> None:
    """Textspalten werden exakt ab einer Erfolgsquote von 90 Prozent zeitbezogen."""
    werte = [f"2024-01-{tag:02d}" for tag in range(1, gueltig + 1)] + ["ungültig"] * ungueltig
    assert _spalte(pd.DataFrame({"zeit": werte}), "zeit").profiltyp is erwarteter_typ


def test_zeitprofil_zeitraum_quote_und_naive_werte() -> None:
    """Naive Eingaben bleiben naive Zeitpunkte und erhalten eine Erfolgsquote."""
    profil = _spalte(
        pd.DataFrame({"zeit": ["2024-01-01", "2024-01-02", "2024-01-03", "x"] * 3}),
        "zeit",
    ).zeitbezogen
    assert profil is None  # 75 Prozent reichen bewusst nicht aus
    profil = _spalte(
        pd.DataFrame({"zeit": [f"2024-01-{tag:02d}" for tag in range(1, 10)] + ["x"]}), "zeit"
    ).zeitbezogen
    assert profil is not None
    assert profil.erfolgsquote == 0.9
    assert profil.nicht_interpretierbare_werte == 1
    assert profil.fruehester_zeitpunkt is not None
    assert profil.fruehester_zeitpunkt.tzinfo is None


def test_datetime_mit_zeitzone_bleibt_zeitzonenbewusst() -> None:
    """Bereits zeitzonenbewusste Zeitwerte behalten ihre Zeitzone."""
    daten = pd.DataFrame({"zeit": pd.date_range("2024-01-01", periods=3, tz=UTC)})
    profil = _spalte(daten, "zeit").zeitbezogen
    assert profil is not None and profil.fruehester_zeitpunkt is not None
    assert profil.fruehester_zeitpunkt.utcoffset() is not None


def test_gemischte_zeitzonen_werden_nicht_stillschweigend_vereinheitlicht() -> None:
    """Naive und bewusste Zeitwerte werden weder verglichen noch nach UTC konvertiert."""
    daten = pd.DataFrame({"zeit": ["2024-01-01", "2024-01-02T00:00:00+01:00"]})
    profil = _spalte(daten, "zeit").zeitbezogen
    assert profil is not None
    assert profil.fruehester_zeitpunkt is None
    assert profil.granularitaet is None


@pytest.mark.parametrize(
    ("start", "ende", "granularitaet"),
    [
        ("2024-01-01 00:00", "2024-01-01 12:00", Zeitgranularitaet.STUNDE),
        ("2024-01-01", "2024-02-01", Zeitgranularitaet.TAG),
        ("2024-01-01", "2024-12-01", Zeitgranularitaet.WOCHE),
        ("2020-01-01", "2024-01-01", Zeitgranularitaet.MONAT),
    ],
)
def test_zeitgranularitaet_ist_deterministisch(
    start: str, ende: str, granularitaet: Zeitgranularitaet
) -> None:
    """Die Zeitspanne bestimmt reproduzierbar die Aggregationsgranularität."""
    profil = _spalte(pd.DataFrame({"zeit": pd.to_datetime([start, ende])}), "zeit").zeitbezogen
    assert profil is not None and profil.granularitaet is granularitaet
    assert sum(wert.anzahl for wert in profil.aggregation) == 2
