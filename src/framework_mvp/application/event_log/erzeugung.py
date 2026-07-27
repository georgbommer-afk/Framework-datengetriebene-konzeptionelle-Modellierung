# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportAssignmentType=false, reportReturnType=false
"""Reine Anwendung eines gespeicherten semantischen Mappings."""

import hashlib
from dataclasses import dataclass
from uuid import UUID

import pandas as pd

from framework_mvp.application.transformation import kombiniere_textspalten
from framework_mvp.domain.models import (
    Attributrolle,
    Ereignisrolle,
    MappingModus,
    SemantischesMapping,
)


@dataclass(frozen=True, slots=True)
class EventLogErgebnis:
    """Kanonische Ereignisse, Kennzahlen, Herkunft und Warnungen."""

    ereignisse: pd.DataFrame
    ereignisanzahl: int
    fallanzahl: int
    aktivitaetsanzahl: int
    fruehester_zeitpunkt: pd.Timestamp | None
    spaetester_zeitpunkt: pd.Timestamp | None
    herkunft_standardspalten: dict[str, str]
    attributrollen: dict[str, str]
    warnungen: tuple[str, ...]


def _fall_ids(daten: pd.DataFrame, mapping: SemantischesMapping) -> pd.Series:
    teile = daten[list(mapping.fall_id.spalten)].astype("string")
    leer = teile.isna().any(axis=1) | teile.apply(
        lambda zeile: any(not str(wert).strip() for wert in zeile), axis=1
    )
    ids = teile.fillna("").agg(mapping.fall_id.trennzeichen.join, axis=1).astype("string")
    ids.loc[leer] = pd.NA
    return ids


def _event_id(datensatz_id: UUID, mapping_id: UUID, quellzeile: int, herkunftsspalte: str) -> str:
    roh = f"{datensatz_id}|{mapping_id}|{quellzeile}|{herkunftsspalte}".encode()
    return hashlib.sha256(roh).hexdigest()


def _attribute(
    daten: pd.DataFrame, mapping: SemantischesMapping, ziel: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, str]]:
    rollen: dict[str, str] = {}
    for zuordnung in mapping.spaltenzuordnungen:
        if zuordnung.rolle is Attributrolle.IGNORIERT:
            continue
        if zuordnung.spaltenname in daten:
            zielname = (
                "source_event_id"
                if zuordnung.rolle is Ereignisrolle.QUELL_EREIGNIS_ID
                else zuordnung.spaltenname
            )
            ziel[zielname] = daten[zuordnung.spaltenname].to_numpy()
            rollen[zuordnung.spaltenname] = zuordnung.rolle.value
    return ziel, rollen


def _ereignisorientiert(
    daten: pd.DataFrame, mapping: SemantischesMapping
) -> tuple[pd.DataFrame, dict[str, str], dict[str, str]]:
    quellzeilen = pd.Series(range(len(daten)), index=daten.index, dtype="int64")
    definition = mapping.wirksame_aktivitaetsdefinition
    if definition is None:
        aktivitaeten = pd.Series(pd.NA, index=daten.index)
        aktivitaetsherkunft = ""
    elif len(definition.quellspalten) == 1:
        aktivitaeten = daten[definition.quellspalten[0]]
        aktivitaetsherkunft = definition.quellspalten[0]
    else:
        aktivitaeten = kombiniere_textspalten(
            daten,
            definition.quellspalten,
            trennzeichen=definition.trennzeichen,
            praefix=definition.praefix,
            suffix=definition.suffix,
            fehlwertstrategie=definition.fehlwertstrategie,
            ersatztext=definition.ersatztext,
        )
        aktivitaetsherkunft = " + ".join(definition.quellspalten)
    ereignisse = pd.DataFrame(
        {
            "case_id": _fall_ids(daten, mapping),
            "activity": aktivitaeten,
            "timestamp": daten[mapping.zeitstempelspalte],
            "_source_row": quellzeilen,
            "_source_timestamp_column": mapping.zeitstempelspalte,
        }
    )
    optionen = {
        "start_timestamp": mapping.startzeitstempelspalte,
        "end_timestamp": mapping.endzeitstempelspalte,
        "lifecycle": mapping.lifecycle_spalte,
        "resource": mapping.ressourcen_spalte,
    }
    herkunft = {
        "case_id": mapping.fall_id.trennzeichen.join(mapping.fall_id.spalten),
        "activity": aktivitaetsherkunft,
        "timestamp": mapping.zeitstempelspalte,
    }
    for ziel, quelle in optionen.items():
        if quelle:
            ereignisse[ziel] = daten[quelle]
            herkunft[ziel] = quelle
    ereignisse, rollen = _attribute(daten, mapping, ereignisse)
    return ereignisse, herkunft, rollen


