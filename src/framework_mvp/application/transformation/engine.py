# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportOperatorIssue=false
"""Reine Ausführung expliziter Transformationsschritte auf Arbeitskopien."""

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    Transformationsart,
    Transformationshistorie,
    Transformationsplan,
    Transformationsschritt,
)

MAXIMALE_VORSCHAUZEILEN = 200


def ermittle_ersatzwert_aus_profil(
    spaltenprofil: dict[str, Any], strategie: str, freier_wert: object = ""
) -> object:
    """Liefert den in R gespeicherten Ersatzwert gemäß Tabelle 3.11."""
    if strategie == "Frei definierter Wert":
        return freier_wert
    numerisch = spaltenprofil.get("numerisch")
    if isinstance(numerisch, dict) and strategie in {
        "Minimum",
        "Maximum",
        "Arithmetisches Mittel",
        "Median",
    }:
        schluessel = {
            "Minimum": "minimum",
            "Maximum": "maximum",
            "Arithmetisches Mittel": "mittelwert",
            "Median": "median",
        }[strategie]
        return numerisch.get(schluessel)
    kategorial = spaltenprofil.get("kategorial")
    if strategie == "Häufigster Wert (Modus)" and isinstance(kategorial, dict):
        return kategorial.get("haeufigster_wert")
    raise Domaenenfehler("Die Ersatzstrategie passt nicht zum Datentyp der Spalte.")


@dataclass(frozen=True, slots=True)
class Transformationsergebnis:
    """Ergebnis, Vorschau, Warnungen und vollständige Transformationshistorie."""

    daten: pd.DataFrame
    vorschau: pd.DataFrame
    historie: tuple[Transformationshistorie, ...]
    warnungen: tuple[str, ...]


def _platzhalter(wert: object) -> bool:
    if not isinstance(wert, str):
        return False
    return wert.strip().upper() in {"", "NULL", "N/A", "NA", "NAN", "-"}


def _konvertiere(spalte: pd.Series, parameter: dict[str, Any]) -> tuple[pd.Series, int]:
    zieltyp = parameter["zieltyp"]
    original = spalte.copy(deep=True)
    if zieltyp == "Text":
        konvertiert = spalte.astype("string")
    elif zieltyp in {"Ganzzahl", "Fließkommazahl"}:
        text = spalte.astype("string")
        dezimal = str(parameter.get("dezimaltrennzeichen", "."))
        if dezimal == ",":
            text = text.str.replace(",", ".", regex=False)
        konvertiert = pd.to_numeric(text, errors="coerce")
        if zieltyp == "Ganzzahl":
            konvertiert = konvertiert.astype("Int64")
    elif zieltyp == "Boolean":
        wahr = {"true", "wahr", "1", "ja"}
        falsch = {"false", "falsch", "0", "nein"}
        normalisiert = spalte.astype("string").str.strip().str.lower()
        konvertiert = normalisiert.map(
            lambda wert: True if wert in wahr else False if wert in falsch else pd.NA
        ).astype("boolean")
    elif zieltyp in {"Datum", "Uhrzeit", "Datum und Uhrzeit"}:
        formatwert = parameter.get("datumsformat") or None
        konvertiert = pd.to_datetime(spalte, format=formatwert, errors="coerce")
        if zieltyp == "Datum":
            konvertiert = pd.Series(konvertiert).dt.normalize()
        elif zieltyp == "Uhrzeit":
            konvertiert = pd.Series(konvertiert).dt.time
    else:
        raise Domaenenfehler(f"Der Zieldatentyp {zieltyp} wird nicht unterstützt.")
    fehler_maske = spalte.notna() & pd.Series(konvertiert).isna()
    fehleranzahl = int(fehler_maske.sum())
    verhalten = parameter.get("fehlerverhalten", "Vorgang abbrechen")
    if fehleranzahl and verhalten == "Vorgang abbrechen":
        beispiele = tuple(str(wert) for wert in original[fehler_maske].head(5))
        raise Domaenenfehler(
            f"{fehleranzahl} Werte können nicht konvertiert werden. Beispiele: {beispiele}"
        )
    if fehleranzahl and verhalten == "Ursprünglichen Wert beibehalten":
        konvertiert = pd.Series(konvertiert, index=spalte.index).astype("object")
        konvertiert.loc[fehler_maske] = original.loc[fehler_maske]
    return pd.Series(konvertiert, index=spalte.index), fehleranzahl


