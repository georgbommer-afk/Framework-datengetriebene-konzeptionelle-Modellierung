"""Reine Schritt-7-Ableitungen für Ressourcen, Entitäten und Zeitgrößen in A_G."""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, cast

import pandas as pd

from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    AktivitaetRessourcenZuordnung,
    Aktivitaetsbearbeitungszeit,
    AnkunftsstromDefinition,
    Attributauswertung,
    Attributbeobachtung,
    Attributstatus,
    Attributzuordnung,
    BestaetigteWarteschlangeninformation,
    Datenartefakt,
    EntitaetsanalyseErgebnis,
    Entitaetsinstanz,
    PotenzielleWartezeit,
    RessourcenanalyseErgebnis,
    Ressourcenzuordnungsmodus,
    RobusteZeitstatistik,
    StrukturiertesErgebnisStatus,
    Vorkommensregel,
    WarteschlangenanalyseErgebnis,
    ZeitbezogeneDatenauswahlErgebnis,
    ZwischenankunftszeitErgebnis,
)


def _text(wert: Any) -> str:
    if pd.isna(wert):
        return ""
    return str(wert).strip()


def _aktivitaeten(event_log: pd.DataFrame) -> tuple[str, ...]:
    if "activity" not in event_log.columns:
        return ()
    return tuple(sorted({_text(wert) for wert in event_log["activity"] if _text(wert)}))


def _tabelle_fuer_quelle(
    quelle: Datenartefakt, zwischendaten: pd.DataFrame, event_log: pd.DataFrame
) -> pd.DataFrame:
    if quelle is Datenartefakt.EVENT_LOG_E_STERN:
        return event_log
    if quelle is Datenartefakt.ZWISCHENDATENSATZ_T:
        return zwischendaten
    raise Domaenenfehler("Attribute und Ankunftsströme dürfen nur E* oder T verwenden.")


def _analysiere_attribute(
    zwischendaten: pd.DataFrame,
    event_log: pd.DataFrame,
    zuordnungen: Sequence[Attributzuordnung],
    *,
    e_stern_schluessel: str,
    erlaubte_instanz_ids: set[str] | None = None,
) -> tuple[Attributauswertung, ...]:
    ergebnisse: list[Attributauswertung] = []
    for zuordnung in zuordnungen:
        if (
            zuordnung.quelle is Datenartefakt.EVENT_LOG_E_STERN
            and zuordnung.schluesselspalte != e_stern_schluessel
        ):
            raise Domaenenfehler(f"In E* muss {e_stern_schluessel} als Schlüssel bestätigt sein.")
        tabelle = _tabelle_fuer_quelle(zuordnung.quelle, zwischendaten, event_log)
        spalten = {zuordnung.schluesselspalte, zuordnung.attributspalte}
        if zuordnung.zeitspalte:
            spalten.add(zuordnung.zeitspalte)
        fehlend = sorted(spalten - set(tabelle.columns))
        if fehlend:
            raise Domaenenfehler(
                "Bestätigte Attributspalten fehlen in der gewählten Quelle: "
                + ", ".join(fehlend)
                + "."
            )
        gruppiert: dict[str, list[Attributbeobachtung]] = {}
        for _, zeile in tabelle.iterrows():
            instanz = _text(zeile[zuordnung.schluesselspalte])
            wert = _text(zeile[zuordnung.attributspalte])
            if (
                not instanz
                or not wert
                or (erlaubte_instanz_ids is not None and instanz not in erlaubte_instanz_ids)
            ):
                continue
            zeitpunkt = ""
            if zuordnung.zeitspalte:
                rohzeit = pd.to_datetime(zeile[zuordnung.zeitspalte], errors="coerce", utc=True)
                if isinstance(rohzeit, pd.Timestamp):
                    zeitpunkt = rohzeit.isoformat()
            gruppiert.setdefault(instanz, []).append(Attributbeobachtung(wert, zeitpunkt))
        for instanz, beobachtungen in sorted(gruppiert.items()):
            werte = {wert.wert for wert in beobachtungen}
            stabil = len(werte) == 1
            ergebnisse.append(
                Attributauswertung(
                    instanz,
                    zuordnung.attributspalte,
                    Attributstatus.STABIL
                    if stabil
                    else Attributstatus.ZEITABHAENGIG_NICHT_EINDEUTIG,
                    zuordnung.quelle,
                    zuordnung.schluesselspalte,
                    zuordnung.attributspalte,
                    zuordnung.zeitspalte,
                    next(iter(werte)) if stabil else "",
                    tuple(beobachtungen),
                )
            )
    return tuple(ergebnisse)