def _breit(
    daten: pd.DataFrame, mapping: SemantischesMapping
) -> tuple[pd.DataFrame, dict[str, str], dict[str, str]]:
    fall_ids = _fall_ids(daten, mapping)
    teile: list[pd.DataFrame] = []
    for zuordnung in mapping.zeitstempelzuordnungen:
        maske = daten[zuordnung.zeitstempelspalte].notna()
        index = daten.index[maske]
        teil = pd.DataFrame(
            {
                "case_id": fall_ids.loc[index].to_numpy(),
                "activity": zuordnung.aktivitaetsbezeichnung,
                "timestamp": daten.loc[index, zuordnung.zeitstempelspalte].to_numpy(),
                "_source_row": [int(daten.index.get_loc(wert)) for wert in index],
                "_source_timestamp_column": zuordnung.zeitstempelspalte,
            }
        )
        if zuordnung.ressourcenspalte:
            teil["resource"] = daten.loc[index, zuordnung.ressourcenspalte].to_numpy()
        if zuordnung.statusspalte:
            teil["lifecycle"] = daten.loc[index, zuordnung.statusspalte].to_numpy()
        for spalte in mapping.spaltenzuordnungen:
            if spalte.rolle is not Attributrolle.IGNORIERT:
                zielname = (
                    "source_event_id"
                    if spalte.rolle is Ereignisrolle.QUELL_EREIGNIS_ID
                    else spalte.spaltenname
                )
                teil[zielname] = daten.loc[index, spalte.spaltenname].to_numpy()
        teile.append(teil)
    ereignisse = (
        pd.concat(teile, ignore_index=True)
        if teile
        else pd.DataFrame(
            columns=[
                "case_id",
                "activity",
                "timestamp",
                "_source_row",
                "_source_timestamp_column",
            ]
        )
    )
    rollen = {
        wert.spaltenname: wert.rolle.value
        for wert in mapping.spaltenzuordnungen
        if wert.rolle is not Attributrolle.IGNORIERT
    }
    return (
        ereignisse,
        {
            "case_id": mapping.fall_id.trennzeichen.join(mapping.fall_id.spalten),
            "activity": "Aktivitätsbezeichnung der Zeitstempelzuordnung",
            "timestamp": "jeweilige konfigurierte Zeitstempelspalte",
        },
        rollen,
    )


def erzeuge_event_log(
    daten: pd.DataFrame,
    mapping: SemantischesMapping,
    zwischendatensatz_id: UUID,
) -> EventLogErgebnis:
    """Wendet das gespeicherte Mapping ohne Mutation auf eine tiefe Datenkopie an."""
    arbeitskopie = daten.copy(deep=True)
    ereignisse, herkunft, rollen = (
        _ereignisorientiert(arbeitskopie, mapping)
        if mapping.mapping_modus is MappingModus.EREIGNISORIENTIERT
        else _breit(arbeitskopie, mapping)
    )
    ereignisse["event_id"] = [
        _event_id(
            zwischendatensatz_id,
            mapping.mapping_id,
            int(zeile),
            str(spalte),
        )
        for zeile, spalte in zip(
            ereignisse["_source_row"],
            ereignisse["_source_timestamp_column"],
            strict=True,
        )
    ]
    ereignisse["_timestamp_raw"] = ereignisse["timestamp"].astype("string")
    zeit = pd.to_datetime(ereignisse["timestamp"], errors="coerce")
    ungueltig = int(ereignisse["timestamp"].notna().sum() - zeit.notna().sum())
    warnungen: list[str] = []
    if ungueltig:
        warnungen.append(f"{ungueltig} Zeitstempel sind nicht interpretierbar.")
    if getattr(zeit.dt, "tz", None) is None and zeit.notna().any():
        warnungen.append(
            "Zeitstempel sind zeitzonenlos; es wurde keine Zeitzone oder UTC-Annahme ergänzt."
        )
    ereignisse["timestamp"] = zeit
    for name in ("start_timestamp", "end_timestamp"):
        if name in ereignisse:
            ereignisse[name] = pd.to_datetime(ereignisse[name], errors="coerce")
    if {"start_timestamp", "end_timestamp"} <= set(ereignisse):
        anzahl = int((ereignisse["start_timestamp"] > ereignisse["end_timestamp"]).sum())
        if anzahl:
            warnungen.append(f"{anzahl} Startzeitpunkte liegen nach dem Endzeitpunkt.")
    ereignisse = ereignisse.sort_values(
        ["case_id", "timestamp", "_source_row", "_source_timestamp_column"],
        kind="stable",
        na_position="last",
    ).reset_index(drop=True)
    gueltige_zeit = ereignisse["timestamp"].dropna()
    return EventLogErgebnis(
        ereignisse,
        len(ereignisse),
        int(ereignisse["case_id"].nunique(dropna=True)),
        int(ereignisse["activity"].nunique(dropna=True)),
        gueltige_zeit.min() if not gueltige_zeit.empty else None,
        gueltige_zeit.max() if not gueltige_zeit.empty else None,
        {**herkunft, "event_id": "stabiler SHA-256 aus Datensatz, Mapping und Quellbezug"},
        rollen,
        tuple(warnungen),
    )
