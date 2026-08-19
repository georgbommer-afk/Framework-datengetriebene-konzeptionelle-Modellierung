"""Reine Schritt-7-Ableitungen für Ressourcen, Warte- und Zeitdaten in A_G."""

from collections.abc import Iterable, Mapping
from typing import Any, cast

import pandas as pd

from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    AktivitaetRessourcenZuordnung,
    Aktivitaetsbearbeitungszeit,
    RessourcenanalyseErgebnis,
    Ressourcenzuordnungsmodus,
    RobusteZeitstatistik,
    StrukturiertesErgebnisStatus,
    Uebergangswartezeit,
    WarteschlangenanalyseErgebnis,
    ZeitbezogeneDatenauswahlErgebnis,
)


def _text(wert: Any) -> str:
    if pd.isna(wert):
        return ""
    return str(wert).strip()


def _aktivitaeten(event_log: pd.DataFrame) -> tuple[str, ...]:
    if "activity" not in event_log.columns:
        return ()
    return tuple(sorted({_text(wert) for wert in event_log["activity"] if _text(wert)}))


def analysiere_ressourcen(
    event_log: pd.DataFrame,
    *,
    manuelle_zuordnungen: Mapping[str, Iterable[str]] | None = None,
    nicht_moeglich_begruendung: str = "",
) -> RessourcenanalyseErgebnis:
    """Schließt die Ressourcenentscheidung automatisch, manuell oder begründet offen ab."""
    aktivitaeten = _aktivitaeten(event_log)
    if not aktivitaeten:
        return RessourcenanalyseErgebnis(
            Ressourcenzuordnungsmodus.NICHT_MOEGLICH,
            "Schritt 7",
            (),
            "E* enthält keine auswertbaren Aktivitäten.",
        )

    automatisch: dict[str, set[str]] = {aktivitaet: set() for aktivitaet in aktivitaeten}
    if "resource" in event_log.columns:
        for aktivitaet, ressource in event_log.loc[:, ["activity", "resource"]].itertuples(
            index=False, name=None
        ):
            aktivitaet_text = _text(aktivitaet)
            ressourcen_text = _text(ressource)
            if aktivitaet_text in automatisch and ressourcen_text:
                automatisch[aktivitaet_text].add(ressourcen_text)
    if automatisch and all(automatisch.values()):
        return RessourcenanalyseErgebnis(
            Ressourcenzuordnungsmodus.AUTOMATISCH,
            "kanonische Ressourcenspalte in E*",
            tuple(
                AktivitaetRessourcenZuordnung(name, tuple(sorted(werte)))
                for name, werte in sorted(automatisch.items())
            ),
            quellspalte="resource",
        )

    if manuelle_zuordnungen is not None:
        normalisiert = {
            aktivitaet: tuple(
                sorted(
                    {
                        _text(wert)
                        for wert in manuelle_zuordnungen.get(aktivitaet, ())
                        if _text(wert)
                    }
                )
            )
            for aktivitaet in aktivitaeten
        }
        fehlend = [aktivitaet for aktivitaet, ressourcen in normalisiert.items() if not ressourcen]
        if fehlend:
            raise Domaenenfehler(
                "Die manuelle Ressourcenzuordnung ist nicht vollständig. Es fehlen: "
                + ", ".join(fehlend)
                + "."
            )
        return RessourcenanalyseErgebnis(
            Ressourcenzuordnungsmodus.MANUELL,
            "menschlich bestätigte Zuordnung in Schritt 7",
            tuple(
                AktivitaetRessourcenZuordnung(name, ressourcen)
                for name, ressourcen in sorted(normalisiert.items())
            ),
        )

    begruendung = nicht_moeglich_begruendung.strip()
    if not begruendung:
        begruendung = (
            "Die kanonische Ressourcenspalte fehlt oder ist nicht für alle Aktivitäten "
            "vollständig; es wurde keine vollständige manuelle Zuordnung bestätigt."
        )
    return RessourcenanalyseErgebnis(
        Ressourcenzuordnungsmodus.NICHT_MOEGLICH,
        "fachliche Entscheidung in Schritt 7",
        (),
        begruendung,
        "resource" if "resource" in event_log.columns else "",
    )


def _statistik(werte: list[float]) -> RobusteZeitstatistik:
    serie = pd.Series(werte, dtype="float64")
    return RobusteZeitstatistik(len(werte), float(serie.mean()), float(serie.median()))


