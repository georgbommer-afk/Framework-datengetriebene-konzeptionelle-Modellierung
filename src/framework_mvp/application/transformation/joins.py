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
    join_art: str = "INNER"
    moeglicher_datenverlust: bool = False
    moegliche_zeilenvervielfachung: bool = False


def pruefe_join(
    links: pd.DataFrame,
    rechts: pd.DataFrame,
    linke_schluessel: tuple[str, ...],
    rechte_schluessel: tuple[str, ...],
    join_art: str = "INNER",
) -> JoinPruefung:
    """Prüft Schlüsseltypen, Kardinalität, Leerwerte und Vervielfachung."""
    if len(linke_schluessel) != len(rechte_schluessel) or not linke_schluessel:
        raise Domaenenfehler("Ein Join benötigt gleich viele linke und rechte Schlüsselspalten.")
    pandas_arten = {"INNER": "inner", "LEFT": "left", "RIGHT": "right", "OUTER": "outer"}
    if join_art not in pandas_arten:
        raise Domaenenfehler(f"Die Join-Art {join_art} wird nicht unterstützt.")
    for links_name, rechts_name in zip(linke_schluessel, rechte_schluessel, strict=True):
        if links_name not in links.columns or rechts_name not in rechts.columns:
            raise Domaenenfehler("Mindestens eine ausgewählte Join-Schlüsselspalte fehlt.")
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
    linke_keys = links[list(linke_schluessel)].dropna().drop_duplicates()
    rechte_keys = rechts[list(rechte_schluessel)].dropna().drop_duplicates()
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
            how=pandas_arten[join_art],
            left_on=list(linke_schluessel),
            right_on=list(rechte_schluessel),
        )
    )
    datenverlust = (
        (join_art == "INNER" and (nicht_links > 0 or nicht_rechts > 0))
        or (join_art == "LEFT" and nicht_rechts > 0)
        or (join_art == "RIGHT" and nicht_links > 0)
    )
    linke_gueltige_keys = links[list(linke_schluessel)].dropna()
    rechte_gueltige_keys = (
        rechts[list(rechte_schluessel)]
        .dropna()
        .rename(columns=dict(zip(rechte_schluessel, linke_schluessel, strict=True)))
    )
    schluesseltreffer = linke_gueltige_keys.merge(
        rechte_gueltige_keys,
        how="inner",
        on=list(linke_schluessel),
    )
    vervielfachung = len(schluesseltreffer) > len(schluesseltreffer.drop_duplicates())
    fehlend_links = int(links[list(linke_schluessel)].isna().any(axis=1).sum())
    fehlend_rechts = int(rechts[list(rechte_schluessel)].isna().any(axis=1).sum())
    warnungen: list[str] = []
    if fehlend_links or fehlend_rechts:
        warnungen.append(
            "Mindestens ein Join-Schlüsselwert fehlt; die betroffenen Zeilen werden "
            "abhängig von der Join-Art nicht zugeordnet."
        )
    if datenverlust:
        warnungen.append(f"Der {join_art} Join kann nicht zuordenbare Zeilen ausschließen.")
    if vervielfachung:
        warnungen.append("Die Verknüpfung kann Zeilen vervielfachen und benötigt Bestätigung.")
    return JoinPruefung(
        kardinalitaet,
        fehlend_links,
        fehlend_rechts,
        links_duplikate,
        rechts_duplikate,
        nicht_links,
        nicht_rechts,
        erwartet,
        tuple(warnungen),
        join_art,
        datenverlust,
        vervielfachung,
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
    if join_art == "FULL OUTER":
        join_art = "OUTER"
    pruefung = pruefe_join(links, rechts, linke_schluessel, rechte_schluessel, join_art=join_art)
    if pruefung.moegliche_zeilenvervielfachung and not nm_bestaetigt:
        raise Domaenenfehler(
            "Eine mögliche Zeilenvervielfachung muss ausdrücklich bestätigt werden."
        )
    pandas_art = {"INNER": "inner", "LEFT": "left", "RIGHT": "right", "OUTER": "outer"}
    ergebnis = links.copy(deep=True).merge(
        rechts.copy(deep=True),
        how=pandas_art[join_art],
        left_on=list(linke_schluessel),
        right_on=list(rechte_schluessel),
        suffixes=suffixe,
    )
    return ergebnis, pruefung