def _fehlwerte(daten: pd.DataFrame, schritt: Transformationsschritt) -> tuple[pd.DataFrame, str]:
    parameter = schritt.parameter
    strategie = parameter["strategie"]
    for name in schritt.betroffene_spalten:
        if strategie == "Unverändert lassen":
            continue
        if strategie == "Zeile entfernen":
            daten = daten.loc[daten[name].notna()].copy()
        elif strategie == "Festen Wert einsetzen":
            daten[name] = daten[name].fillna(parameter.get("wert"))
        elif strategie == "Mittelwert einsetzen":
            daten[name] = daten[name].fillna(pd.to_numeric(daten[name]).mean())
        elif strategie == "Median einsetzen":
            daten[name] = daten[name].fillna(pd.to_numeric(daten[name]).median())
        elif strategie == "Häufigsten Wert einsetzen":
            modus = daten[name].mode(dropna=True)
            if not modus.empty:
                daten[name] = daten[name].fillna(modus.iloc[0])
        elif strategie == "Vorwärtsfüllen":
            daten[name] = daten[name].ffill()
        elif strategie == "Rückwärtsfüllen":
            daten[name] = daten[name].bfill()
        else:
            raise Domaenenfehler(f"Die Fehlwertstrategie {strategie} ist unbekannt.")
    return daten, strategie


def _duplikate(daten: pd.DataFrame, schritt: Transformationsschritt) -> tuple[pd.DataFrame, str]:
    parameter = schritt.parameter
    strategie = parameter["strategie"]
    schluessel = list(schritt.betroffene_spalten) or None
    behalten = {"Erstes Vorkommen": "first", "Letztes Vorkommen": "last", "Alle": False}.get(
        parameter.get("behalten", "Erstes Vorkommen"), "first"
    )
    maske = daten.duplicated(subset=schluessel, keep=behalten)
    if strategie == "Markieren":
        ziel = parameter.get("zielspalte", "ist_duplikat")
        daten[ziel] = daten.duplicated(subset=schluessel, keep=False)
    elif strategie == "Entfernen":
        if behalten is False:
            daten = daten.loc[~daten.duplicated(subset=schluessel, keep=False)].copy()
        else:
            daten = daten.loc[~maske].copy()
    elif strategie != "Unverändert lassen":
        raise Domaenenfehler(f"Die Duplikatstrategie {strategie} ist unbekannt.")
    return daten, f"{int(maske.sum())} betroffene Zeilen"


def _ausreisser(daten: pd.DataFrame, schritt: Transformationsschritt) -> tuple[pd.DataFrame, str]:
    parameter = schritt.parameter
    name = schritt.betroffene_spalten[0]
    werte = pd.to_numeric(daten[name], errors="coerce")
    if parameter.get("methode", "IQR") == "IQR":
        q1, q3 = werte.quantile([0.25, 0.75])
        iqr = q3 - q1
        unten, oben = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    else:
        unten = float(parameter["untere_grenze"])
        oben = float(parameter["obere_grenze"])
    maske = (werte < unten) | (werte > oben)
    strategie = parameter["strategie"]
    if strategie == "Markieren":
        daten[parameter.get("zielspalte", f"{name}_ist_ausreisser")] = maske
    elif strategie == "Zeilen entfernen":
        daten = daten.loc[~maske].copy()
    elif strategie == "Auf Grenzwerte begrenzen":
        daten[name] = werte.clip(lower=unten, upper=oben)
    elif strategie == "Als fehlend markieren":
        daten.loc[maske, name] = np.nan
    elif strategie != "Unverändert lassen":
        raise Domaenenfehler(f"Die Ausreißerstrategie {strategie} ist unbekannt.")
    return daten, f"Grenzen {unten:g} bis {oben:g}; {int(maske.sum())} betroffene Werte"