def analysiere_warteschlangen(event_log: pd.DataFrame) -> WarteschlangenanalyseErgebnis:
    """Berechnet Start(B)-End(A) nur für fallweise aufeinanderfolgende Aktivitäten."""
    regel = (
        "Für je zwei aufeinanderfolgende Ereignisse desselben Falls: "
        "Start(B) − Ende(A); negative und nicht auswertbare Werte werden ausgeschlossen."
    )
    erforderlich = {"case_id", "activity", "start_timestamp", "end_timestamp"}
    if not erforderlich <= set(event_log.columns):
        fehlend = sorted(erforderlich - set(event_log.columns))
        return WarteschlangenanalyseErgebnis(
            StrukturiertesErgebnisStatus.NICHT_MOEGLICH,
            regel,
            (),
            0,
            0,
            "Erforderliche kanonische Spalten fehlen: " + ", ".join(fehlend) + ".",
        )

    daten = event_log.loc[:, ["case_id", "activity", "start_timestamp", "end_timestamp"]].copy(
        deep=True
    )
    daten["start_timestamp"] = pd.to_datetime(daten["start_timestamp"], errors="coerce", utc=True)
    daten["end_timestamp"] = pd.to_datetime(daten["end_timestamp"], errors="coerce", utc=True)
    daten["_reihenfolge"] = range(len(daten))
    gruppiert: dict[tuple[str, str], list[float]] = {}
    negativ = 0
    nicht_auswertbar = 0
    for case_id, fall in daten.groupby("case_id", sort=False, dropna=False):
        if not _text(case_id):
            nicht_auswertbar += max(len(fall) - 1, 0)
            continue
        sortiert = fall.sort_values(
            ["start_timestamp", "_reihenfolge"], kind="stable", na_position="last"
        )
        for position in range(len(sortiert) - 1):
            aktuell = sortiert.iloc[position]
            folgend = sortiert.iloc[position + 1]
            von = _text(aktuell["activity"])
            zu = _text(folgend["activity"])
            if (
                not von
                or not zu
                or pd.isna(aktuell["end_timestamp"])
                or pd.isna(folgend["start_timestamp"])
            ):
                nicht_auswertbar += 1
                continue
            sekunden = float(
                (folgend["start_timestamp"] - aktuell["end_timestamp"]).total_seconds()
            )
            if sekunden < 0:
                negativ += 1
                continue
            gruppiert.setdefault((von, zu), []).append(sekunden)
    uebergaenge = tuple(
        Uebergangswartezeit(von, zu, _statistik(werte))
        for (von, zu), werte in sorted(gruppiert.items())
    )
    if not uebergaenge:
        return WarteschlangenanalyseErgebnis(
            StrukturiertesErgebnisStatus.NICHT_MOEGLICH,
            regel,
            (),
            negativ,
            nicht_auswertbar,
            "Es verblieben keine nichtnegativen, auswertbaren Übergangswartezeiten.",
        )
    return WarteschlangenanalyseErgebnis(
        StrukturiertesErgebnisStatus.ABLEITBAR,
        regel,
        uebergaenge,
        negativ,
        nicht_auswertbar,
    )


def _bearbeitungszeiten(
    event_log: pd.DataFrame,
) -> tuple[tuple[Aktivitaetsbearbeitungszeit, ...], int, int]:
    erforderlich = {"activity", "start_timestamp", "end_timestamp"}
    if not erforderlich <= set(event_log.columns):
        return (), 0, len(event_log)
    daten = event_log.loc[:, ["activity", "start_timestamp", "end_timestamp"]].copy(deep=True)
    daten["start_timestamp"] = pd.to_datetime(daten["start_timestamp"], errors="coerce", utc=True)
    daten["end_timestamp"] = pd.to_datetime(daten["end_timestamp"], errors="coerce", utc=True)
    gruppiert: dict[str, list[float]] = {}
    negativ = 0
    nicht_auswertbar = 0
    for aktivitaet, start, ende in daten.itertuples(index=False, name=None):
        name = _text(aktivitaet)
        if not name or pd.isna(start) or pd.isna(ende):
            nicht_auswertbar += 1
            continue
        sekunden = float((ende - start).total_seconds())
        if sekunden < 0:
            negativ += 1
            continue
        gruppiert.setdefault(name, []).append(sekunden)
    return (
        tuple(
            Aktivitaetsbearbeitungszeit(name, _statistik(werte))
            for name, werte in sorted(gruppiert.items())
        ),
        negativ,
        nicht_auswertbar,
    )


