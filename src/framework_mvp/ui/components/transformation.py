"""Fachlich begrenzter Transformationseditor gemäß Tabelle 3.11."""

from dataclasses import asdict
from typing import Any, cast

import pandas as pd
import streamlit as st

from framework_mvp.application.transformation import (
    ermittle_ersatzwert_aus_profil,
    zaehle_zu_loeschende_zeilen,
)
from framework_mvp.application.transformations_service import TransformationsService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    FRAMEWORKKONFORME_TRANSFORMATIONSARTEN,
    TRANSFORMATIONSART_BEZEICHNUNGEN,
    Transformationsart,
    Transformationsplan,
    Transformationsschritt,
)
from framework_mvp.ui.helpers import fachliche_auswahl

TECHNISCHE_ZIELTYPEN = (
    "Text",
    "Ganzzahl",
    "Fließkommazahl",
    "Boolean",
    "Datum",
    "Uhrzeit",
    "Datum und Uhrzeit",
)


def _profil_spalten(profil: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(wert["spaltenname"]): wert
        for wert in profil.get("spaltenprofile", [])
        if isinstance(wert, dict) and wert.get("spaltenname") is not None
    }


def _ist_platzhalter(wert: object, zusaetzliche: tuple[str, ...]) -> bool:
    if not isinstance(wert, str):
        return False
    text = wert.strip()
    return (
        not text
        or text.upper() in {"NULL", "NAN", "N/A", "NA", "-"}
        or text.casefold() in {eintrag.casefold() for eintrag in zusaetzliche}
    )


def _jsonfaehiger_wert(wert: object) -> object:
    """Normalisiert von Pandas/Numpy gelieferte Skalare für den Transformationsplan."""
    item = getattr(wert, "item", None)
    if callable(item):
        return item()
    if isinstance(wert, pd.Timestamp):
        return wert.isoformat()
    return wert


def _konvertierung_formular(
    daten: pd.DataFrame,
) -> tuple[tuple[str, ...], dict[str, Any], str] | None:
    spalte = fachliche_auswahl("Spalte", [str(name) for name in daten.columns])
    zieltyp = fachliche_auswahl("Bestätigter technischer Zieldatentyp", TECHNISCHE_ZIELTYPEN)
    if spalte is None or zieltyp is None:
        st.info("Wählen Sie eine Spalte und einen Zieldatentyp aus.")
        return None
    parameter: dict[str, Any] = {"zieltyp": zieltyp, "fehlerverhalten": "Vorgang abbrechen"}
    if zieltyp in {"Datum", "Uhrzeit", "Datum und Uhrzeit"}:
        parameter["datumsformat"] = st.text_input("Datums-/Zeitformat (optional)")
    st.caption("Nicht konvertierbare Werte brechen den Vorgang ohne Datenverlust ab.")
    return (spalte,), parameter, f"{spalte} in {zieltyp} konvertieren"