def _filtermaske(spalte: pd.Series, parameter: dict[str, Any]) -> pd.Series:
    operator = parameter["operator"]
    wert = parameter.get("wert")
    vergleichsspalte = spalte
    if pd.api.types.is_numeric_dtype(spalte.dtype) and wert is not None:
        wert = float(wert)
    elif pd.api.types.is_datetime64_any_dtype(spalte.dtype) and wert is not None:
        vergleichsspalte = pd.to_datetime(spalte, errors="coerce", utc=True)
        wert = pd.to_datetime(wert, utc=True)
    if operator == "gleich":
        return vergleichsspalte == wert
    if operator == "ungleich":
        return vergleichsspalte != wert
    if operator in {"enthält", "beginnt mit", "endet mit"}:
        text = spalte.astype("string")
        return {
            "enthält": text.str.contains(str(wert), na=False, regex=False),
            "beginnt mit": text.str.startswith(str(wert), na=False),
            "endet mit": text.str.endswith(str(wert), na=False),
        }[operator]
    if operator == "ist leer":
        return spalte.isna()
    if operator == "ist nicht leer":
        return spalte.notna()
    if operator in {"kleiner", "kleiner oder gleich", "größer", "größer oder gleich"}:
        vergleich = pd.to_numeric(spalte, errors="coerce")
        grenze = float(wert)
        return {
            "kleiner": vergleich < grenze,
            "kleiner oder gleich": vergleich <= grenze,
            "größer": vergleich > grenze,
            "größer oder gleich": vergleich >= grenze,
        }[operator]
    if operator in {"zwischen", "zeitlich zwischen"}:
        if operator.startswith("zeitlich"):
            vergleich = pd.to_datetime(spalte, errors="coerce", utc=True)
            von = pd.to_datetime(parameter["von"], utc=True)
            bis = pd.to_datetime(parameter["bis"], utc=True)
        else:
            vergleich = pd.to_numeric(spalte, errors="coerce")
            von, bis = float(parameter["von"]), float(parameter["bis"])
        return vergleich.between(von, bis)
    if operator in {"vor", "nach"}:
        vergleich = pd.to_datetime(spalte, errors="coerce", utc=True)
        grenze = pd.to_datetime(wert, utc=True)
        return vergleich < grenze if operator == "vor" else vergleich > grenze
    if operator in {"enthalten in", "nicht enthalten in"}:
        werte = parameter.get("werte", [])
        if pd.api.types.is_numeric_dtype(spalte.dtype):
            werte = [float(eintrag) for eintrag in werte]
        elif pd.api.types.is_datetime64_any_dtype(spalte.dtype):
            werte = [pd.to_datetime(eintrag, utc=True) for eintrag in werte]
            vergleichsspalte = pd.to_datetime(spalte, errors="coerce", utc=True)
        maske = vergleichsspalte.isin(werte)
        return maske if operator == "enthalten in" else ~maske
    raise Domaenenfehler(f"Der Filteroperator {operator} ist unbekannt.")


def zaehle_zu_loeschende_zeilen(daten: pd.DataFrame, spalte: str, parameter: dict[str, Any]) -> int:
    """Validiert eine Löschbedingung und zählt ihre Treffer ohne Datenmutation."""
    if spalte not in daten.columns:
        raise Domaenenfehler(f"Die ausgewählte Spalte {spalte} ist nicht vorhanden.")
    return int(_filtermaske(daten[spalte], parameter).fillna(False).sum())