def analysiere_ressourcen(
    event_log: pd.DataFrame,
    *,
    manuelle_zuordnungen: Mapping[str, Iterable[str]] | None = None,
    offene_aktivitaeten: Iterable[str] = (),
    nicht_moeglich_begruendung: str = "",
    zwischendaten: pd.DataFrame | None = None,
    attributzuordnungen: Sequence[Attributzuordnung] = (),
) -> RessourcenanalyseErgebnis:
    """Erhält jedes beobachtete Paar und dokumentiert Ergänzungen/Lücken je Aktivität."""
    aktivitaeten = _aktivitaeten(event_log)
    if not aktivitaeten:
        return RessourcenanalyseErgebnis(
            Ressourcenzuordnungsmodus.NICHT_MOEGLICH,
            "Schritt 7",
            (),
            "E* enthält keine auswertbaren Aktivitäten.",
        )
    automatisch: dict[str, set[str]] = {name: set() for name in aktivitaeten}
    if "resource" in event_log.columns:
        for aktivitaet, ressource in event_log.loc[:, ["activity", "resource"]].itertuples(
            index=False, name=None
        ):
            name, wert = _text(aktivitaet), _text(ressource)
            if name in automatisch and wert:
                automatisch[name].add(wert)
    manuell: dict[str, tuple[str, ...]] = {}
    if manuelle_zuordnungen is not None:
        fremd = sorted(set(manuelle_zuordnungen) - set(aktivitaeten))
        if fremd:
            raise Domaenenfehler("Unbekannte Aktivitäten: " + ", ".join(fremd))
        manuell = {
            name: tuple(sorted({_text(wert) for wert in werte if _text(wert)}))
            for name, werte in manuelle_zuordnungen.items()
        }
    offen = {_text(wert) for wert in offene_aktivitaeten if _text(wert)}
    fremd_offen = sorted(offen - set(aktivitaeten))
    if fremd_offen:
        raise Domaenenfehler("Unbekannte offene Aktivitäten: " + ", ".join(fremd_offen))
    if manuelle_zuordnungen is not None:
        unentschieden = [
            name
            for name in aktivitaeten
            if not automatisch[name] and not manuell.get(name) and name not in offen
        ]
        if unentschieden:
            raise Domaenenfehler(
                "Die Ressourcenzuordnung ist für Lücken weder ergänzt noch ausdrücklich "
                "offen. Es fehlen: " + ", ".join(unentschieden) + "."
            )
    else:
        offen.update(name for name in aktivitaeten if not automatisch[name])
    zuordnungen = tuple(
        AktivitaetRessourcenZuordnung(
            name,
            tuple(sorted(automatisch[name] | set(manuell.get(name, ())))),
            tuple(sorted(automatisch[name])),
            manuell.get(name, ()),
            name in offen,
        )
        for name in aktivitaeten
    )
    begruendung = nicht_moeglich_begruendung.strip()
    hat_automatisch, hat_manuell = any(automatisch.values()), any(manuell.values())
    if begruendung and not hat_manuell:
        modus = Ressourcenzuordnungsmodus.NICHT_MOEGLICH
        herkunft = "fachliche Entscheidung in Schritt 7"
    elif hat_automatisch and not hat_manuell and not offen:
        modus = Ressourcenzuordnungsmodus.AUTOMATISCH
        herkunft = "beobachtete Paare aus E*.resource"
    elif hat_manuell and not hat_automatisch and not offen:
        modus = Ressourcenzuordnungsmodus.MANUELL
        herkunft = "menschlich bestätigte Zuordnung in Schritt 7"
    else:
        modus = Ressourcenzuordnungsmodus.GEMISCHT
        herkunft = "beobachtete, manuell bestätigte und/oder offene Zuordnungen"
    attribute = _analysiere_attribute(
        zwischendaten if zwischendaten is not None else pd.DataFrame(),
        event_log,
        attributzuordnungen,
        e_stern_schluessel="resource",
    )
    return RessourcenanalyseErgebnis(
        modus,
        herkunft,
        zuordnungen,
        begruendung,
        "resource" if "resource" in event_log.columns else "",
        attribute,
    )