def _wertersetzung_formular(
    daten: pd.DataFrame, profil: dict[str, Any]
) -> tuple[tuple[str, ...], dict[str, Any], str] | None:
    profile = _profil_spalten(profil)
    spalte = fachliche_auswahl("Spalte", [str(name) for name in daten.columns])
    auswahlart = fachliche_auswahl(
        "Zu ersetzende Werte",
        ("Einzelne konkrete Werte", "Fehlwertplatzhalter", "Potenzielle Ausreißer"),
    )
    if spalte is None or auswahlart is None:
        st.info("Wählen Sie eine Spalte und die Art der zu ersetzenden Werte aus.")
        return None
    spaltenprofil = profile.get(spalte, {})
    position = [str(name) for name in daten.columns].index(spalte)
    serie = cast(pd.Series, daten.iloc[:, position])
    if auswahlart == "Einzelne konkrete Werte":
        optionen = list(serie.dropna().drop_duplicates())
    elif auswahlart == "Fehlwertplatzhalter":
        zusaetzliche = tuple(profil.get("bestaetigte_zusaetzliche_platzhalter", ()))
        optionen = [
            wert
            for wert in serie.dropna().drop_duplicates()
            if _ist_platzhalter(wert, zusaetzliche)
        ]
    else:
        numerisch = spaltenprofil.get("numerisch")
        if not isinstance(numerisch, dict):
            optionen = []
        else:
            unten = numerisch.get("untere_ausreissergrenze")
            oben = numerisch.get("obere_ausreissergrenze")
            if unten is None or oben is None:
                optionen = []
            else:
                zahlen = pd.Series(pd.to_numeric(serie, errors="coerce"), index=serie.index)
                maske = (zahlen < unten) | (zahlen > oben)
                optionen = list(serie.loc[maske].drop_duplicates())
    gesuchte_werte = st.multiselect("Werte", optionen)
    numerisch = spaltenprofil.get("numerisch")
    kategorial = spaltenprofil.get("kategorial")
    strategien = ["Frei definierter Wert"]
    if isinstance(numerisch, dict):
        strategien.extend(("Minimum", "Maximum", "Arithmetisches Mittel", "Median"))
    if isinstance(kategorial, dict):
        strategien.append("Häufigster Wert (Modus)")
    strategie = fachliche_auswahl("Ersatz", strategien)
    if strategie is None:
        st.info("Wählen Sie eine Ersatzstrategie aus.")
        return None
    freier_wert: object = ""
    if strategie == "Frei definierter Wert":
        if isinstance(numerisch, dict):
            freier_wert = st.number_input("Frei definierter Ersatzwert")
        elif spaltenprofil.get("technischer_datentyp") == "Boolean":
            boolescher_wert = fachliche_auswahl("Frei definierter Ersatzwert", (True, False))
            if boolescher_wert is None:
                st.info("Wählen Sie einen booleschen Ersatzwert aus.")
                return None
            freier_wert = boolescher_wert
        else:
            freier_wert = st.text_input("Frei definierter Ersatzwert")
    ersatz = ermittle_ersatzwert_aus_profil(spaltenprofil, strategie, freier_wert)
    anzahl = int(serie.isin(gesuchte_werte).to_numpy().sum())
    serialisierbare_werte = [_jsonfaehiger_wert(wert) for wert in gesuchte_werte]
    ersatz = _jsonfaehiger_wert(ersatz)
    st.info(f"Betroffen: {anzahl} Beobachtungen · Ersatzwert: {ersatz!s}")
    return (
        (spalte,),
        {
            "auswahlart": auswahlart,
            "gesuchte_werte": serialisierbare_werte,
            "ersatzstrategie": strategie,
            "ersatzwert": ersatz,
            "betroffene_beobachtungen": anzahl,
        },
        f"{anzahl} Werte in {spalte} ersetzen",
    )


def _duplikate_formular(daten: pd.DataFrame) -> tuple[tuple[str, ...], dict[str, Any], str]:
    anzahl = int(daten.duplicated(keep="first").sum())
    st.info(
        f"{anzahl} zusätzliche, über alle {len(daten.columns)} Spalten vollständig "
        "übereinstimmende Tupel werden entfernt; ein Vorkommen bleibt erhalten."
    )
    return (), {"betroffene_tupel": anzahl}, f"{anzahl} exakte Tupel-Duplikate entfernen"


def _leere_spalten_formular(
    daten: pd.DataFrame,
) -> tuple[tuple[str, ...], dict[str, Any], str]:
    leere_spalten = tuple(
        str(daten.columns[position])
        for position in range(len(daten.columns))
        if daten.iloc[:, position].isna().to_numpy().all()
    )
    st.info(
        "Betroffene vollständig leere Spalten: "
        + (", ".join(leere_spalten) if leere_spalten else "keine")
    )
    return (
        leere_spalten,
        {"vollstaendig_leere_spalten": list(leere_spalten)},
        f"{len(leere_spalten)} vollständig leere Spalten entfernen",
    )


