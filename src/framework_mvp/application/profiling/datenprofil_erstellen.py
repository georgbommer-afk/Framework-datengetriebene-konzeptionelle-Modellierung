"""Reine Berechnung technischer Profile auf vollständigen DataFrames."""

import warnings
from collections import Counter
from datetime import timedelta
from typing import cast

import numpy as np
import pandas as pd
from pandas.api.types import is_datetime64_any_dtype, is_numeric_dtype

from framework_mvp.domain.models import (
    Datenprofil,
    Fehlwertprofil,
    KategorialesSpaltenprofil,
    KategorieHaeufigkeit,
    NumerischesSpaltenprofil,
    PlatzhalterAnzahl,
    Profiltyp,
    Spaltenprofil,
    ZeitbezogenesSpaltenprofil,
    Zeitgranularitaet,
    ZeitintervallAggregation,
)

ZEIT_ERKENNUNG_MINDESTANTEIL = 0.9
SELTENE_WERTE_ANTEIL = 0.01
MAXIMALE_HAEUFIGE_KATEGORIEN = 15

_PLATZHALTER = {
    "": "Leere Zeichenkette",
    "NULL": "NULL",
    "NAN": "NaN",
    "N/A": "N/A",
    "NA": "NA",
    "-": "-",
}


def _platzhalterklasse(wert: object) -> str | None:
    if not isinstance(wert, str):
        return None
    bereinigt = wert.strip()
    if not bereinigt:
        return "Leere Zeichenkette" if wert == "" else "Nur Leerzeichen"
    return _PLATZHALTER.get(bereinigt.upper())


def _fehlwertprofil(spalte: pd.Series) -> tuple[Fehlwertprofil, pd.Series]:
    anzahl = len(spalte)
    echte_maske = spalte.isna()
    klassen = spalte.map(_platzhalterklasse)
    platzhalter_maske = klassen.notna() & ~echte_maske
    zaehler = Counter(str(wert) for wert in klassen[platzhalter_maske])
    echte = int(echte_maske.sum())
    platzhalter = int(platzhalter_maske.sum())
    profil = Fehlwertprofil(
        echte_fehlwerte=echte,
        anteil_echter_fehlwerte=echte / anzahl if anzahl else 0.0,
        platzhalter=platzhalter,
        anteil_platzhalter=platzhalter / anzahl if anzahl else 0.0,
        platzhalterklassen=tuple(
            PlatzhalterAnzahl(name, wert) for name, wert in sorted(zaehler.items())
        ),
        gueltige_regulaere_werte=anzahl - echte - platzhalter,
    )
    return profil, ~(echte_maske | platzhalter_maske)


def _numerisches_profil(spalte: pd.Series, regulaer: pd.Series) -> NumerischesSpaltenprofil:
    numerisch = pd.Series(pd.to_numeric(spalte[regulaer], errors="coerce"), dtype="float64")
    alle_werte = np.asarray(numerisch.tolist(), dtype=float)
    endlich = alle_werte[np.isfinite(alle_werte)]
    unendlich = int(np.isinf(alle_werte).sum())
    if len(endlich) == 0:
        return NumerischesSpaltenprofil(
            0, unendlich, None, None, None, None, None, None, None, None, None, None, 0
        )
    q1 = float(np.quantile(endlich, 0.25))
    q3 = float(np.quantile(endlich, 0.75))
    iqr = q3 - q1
    unten = q1 - 1.5 * iqr
    oben = q3 + 1.5 * iqr
    return NumerischesSpaltenprofil(
        gueltige_werte=len(endlich),
        unendliche_werte=unendlich,
        minimum=float(np.min(endlich)),
        maximum=float(np.max(endlich)),
        mittelwert=float(np.mean(endlich)),
        median=float(np.median(endlich)),
        standardabweichung=float(np.std(endlich, ddof=1)) if len(endlich) > 1 else None,
        q1=q1,
        q3=q3,
        interquartilsabstand=iqr,
        untere_ausreissergrenze=unten,
        obere_ausreissergrenze=oben,
        potenzielle_ausreisser=int(np.sum((endlich < unten) | (endlich > oben))),
    )