def analysiere_entitaeten(
    zwischendaten: pd.DataFrame,
    event_log: pd.DataFrame,
    *,
    attributzuordnungen: Sequence[Attributzuordnung] = (),
    entitaetstyp: str = "",
) -> EntitaetsanalyseErgebnis:
    """Behält E*.case_id neutral als Instanz-ID; verdichtet Attribute nur bei Eindeutigkeit."""
    instanzen = ()
    if "case_id" in event_log.columns:
        instanzen = tuple(
            Entitaetsinstanz(wert)
            for wert in sorted({_text(wert) for wert in event_log["case_id"] if _text(wert)})
        )
    return EntitaetsanalyseErgebnis(
        instanzen,
        _analysiere_attribute(
            zwischendaten,
            event_log,
            attributzuordnungen,
            e_stern_schluessel="case_id",
            erlaubte_instanz_ids={wert.instanz_id for wert in instanzen},
        ),
        entitaetstyp.strip(),
    )


def _statistik(werte: list[float]) -> RobusteZeitstatistik:
    serie = pd.Series(werte, dtype="float64")
    return RobusteZeitstatistik(len(werte), float(serie.mean()), float(serie.median()))


def bearbeitungszeit_einer_ausfuehrung(
    ist_start: Any,
    ist_ende: Any,
) -> tuple[float | None, str]:
    """Gemeinsame, nicht korrigierende Umsetzung von Gleichung 3.3."""
    start = pd.to_datetime(ist_start, errors="coerce", utc=True)
    ende = pd.to_datetime(ist_ende, errors="coerce", utc=True)
    if pd.isna(start) or pd.isna(ende):
        return None, "nicht_auswertbar"
    sekunden = float((ende - start).total_seconds())
    if sekunden < 0:
        return None, "negativ"
    return sekunden, ""


