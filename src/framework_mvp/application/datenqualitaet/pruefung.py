# ruff: noqa: E501
# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportOperatorIssue=false, reportReturnType=false
"""Reine Ausführung standardisierter Event-Log-Qualitätsregeln."""

import json
from dataclasses import dataclass

import pandas as pd

from framework_mvp.domain.models import (
    Qualitaetsbefund,
    Qualitaetsdimension,
    Qualitaetsregel,
    Schweregrad,
)


@dataclass(frozen=True, slots=True)
class QualitaetspruefungErgebnis:
    """Gesamtkennzahlen und Befunde einer vollständigen Prüfung."""

    ereignisanzahl: int
    fallanzahl: int
    bestandene_regeln: int
    befunde: tuple[Qualitaetsbefund, ...]


def _regel(
    regel_id: str,
    name: str,
    dimension: Qualitaetsdimension,
    schwere: Schweregrad,
    *,
    parameter: dict[str, object] | None = None,
    reaktion: str = "",
) -> Qualitaetsregel:
    if not reaktion:
        if regel_id in {"ungueltiger_zeitstempel"}:
            reaktion = "Import und Datentyp in Framework-Schritt 2 prüfen."
        elif regel_id in {
            "fehlende_fall_id",
            "fehlende_aktivitaet",
            "fehlender_zeitstempel",
        }:
            reaktion = "Semantische Rollen in Framework-Schritt 3 prüfen."
        elif regel_id in {"doppelte_quellzeile", "lifecycle_paarung"}:
            reaktion = "Event-Log-Aufbau in Framework-Schritt 4 prüfen."
        else:
            reaktion = "In Framework-Schritt 5 fachlich bewerten."
    return Qualitaetsregel(
        regel_id,
        name,
        dimension,
        schwere,
        True,
        json.dumps(parameter or {}, ensure_ascii=False, sort_keys=True),
        name,
        reaktion,
    )


def standardregeln() -> tuple[Qualitaetsregel, ...]:
    """Liefert alle verpflichtenden Regeln mit konservativen Standardparametern."""
    v = Qualitaetsdimension.VOLLSTAENDIGKEIT
    e = Qualitaetsdimension.EINDEUTIGKEIT
    z = Qualitaetsdimension.ZEITLICHE_PLAUSIBILITAET
    k = Qualitaetsdimension.KONSISTENZ
    return (
        _regel("fehlende_fall_id", "Fehlende oder leere Fall-ID", v, Schweregrad.BLOCKIEREND),
        _regel("fehlende_aktivitaet", "Fehlende oder leere Aktivität", v, Schweregrad.FEHLER),
        _regel("fehlender_zeitstempel", "Fehlender Zeitstempel", v, Schweregrad.FEHLER),
        _regel(
            "ungueltiger_zeitstempel",
            "Nicht interpretierbarer Zeitstempel",
            Qualitaetsdimension.VALIDITAET,
            Schweregrad.FEHLER,
        ),
        _regel(
            "identische_ereignisse", "Vollständig identische Ereignisse", e, Schweregrad.WARNUNG
        ),
        _regel("fachlich_doppelt", "Gleiche Fall-ID, Aktivität und Zeit", e, Schweregrad.WARNUNG),
        _regel("doppelte_event_id", "Doppelte event_id", e, Schweregrad.BLOCKIEREND),
        _regel("doppelte_quellzeile", "Mehrfach vorkommende Quellzeile", e, Schweregrad.WARNUNG),
        _regel("start_nach_ende", "Startzeitpunkt nach Endzeitpunkt", z, Schweregrad.FEHLER),
        _regel("negative_dauer", "Negative Ereignisdauer", z, Schweregrad.FEHLER),
        _regel(
            "ruecklaeufige_zeit", "Rückläufige ursprüngliche Ereignisfolge", z, Schweregrad.WARNUNG
        ),
        _regel(
            "identische_zeit",
            "Identische Zeitstempel innerhalb eines Falls",
            z,
            Schweregrad.INFORMATION,
        ),
        _regel(
            "extreme_wartezeit",
            "Extreme Wartezeit",
            z,
            Schweregrad.WARNUNG,
            parameter={"iqr_faktor": 1.5},
        ),
        _regel(
            "extreme_dauer",
            "Extreme Ereignisdauer",
            z,
            Schweregrad.WARNUNG,
            parameter={"iqr_faktor": 1.5},
        ),
        _regel("einzelereignis", "Fall mit nur einem Ereignis", k, Schweregrad.INFORMATION),
        _regel(
            "fehlender_start",
            "Fall ohne erkennbare Startaktivität",
            k,
            Schweregrad.INFORMATION,
            parameter={"aktivitaeten": ["Start"]},
        ),
        _regel(
            "fehlendes_ende",
            "Fall ohne erkennbare Endaktivität",
            k,
            Schweregrad.INFORMATION,
            parameter={"aktivitaeten": ["Ende"]},
        ),
        _regel(
            "viele_ereignisse",
            "Sehr viele Ereignisse je Fall",
            k,
            Schweregrad.WARNUNG,
            parameter={"schwelle": 100},
        ),
        _regel(
            "seltene_aktivitaet",
            "Seltene Aktivität",
            k,
            Schweregrad.INFORMATION,
            parameter={"anteil": 0.01},
        ),
        _regel("leere_ressource", "Leere oder unbekannte Ressource", v, Schweregrad.INFORMATION),
        _regel("lifecycle_paarung", "Inkonsistente Lifecycle-Paarung", k, Schweregrad.WARNUNG),
        _regel("wechselndes_fallattribut", "Wechselndes Fallattribut", k, Schweregrad.WARNUNG),
    )