FILTEROPERATOREN = (
    "gleich",
    "ungleich",
    "enthält",
    "beginnt mit",
    "endet mit",
    "ist leer",
    "ist nicht leer",
    "kleiner",
    "kleiner oder gleich",
    "größer",
    "größer oder gleich",
    "zwischen",
    "vor",
    "nach",
    "zeitlich zwischen",
    "enthalten in",
    "nicht enthalten in",
)


def _zeilen_loeschen_formular(
    daten: pd.DataFrame,
) -> tuple[tuple[str, ...], dict[str, Any], str] | None:
    spalte = fachliche_auswahl("Spalte für Löschbedingung", [str(name) for name in daten.columns])
    operator = fachliche_auswahl("Operator der Löschbedingung", FILTEROPERATOREN)
    if spalte is None or operator is None:
        st.info("Wählen Sie eine Spalte und einen Operator aus.")
        return None
    parameter: dict[str, Any] = {"operator": operator}
    if operator in {"zwischen", "zeitlich zwischen"}:
        parameter["von"] = st.text_input("Unterer Wert beziehungsweise Startzeitpunkt")
        parameter["bis"] = st.text_input("Oberer Wert beziehungsweise Endzeitpunkt")
        vollstaendig = bool(parameter["von"] and parameter["bis"])
    elif operator in {"enthalten in", "nicht enthalten in"}:
        listenwert = st.text_area("Werteliste (ein Wert pro Zeile)")
        parameter["werte"] = [wert.strip() for wert in listenwert.splitlines() if wert.strip()]
        vollstaendig = bool(parameter["werte"])
    elif operator in {"ist leer", "ist nicht leer"}:
        vollstaendig = True
    else:
        parameter["wert"] = st.text_input("Vergleichswert")
        vollstaendig = bool(str(parameter["wert"]))
    if not vollstaendig:
        st.info("Vervollständigen Sie die Löschbedingung.")
        return None
    try:
        anzahl = zaehle_zu_loeschende_zeilen(daten, spalte, parameter)
    except (Domaenenfehler, TypeError, ValueError) as fehler:
        st.error(f"Die Löschbedingung ist ungültig: {fehler}")
        return None
    st.info(f"Vorschau: {anzahl} von {len(daten)} Zeilen werden gelöscht.")
    parameter["vorschau_zu_loeschende_zeilen"] = anzahl
    return (spalte,), parameter, f"{anzahl} Zeilen in {spalte} löschen"


def _text_bereinigen_formular(
    daten: pd.DataFrame,
) -> tuple[tuple[str, ...], dict[str, Any], str] | None:
    spalte = fachliche_auswahl("Textspalte", [str(name) for name in daten.columns])
    art = fachliche_auswahl(
        "Textoperation",
        (
            "Festen Präfix entfernen",
            "Festen Suffix entfernen",
            "Zwischen Begrenzern extrahieren",
        ),
    )
    if spalte is None or art is None:
        st.info("Wählen Sie eine Textspalte und eine Textoperation aus.")
        return None
    parameter: dict[str, Any] = {
        "art": art,
        "nichttreffer": "Originalwert beibehalten",
    }
    if art == "Festen Präfix entfernen":
        parameter["praefix"] = st.text_input("Fester Präfix")
        vollstaendig = bool(parameter["praefix"])
    elif art == "Festen Suffix entfernen":
        parameter["suffix"] = st.text_input("Fester Suffix")
        vollstaendig = bool(parameter["suffix"])
    else:
        parameter["startbegrenzer"] = st.text_input("Startbegrenzer")
        parameter["endbegrenzer"] = st.text_input("Endbegrenzer")
        vollstaendig = bool(parameter["startbegrenzer"] and parameter["endbegrenzer"])
    st.caption("Sicherer Standard: Werte ohne Treffer bleiben unverändert.")
    if not vollstaendig:
        st.info("Geben Sie die erforderlichen Begrenzer vollständig an.")
        return None
    return (spalte,), parameter, f"Text in {spalte}: {art}"


