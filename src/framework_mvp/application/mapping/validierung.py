# pyright: reportArgumentType=false, reportReturnType=false
"""Reine Validierung ereignisorientierter und breiter Datensätze."""

from dataclasses import dataclass

import pandas as pd

from framework_mvp.domain.models import (
    MappingModus,
    MappingValidierung,
    MappingWarnung,
    SemantischesMapping,
    Warnungsstufe,
)

VIELE_EREIGNISSE_SCHWELLE = 100


@dataclass(frozen=True, slots=True)
class MappingErgebnis:
    """Standardisierte temporäre Ereignisvorschau und Validierungsbefund."""

    vorschau: pd.DataFrame
    vollstaendige_ereignisse: pd.DataFrame
    validierung: MappingValidierung


def _fall_id(daten: pd.DataFrame, mapping: SemantischesMapping) -> pd.Series:
    if not mapping.fall_id.spalten:
        return pd.Series(pd.NA, index=daten.index, dtype="string")
    teile = daten[list(mapping.fall_id.spalten)].astype("string")
    leer = teile.isna().any(axis=1) | teile.apply(
        lambda zeile: any(not str(wert).strip() for wert in zeile), axis=1
    )
    ergebnis = teile.fillna("").agg(mapping.fall_id.trennzeichen.join, axis=1).astype("string")
    ergebnis.loc[leer] = pd.NA
    return ergebnis


def _ereignisorientiert(daten: pd.DataFrame, mapping: SemantischesMapping) -> pd.DataFrame:
    ereignisse = pd.DataFrame(index=daten.index)
    ereignisse["case_id"] = _fall_id(daten, mapping)
    ereignisse["activity"] = (
        daten[mapping.aktivitaetsspalte]
        if mapping.aktivitaetsspalte in daten
        else pd.Series(pd.NA, index=daten.index)
    )
    ereignisse["timestamp"] = (
        daten[mapping.zeitstempelspalte]
        if mapping.zeitstempelspalte in daten
        else pd.Series(pd.NA, index=daten.index)
    )
    optionen = {
        "start_timestamp": mapping.startzeitstempelspalte,
        "end_timestamp": mapping.endzeitstempelspalte,
        "lifecycle": mapping.lifecycle_spalte,
        "resource": mapping.ressourcen_spalte,
    }
    for ziel, quelle in optionen.items():
        if quelle and quelle in daten:
            ereignisse[ziel] = daten[quelle]
    return ereignisse


def _breit(daten: pd.DataFrame, mapping: SemantischesMapping) -> pd.DataFrame:
    teile: list[pd.DataFrame] = []
    fall_ids = _fall_id(daten, mapping)
    for zuordnung in mapping.zeitstempelzuordnungen:
        teil = pd.DataFrame(
            {
                "case_id": fall_ids,
                "activity": zuordnung.aktivitaetsbezeichnung,
                "timestamp": daten[zuordnung.zeitstempelspalte],
            }
        )
        if zuordnung.ressourcenspalte:
            teil["resource"] = daten[zuordnung.ressourcenspalte]
        if zuordnung.statusspalte:
            teil["lifecycle"] = daten[zuordnung.statusspalte]
        teile.append(teil)
    if not teile:
        return pd.DataFrame(columns=["case_id", "activity", "timestamp"])
    return pd.concat(teile, ignore_index=True).loc[lambda wert: wert["timestamp"].notna()]


def validiere_mapping(daten: pd.DataFrame, mapping: SemantischesMapping) -> MappingErgebnis:
    """Erzeugt eine temporäre Standardvorschau und vollständige Qualitätskennzahlen."""
    ereignisse = (
        _ereignisorientiert(daten, mapping)
        if mapping.mapping_modus is MappingModus.EREIGNISORIENTIERT
        else _breit(daten, mapping)
    )
    case_text = ereignisse["case_id"].astype("string")
    activity_text = ereignisse["activity"].astype("string")
    fehlende_ids = int((case_text.isna() | case_text.str.strip().eq("")).sum())
    fehlende_aktivitaeten = int((activity_text.isna() | activity_text.str.strip().eq("")).sum())
    zeit = pd.to_datetime(ereignisse["timestamp"], errors="coerce")
    nicht_zeit = int(ereignisse["timestamp"].notna().sum() - zeit.notna().sum())
    start_nach_ende = 0
    if {"start_timestamp", "end_timestamp"} <= set(ereignisse.columns):
        start = pd.to_datetime(ereignisse["start_timestamp"], errors="coerce")
        ende = pd.to_datetime(ereignisse["end_timestamp"], errors="coerce")
        start_nach_ende = int((start > ende).sum())
    identisch = int(ereignisse.duplicated().sum())
    moeglich = int(ereignisse.duplicated(["case_id", "activity", "timestamp"], keep=False).sum())
    analyse = ereignisse.assign(_zeit=zeit).loc[lambda wert: wert["case_id"].notna()]
    gruppen = analyse.groupby("case_id", dropna=True, sort=False)
    groessen = gruppen.size()
    einzelne = int((groessen == 1).sum())
    viele = int((groessen > VIELE_EREIGNISSE_SCHWELLE).sum())
    unsortiert = sum(not gruppe["_zeit"].dropna().is_monotonic_increasing for _, gruppe in gruppen)
    warnungen: list[MappingWarnung] = []
    fehler = (
        ("FEHLENDE_FALL_ID", "Fall-IDs fehlen oder sind leer.", fehlende_ids),
        ("FEHLENDE_AKTIVITAET", "Aktivitäten fehlen oder sind leer.", fehlende_aktivitaeten),
        ("UNGUELTIGE_ZEIT", "Zeitstempel sind nicht interpretierbar.", nicht_zeit),
        ("START_NACH_ENDE", "Startzeitpunkte liegen nach Endzeitpunkten.", start_nach_ende),
    )
    for code, meldung, anzahl in fehler:
        if anzahl:
            warnungen.append(MappingWarnung(Warnungsstufe.FEHLER, code, meldung, anzahl))
    for code, meldung, anzahl in (
        ("DOPPELTE_EREIGNISSE", "Mögliche doppelte Ereignisse wurden erkannt.", moeglich),
        (
            "UNSORTIERTE_FÄLLE",
            "Ereignisse sind innerhalb von Fällen zeitlich unsortiert.",
            unsortiert,
        ),
        ("EINZELEREIGNIS", "Fälle mit nur einem Ereignis wurden erkannt.", einzelne),
        ("VIELE_EREIGNISSE", "Fälle mit sehr vielen Ereignissen wurden erkannt.", viele),
    ):
        if anzahl:
            warnungen.append(MappingWarnung(Warnungsstufe.WARNUNG, code, meldung, anzahl))
    gueltig = not any(wert.stufe is Warnungsstufe.FEHLER for wert in warnungen)
    validierung = MappingValidierung(
        gueltig,
        fehlende_ids,
        fehlende_aktivitaeten,
        nicht_zeit,
        start_nach_ende,
        identisch,
        moeglich,
        einzelne,
        viele,
        int(activity_text.dropna().nunique()),
        int(case_text.dropna().nunique()),
        tuple(warnungen),
    )
    standard = ereignisse.copy(deep=True)
    standard["timestamp"] = zeit
    return MappingErgebnis(standard.head(200).copy(), standard, validierung)
