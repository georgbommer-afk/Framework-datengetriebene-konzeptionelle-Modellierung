# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
"""Reine Aufbereitung technischer Profile als Transformationsentscheidung."""

from dataclasses import dataclass
from typing import Any

import pandas as pd

from framework_mvp.domain.models import Transformationsart

AUFFAELLIGKEITSARTEN = (
    "Fehlwerte",
    "Platzhalter",
    "Ausreißer",
    "Duplikate",
    "Zeitprobleme",
    "Datentypprobleme",
)


def transformationsart_fuer_auffaelligkeit(art: str) -> Transformationsart:
    """Ordnet einen Befund einer der vier zulässigen Transformationen zu."""
    return {
        "Fehlwerte": Transformationsart.WERTE_ERSETZEN,
        "Platzhalter": Transformationsart.WERTE_ERSETZEN,
        "Ausreißer": Transformationsart.WERTE_ERSETZEN,
        "Duplikate": Transformationsart.EXAKTE_TUPEL_DUPLIKATE_ENTFERNEN,
        "Zeitprobleme": Transformationsart.DATENTYP_KONVERTIEREN,
        "Datentypprobleme": Transformationsart.DATENTYP_KONVERTIEREN,
    }[art]


def bereite_gemischte_anzeigetabelle(
    zeilen: tuple[tuple[str, object, object], ...],
) -> pd.DataFrame:
    """Formatiert heterogene Vergleichswerte verlustfrei als Arrow-kompatible Texte."""

    def text(wert: object) -> str:
        return "–" if wert is None else str(wert)

    return pd.DataFrame(
        (
            {"Kennzahl": name, "Vorher": text(vorher), "Nachher": text(nachher)}
            for name, vorher, nachher in zeilen
        ),
        columns=["Kennzahl", "Vorher", "Nachher"],
        dtype="string",
    )


@dataclass(frozen=True, slots=True)
class ErkannteAuffaelligkeit:
    """Eine einer Spalte oder der Gesamttabelle zugeordnete Auffälligkeit."""

    spaltenname: str
    art: str
    anzahl: int
    anteil: float
    detailwerte: str
    beispielzeilen: tuple[int, ...] = ()


def _beispielindizes(maske: pd.Series, maximal: int = 5) -> tuple[int, ...]:
    """Liefert höchstens fünf reproduzierbare Positionen betroffener Zeilen."""
    return tuple(int(wert) for wert in maske[maske].index[:maximal] if isinstance(wert, int))


def ermittle_auffaelligkeiten(
    profil: dict[str, Any], daten: pd.DataFrame
) -> tuple[ErkannteAuffaelligkeit, ...]:
    """Ordnet gespeicherte Profilbefunde ihren Spalten und Beispielzeilen zu."""
    ergebnis: list[ErkannteAuffaelligkeit] = []
    zeilen = int(profil["zeilen"])
    for spalte in profil["spaltenprofile"]:
        name = str(spalte["spaltenname"])
        if name not in daten.columns:
            continue
        fehlwerte = spalte["fehlwerte"]
        echte = int(fehlwerte["echte_fehlwerte"])
        if echte:
            ergebnis.append(
                ErkannteAuffaelligkeit(
                    name,
                    "Fehlwerte",
                    echte,
                    float(fehlwerte["anteil_echter_fehlwerte"]),
                    f"Profiltyp: {spalte['profiltyp']}; Pandas: {spalte['originaldatentyp']}",
                    _beispielindizes(daten[name].isna()),
                )
            )
        platzhalter = int(fehlwerte["platzhalter"])
        if platzhalter:
            klassen = ", ".join(
                f"{wert['bezeichnung']}: {wert['anzahl']}"
                for wert in fehlwerte["platzhalterklassen"]
                if wert["anzahl"]
            )
            ergebnis.append(
                ErkannteAuffaelligkeit(
                    name,
                    "Platzhalter",
                    platzhalter,
                    float(fehlwerte["anteil_platzhalter"]),
                    klassen,
                )
            )
        numerisch = spalte.get("numerisch")
        if numerisch and int(numerisch["potenzielle_ausreisser"]):
            anzahl = int(numerisch["potenzielle_ausreisser"])
            unten = numerisch["untere_ausreissergrenze"]
            oben = numerisch["obere_ausreissergrenze"]
            werte = pd.to_numeric(daten[name], errors="coerce")
            maske = (werte < unten) | (werte > oben)
            detail = (
                f"Median {numerisch['median']}; Q1 {numerisch['q1']}; "
                f"Q3 {numerisch['q3']}; IQR {numerisch['interquartilsabstand']}; "
                f"Grenzen {unten} bis {oben}"
            )
            ergebnis.append(
                ErkannteAuffaelligkeit(
                    name,
                    "Ausreißer",
                    anzahl,
                    anzahl / zeilen if zeilen else 0.0,
                    detail,
                    _beispielindizes(maske),
                )
            )
        zeit = spalte.get("zeitbezogen")
        if zeit and int(zeit["nicht_interpretierbare_werte"]):
            anzahl = int(zeit["nicht_interpretierbare_werte"])
            ergebnis.append(
                ErkannteAuffaelligkeit(
                    name,
                    "Zeitprobleme",
                    anzahl,
                    anzahl / zeilen if zeilen else 0.0,
                    f"Erfolgsquote: {float(zeit['erfolgsquote']):.1%}",
                )
            )
        ergebnis.append(
            ErkannteAuffaelligkeit(
                name,
                "Datentypprobleme",
                0,
                0.0,
                f"Profiltyp: {spalte['profiltyp']}; Pandas: {spalte['originaldatentyp']}",
            )
        )
    duplikate = int(profil["exakte_duplikate"])
    if duplikate:
        ergebnis.append(
            ErkannteAuffaelligkeit(
                "Gesamttabelle",
                "Duplikate",
                duplikate,
                duplikate / zeilen if zeilen else 0.0,
                "Exakt identische Zeilen",
                _beispielindizes(daten.duplicated(keep=False)),
            )
        )
    return tuple(ergebnis)