def _maske(daten: pd.DataFrame, regel: Qualitaetsregel) -> tuple[pd.Series, tuple[str, ...]]:
    index = daten.index
    falsch = pd.Series(False, index=index)
    rid = regel.regel_id
    if rid == "fehlende_fall_id":
        return daten["case_id"].isna() | daten["case_id"].astype("string").str.strip().eq(""), (
            "case_id",
        )
    if rid == "fehlende_aktivitaet":
        return daten["activity"].isna() | daten["activity"].astype("string").str.strip().eq(""), (
            "activity",
        )
    if rid == "fehlender_zeitstempel":
        return daten["timestamp"].isna(), ("timestamp",)
    if rid == "ungueltiger_zeitstempel":
        if "_timestamp_raw" in daten:
            roh = daten["_timestamp_raw"].astype("string")
            return (
                roh.notna() & roh.str.strip().ne("") & pd.to_datetime(roh, errors="coerce").isna(),
                ("timestamp", "_timestamp_raw"),
            )
        return daten["timestamp"].notna() & pd.to_datetime(
            daten["timestamp"], errors="coerce"
        ).isna(), ("timestamp",)
    if rid == "identische_ereignisse":
        fachspalten = [
            wert
            for wert in daten.columns
            if wert != "event_id" and not str(wert).startswith("_source")
        ]
        return daten.duplicated(fachspalten, keep=False), tuple(str(wert) for wert in fachspalten)
    if rid == "fachlich_doppelt":
        return daten.duplicated(["case_id", "activity", "timestamp"], keep=False), (
            "case_id",
            "activity",
            "timestamp",
        )
    if rid == "doppelte_event_id":
        return daten["event_id"].duplicated(keep=False), ("event_id",)
    if rid == "doppelte_quellzeile" and "_source_row" in daten:
        subset = ["_source_row"]
        if "_source_timestamp_column" in daten:
            subset.append("_source_timestamp_column")
        return daten.duplicated(subset, keep=False), tuple(subset)
    if rid in {"start_nach_ende", "negative_dauer"} and {
        "start_timestamp",
        "end_timestamp",
    } <= set(daten):
        return pd.to_datetime(daten["start_timestamp"], errors="coerce") > pd.to_datetime(
            daten["end_timestamp"], errors="coerce"
        ), ("start_timestamp", "end_timestamp")
    if rid == "ruecklaeufige_zeit" and "_source_row" in daten:
        original = daten.sort_values(["case_id", "_source_row"], kind="stable")
        diff = (
            pd.to_datetime(original["timestamp"], errors="coerce")
            .groupby(original["case_id"])
            .diff()
        )
        return pd.Series(diff.lt(pd.Timedelta(0)).to_numpy(), index=original.index).reindex(
            index, fill_value=False
        ), ("timestamp",)
    if rid == "identische_zeit":
        return daten.duplicated(["case_id", "timestamp"], keep=False), ("case_id", "timestamp")
    if rid == "extreme_wartezeit":
        zeit = pd.to_datetime(daten["timestamp"], errors="coerce")
        dauer = zeit.groupby(daten["case_id"]).diff().dt.total_seconds()
        return _iqr_maske(dauer), ("timestamp",)
    if rid == "extreme_dauer" and {"start_timestamp", "end_timestamp"} <= set(daten):
        dauer = (
            pd.to_datetime(daten["end_timestamp"], errors="coerce")
            - pd.to_datetime(daten["start_timestamp"], errors="coerce")
        ).dt.total_seconds()
        return _iqr_maske(dauer), ("start_timestamp", "end_timestamp")
    if rid == "einzelereignis":
        return daten["case_id"].map(daten["case_id"].value_counts()).eq(1), ("case_id",)
    if rid == "fehlender_start":
        rohwerte = regel.parameter.get("aktivitaeten", ["Start"])
        werte = rohwerte if isinstance(rohwerte, list | tuple | set) else [rohwerte]
        aktivitaeten = {str(wert) for wert in werte}
        hat_start = daten["activity"].isin(aktivitaeten).groupby(daten["case_id"]).transform("any")
        return ~hat_start, ("activity",)
    if rid == "fehlendes_ende":
        rohwerte = regel.parameter.get("aktivitaeten", ["Ende"])
        werte = rohwerte if isinstance(rohwerte, list | tuple | set) else [rohwerte]
        aktivitaeten = {str(wert) for wert in werte}
        hat_ende = daten["activity"].isin(aktivitaeten).groupby(daten["case_id"]).transform("any")
        return ~hat_ende, ("activity",)
    if rid == "viele_ereignisse":
        groesse = daten["case_id"].map(daten["case_id"].value_counts())
        return groesse.gt(int(regel.parameter["schwelle"])), ("case_id",)
    if rid == "seltene_aktivitaet":
        anteile = daten["activity"].value_counts(normalize=True)
        return daten["activity"].map(anteile).lt(float(regel.parameter["anteil"])), ("activity",)
    if rid == "leere_ressource" and "resource" in daten:
        return daten["resource"].isna() | daten["resource"].astype("string").str.strip().eq(""), (
            "resource",
        )
    if rid == "lifecycle_paarung" and "lifecycle" in daten:
        return _lifecycle_maske(daten), ("lifecycle",)
    if rid == "wechselndes_fallattribut":
        fallattribute = [
            wert for wert in daten.columns if str(wert).startswith("case_") and wert != "case_id"
        ]
        if fallattribute:
            betroffen = falsch.copy()
            for name in fallattribute:
                wechsel = daten.groupby("case_id")[name].transform("nunique").gt(1)
                betroffen |= wechsel
            return betroffen, tuple(fallattribute)
    return falsch, ()