def _kategoriales_profil(spalte: pd.Series, regulaer: pd.Series) -> KategorialesSpaltenprofil:
    werte = [str(wert) for wert in spalte[regulaer]]
    zaehler = Counter(werte)
    gesamt = len(werte)
    sortiert = sorted(zaehler.items(), key=lambda eintrag: (-eintrag[1], eintrag[0]))
    haeufigkeiten = tuple(
        KategorieHaeufigkeit(name, anzahl, anzahl / gesamt if gesamt else 0.0)
        for name, anzahl in sortiert
    )
    selten = sum(
        anzahl for anzahl in zaehler.values() if gesamt and anzahl / gesamt < SELTENE_WERTE_ANTEIL
    )
    return KategorialesSpaltenprofil(gesamt, len(zaehler), haeufigkeiten, selten)


def _interpretiere_zeitwerte(
    spalte: pd.Series, regulaer: pd.Series
) -> tuple[list[pd.Timestamp], int, float]:
    werte = list(spalte[regulaer])
    interpretiert: list[pd.Timestamp] = []
    for wert in werte:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                zeitwert = cast(pd.Timestamp, pd.Timestamp(wert))
            if not pd.isna(zeitwert):
                interpretiert.append(zeitwert)
        except (TypeError, ValueError, OverflowError):
            continue
    nicht_interpretierbar = len(werte) - len(interpretiert)
    quote = len(interpretiert) / len(werte) if werte else 0.0
    return interpretiert, nicht_interpretierbar, quote


def _granularitaet(werte: list[pd.Timestamp]) -> Zeitgranularitaet | None:
    if not werte:
        return None
    differenz = max(werte) - min(werte)
    if differenz <= timedelta(days=2):
        return Zeitgranularitaet.STUNDE
    if differenz <= timedelta(days=90):
        return Zeitgranularitaet.TAG
    if differenz <= timedelta(days=730):
        return Zeitgranularitaet.WOCHE
    return Zeitgranularitaet.MONAT


def _intervallbeginn(wert: pd.Timestamp, granularitaet: Zeitgranularitaet) -> pd.Timestamp:
    if granularitaet is Zeitgranularitaet.STUNDE:
        return cast(pd.Timestamp, wert.floor("h"))
    if granularitaet is Zeitgranularitaet.TAG:
        return cast(pd.Timestamp, wert.normalize())
    if granularitaet is Zeitgranularitaet.WOCHE:
        wochenwert = cast(pd.Timestamp, wert - pd.Timedelta(days=wert.weekday()))
        return cast(pd.Timestamp, wochenwert.normalize())
    return cast(pd.Timestamp, pd.Timestamp(year=wert.year, month=wert.month, day=1, tz=wert.tz))


def _zeitprofil(spalte: pd.Series, regulaer: pd.Series) -> ZeitbezogenesSpaltenprofil:
    werte, nicht_interpretierbar, quote = _interpretiere_zeitwerte(spalte, regulaer)
    zeitzonenbewusstsein = {wert.utcoffset() is not None for wert in werte}
    if len(zeitzonenbewusstsein) > 1:
        return ZeitbezogenesSpaltenprofil(
            fruehester_zeitpunkt=None,
            spaetester_zeitpunkt=None,
            interpretierbare_werte=len(werte),
            nicht_interpretierbare_werte=nicht_interpretierbar,
            erfolgsquote=quote,
            granularitaet=None,
            aggregation=(),
        )
    granularitaet = _granularitaet(werte)
    aggregation: tuple[ZeitintervallAggregation, ...] = ()
    if granularitaet is not None:
        zaehler = Counter(_intervallbeginn(wert, granularitaet) for wert in werte)
        aggregation = tuple(
            ZeitintervallAggregation(intervall.to_pydatetime(), anzahl)
            for intervall, anzahl in sorted(zaehler.items(), key=lambda eintrag: eintrag[0])
        )
    return ZeitbezogenesSpaltenprofil(
        fruehester_zeitpunkt=min(werte).to_pydatetime() if werte else None,
        spaetester_zeitpunkt=max(werte).to_pydatetime() if werte else None,
        interpretierbare_werte=len(werte),
        nicht_interpretierbare_werte=nicht_interpretierbar,
        erfolgsquote=quote,
        granularitaet=granularitaet,
        aggregation=aggregation,
    )