def filtere_auffaelligkeiten(
    auffaelligkeiten: tuple[ErkannteAuffaelligkeit, ...],
    *,
    nur_mit_befund: bool,
    arten: tuple[str, ...],
) -> tuple[ErkannteAuffaelligkeit, ...]:
    """Filtert Befunde ohne das zugrunde liegende Profil zu verändern."""
    return tuple(
        wert
        for wert in auffaelligkeiten
        if (not nur_mit_befund or wert.anzahl > 0) and (not arten or wert.art in arten)
    )


def fachlich_zulaessige_ersatzstrategien(
    profil: dict[str, Any], spalten: tuple[str, ...]
) -> tuple[str, ...]:
    """Begrenzt die Wertersetzung abhängig vom bestätigten Profiltyp."""
    profile = {str(wert["spaltenname"]): wert for wert in profil["spaltenprofile"]}
    if spalten and all(profile[name].get("numerisch") for name in spalten):
        return (
            "Frei definierter Wert",
            "Minimum",
            "Maximum",
            "Arithmetisches Mittel",
            "Median",
        )
    if spalten and all(profile[name].get("kategorial") for name in spalten):
        return ("Frei definierter Wert", "Häufigster Wert (Modus)")
    return ("Frei definierter Wert",)


def fachlich_zulaessige_fehlwertstrategien(
    profil: dict[str, Any], spalten: tuple[str, ...]
) -> tuple[str, ...]:
    """Kompatibilitätsalias für Aufrufer vor der Begrenzung durch Tabelle 3.11."""
    return fachlich_zulaessige_ersatzstrategien(profil, spalten)


def vergleiche_profile(
    vorher: dict[str, Any], nachher: dict[str, Any]
) -> tuple[dict[str, int | float | str | None], ...]:
    """Erzeugt einen kompakten Vergleich zentraler Gesamtkennzahlen."""

    def ausreisser(profil: dict[str, Any]) -> int:
        return sum(
            int(spalte["numerisch"]["potenzielle_ausreisser"])
            for spalte in profil["spaltenprofile"]
            if spalte.get("numerisch")
        )

    kennzahlen = {
        "Zeilen": (int(vorher["zeilen"]), int(nachher["zeilen"])),
        "Spalten": (int(vorher["spalten"]), int(nachher["spalten"])),
        "Echte Fehlwerte": (
            int(vorher["echte_fehlwerte"]),
            int(nachher["echte_fehlwerte"]),
        ),
        "Textuelle Platzhalter": (
            int(vorher["textuelle_platzhalter"]),
            int(nachher["textuelle_platzhalter"]),
        ),
        "Exakte Duplikate": (
            int(vorher["exakte_duplikate"]),
            int(nachher["exakte_duplikate"]),
        ),
        "Vollständig leere Spalten": (
            int(vorher["vollstaendig_leere_spalten"]),
            int(nachher["vollstaendig_leere_spalten"]),
        ),
        "Potenzielle Ausreißer": (ausreisser(vorher), ausreisser(nachher)),
    }
    return tuple(
        {
            "Kennzahl": name,
            "Vorher": alt,
            "Nachher": neu,
            "Absolute Veränderung": neu - alt,
            "Relative Veränderung": ((neu - alt) / alt) if alt else None,
        }
        for name, (alt, neu) in kennzahlen.items()
    )