def _iqr_maske(werte: pd.Series) -> pd.Series:
    gueltig = werte.dropna()
    if gueltig.empty:
        return pd.Series(False, index=werte.index)
    q1, q3 = gueltig.quantile([0.25, 0.75])
    iqr = q3 - q1
    return (werte < q1 - 1.5 * iqr) | (werte > q3 + 1.5 * iqr)


def _lifecycle_maske(daten: pd.DataFrame) -> pd.Series:
    erlaubt = {"start", "complete"}
    normal = daten["lifecycle"].astype("string").str.lower()
    ungueltig = ~normal.isin(erlaubt) & normal.notna()
    for _, gruppe in daten.assign(_lc=normal).groupby(["case_id", "activity"], dropna=False):
        offene_starts: list[int] = []
        for index, wert in gruppe["_lc"].items():
            if wert == "start":
                if offene_starts:
                    ungueltig.loc[index] = True
                offene_starts.append(index)
            elif wert == "complete":
                if not offene_starts:
                    ungueltig.loc[index] = True
                else:
                    offene_starts.pop(0)
        if offene_starts:
            ungueltig.loc[offene_starts] = True
    return ungueltig


def pruefe_event_log(
    event_log: pd.DataFrame, regeln: tuple[Qualitaetsregel, ...]
) -> QualitaetspruefungErgebnis:
    """Prüft eine tiefe Arbeitskopie und verändert das Original nicht."""
    daten = event_log.copy(deep=True)
    befunde: list[Qualitaetsbefund] = []
    bestanden = 0
    for regel in regeln:
        if not regel.aktiviert:
            continue
        maske, spalten = _maske(daten, regel)
        maske = maske.fillna(False)
        anzahl = int(maske.sum())
        if not anzahl:
            bestanden += 1
            continue
        faelle = int(daten.loc[maske, "case_id"].nunique(dropna=True))
        befunde.append(
            Qualitaetsbefund(
                regel.regel_id,
                regel.bezeichnung,
                regel.dimension,
                regel.schweregrad,
                anzahl,
                faelle,
                anzahl / len(daten) if len(daten) else 0.0,
                tuple(int(wert) for wert in daten.index[maske][:5]),
                spalten,
                regel.beschreibung,
                regel.empfohlene_reaktion,
            )
        )
    return QualitaetspruefungErgebnis(
        len(daten),
        int(daten["case_id"].nunique(dropna=True)),
        bestanden,
        tuple(befunde),
    )


def filtere_befunde(
    befunde: tuple[Qualitaetsbefund, ...],
    *,
    dimensionen: tuple[str, ...] = (),
    schweregrade: tuple[str, ...] = (),
    regel_ids: tuple[str, ...] = (),
    spalten: tuple[str, ...] = (),
    aktivitaet: str = "",
    fall_id: str = "",
    event_log: pd.DataFrame | None = None,
) -> tuple[Qualitaetsbefund, ...]:
    """Filtert Befunde reproduzierbar nach fachlichen und technischen Kriterien."""
    ergebnis = []
    for wert in befunde:
        if dimensionen and wert.dimension.value not in dimensionen:
            continue
        if schweregrade and wert.schweregrad.value not in schweregrade:
            continue
        if regel_ids and wert.regel_id not in regel_ids:
            continue
        if spalten and not set(spalten) & set(wert.betroffene_spalten):
            continue
        if event_log is not None and (aktivitaet or fall_id):
            beispiele = event_log.loc[
                [index for index in wert.beispielindizes if index in event_log.index]
            ]
            if aktivitaet and aktivitaet not in set(beispiele["activity"].astype(str)):
                continue
            if fall_id and fall_id not in set(beispiele["case_id"].astype(str)):
                continue
        ergebnis.append(wert)
    return tuple(ergebnis)