def transformiere_textwerte(
    spalte: pd.Series, parameter: dict[str, Any]
) -> tuple[pd.Series, pd.Series]:
    """Transformiert Textwerte rein und liefert zusätzlich die zeilenbezogene Treffermaske."""
    art = str(parameter["art"])
    nichttreffer = str(parameter.get("nichttreffer", "Originalwert beibehalten"))
    if nichttreffer not in {"Originalwert beibehalten", "Fehlwert setzen"}:
        raise Domaenenfehler("Das Verhalten für Textwerte ohne Treffer ist unbekannt.")
    text = spalte.astype("string")
    if art == "Festen Präfix entfernen":
        begrenzer = str(parameter.get("praefix", ""))
        if not begrenzer:
            raise Domaenenfehler("Der zu entfernende Präfix darf nicht leer sein.")
        treffer = text.str.startswith(begrenzer, na=False)
        transformiert = text.str.slice(start=len(begrenzer))
    elif art == "Festen Suffix entfernen":
        begrenzer = str(parameter.get("suffix", ""))
        if not begrenzer:
            raise Domaenenfehler("Der zu entfernende Suffix darf nicht leer sein.")
        treffer = text.str.endswith(begrenzer, na=False)
        transformiert = text.str.slice(stop=-len(begrenzer))
    elif art == "Zwischen Begrenzern extrahieren":
        start = str(parameter.get("startbegrenzer", ""))
        ende = str(parameter.get("endbegrenzer", ""))
        if not start or not ende:
            raise Domaenenfehler("Start- und Endbegrenzer dürfen nicht leer sein.")
        startposition = text.str.find(start)
        inhaltsstart = startposition + len(start)
        endposition = pd.Series(
            [
                wert.find(ende, start_index) if pd.notna(wert) and start_index >= len(start) else -1
                for wert, start_index in zip(text, inhaltsstart, strict=True)
            ],
            index=spalte.index,
            dtype="Int64",
        )
        treffer = (startposition >= 0) & (endposition >= inhaltsstart)
        transformiert = pd.Series(
            [
                wert[start_index:end_index] if pd.notna(wert) and bool(ok) else pd.NA
                for wert, start_index, end_index, ok in zip(
                    text, inhaltsstart, endposition, treffer, strict=True
                )
            ],
            index=spalte.index,
            dtype="string",
        )
    else:
        raise Domaenenfehler(f"Die Textoperation {art} ist unbekannt.")
    ergebnis = transformiert.where(
        treffer, text if nichttreffer == "Originalwert beibehalten" else pd.NA
    )
    return ergebnis.astype("string"), treffer.fillna(False).astype(bool)


def _abgeleitet(daten: pd.DataFrame, parameter: dict[str, Any]) -> None:
    ziel = str(parameter["zielspalte"]).strip()
    if not ziel or ziel in daten.columns:
        raise Domaenenfehler("Der Name einer abgeleiteten Spalte muss neu und nicht leer sein.")
    art = parameter["art"]
    quellen = parameter.get("quellspalten", [])
    if art == "Konstante":
        daten[ziel] = parameter.get("wert")
    elif art == "Kopie":
        daten[ziel] = daten[quellen[0]]
    elif art in {"Text verketten", "Textspalten kombinieren"}:
        daten[ziel] = kombiniere_textspalten(
            daten,
            tuple(str(name) for name in quellen),
            trennzeichen=str(parameter.get("trennzeichen", "")),
            praefix=str(parameter.get("praefix", "")),
            suffix=str(parameter.get("suffix", "")),
            fehlwertstrategie=str(
                parameter.get("fehlwertstrategie", "Nur vorhandene Bestandteile kombinieren")
            ),
            ersatztext=str(parameter.get("ersatztext", "")),
        )
        if not bool(parameter.get("originalspalten_behalten", True)):
            daten.drop(columns=list(quellen), inplace=True)
    elif art in {"Addition", "Subtraktion"}:
        links = pd.to_numeric(daten[quellen[0]], errors="coerce")
        rechts = pd.to_numeric(daten[quellen[1]], errors="coerce")
        daten[ziel] = links + rechts if art == "Addition" else links - rechts
    elif art == "Zeitdifferenz":
        daten[ziel] = pd.to_datetime(daten[quellen[1]]) - pd.to_datetime(daten[quellen[0]])
    elif art in {"Jahr", "Monat", "Tag", "Stunde"}:
        zeit = pd.to_datetime(daten[quellen[0]], errors="coerce").dt
        daten[ziel] = {
            "Jahr": zeit.year,
            "Monat": zeit.month,
            "Tag": zeit.day,
            "Stunde": zeit.hour,
        }[art]
    else:
        raise Domaenenfehler(f"Die Art der abgeleiteten Spalte {art} ist unbekannt.")


