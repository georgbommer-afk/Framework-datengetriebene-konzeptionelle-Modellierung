# pyright: reportArgumentType=false, reportReturnType=false
"""Reine Validierung ereignisorientierter und breiter Datensätze."""

from dataclasses import dataclass

import pandas as pd

from framework_mvp.application.transformation import kombiniere_textspalten
from framework_mvp.domain.models import (
    Attributrolle,
    Ereignisrolle,
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
    definition = mapping.wirksame_aktivitaetsdefinition
    if definition is None or any(wert not in daten for wert in definition.quellspalten):
        ereignisse["activity"] = pd.Series(pd.NA, index=daten.index)
    elif len(definition.quellspalten) == 1:
        ereignisse["activity"] = daten[definition.quellspalten[0]]
    else:
        ereignisse["activity"] = kombiniere_textspalten(
            daten,
            definition.quellspalten,
            trennzeichen=definition.trennzeichen,
            praefix=definition.praefix,
            suffix=definition.suffix,
            fehlwertstrategie=definition.fehlwertstrategie,
            ersatztext=definition.ersatztext,
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
    for zuordnung in mapping.spaltenzuordnungen:
        if zuordnung.spaltenname not in daten or zuordnung.rolle is Attributrolle.IGNORIERT:
            continue
        ziel = (
            "source_event_id"
            if zuordnung.rolle is Ereignisrolle.QUELL_EREIGNIS_ID
            else zuordnung.spaltenname
        )
        ereignisse[ziel] = daten[zuordnung.spaltenname]
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
        for attribut in mapping.spaltenzuordnungen:
            if attribut.spaltenname not in daten or attribut.rolle is Attributrolle.IGNORIERT:
                continue
            ziel = (
                "source_event_id"
                if attribut.rolle is Ereignisrolle.QUELL_EREIGNIS_ID
                else attribut.spaltenname
            )
            teil[ziel] = daten[attribut.spaltenname]
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
    fehlende_zeit = int(ereignisse["timestamp"].isna().sum())
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
    definition = mapping.wirksame_aktivitaetsdefinition
    referenzen = {
        *mapping.fall_id.spalten,
        *(definition.quellspalten if definition else ()),
        mapping.zeitstempelspalte,
        mapping.startzeitstempelspalte,
        mapping.endzeitstempelspalte,
        mapping.lifecycle_spalte,
        mapping.ressourcen_spalte,
        *(wert.zeitstempelspalte for wert in mapping.zeitstempelzuordnungen),
        *(wert.spaltenname for wert in mapping.spaltenzuordnungen),
    }
    fehlende_spalten = sorted(wert for wert in referenzen if wert and wert not in daten)
    if fehlende_spalten:
        warnungen.append(
            MappingWarnung(
                Warnungsstufe.FEHLER,
                "FEHLENDE_SPALTEN",
                f"Referenzierte Spalten fehlen: {', '.join(fehlende_spalten)}.",
                len(fehlende_spalten),
            )
        )
    rollenbelegungen = [
        *mapping.fall_id.spalten,
        *(definition.quellspalten if definition else ()),
        mapping.zeitstempelspalte,
        mapping.startzeitstempelspalte,
        mapping.endzeitstempelspalte,
        mapping.lifecycle_spalte,
        mapping.ressourcen_spalte,
        *(wert.zeitstempelspalte for wert in mapping.zeitstempelzuordnungen),
        *(wert.spaltenname for wert in mapping.spaltenzuordnungen),
    ]
    belegte_spalten = [wert for wert in rollenbelegungen if wert]
    doppelte_belegungen = len(belegte_spalten) - len(set(belegte_spalten))
    if doppelte_belegungen:
        warnungen.append(
            MappingWarnung(
                Warnungsstufe.FEHLER,
                "DOPPELTE_ROLLENBELEGUNG",
                "Mindestens eine Spalte wurde mehreren Rollen zugeordnet.",
                doppelte_belegungen,
            )
        )
    if mapping.mapping_modus is MappingModus.BREITER_ZEITSTEMPELDATENSATZ:
        bezeichnungen = [wert.aktivitaetsbezeichnung for wert in mapping.zeitstempelzuordnungen]
        if not bezeichnungen or any(not wert for wert in bezeichnungen):
            warnungen.append(
                MappingWarnung(
                    Warnungsstufe.FEHLER,
                    "LEERE_ZEITSTEMPELDEFINITION",
                    "Mindestens eine Zeitstempelspalte mit Aktivitätsbezeichnung ist erforderlich.",
                )
            )
        if len(bezeichnungen) != len(set(bezeichnungen)):
            warnungen.append(
                MappingWarnung(
                    Warnungsstufe.FEHLER,
                    "DOPPELTE_AKTIVITAETSBEZEICHNUNG",
                    "Aktivitätsbezeichnungen der Zeitstempelspalten müssen eindeutig sein.",
                )
            )
    elif definition is None or not mapping.zeitstempelspalte:
        warnungen.append(
            MappingWarnung(
                Warnungsstufe.FEHLER,
                "FEHLENDE_PFLICHTROLLE",
                "Aktivität und Ereigniszeitstempel müssen definiert sein.",
            )
        )
    fehler = (
        ("FEHLENDE_FALL_ID", "Fall-IDs fehlen oder sind leer.", fehlende_ids),
        ("FEHLENDE_AKTIVITAET", "Aktivitäten fehlen oder sind leer.", fehlende_aktivitaeten),
        ("FEHLENDE_ZEIT", "Ereigniszeitstempel fehlen oder sind leer.", fehlende_zeit),
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
    if len(activity_text):
        kardinalitaet = int(activity_text.dropna().nunique())
        if kardinalitaet / len(activity_text) > 0.25:
            warnungen.append(
                MappingWarnung(
                    Warnungsstufe.WARNUNG,
                    "HOHE_AKTIVITAETSVIELFALT",
                    "Die Aktivitätsdefinition besitzt eine sehr hohe Vielfalt.",
                    kardinalitaet,
                )
            )
    fall_ids = _fall_id(daten, mapping)
    for zuordnung in mapping.spaltenzuordnungen:
        if zuordnung.rolle is not Attributrolle.FALLATTRIBUT:
            continue
        wechsel = int(
            pd.DataFrame({"fall": fall_ids, "wert": daten[zuordnung.spaltenname]})
            .groupby("fall", dropna=True)["wert"]
            .nunique(dropna=False)
            .gt(1)
            .sum()
        )
        if wechsel:
            warnungen.append(
                MappingWarnung(
                    Warnungsstufe.WARNUNG,
                    "WECHSELNDES_FALLATTRIBUT",
                    f"Das Fallattribut {zuordnung.spaltenname} wechselt innerhalb von Fällen.",
                    wechsel,
                )
            )
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
    return MappingErgebnis(standard.head(100).copy(), standard, validierung)
