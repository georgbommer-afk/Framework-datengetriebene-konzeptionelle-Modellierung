# pyright: reportArgumentType=false, reportAttributeAccessIssue=false
"""Explizite Anwendung eines Qualitätsmaßnahmenplans auf einer Arbeitskopie."""

from dataclasses import dataclass

import pandas as pd

from framework_mvp.application.datenqualitaet.pruefung import (
    QualitaetspruefungErgebnis,
    _maske,
    pruefe_event_log,
)
from framework_mvp.domain.models import (
    Massnahmenaktion,
    Qualitaetsmassnahmenplan,
    Qualitaetsregel,
)


@dataclass(frozen=True, slots=True)
class Massnahmenergebnis:
    """Arbeitskopie und erneut berechnetes Qualitätsergebnis."""

    daten: pd.DataFrame
    pruefung: QualitaetspruefungErgebnis


def wende_massnahmen_an(
    event_log: pd.DataFrame,
    plan: Qualitaetsmassnahmenplan,
    regeln: tuple[Qualitaetsregel, ...],
) -> Massnahmenergebnis:
    """Wendet nur explizit konfigurierte Maßnahmen geordnet auf eine Kopie an."""
    daten = event_log.copy(deep=True)
    regel_map = {wert.regel_id: wert for wert in regeln}
    for massnahme in sorted(plan.massnahmen, key=lambda wert: wert.reihenfolge):
        regel = regel_map[massnahme.regel_id]
        maske, _ = _maske(daten, regel)
        maske = maske.fillna(False)
        if massnahme.aktion in {
            Massnahmenaktion.AKZEPTIEREN,
            Massnahmenaktion.ZURUECK_ZU_ETL,
            Massnahmenaktion.ZURUECK_ZU_MAPPING,
            Massnahmenaktion.FACHLICHE_PRUEFUNG,
        }:
            continue
        if massnahme.aktion is Massnahmenaktion.EREIGNISSE_MARKIEREN:
            daten[f"quality_{massnahme.regel_id}"] = maske
        elif massnahme.aktion is Massnahmenaktion.EREIGNISSE_AUSSCHLIESSEN:
            daten = daten.loc[~maske].copy()
        elif massnahme.aktion is Massnahmenaktion.FAELLE_AUSSCHLIESSEN:
            faelle = set(daten.loc[maske, "case_id"].dropna())
            daten = daten.loc[~daten["case_id"].isin(faelle)].copy()
        elif massnahme.aktion is Massnahmenaktion.DUPLIKATE_ENTFERNEN:
            daten = daten.drop_duplicates(keep="first").copy()
        elif massnahme.aktion is Massnahmenaktion.FESTEN_WERT_SETZEN:
            parameter = massnahme.parameter
            daten.loc[maske, str(parameter["spalte"])] = parameter["wert"]
    return Massnahmenergebnis(daten, pruefe_event_log(daten, regeln))
