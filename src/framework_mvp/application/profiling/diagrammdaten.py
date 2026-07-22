"""Reine Aufbereitung aggregierter Diagrammdaten aus Profil und Quelldaten."""

from math import ceil, isfinite, sqrt

import numpy as np
import pandas as pd

from framework_mvp.application.profiling.datenprofil_erstellen import (
    MAXIMALE_HAEUFIGE_KATEGORIEN,
)
from framework_mvp.domain.models import (
    BoxplotDaten,
    Datenprofil,
    DatenprofilDiagramme,
    FehlwertDiagrammEintrag,
    HistogrammDaten,
    HistogrammKlasse,
    KategorieHaeufigkeit,
    NumerischeDiagrammdaten,
    Profiltyp,
    SpaltenDiagrammdaten,
)

MAXIMALE_HISTOGRAMM_KLASSEN = 100


def _endliche_werte(spalte: pd.Series) -> np.ndarray:
    numerisch = np.asarray(pd.Series(pd.to_numeric(spalte, errors="coerce")).tolist(), dtype=float)
    return numerisch[np.isfinite(numerisch)]


def erstelle_histogrammdaten(spalte: pd.Series) -> HistogrammDaten:
    """Aggregiert endliche Werte mit Freedman-Diaconis und stabilem Fallback."""
    werte = _endliche_werte(spalte)
    if len(werte) == 0:
        return HistogrammDaten((), None, 0)
    median = float(np.median(werte))
    minimum = float(np.min(werte))
    maximum = float(np.max(werte))
    if minimum == maximum:
        return HistogrammDaten(
            (HistogrammKlasse(minimum, maximum, len(werte)),), median, len(werte)
        )
    q1, q3 = np.quantile(werte, [0.25, 0.75])
    iqr = float(q3 - q1)
    breite = 2 * iqr / np.cbrt(len(werte)) if iqr > 0 and len(werte) > 1 else 0.0
    if breite > 0 and isfinite(breite):
        klassenanzahl = ceil((maximum - minimum) / breite)
    else:
        klassenanzahl = ceil(sqrt(len(werte)))
    klassenanzahl = max(1, min(klassenanzahl, MAXIMALE_HISTOGRAMM_KLASSEN))
    haeufigkeiten, grenzen = np.histogram(werte, bins=klassenanzahl)
    klassen = tuple(
        HistogrammKlasse(float(grenzen[index]), float(grenzen[index + 1]), int(anzahl))
        for index, anzahl in enumerate(haeufigkeiten)
    )
    return HistogrammDaten(klassen, median, len(werte))


def _boxplot(spalte: pd.Series, profil: Datenprofil, position: int) -> BoxplotDaten:
    numerisch = profil.spaltenprofile[position].numerisch
    werte = _endliche_werte(spalte)
    if numerisch is None or len(werte) == 0:
        return BoxplotDaten(None, None, None, None, None, 0)
    assert numerisch.untere_ausreissergrenze is not None
    assert numerisch.obere_ausreissergrenze is not None
    innerhalb = werte[
        (werte >= numerisch.untere_ausreissergrenze) & (werte <= numerisch.obere_ausreissergrenze)
    ]
    return BoxplotDaten(
        unterer_whisker=float(np.min(innerhalb)) if len(innerhalb) else numerisch.minimum,
        q1=numerisch.q1,
        median=numerisch.median,
        q3=numerisch.q3,
        oberer_whisker=float(np.max(innerhalb)) if len(innerhalb) else numerisch.maximum,
        ausreisser=numerisch.potenzielle_ausreisser,
    )


def _kategoriedaten(profil: Datenprofil, position: int) -> tuple[KategorieHaeufigkeit, ...]:
    kategorial = profil.spaltenprofile[position].kategorial
    if kategorial is None:
        return ()
    hauptwerte = list(kategorial.haeufigste_werte[:MAXIMALE_HAEUFIGE_KATEGORIEN])
    rest = kategorial.haeufigste_werte[MAXIMALE_HAEUFIGE_KATEGORIEN:]
    if rest:
        anzahl = sum(eintrag.anzahl for eintrag in rest)
        anteil = sum(eintrag.anteil for eintrag in rest)
        hauptwerte.append(KategorieHaeufigkeit("Weitere", anzahl, anteil))
    return tuple(hauptwerte)


def erstelle_diagrammdaten(daten: pd.DataFrame, profil: Datenprofil) -> DatenprofilDiagramme:
    """Erzeugt ausschließlich aggregierte, stabil sortierte Diagrammdaten."""
    sortierte_profile = sorted(
        profil.spaltenprofile,
        key=lambda wert: (
            -(wert.fehlwerte.anteil_echter_fehlwerte + wert.fehlwerte.anteil_platzhalter),
            wert.spaltenname,
        ),
    )
    fehlwerte = tuple(
        eintrag
        for spaltenprofil in sortierte_profile
        for eintrag in (
            FehlwertDiagrammEintrag(
                spaltenprofil.spaltenname,
                "Echte Fehlwerte",
                spaltenprofil.fehlwerte.echte_fehlwerte,
                spaltenprofil.fehlwerte.anteil_echter_fehlwerte,
            ),
            FehlwertDiagrammEintrag(
                spaltenprofil.spaltenname,
                "Textuelle Platzhalter",
                spaltenprofil.fehlwerte.platzhalter,
                spaltenprofil.fehlwerte.anteil_platzhalter,
            ),
        )
    )
    spaltendaten: list[SpaltenDiagrammdaten] = []
    for position, spaltenprofil in enumerate(profil.spaltenprofile):
        if spaltenprofil.profiltyp is Profiltyp.NUMERISCH:
            numerisch = NumerischeDiagrammdaten(
                erstelle_histogrammdaten(daten.iloc[:, position]),
                _boxplot(daten.iloc[:, position], profil, position),
            )
            spaltendaten.append(
                SpaltenDiagrammdaten(spaltenprofil.spaltenname, numerisch=numerisch)
            )
        elif spaltenprofil.profiltyp is Profiltyp.KATEGORIAL:
            spaltendaten.append(
                SpaltenDiagrammdaten(
                    spaltenprofil.spaltenname,
                    kategorien=_kategoriedaten(profil, position),
                )
            )
        elif spaltenprofil.profiltyp is Profiltyp.ZEITBEZOGEN:
            assert spaltenprofil.zeitbezogen is not None
            spaltendaten.append(
                SpaltenDiagrammdaten(
                    spaltenprofil.spaltenname,
                    zeitintervalle=spaltenprofil.zeitbezogen.aggregation,
                )
            )
        else:
            spaltendaten.append(SpaltenDiagrammdaten(spaltenprofil.spaltenname))
    return DatenprofilDiagramme(fehlwerte, tuple(spaltendaten))
