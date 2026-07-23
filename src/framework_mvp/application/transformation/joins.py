# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportCallIssue=false
"""Prüfung und Ausführung explizit konfigurierter Tabellenverknüpfungen."""

from dataclasses import dataclass

import pandas as pd

from framework_mvp.domain.exceptions import Domaenenfehler


@dataclass(frozen=True, slots=True)
class JoinPruefung:
    """Kardinalität und erwartete Wirkung einer Tabellenverknüpfung."""

    kardinalitaet: str
    fehlende_schluessel_links: int
    fehlende_schluessel_rechts: int
    doppelte_schluessel_links: int
    doppelte_schluessel_rechts: int
    nicht_zuordenbar_links: int
    nicht_zuordenbar_rechts: int
    erwartete_zeilen: int
    warnungen: tuple[str, ...]


def pruefe_join(
    links: pd.DataFrame,
    rechts: pd.DataFrame,
    linke_schluessel: tuple[str, ...],
    rechte_schluessel: tuple[str, ...],
) -> JoinPruefung:
    """Prüft Schlüsseltypen, Kardinalität, Leerwerte und Vervielfachung."""
    if len(linke_schluessel) != len(rechte_schluessel) or not linke_schluessel:
        raise Domaenenfehler("Ein Join benötigt gleich viele linke und rechte Schlüsselspalten.")
    for links_name, rechts_name in zip(linke_schluessel, rechte_schluessel, strict=True):
        if str(links[links_name].dtype) != str(rechts[rechts_name].dtype):
            raise Domaenenfehler(
                "Die technischen Datentypen der Join-Schlüssel stimmen nicht überein."
            )
    links_duplikate = int(links.duplicated(list(linke_schluessel), keep=False).sum())
    rechts_duplikate = int(rechts.duplicated(list(rechte_schluessel), keep=False).sum())
    links_eindeutig = links_duplikate == 0
    rechts_eindeutig = rechts_duplikate == 0
    kardinalitaet = (
        "1:1"
        if links_eindeutig and rechts_eindeutig
        else "1:n"
        if links_eindeutig
        else "n:1"
        if rechts_eindeutig
        else "n:m"
    )
    linke_keys = links[list(linke_schluessel)].drop_duplicates()
    rechte_keys = rechts[list(rechte_schluessel)].drop_duplicates()
    angepasst = rechte_keys.rename(
        columns=dict(zip(rechte_schluessel, linke_schluessel, strict=True))
    )
    nicht_links = len(
        linke_keys.merge(angepasst, how="left", indicator=True).query("_merge == 'left_only'")
    )
    nicht_rechts = len(
        angepasst.merge(linke_keys, how="left", indicator=True).query("_merge == 'left_only'")
    )
    erwartet = len(
        links.merge(
            rechts,
            how="inner",
            left_on=list(linke_schluessel),
            right_on=list(rechte_schluessel),
        )
    )
    warnungen = (
        ("n:m-Verknüpfung kann Zeilen vervielfachen und benötigt Bestätigung.",)
        if kardinalitaet == "n:m"
        else ()
    )
    return JoinPruefung(
        kardinalitaet,
        int(links[list(linke_schluessel)].isna().any(axis=1).sum()),
        int(rechts[list(rechte_schluessel)].isna().any(axis=1).sum()),
        links_duplikate,
        rechts_duplikate,
        nicht_links,
        nicht_rechts,
        erwartet,
        warnungen,
    )


def fuehre_join_aus(
    links: pd.DataFrame,
    rechts: pd.DataFrame,
    *,
    join_art: str,
    linke_schluessel: tuple[str, ...],
    rechte_schluessel: tuple[str, ...],
    suffixe: tuple[str, str] = ("_links", "_rechts"),
    nm_bestaetigt: bool = False,
) -> tuple[pd.DataFrame, JoinPruefung]:
    """Führt einen geprüften Join auf Kopien aus und schützt n:m-Verknüpfungen."""
    pruefung = pruefe_join(links, rechts, linke_schluessel, rechte_schluessel)
    if pruefung.kardinalitaet == "n:m" and not nm_bestaetigt:
        raise Domaenenfehler("Eine n:m-Verknüpfung muss ausdrücklich bestätigt werden.")
    pandas_art = {"INNER": "inner", "LEFT": "left", "RIGHT": "right", "FULL OUTER": "outer"}
    if join_art not in pandas_art:
        raise Domaenenfehler(f"Die Join-Art {join_art} wird nicht unterstützt.")
    ergebnis = links.copy(deep=True).merge(
        rechts.copy(deep=True),
        how=pandas_art[join_art],
        left_on=list(linke_schluessel),
        right_on=list(rechte_schluessel),
        suffixes=suffixe,
    )
    return ergebnis, pruefung