def analysiere_warteschlangen(
    event_log: pd.DataFrame,
    *,
    bestaetigte_warteschlangen: Sequence[BestaetigteWarteschlangeninformation] = (),
    zwischendaten: pd.DataFrame | None = None,
) -> WarteschlangenanalyseErgebnis:
    """Berechnet zeitliche Lücken in kanonischer Eventfolge, ohne Warteschlangen zu folgern."""
    for information in bestaetigte_warteschlangen:
        if information.quelle not in {
            Datenartefakt.EVENT_LOG_E_STERN,
            Datenartefakt.ZWISCHENDATENSATZ_T,
        }:
            raise Domaenenfehler("Warteschlangeninformationen dürfen nur E* oder T verwenden.")
        if not all(
            (
                information.bezeichnung.strip(),
                information.von_aktivitaet.strip(),
                information.zu_aktivitaet.strip(),
                information.informationsspalte.strip(),
            )
        ):
            raise Domaenenfehler(
                "Eine bestätigte Warteschlangeninformation benötigt Bezeichnung, Übergang "
                "und Informationsspalte."
            )
        quelltabelle = (
            event_log if information.quelle is Datenartefakt.EVENT_LOG_E_STERN else zwischendaten
        )
        if quelltabelle is not None and information.informationsspalte not in quelltabelle.columns:
            raise Domaenenfehler(
                "Die bestätigte Warteschlangen-Informationsspalte fehlt in der Quelle."
            )
    regel = (
        "Potenzielle Wartezeit je unmittelbar aufeinanderfolgendem Ereignispaar in der "
        "kanonischen Reihenfolge E*.timestamp (Gleichstand: stabile Quellreihenfolge): "
        "Start(B) − Ende(A). Negative Werte sind Überlappungen und werden ausgeschlossen."
    )
    erforderlich = {"case_id", "activity", "timestamp", "start_timestamp", "end_timestamp"}
    if not erforderlich <= set(event_log.columns):
        fehlend = sorted(erforderlich - set(event_log.columns))
        return WarteschlangenanalyseErgebnis(
            StrukturiertesErgebnisStatus.ABLEITBAR
            if bestaetigte_warteschlangen
            else StrukturiertesErgebnisStatus.NICHT_MOEGLICH,
            regel,
            (),
            0,
            0,
            "Erforderliche kanonische Spalten fehlen: " + ", ".join(fehlend) + ".",
            tuple(bestaetigte_warteschlangen),
        )
    daten = event_log.loc[
        :, ["case_id", "activity", "timestamp", "start_timestamp", "end_timestamp"]
    ].copy(deep=True)
    for spalte in ("timestamp", "start_timestamp", "end_timestamp"):
        daten[spalte] = pd.to_datetime(daten[spalte], errors="coerce", utc=True)
    daten["_reihenfolge"] = range(len(daten))
    gruppiert: dict[tuple[str, str], list[float]] = {}
    negativ = nicht_auswertbar = 0
    for case_id, fall in daten.groupby("case_id", sort=False, dropna=False):
        if not _text(case_id):
            nicht_auswertbar += max(len(fall) - 1, 0)
            continue
        sortiert = fall.sort_values(
            ["timestamp", "_reihenfolge"], kind="stable", na_position="last"
        )
        for position in range(len(sortiert) - 1):
            aktuell, folgend = sortiert.iloc[position], sortiert.iloc[position + 1]
            von, zu = _text(aktuell["activity"]), _text(folgend["activity"])
            if (
                not von
                or not zu
                or pd.isna(aktuell["timestamp"])
                or pd.isna(folgend["timestamp"])
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
    potentiale = tuple(
        PotenzielleWartezeit(von, zu, _statistik(werte))
        for (von, zu), werte in sorted(gruppiert.items())
    )
    ableitbar = bool(potentiale or bestaetigte_warteschlangen)
    return WarteschlangenanalyseErgebnis(
        StrukturiertesErgebnisStatus.ABLEITBAR
        if ableitbar
        else StrukturiertesErgebnisStatus.NICHT_MOEGLICH,
        regel,
        potentiale,
        negativ,
        nicht_auswertbar,
        "" if ableitbar else "Es verblieben keine auswertbaren potenziellen Wartezeiten.",
        tuple(bestaetigte_warteschlangen),
    )


def _bearbeitungszeiten(
    event_log: pd.DataFrame,
) -> tuple[tuple[Aktivitaetsbearbeitungszeit, ...], int, int]:
    erforderlich = {"activity", "start_timestamp", "end_timestamp"}
    if not erforderlich <= set(event_log.columns):
        return (), 0, len(event_log)
    spalten = ["activity", "start_timestamp", "end_timestamp"]
    hat_ressource = "resource" in event_log.columns
    if hat_ressource:
        spalten.append("resource")
    daten = event_log.loc[:, spalten].copy(deep=True)
    daten["start_timestamp"] = pd.to_datetime(daten["start_timestamp"], errors="coerce", utc=True)
    daten["end_timestamp"] = pd.to_datetime(daten["end_timestamp"], errors="coerce", utc=True)
    gruppiert: dict[tuple[str, str], list[float]] = {}
    negativ = nicht_auswertbar = 0
    for _, zeile in daten.iterrows():
        name, start, ende = (
            _text(zeile["activity"]),
            zeile["start_timestamp"],
            zeile["end_timestamp"],
        )
        if not name or pd.isna(start) or pd.isna(ende):
            nicht_auswertbar += 1
            continue
        sekunden, grund = bearbeitungszeit_einer_ausfuehrung(start, ende)
        if grund == "negativ":
            negativ += 1
            continue
        if sekunden is None:
            nicht_auswertbar += 1
            continue
        ressource = _text(zeile["resource"]) if hat_ressource else ""
        gruppiert.setdefault((name, ressource), []).append(sekunden)
    return (
        tuple(
            Aktivitaetsbearbeitungszeit(
                name,
                _statistik(werte),
                ressource,
                bool(ressource),
                (
                    "Bearbeitungszeit nach Aktivität + Ressource"
                    if ressource
                    else "Bearbeitungszeit nach Aktivität; kein Ressourcenbezug verfügbar"
                ),
            )
            for (name, ressource), werte in sorted(gruppiert.items())
        ),
        negativ,
        nicht_auswertbar,
    )


def _zwischenankunftszeit(
    definition: AnkunftsstromDefinition,
    zwischendaten: pd.DataFrame,
    event_log: pd.DataFrame,
    datenbasis_referenzen: Mapping[str, Any],
) -> ZwischenankunftszeitErgebnis:
    tabelle = _tabelle_fuer_quelle(definition.quelle, zwischendaten, event_log).copy(deep=True)
    if (
        definition.quelle is Datenartefakt.EVENT_LOG_E_STERN
        and definition.entitaetsspalte != "case_id"
    ):
        raise Domaenenfehler("Ein Ankunftsstrom aus E* muss case_id als Entitäts-ID verwenden.")
    benoetigt = {definition.entitaetsspalte, definition.zeitspalte}
    if definition.aktivitaet:
        benoetigt.add("activity")
    if definition.filterspalte:
        benoetigt.add(definition.filterspalte)
    fehlend = sorted(benoetigt - set(tabelle.columns))
    if not definition.bezeichnung.strip():
        raise Domaenenfehler("Jeder Ankunftsstrom benötigt eine fachliche Bezeichnung q.")
    if fehlend:
        raise Domaenenfehler(
            f"Im Ankunftsstrom {definition.bezeichnung} fehlen bestätigte Spalten: "
            + ", ".join(fehlend)
            + "."
        )
    tabelle["_reihenfolge"] = range(len(tabelle))
    alle_entitaeten = {_text(wert) for wert in tabelle[definition.entitaetsspalte] if _text(wert)}
    kandidaten = tabelle
    if definition.aktivitaet:
        kandidaten = kandidaten.loc[
            kandidaten["activity"].map(_text) == definition.aktivitaet.strip()
        ]
    if definition.filterspalte:
        kandidaten = kandidaten.loc[
            kandidaten[definition.filterspalte].map(_text) == definition.filterwert.strip()
        ]
    ankuenfte: list[pd.Timestamp] = []
    gruende = {
        "kein_passendes_ereignis": 0,
        "fehlender_oder_ungueltiger_zeitpunkt": 0,
        "mehrdeutig_ohne_vorkommensregel": 0,
        "vorkommensnummer_nicht_vorhanden": 0,
    }
    for entitaet in sorted(alle_entitaeten):
        passend = kandidaten.loc[
            kandidaten[definition.entitaetsspalte].map(_text) == entitaet
        ].copy()
        if passend.empty:
            gruende["kein_passendes_ereignis"] += 1
            continue
        passend["_ankunft"] = pd.to_datetime(
            passend[definition.zeitspalte], errors="coerce", utc=True
        )
        passend = passend.loc[passend["_ankunft"].notna()].sort_values(
            ["_ankunft", "_reihenfolge"], kind="stable"
        )
        if passend.empty:
            gruende["fehlender_oder_ungueltiger_zeitpunkt"] += 1
            continue
        if len(passend) > 1 and definition.vorkommensregel is None:
            gruende["mehrdeutig_ohne_vorkommensregel"] += 1
            continue
        if definition.vorkommensregel is Vorkommensregel.LETZTES:
            gewaehlt = passend.iloc[-1]
        elif definition.vorkommensregel is Vorkommensregel.AUFTRETENSNUMMER:
            nummer = cast(int, definition.vorkommensnummer)
            if len(passend) < nummer:
                gruende["vorkommensnummer_nicht_vorhanden"] += 1
                continue
            gewaehlt = passend.iloc[nummer - 1]
        else:
            gewaehlt = passend.iloc[0]
        ankuenfte.append(cast(pd.Timestamp, gewaehlt["_ankunft"]))
    ankuenfte.sort()
    differenzen = [
        float((ankuenfte[index] - ankuenfte[index - 1]).total_seconds())
        for index in range(1, len(ankuenfte))
    ]
    quelle = definition.quelle.value
    regel = (
        f"Ankunftsstrom {definition.bezeichnung}: je Entitätsinstanz genau ein bestätigter "
        f"Zeitpunkt aus {quelle}.{definition.zeitspalte}; zeitlich sortierte Differenzen."
    )
    if definition.vorkommensregel is not None:
        regel += (
            f" Vorkommensregel: {definition.vorkommensregel.value}; deterministische "
            "Sortierung nach Ankunftszeit und bei Gleichstand nach stabiler Quellreihenfolge."
        )
    return ZwischenankunftszeitErgebnis(
        definition,
        StrukturiertesErgebnisStatus.ABLEITBAR
        if differenzen
        else StrukturiertesErgebnisStatus.NICHT_MOEGLICH,
        _statistik(differenzen) if differenzen else None,
        sum(gruende.values()),
        {name: anzahl for name, anzahl in gruende.items() if anzahl},
        {
            "quelle": quelle,
            "quellenreferenz": datenbasis_referenzen.get(quelle, {}),
            "entitaetsspalte": definition.entitaetsspalte,
            "zeitspalte": definition.zeitspalte,
            "aktivitaet": definition.aktivitaet,
            "filterspalte": definition.filterspalte,
            "filterwert": definition.filterwert,
            "vorkommensregel": definition.vorkommensregel.value
            if definition.vorkommensregel
            else "",
        },
        regel,
    )


def analysiere_zeitbezogene_datenauswahl(
    zwischendaten: pd.DataFrame,
    event_log: pd.DataFrame,
    *,
    ankunftsstroeme: Sequence[AnkunftsstromDefinition] = (),
    datenbasis_referenzen: Mapping[str, Any] | None = None,
) -> ZeitbezogeneDatenauswahlErgebnis:
    """Berechnet Zeitgrößen getrennt und speichert ihre tatsächliche Lineage."""
    referenzen = dict(datenbasis_referenzen or {})
    warten = analysiere_warteschlangen(event_log)
    bearbeitung, negativ, nicht_auswertbar = _bearbeitungszeiten(event_log)
    zwischenankuenfte = tuple(
        _zwischenankunftszeit(definition, zwischendaten, event_log, referenzen)
        for definition in ankunftsstroeme
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
    verwendete_quellen: set[str] = set()
    if bearbeitung or warten.potenzielle_wartezeiten:
        verwendete_quellen.add("E*")
    verwendete_quellen.update(definition.quelle.value for definition in ankunftsstroeme)
    lineage = {
        "bearbeitungszeit": {
            "quelle": "E*",
            "spalten": [
                name
                for name in ("activity", "start_timestamp", "end_timestamp", "resource")
                if name in event_log.columns
            ],
            "ressourcenbezug_vorhanden": (
                "resource" in event_log.columns
                and any(_text(wert) for wert in event_log["resource"])
            ),
            "berechenbar": bool(bearbeitung),
        },
        "potenzielle_wartezeit": {
            "quelle": "E*",
            "reihenfolge": ["timestamp", "stabile Quellreihenfolge"],
            "spalten": ["end_timestamp des Vorgängers", "start_timestamp des Nachfolgers"],
            "bedeutung": "zeitliche Lücke; keine bestätigte Warteschlange",
            "berechenbar": bool(warten.potenzielle_wartezeiten),
        },
        "zwischenankunftszeiten": [wert.lineage for wert in zwischenankuenfte],
    }
    ableitbar = bool(
        bearbeitung
        or warten.potenzielle_wartezeiten
        or any(wert.status is StrukturiertesErgebnisStatus.ABLEITBAR for wert in zwischenankuenfte)
    )
    return ZeitbezogeneDatenauswahlErgebnis(
        StrukturiertesErgebnisStatus.ABLEITBAR
        if ableitbar
        else StrukturiertesErgebnisStatus.NICHT_MOEGLICH,
        tuple(sorted(verwendete_quellen)),
        {name: referenzen[name] for name in sorted(verwendete_quellen) if name in referenzen},
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
        warten.potenzielle_wartezeiten,
        zwischenankuenfte,
        lineage,
        negativ,
        nicht_auswertbar,
        "" if ableitbar else "Aus den bestätigten Spalten war keine Zeitgröße ableitbar.",
    )