def _zwischenankunftszeit(
    event_log: pd.DataFrame, ankunftsspalte: str
) -> tuple[RobusteZeitstatistik | None, str, int]:
    if "case_id" not in event_log.columns:
        return None, "nicht möglich: case_id fehlt", len(event_log)
    explizit = bool(ankunftsspalte)
    spalte = ankunftsspalte if explizit else "timestamp"
    if spalte not in event_log.columns:
        return None, f"nicht möglich: Spalte {spalte} fehlt", len(event_log)
    daten = event_log.loc[:, ["case_id", spalte]].copy(deep=True)
    daten[spalte] = pd.to_datetime(daten[spalte], errors="coerce", utc=True)
    ankuenfte: list[pd.Timestamp] = []
    ausgeschlossen = 0
    for case_id, fall in daten.groupby("case_id", sort=False, dropna=False):
        gueltig = cast(pd.Series, fall[spalte]).dropna()
        if not _text(case_id) or gueltig.empty:
            ausgeschlossen += 1
            continue
        if explizit and gueltig.nunique() != 1:
            ausgeschlossen += 1
            continue
        ankuenfte.append(cast(pd.Timestamp, gueltig.iloc[0] if explizit else gueltig.min()))
    ankuenfte.sort()
    differenzen = [
        float((ankuenfte[index] - ankuenfte[index - 1]).total_seconds())
        for index in range(1, len(ankuenfte))
    ]
    regel = (
        f"Expliziter Ankunftszeitpunkt je Fall aus E*.{spalte}; mehrdeutige Fälle ausgeschlossen."
        if explizit
        else "Erster gültiger kanonischer Ereigniszeitstempel E*.timestamp je Fall."
    )
    return (_statistik(differenzen) if differenzen else None), regel, ausgeschlossen


def analysiere_zeitbezogene_datenauswahl(
    zwischendaten: pd.DataFrame,
    event_log: pd.DataFrame,
    *,
    ankunftsspalte: str = "",
    datenbasis_referenzen: Mapping[str, Any] | None = None,
) -> ZeitbezogeneDatenauswahlErgebnis:
    """Dokumentiert Q/R/T/E* und berechnet nur eindeutig definierte Zeitgrößen."""
    warten = analysiere_warteschlangen(event_log)
    bearbeitung, negativ, nicht_auswertbar = _bearbeitungszeiten(event_log)
    zwischenankunft, ankunftsregel, ausgeschlossene_ankuenfte = _zwischenankunftszeit(
        event_log, ankunftsspalte
    )
    fallanzahl = (
        len(cast(pd.Series, event_log["case_id"]).dropna().unique())
        if "case_id" in event_log.columns
        else 0
    )
    aktivitaetsanzahl = (
        len(cast(pd.Series, event_log["activity"]).dropna().unique())
        if "activity" in event_log.columns
        else 0
    )
    ableitbar = bool(bearbeitung or warten.uebergaenge or zwischenankunft)
    begruendung = "" if ableitbar else "Aus den bestätigten Spalten war keine Zeitgröße ableitbar."
    return ZeitbezogeneDatenauswahlErgebnis(
        StrukturiertesErgebnisStatus.ABLEITBAR
        if ableitbar
        else StrukturiertesErgebnisStatus.NICHT_MOEGLICH,
        ("Q", "R", "T", "E*"),
        dict(datenbasis_referenzen or {}),
        tuple(
            {"name": str(name), "datentyp": str(typ)} for name, typ in zwischendaten.dtypes.items()
        ),
        tuple({"name": str(name), "datentyp": str(typ)} for name, typ in event_log.dtypes.items()),
        {
            "ereignisanzahl": len(event_log),
            "fallanzahl": fallanzahl,
            "aktivitaetsanzahl": aktivitaetsanzahl,
            "zeitraum_von": (
                pd.to_datetime(event_log["timestamp"], errors="coerce", utc=True).min()
                if "timestamp" in event_log.columns
                else None
            ),
            "zeitraum_bis": (
                pd.to_datetime(event_log["timestamp"], errors="coerce", utc=True).max()
                if "timestamp" in event_log.columns
                else None
            ),
        },
        bearbeitung,
        warten.uebergaenge,
        zwischenankunft,
        ankunftsregel,
        negativ,
        nicht_auswertbar,
        ausgeschlossene_ankuenfte,
        begruendung,
    )
