# pyright: reportArgumentType=false, reportAttributeAccessIssue=false
# pyright: reportGeneralTypeIssues=false, reportOptionalMemberAccess=false
"""Getrennte Soll-/Ist-Performance und ressourcenbezogene Busy-Ratio."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pandas as pd

from framework_mvp.application.ergebnisaggregation.strukturierte_ergebnisse import (
    bearbeitungszeit_einer_ausfuehrung,
)
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    Bearbeitungszeitabweichungsstatistik,
    BusyRatioEinzelwert,
    BusyRatioErgebnis,
    BusyRatioKonfiguration,
    BusyRatioRessourcenstatistik,
    PerformanceZeitabweichung,
    PerformanceZeitvergleichErgebnis,
    PerformanceZeitvergleichKonfiguration,
    Terminabweichungsstatistik,
    Vorkommensregel,
)


def _spalten_pruefen(daten: pd.DataFrame, spalten: tuple[str, ...], quelle: str) -> None:
    fehlend = [wert for wert in spalten if not wert or wert not in daten.columns]
    if fehlend:
        raise Domaenenfehler(
            f"In {quelle} fehlen ausdrücklich zuzuordnende Spalten: " + ", ".join(fehlend)
        )


def _gueltige_schluessel(daten: pd.DataFrame, spalten: tuple[str, ...]) -> pd.Series:
    gueltig = pd.Series(True, index=daten.index, dtype="bool")
    for spalte in spalten:
        werte = daten[spalte]
        gueltig &= werte.notna() & werte.astype("string").str.strip().ne("")
    return gueltig


def _klassifikation_dt(sekunden: float) -> str:
    if sekunden > 0:
        return "verspätet"
    if sekunden < 0:
        return "vorzeitig"
    return "planmäßig"


def _klassifikation_db(sekunden: float) -> str:
    if sekunden > 0:
        return "länger als geplant"
    if sekunden < 0:
        return "kürzer als geplant"
    return "entspricht der geplanten Bearbeitungszeit"


def _vorkommen_zuordnen(
    soll: pd.DataFrame,
    ist: pd.DataFrame,
    konfiguration: PerformanceZeitvergleichKonfiguration,
) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    schluessel = ["_case", "_activity"]
    wiederholt = bool(soll.duplicated(schluessel, keep=False).any()) or bool(
        ist.duplicated(schluessel, keep=False).any()
    )
    if konfiguration.vorkommensregel is Vorkommensregel.AUFTRETENSNUMMER:
        if not konfiguration.soll_auftretensnummer_spalte:
            raise Domaenenfehler(
                "Die bestätigte Auftretensnummer benötigt eine Spalte in den Soll-Daten."
            )
        _spalten_pruefen(
            soll,
            (konfiguration.soll_auftretensnummer_spalte,),
            "den Soll-Daten",
        )
        soll["_vorkommen"] = pd.to_numeric(
            soll[konfiguration.soll_auftretensnummer_spalte], errors="coerce"
        ).astype("Int64")
        ungueltig = int(soll["_vorkommen"].isna().sum())
        soll = soll.loc[soll["_vorkommen"].notna()].copy()
        ist["_vorkommen"] = ist.groupby(schluessel, sort=False).cumcount() + 1
        return soll, ist, ungueltig
    if wiederholt:
        soll_gruppen = soll.groupby(schluessel, sort=False, dropna=False)
        ist_gruppen = ist.groupby(schluessel, sort=False, dropna=False)
        if konfiguration.vorkommensregel is Vorkommensregel.LETZTES:
            soll = soll_gruppen.tail(1).copy()
            ist = ist_gruppen.tail(1).copy()
        else:
            soll = soll_gruppen.head(1).copy()
            ist = ist_gruppen.head(1).copy()
    soll["_vorkommen"] = 1
    ist["_vorkommen"] = 1
    return soll, ist, 0


def _dt_statistik(werte: list[float]) -> Terminabweichungsstatistik | None:
    if not werte:
        return None
    serie = pd.Series(werte, dtype="float64")
    return Terminabweichungsstatistik(
        len(werte),
        sum(wert > 0 for wert in werte),
        sum(wert == 0 for wert in werte),
        sum(wert < 0 for wert in werte),
        float(serie.mean()),
        float(serie.median()),
    )


def _db_statistik(werte: list[float]) -> Bearbeitungszeitabweichungsstatistik | None:
    if not werte:
        return None
    serie = pd.Series(werte, dtype="float64")
    return Bearbeitungszeitabweichungsstatistik(
        len(werte),
        sum(wert > 0 for wert in werte),
        sum(wert == 0 for wert in werte),
        sum(wert < 0 for wert in werte),
        float(serie.mean()),
        float(serie.median()),
    )


def performance_zeitvergleich_berechnen(
    *,
    soll_daten: pd.DataFrame,
    event_log: pd.DataFrame,
    konfiguration: PerformanceZeitvergleichKonfiguration,
    auswertungs_id: UUID | None = None,
) -> PerformanceZeitvergleichErgebnis:
    """Berechnet dT nach Gl. 3.1 und dB nach Gl. 3.2 strikt getrennt."""
    if not (
        konfiguration.fertigstellungsabweichung_aktiv
        or konfiguration.bearbeitungszeitabweichung_aktiv
    ):
        raise Domaenenfehler("Mindestens dT oder dB muss ausdrücklich aktiviert sein.")
    soll_spalten = (
        konfiguration.soll_case_id_spalte,
        konfiguration.soll_activity_spalte,
        konfiguration.plan_ende_spalte,
    )
    ist_spalten = (
        konfiguration.ist_case_id_spalte,
        konfiguration.ist_activity_spalte,
        konfiguration.ist_ende_spalte,
    )
    if konfiguration.bearbeitungszeitabweichung_aktiv:
        soll_spalten = (*soll_spalten, konfiguration.plan_start_spalte)
        ist_spalten = (*ist_spalten, konfiguration.ist_start_spalte)
    _spalten_pruefen(soll_daten, soll_spalten, "den Soll-Daten")
    _spalten_pruefen(event_log, ist_spalten, "E*")
    soll_original = soll_daten.copy(deep=True)
    ist_original = event_log.copy(deep=True)
    soll = soll_daten.copy(deep=True)
    ist = event_log.copy(deep=True)
    soll_gueltig = _gueltige_schluessel(
        soll,
        (konfiguration.soll_case_id_spalte, konfiguration.soll_activity_spalte),
    )
    ist_gueltig = _gueltige_schluessel(
        ist,
        (konfiguration.ist_case_id_spalte, konfiguration.ist_activity_spalte),
    )
    ausschluss = {
        "ungueltiger_schluessel": int((~soll_gueltig).sum() + (~ist_gueltig).sum()),
        "ungueltige_auftretensnummer": 0,
        "nicht_zuordenbar": 0,
        "dt_zeitwert_fehlt": 0,
        "db_zeitwert_fehlt": 0,
        "negative_plan_bearbeitungszeit": 0,
        "negative_ist_bearbeitungszeit": 0,
    }
    soll = soll.loc[soll_gueltig].copy()
    ist = ist.loc[ist_gueltig].copy()
    soll["_case"] = soll[konfiguration.soll_case_id_spalte].astype("string")
    soll["_activity"] = soll[konfiguration.soll_activity_spalte].astype("string")
    ist["_case"] = ist[konfiguration.ist_case_id_spalte].astype("string")
    ist["_activity"] = ist[konfiguration.ist_activity_spalte].astype("string")
    soll, ist, ungueltige_nummern = _vorkommen_zuordnen(soll, ist, konfiguration)
    ausschluss["ungueltige_auftretensnummer"] = ungueltige_nummern
    soll["_plan_ende"] = pd.to_datetime(
        soll[konfiguration.plan_ende_spalte], errors="coerce", utc=True
    )
    ist["_ist_ende"] = pd.to_datetime(ist[konfiguration.ist_ende_spalte], errors="coerce", utc=True)
    if konfiguration.bearbeitungszeitabweichung_aktiv:
        soll["_plan_start"] = pd.to_datetime(
            soll[konfiguration.plan_start_spalte], errors="coerce", utc=True
        )
        ist["_ist_start"] = pd.to_datetime(
            ist[konfiguration.ist_start_spalte], errors="coerce", utc=True
        )
    else:
        soll["_plan_start"] = pd.NaT
        ist["_ist_start"] = pd.NaT
    schluessel = ["_case", "_activity", "_vorkommen"]
    if bool(soll.duplicated(schluessel, keep=False).any()) or bool(
        ist.duplicated(schluessel, keep=False).any()
    ):
        raise Domaenenfehler("Die bestätigten Performance-Schlüssel sind nicht eindeutig.")
    verbunden = soll[[*schluessel, "_plan_start", "_plan_ende"]].merge(
        ist[[*schluessel, "_ist_start", "_ist_ende"]],
        on=schluessel,
        how="outer",
        indicator=True,
    )
    einzelwerte: list[PerformanceZeitabweichung] = []
    dt_werte: list[float] = []
    db_werte: list[float] = []
    for _, zeile in verbunden.iterrows():
        if zeile["_merge"] != "both":
            ausschluss["nicht_zuordenbar"] += 1
            continue
        plan_start = zeile["_plan_start"]
        plan_ende = zeile["_plan_ende"]
        ist_start = zeile["_ist_start"]
        ist_ende = zeile["_ist_ende"]
        dt: float | None = None
        db: float | None = None
        if konfiguration.fertigstellungsabweichung_aktiv:
            if pd.isna(plan_ende) or pd.isna(ist_ende):
                ausschluss["dt_zeitwert_fehlt"] += 1
            else:
                dt = float((ist_ende - plan_ende).total_seconds())
                dt_werte.append(dt)
        if konfiguration.bearbeitungszeitabweichung_aktiv:
            if any(pd.isna(wert) for wert in (plan_start, plan_ende, ist_start, ist_ende)):
                ausschluss["db_zeitwert_fehlt"] += 1
            else:
                plan_dauer, plan_grund = bearbeitungszeit_einer_ausfuehrung(plan_start, plan_ende)
                ist_dauer, ist_grund = bearbeitungszeit_einer_ausfuehrung(ist_start, ist_ende)
                if plan_grund == "negativ":
                    ausschluss["negative_plan_bearbeitungszeit"] += 1
                elif ist_grund == "negativ":
                    ausschluss["negative_ist_bearbeitungszeit"] += 1
                elif plan_dauer is None or ist_dauer is None:
                    ausschluss["db_zeitwert_fehlt"] += 1
                else:
                    db = ist_dauer - plan_dauer
                    db_werte.append(db)
        if dt is None and db is None:
            continue
        einzelwerte.append(
            PerformanceZeitabweichung(
                str(zeile["_case"]),
                str(zeile["_activity"]),
                int(zeile["_vorkommen"]),
                plan_start.isoformat() if pd.notna(plan_start) else "",
                plan_ende.isoformat() if pd.notna(plan_ende) else "",
                ist_start.isoformat() if pd.notna(ist_start) else "",
                ist_ende.isoformat() if pd.notna(ist_ende) else "",
                dt,
                _klassifikation_dt(dt) if dt is not None else "",
                db,
                _klassifikation_db(db) if db is not None else "",
            )
        )
    pd.testing.assert_frame_equal(soll_daten, soll_original, check_dtype=True)
    pd.testing.assert_frame_equal(event_log, ist_original, check_dtype=True)
    return PerformanceZeitvergleichErgebnis(
        auswertungs_id or uuid4(),
        konfiguration,
        tuple(einzelwerte),
        _dt_statistik(dt_werte),
        _db_statistik(db_werte),
        ausschluss,
        datetime.now(UTC),
    )


def busy_ratio_berechnen(
    *,
    event_log: pd.DataFrame,
    konfiguration: BusyRatioKonfiguration,
    auswertungs_id: UUID | None = None,
) -> BusyRatioErgebnis:
    """Berechnet Gl. 3.3 bis 3.5 je Ressource, unabhängig von Ankunftsströmen q."""
    _spalten_pruefen(
        event_log,
        (konfiguration.ressourcenspalte, konfiguration.startspalte, konfiguration.endspalte),
        "E*",
    )
    original = event_log.copy(deep=True)
    daten = event_log.copy(deep=True)
    daten["_quellreihenfolge"] = range(len(daten))
    ressourcen_gueltig = daten[konfiguration.ressourcenspalte].notna() & daten[
        konfiguration.ressourcenspalte
    ].astype("string").str.strip().ne("")
    ausschluss = {
        "fehlende_ressource": int((~ressourcen_gueltig).sum()),
        "ungueltiger_start_oder_ende": 0,
        "negative_bearbeitungszeit": 0,
        "ausserhalb_betrachtungszeitraum": 0,
        "keine_nachfolgende_ausfuehrung": 0,
        "zwischenankunftszeit_null": 0,
        "negative_zwischenankunftszeit": 0,
    }
    daten = daten.loc[ressourcen_gueltig].copy()
    daten["_ressource"] = daten[konfiguration.ressourcenspalte].astype("string")
    daten["_start"] = pd.to_datetime(daten[konfiguration.startspalte], errors="coerce", utc=True)
    daten["_ende"] = pd.to_datetime(daten[konfiguration.endspalte], errors="coerce", utc=True)
    alle_ressourcen = tuple(sorted(str(wert) for wert in daten["_ressource"].unique()))
    einzelwerte: list[BusyRatioEinzelwert] = []
    statistiken: list[BusyRatioRessourcenstatistik] = []
    for ressource in alle_ressourcen:
        gruppe = daten[daten["_ressource"] == ressource].copy()
        lokal_ausgeschlossen = 0
        zeiten_gueltig = gruppe["_start"].notna() & gruppe["_ende"].notna()
        ungueltige_zeiten = int((~zeiten_gueltig).sum())
        ausschluss["ungueltiger_start_oder_ende"] += ungueltige_zeiten
        lokal_ausgeschlossen += ungueltige_zeiten
        gruppe = gruppe.loc[zeiten_gueltig].copy()
        bearbeitungszeiten = [
            bearbeitungszeit_einer_ausfuehrung(start, ende)
            for start, ende in zip(gruppe["_start"], gruppe["_ende"], strict=True)
        ]
        gruppe["_bearbeitungszeit"] = [wert for wert, _ in bearbeitungszeiten]
        gruppe["_bearbeitungszeit_grund"] = [grund for _, grund in bearbeitungszeiten]
        negative = sum(grund == "negativ" for _, grund in bearbeitungszeiten)
        ausschluss["negative_bearbeitungszeit"] += negative
        lokal_ausgeschlossen += negative
        gruppe = gruppe.loc[gruppe["_bearbeitungszeit_grund"] == ""].copy()
        innerhalb = pd.Series(True, index=gruppe.index, dtype="bool")
        if konfiguration.zeitraum_von is not None:
            innerhalb &= gruppe["_start"] >= konfiguration.zeitraum_von
        if konfiguration.zeitraum_bis is not None:
            innerhalb &= gruppe["_start"] <= konfiguration.zeitraum_bis
        ausserhalb = int((~innerhalb).sum())
        ausschluss["ausserhalb_betrachtungszeitraum"] += ausserhalb
        lokal_ausgeschlossen += ausserhalb
        gruppe = gruppe.loc[innerhalb].sort_values(["_start", "_quellreihenfolge"], kind="stable")
        ratios: list[float] = []
        for position in range(len(gruppe)):
            if position + 1 >= len(gruppe):
                ausschluss["keine_nachfolgende_ausfuehrung"] += 1
                lokal_ausgeschlossen += 1
                continue
            aktuell = gruppe.iloc[position]
            nachfolger = gruppe.iloc[position + 1]
            zwischenankunft = float((nachfolger["_start"] - aktuell["_start"]).total_seconds())
            if zwischenankunft == 0:
                ausschluss["zwischenankunftszeit_null"] += 1
                lokal_ausgeschlossen += 1
                continue
            if zwischenankunft < 0:
                ausschluss["negative_zwischenankunftszeit"] += 1
                lokal_ausgeschlossen += 1
                continue
            bearbeitungszeit = float(aktuell["_bearbeitungszeit"])
            ratio = bearbeitungszeit / zwischenankunft
            ratios.append(ratio)
            einzelwerte.append(
                BusyRatioEinzelwert(
                    ressource,
                    str(aktuell.get("case_id", "")),
                    str(aktuell.get("activity", "")),
                    position + 1,
                    aktuell["_start"].isoformat(),
                    aktuell["_ende"].isoformat(),
                    nachfolger["_start"].isoformat(),
                    bearbeitungszeit,
                    zwischenankunft,
                    ratio,
                )
            )
        serie = pd.Series(ratios, dtype="float64")
        statistiken.append(
            BusyRatioRessourcenstatistik(
                ressource,
                len(ratios),
                float(serie.mean()) if ratios else None,
                float(serie.median()) if ratios else None,
                float(serie.min()) if ratios else None,
                float(serie.max()) if ratios else None,
                lokal_ausgeschlossen,
            )
        )
    auswertbar = [wert for wert in statistiken if wert.anzahl_gueltige_busy_ratios > 0]
    potenzieller_engpass = ""
    if len(auswertbar) >= 2:
        potenzieller_engpass = max(
            auswertbar,
            key=lambda wert: (
                float(wert.mittelwert_busy_ratio or 0),
                wert.ressource,
            ),
        ).ressource
    pd.testing.assert_frame_equal(event_log, original, check_dtype=True)
    return BusyRatioErgebnis(
        auswertungs_id or uuid4(),
        konfiguration,
        tuple(einzelwerte),
        tuple(statistiken),
        potenzieller_engpass,
        ausschluss,
        (
            "Gl. 3.3: t_Bearb = Ist-Ende − Ist-Start; Gl. 3.4: "
            "ressourcenbezogene Zwischenankunftszeit = nächster Ist-Start − aktueller "
            "Ist-Start; Gl. 3.5: BR = t_Bearb / ressourcenbezogene Zwischenankunftszeit. "
            "BR > 1 ist nur ein Hinweis auf potenziellen Rückstau."
        ),
        datetime.now(UTC),
    )
