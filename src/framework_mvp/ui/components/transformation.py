"""Fachlich begrenzter Transformationseditor gemäß Tabelle 3.11."""

from dataclasses import asdict
from typing import Any, cast

import pandas as pd
import streamlit as st

from framework_mvp.application.transformation import ermittle_ersatzwert_aus_profil
from framework_mvp.application.transformations_service import TransformationsService
from framework_mvp.domain.models import (
    FRAMEWORKKONFORME_TRANSFORMATIONSARTEN,
    TRANSFORMATIONSART_BEZEICHNUNGEN,
    Transformationsart,
    Transformationsplan,
    Transformationsschritt,
)

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


def _konvertierung_formular(daten: pd.DataFrame) -> tuple[tuple[str, ...], dict[str, Any], str]:
    spalte = st.selectbox("Spalte", [str(name) for name in daten.columns])
    zieltyp = st.selectbox("Bestätigter technischer Zieldatentyp", TECHNISCHE_ZIELTYPEN)
    parameter: dict[str, Any] = {"zieltyp": zieltyp, "fehlerverhalten": "Vorgang abbrechen"}
    if zieltyp in {"Datum", "Uhrzeit", "Datum und Uhrzeit"}:
        parameter["datumsformat"] = st.text_input("Datums-/Zeitformat (optional)")
    st.caption("Nicht konvertierbare Werte brechen den Vorgang ohne Datenverlust ab.")
    return (spalte,), parameter, f"{spalte} in {zieltyp} konvertieren"


def _wertersetzung_formular(
    daten: pd.DataFrame, profil: dict[str, Any]
) -> tuple[tuple[str, ...], dict[str, Any], str]:
    profile = _profil_spalten(profil)
    spalte = st.selectbox("Spalte", [str(name) for name in daten.columns])
    spaltenprofil = profile.get(spalte, {})
    auswahlart = st.selectbox(
        "Zu ersetzende Werte",
        ("Einzelne konkrete Werte", "Fehlwertplatzhalter", "Potenzielle Ausreißer"),
    )
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
    strategie = st.selectbox("Ersatz", strategien)
    freier_wert: object = ""
    if strategie == "Frei definierter Wert":
        if isinstance(numerisch, dict):
            freier_wert = st.number_input("Frei definierter Ersatzwert")
        elif spaltenprofil.get("technischer_datentyp") == "Boolean":
            freier_wert = st.selectbox("Frei definierter Ersatzwert", (True, False))
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


def _neuer_schritt(
    art: Transformationsart,
    daten: pd.DataFrame,
    profil: dict[str, Any],
    reihenfolge: int,
) -> Transformationsschritt:
    if art is Transformationsart.DATENTYP_KONVERTIEREN:
        spalten, parameter, beschreibung = _konvertierung_formular(daten)
    elif art is Transformationsart.WERTE_ERSETZEN:
        spalten, parameter, beschreibung = _wertersetzung_formular(daten, profil)
    elif art is Transformationsart.EXAKTE_TUPEL_DUPLIKATE_ENTFERNEN:
        spalten, parameter, beschreibung = _duplikate_formular(daten)
    else:
        spalten, parameter, beschreibung = _leere_spalten_formular(daten)
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
    """Erfasst ausschließlich die vier Transformationen aus Tabelle 3.11."""
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
    art = st.selectbox(
        "Transformationsart",
        FRAMEWORKKONFORME_TRANSFORMATIONSARTEN,
        format_func=TRANSFORMATIONSART_BEZEICHNUNGEN.__getitem__,
    )
    schritt = _neuer_schritt(art, ausgangsdaten, ausgangsprofil, len(plan.schritte) + 1)
    if st.button("Transformation zum Plan hinzufügen"):
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