def kombiniere_textspalten(
    daten: pd.DataFrame,
    quellspalten: tuple[str, ...],
    *,
    trennzeichen: str,
    praefix: str = "",
    suffix: str = "",
    fehlwertstrategie: str = "Nur vorhandene Bestandteile kombinieren",
    ersatztext: str = "",
) -> pd.Series:
    """Kombiniert Textwerte ohne technische Fehlwertrepräsentationen."""
    if not quellspalten:
        raise Domaenenfehler("Zum Kombinieren muss mindestens eine Quellspalte gewählt werden.")
    fehlend = [name for name in quellspalten if name not in daten.columns]
    if fehlend:
        raise Domaenenfehler(f"Die Quellspalten sind nicht vorhanden: {', '.join(fehlend)}")

    def kombinieren(zeile: pd.Series) -> object:
        bestandteile: list[str] = []
        hat_fehlwert = False
        for wert in zeile:
            ist_fehlwert = pd.isna(wert) or _platzhalter(wert)
            if ist_fehlwert:
                hat_fehlwert = True
                if fehlwertstrategie == "Festen Ersatztext verwenden":
                    bestandteile.append(ersatztext)
                continue
            bestandteile.append(str(wert).strip())
        if hat_fehlwert and fehlwertstrategie == "Ergebnis leer lassen":
            return pd.NA
        if not bestandteile:
            return pd.NA
        return f"{praefix}{trennzeichen.join(bestandteile)}{suffix}"

    return daten.loc[:, list(quellspalten)].apply(kombinieren, axis=1).astype("string")


def _wende_schritt_an(
    daten: pd.DataFrame, schritt: Transformationsschritt
) -> tuple[pd.DataFrame, str]:
    parameter = schritt.parameter
    if not schritt.frameworkkonform:
        raise Domaenenfehler(
            f"Der Legacy-Transformationsschritt '{schritt.typ.value}' ist nicht mehr "
            "frameworkkonform und wird nicht ausgeführt."
        )
    if schritt.typ is Transformationsart.SPALTENAUSWAHL:
        spalten = list(schritt.betroffene_spalten)
        return daten.loc[
            :, spalten
        ].copy(), f"{len(daten.columns) - len(spalten)} Spalten ausgeschlossen"
    if schritt.typ is Transformationsart.UMBENENNEN:
        mapping = parameter["mapping"]
        zielnamen = [mapping.get(name, name) for name in daten.columns]
        if any(not str(name).strip() for name in zielnamen) or len(set(zielnamen)) != len(
            zielnamen
        ):
            raise Domaenenfehler("Technische Zielnamen müssen eindeutig und nicht leer sein.")
        return daten.rename(columns=mapping).copy(), f"{len(mapping)} Spalten umbenannt"
    if schritt.typ is Transformationsart.WERTE_ERSETZEN:
        gesuchte_werte = parameter.get("gesuchte_werte")
        if not isinstance(gesuchte_werte, list):
            gesuchte_werte = [parameter.get("gesuchter_wert")]
        ersatz = parameter.get("ersatzwert")
        anzahl = 0
        for name in schritt.betroffene_spalten:
            maske = daten[name].isin(gesuchte_werte)
            anzahl += int(maske.sum())
            daten.loc[maske.fillna(False), name] = ersatz
        return daten, f"{anzahl} Werte ersetzt"
    if schritt.typ is Transformationsart.DATENTYP_KONVERTIEREN:
        fehler = 0
        for name in schritt.betroffene_spalten:
            daten[name], anzahl = _konvertiere(daten[name], parameter)
            fehler += anzahl
        return daten, f"{fehler} nicht konvertierbare Werte"
    if schritt.typ is Transformationsart.EXAKTE_TUPEL_DUPLIKATE_ENTFERNEN:
        anzahl = int(daten.duplicated(keep="first").sum())
        return daten.drop_duplicates(keep="first").copy(), f"{anzahl} zusätzliche Tupel entfernt"
    if schritt.typ is Transformationsart.VOLLSTAENDIG_LEERE_SPALTEN_ENTFERNEN:
        leere_positionen = [
            position
            for position in range(len(daten.columns))
            if daten.iloc[:, position].isna().to_numpy().all()
        ]
        leere_spalten = [str(daten.columns[position]) for position in leere_positionen]
        behalten = [
            position for position in range(len(daten.columns)) if position not in leere_positionen
        ]
        return (
            daten.iloc[:, behalten].copy(),
            f"{len(leere_spalten)} vollständig leere Spalten entfernt: "
            + (", ".join(leere_spalten) if leere_spalten else "keine"),
        )
    if schritt.typ is Transformationsart.PLATZHALTER_BEHANDELN:
        strategie = parameter["strategie"]
        ausgewaehlt = {str(wert) for wert in parameter.get("platzhalterarten", ())}

        def ist_ausgewaehlt(wert: object) -> bool:
            if not _platzhalter(wert):
                return False
            text = str(wert)
            klasse = (
                "Leere Zeichenkette"
                if text == ""
                else "Nur Leerzeichen"
                if not text.strip()
                else "NaN"
                if text.strip().upper() == "NAN"
                else text.strip().upper()
            )
            return not ausgewaehlt or klasse in ausgewaehlt

        for name in schritt.betroffene_spalten:
            maske = daten[name].map(ist_ausgewaehlt) & daten[name].notna()
            if strategie == "Als echten Fehlwert interpretieren":
                daten.loc[maske, name] = pd.NA
            elif strategie == "Durch Wert ersetzen":
                daten.loc[maske, name] = parameter.get("wert")
            elif strategie != "Unverändert lassen":
                raise Domaenenfehler(f"Die Platzhalterstrategie {strategie} ist unbekannt.")
        return daten, strategie
    if schritt.typ is Transformationsart.FEHLWERTE_BEHANDELN:
        return _fehlwerte(daten, schritt)
    if schritt.typ is Transformationsart.DUPLIKATE_BEHANDELN:
        return _duplikate(daten, schritt)
    if schritt.typ is Transformationsart.AUSREISSER_BEHANDELN:
        return _ausreisser(daten, schritt)
    if schritt.typ is Transformationsart.ZEILEN_FILTERN:
        name = schritt.betroffene_spalten[0]
        maske = _filtermaske(daten[name], parameter).fillna(False)
        return daten.loc[maske].copy(), f"{int((~maske).sum())} Zeilen herausgefiltert"
    if schritt.typ is Transformationsart.ZEILEN_LOESCHEN:
        name = schritt.betroffene_spalten[0]
        maske = _filtermaske(daten[name], parameter).fillna(False)
        geloescht = int(maske.sum())
        return daten.loc[~maske].copy(), f"{geloescht} Zeilen gelöscht"
    if schritt.typ is Transformationsart.TEXT_BEREINIGEN:
        name = schritt.betroffene_spalten[0]
        daten[name], treffermaske = transformiere_textwerte(daten[name], parameter)
        return daten, f"{int(treffermaske.sum())} Textwerte transformiert"
    if schritt.typ is Transformationsart.ABGELEITETE_SPALTE:
        _abgeleitet(daten, parameter)
        return daten, f"Spalte {parameter['zielspalte']} erzeugt"
    raise Domaenenfehler(f"Die Transformation {schritt.typ.value} benötigt einen eigenen Adapter.")