def _neuer_schritt(
    art: Transformationsart,
    daten: pd.DataFrame,
    profil: dict[str, Any],
    reihenfolge: int,
) -> Transformationsschritt | None:
    if art is Transformationsart.DATENTYP_KONVERTIEREN:
        ergebnis = _konvertierung_formular(daten)
    elif art is Transformationsart.WERTE_ERSETZEN:
        ergebnis = _wertersetzung_formular(daten, profil)
    elif art is Transformationsart.EXAKTE_TUPEL_DUPLIKATE_ENTFERNEN:
        ergebnis = _duplikate_formular(daten)
    elif art is Transformationsart.VOLLSTAENDIG_LEERE_SPALTEN_ENTFERNEN:
        ergebnis = _leere_spalten_formular(daten)
    elif art is Transformationsart.ZEILEN_LOESCHEN:
        ergebnis = _zeilen_loeschen_formular(daten)
    else:
        ergebnis = _text_bereinigen_formular(daten)
    if ergebnis is None:
        return None
    spalten, parameter, beschreibung = ergebnis
    return Transformationsschritt.neu(
        typ=art,
        betroffene_spalten=spalten,
        parameter=parameter,
        reihenfolge=reihenfolge,
        beschreibung=beschreibung,
    )


def zeige_transformationseditor(
    service: TransformationsService,
    plan: Transformationsplan,
    ausgangsdaten: pd.DataFrame,
    ausgangsprofil: dict[str, Any],
) -> Transformationsplan:
    """Erfasst die explizit frameworkkonformen Transformationen für Schritt 2."""
    st.subheader("Transformationsplan")
    st.caption(
        "Transformationen werden nur nach Ihrer ausdrücklichen Auswahl ausgeführt. "
        "Ein Durchlauf ohne Transformation ist zulässig."
    )
    for schritt in sorted(plan.schritte, key=lambda wert: wert.reihenfolge):
        if schritt.typ is Transformationsart.TABELLEN_JOIN:
            continue
        if not schritt.frameworkkonform:
            st.warning(
                f"Legacy-Schritt '{schritt.typ.value}' ist nicht mehr frameworkkonform und "
                "wird nicht ausgeführt."
            )
        else:
            st.write(f"{schritt.reihenfolge}. {schritt.beschreibung}")
        if st.button("Schritt entfernen", key=f"etl_remove_{schritt.transformationsschritt_id}"):
            plan = service.schritt_entfernen(plan, schritt.transformationsschritt_id)
            service.plan_speichern(plan)
            st.session_state.etl_transformationsplan = plan
            st.rerun()

    st.write("**Transformation hinzufügen**")
    art = fachliche_auswahl(
        "Transformationsart",
        FRAMEWORKKONFORME_TRANSFORMATIONSARTEN,
        format_func=TRANSFORMATIONSART_BEZEICHNUNGEN.__getitem__,
    )
    schritt = (
        _neuer_schritt(art, ausgangsdaten, ausgangsprofil, len(plan.schritte) + 1)
        if art is not None
        else None
    )
    if art is None:
        st.info("Wählen Sie zuerst eine Transformationsart aus.")
    if st.button("Transformation zum Plan hinzufügen", disabled=schritt is None):
        assert schritt is not None
        plan = service.schritt_hinzufuegen(plan, schritt)
        service.plan_speichern(plan)
        st.session_state.etl_transformationsplan = plan
        st.rerun()

    if st.button("Transformationsvorschau berechnen", type="primary"):
        ergebnis = service.vorschau(plan)
        st.session_state.etl_transformationsergebnis = ergebnis
        st.dataframe(ergebnis.vorschau, width="stretch")
        if ergebnis.historie:
            st.dataframe([asdict(wert) for wert in ergebnis.historie], hide_index=True)
        else:
            st.info("Keine Transformation ausgewählt; der Datensatz bleibt unverändert.")
    return plan