def _spaltenprofil(name: object, spalte: pd.Series) -> Spaltenprofil:
    fehlwerte, regulaer = _fehlwertprofil(spalte)
    regulaere_spalte = pd.Series(spalte[regulaer])
    eindeutige = int(regulaere_spalte.nunique(dropna=True))
    if is_datetime64_any_dtype(spalte.dtype):
        zeitprofil = _zeitprofil(spalte, regulaer)
        return Spaltenprofil(
            str(name),
            str(spalte.dtype),
            Profiltyp.ZEITBEZOGEN,
            fehlwerte,
            eindeutige,
            zeitbezogen=zeitprofil,
        )
    if is_numeric_dtype(spalte.dtype):
        numerisch = _numerisches_profil(spalte, regulaer)
        return Spaltenprofil(
            str(name),
            str(spalte.dtype),
            Profiltyp.NUMERISCH,
            fehlwerte,
            eindeutige,
            numerisch=numerisch,
        )
    zeitprofil = _zeitprofil(spalte, regulaer)
    if (
        fehlwerte.gueltige_regulaere_werte
        and zeitprofil.erfolgsquote >= ZEIT_ERKENNUNG_MINDESTANTEIL
    ):
        return Spaltenprofil(
            str(name),
            str(spalte.dtype),
            Profiltyp.ZEITBEZOGEN,
            fehlwerte,
            eindeutige,
            zeitbezogen=zeitprofil,
        )
    if (
        spalte.dtype == "object"
        or isinstance(spalte.dtype, pd.StringDtype)
        or str(spalte.dtype) in {"category", "bool"}
    ):
        kategorial = _kategoriales_profil(spalte, regulaer)
        return Spaltenprofil(
            str(name),
            str(spalte.dtype),
            Profiltyp.KATEGORIAL,
            fehlwerte,
            eindeutige,
            kategorial=kategorial,
        )
    return Spaltenprofil(str(name), str(spalte.dtype), Profiltyp.SONSTIG, fehlwerte, eindeutige)


def erstelle_datenprofil(daten: pd.DataFrame) -> Datenprofil:
    """Berechnet ein nachvollziehbares Profil ohne Mutation des DataFrames."""
    profile = tuple(
        _spaltenprofil(name, daten.iloc[:, position]) for position, name in enumerate(daten.columns)
    )
    typen = Counter(profil.profiltyp for profil in profile)
    return Datenprofil(
        zeilen=len(daten),
        spalten=len(daten.columns),
        speicherbedarf_bytes=int(daten.memory_usage(index=True, deep=True).sum()),
        exakte_duplikate=int(daten.duplicated().sum()),
        vollstaendig_leere_spalten=sum(
            profil.fehlwerte.gueltige_regulaere_werte == 0 for profil in profile
        ),
        numerische_spalten=typen[Profiltyp.NUMERISCH],
        kategoriale_spalten=typen[Profiltyp.KATEGORIAL],
        zeitbezogene_spalten=typen[Profiltyp.ZEITBEZOGEN],
        sonstige_spalten=typen[Profiltyp.SONSTIG],
        echte_fehlwerte=sum(profil.fehlwerte.echte_fehlwerte for profil in profile),
        textuelle_platzhalter=sum(profil.fehlwerte.platzhalter for profil in profile),
        spaltenprofile=profile,
    )