def fuehre_transformationsplan_aus(
    ausgangsdaten: pd.DataFrame, plan: Transformationsplan
) -> Transformationsergebnis:
    """Wendet aktivierte Schritte geordnet auf eine tiefe Arbeitskopie an."""
    daten = ausgangsdaten.copy(deep=True)
    historie: list[Transformationshistorie] = []
    warnungen: list[str] = []
    for schritt in sorted(plan.schritte, key=lambda wert: wert.reihenfolge):
        if not schritt.aktiviert or schritt.typ is Transformationsart.TABELLEN_JOIN:
            continue
        zeilen_vorher, spalten_vorher = daten.shape
        daten, ergebnis = _wende_schritt_an(daten, schritt)
        historie.append(
            Transformationshistorie(
                schritt.reihenfolge,
                schritt.beschreibung or schritt.typ.value,
                schritt.betroffene_spalten,
                zeilen_vorher,
                len(daten),
                spalten_vorher,
                len(daten.columns),
                ergebnis,
            )
        )
        if "nicht konvertierbare" in ergebnis and not ergebnis.startswith("0 "):
            warnungen.append(ergebnis)
    return Transformationsergebnis(
        daten=daten,
        vorschau=daten.head(MAXIMALE_VORSCHAUZEILEN).copy(deep=True),
        historie=tuple(historie),
        warnungen=tuple(warnungen),
    )
