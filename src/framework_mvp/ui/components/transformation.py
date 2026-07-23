"""Streamlit-Darstellung für profilgestützte Transformationspläne."""

import json
from dataclasses import asdict
from typing import Any

import pandas as pd
import streamlit as st

from framework_mvp.application.profiling.entscheidungsgrundlage import (
    AUFFAELLIGKEITSARTEN,
    ErkannteAuffaelligkeit,
    bereite_gemischte_anzeigetabelle,
    ermittle_auffaelligkeiten,
    fachlich_zulaessige_fehlwertstrategien,
    filtere_auffaelligkeiten,
    transformationsart_fuer_auffaelligkeit,
    vergleiche_profile,
)
from framework_mvp.application.transformations_service import TransformationsService
from framework_mvp.domain.models import (
    Transformationsart,
    Transformationsplan,
    Transformationsschritt,
)


def _standardparameter(art: Transformationsart, spalten: list[str]) -> dict[str, Any]:
    """Liefert neutrale, nicht automatisch angewandte Standardparameter."""
    erste = spalten[0] if spalten else ""
    return {
        Transformationsart.SPALTENAUSWAHL: {},
        Transformationsart.UMBENENNEN: {"mapping": {erste: f"{erste}_neu"}},
        Transformationsart.DATENTYP_KONVERTIEREN: {
            "zieltyp": "Text",
            "fehlerverhalten": "Vorgang abbrechen",
        },
        Transformationsart.PLATZHALTER_BEHANDELN: {"strategie": "Unverändert lassen"},
        Transformationsart.FEHLWERTE_BEHANDELN: {"strategie": "Unverändert lassen"},
        Transformationsart.DUPLIKATE_BEHANDELN: {"strategie": "Unverändert lassen"},
        Transformationsart.AUSREISSER_BEHANDELN: {
            "methode": "IQR",
            "strategie": "Unverändert lassen",
        },
        Transformationsart.ZEILEN_FILTERN: {"operator": "gleich", "wert": ""},
        Transformationsart.ABGELEITETE_SPALTE: {
            "zielspalte": "abgeleitete_spalte",
            "art": "Konstante",
            "wert": "",
        },
        Transformationsart.TABELLEN_JOIN: {},
    }[art]


def _profil_spalten(profil: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(wert["spaltenname"]): wert for wert in profil["spaltenprofile"]}


def _qualitaetsuebersicht(profil: dict[str, Any]) -> None:
    """Zeigt die dauerhaft sichtbare, kompakte Ausgangsqualität."""
    ausreisser = sum(
        int(wert["numerisch"]["potenzielle_ausreisser"])
        for wert in profil["spaltenprofile"]
        if wert.get("numerisch")
    )
    st.write("**Qualitätsübersicht des bestätigten Ausgangsdatensatzes**")
    st.dataframe(
        pd.DataFrame(
            [
                ("Zeilen", profil["zeilen"]),
                ("Spalten", profil["spalten"]),
                ("Echte Fehlwerte", profil["echte_fehlwerte"]),
                ("Textuelle Platzhalter", profil["textuelle_platzhalter"]),
                ("Exakte Duplikate", profil["exakte_duplikate"]),
                ("Vollständig leere Spalten", profil["vollstaendig_leere_spalten"]),
                ("Potenzielle Ausreißer", ausreisser),
                ("Numerische Spalten", profil["numerische_spalten"]),
                ("Kategoriale Spalten", profil["kategoriale_spalten"]),
                ("Zeitbezogene Spalten", profil["zeitbezogene_spalten"]),
            ],
            columns=["Kennzahl", "Wert"],
        ),
        hide_index=True,
        width="stretch",
    )


def _auffaelligkeiten(
    profil: dict[str, Any], daten: pd.DataFrame
) -> tuple[ErkannteAuffaelligkeit, ...]:
    """Zeigt filterbare Befunde und setzt auf Wunsch nur eine Formularvorauswahl."""
    alle = ermittle_auffaelligkeiten(profil, daten)
    with st.expander("Erkannte Auffälligkeiten"):
        nur_befunde = st.checkbox("Nur Spalten mit Auffälligkeiten", value=True)
        arten = tuple(st.multiselect("Auffälligkeitsart", AUFFAELLIGKEITSARTEN))
        sichtbar = filtere_auffaelligkeiten(alle, nur_mit_befund=nur_befunde, arten=arten)
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Spalte": wert.spaltenname,
                        "Art": wert.art,
                        "Anzahl": wert.anzahl,
                        "Anteil": wert.anteil,
                        "Details": wert.detailwerte,
                        "Beispielzeilen": ", ".join(map(str, wert.beispielzeilen)),
                    }
                    for wert in sichtbar
                ]
            ),
            hide_index=True,
            column_config={"Anteil": st.column_config.NumberColumn(format="%.1%%")},
            width="stretch",
        )
        optionen = [
            wert
            for wert in sichtbar
            if wert.spaltenname != "Gesamttabelle"
            and wert.art in {"Fehlwerte", "Platzhalter", "Ausreißer", "Datentypprobleme"}
        ]
        if optionen:
            auswahl = st.selectbox(
                "Auffälligkeit für Transformation auswählen",
                optionen,
                format_func=lambda wert: f"{wert.spaltenname} – {wert.art}",
            )
            if st.button("Transformation für diese Spalte konfigurieren"):
                st.session_state.transformations_vorauswahl = (
                    transformationsart_fuer_auffaelligkeit(auswahl.art),
                    auswahl.spaltenname,
                )
                st.rerun()
    return alle


def _kontexthinweise(
    art: Transformationsart,
    betroffene: list[str],
    profil: dict[str, Any],
    daten: pd.DataFrame,
    parameter: dict[str, Any],
) -> None:
    """Zeigt ausschließlich zur gewählten Transformation passende Profilwerte."""
    profile = _profil_spalten(profil)
    for name in betroffene:
        spalte = profile[name]
        fehlwerte = spalte["fehlwerte"]
        if art is Transformationsart.AUSREISSER_BEHANDELN and spalte.get("numerisch"):
            wert = spalte["numerisch"]
            st.info(
                f"{name}: {wert['potenzielle_ausreisser']} Ausreißer · "
                f"Min {wert['minimum']} · Max {wert['maximum']} · Median {wert['median']} · "
                f"Q1 {wert['q1']} · Q3 {wert['q3']} · IQR {wert['interquartilsabstand']} · "
                f"Grenzen {wert['untere_ausreissergrenze']} bis "
                f"{wert['obere_ausreissergrenze']}"
            )
            werte = pd.to_numeric(daten[name], errors="coerce")
            unten = wert["untere_ausreissergrenze"]
            oben = wert["obere_ausreissergrenze"]
            maske = (
                ((werte < unten) | (werte > oben))
                if unten is not None and oben is not None
                else pd.Series(False, index=daten.index)
            )
            if maske.any():
                st.dataframe(daten.loc[maske].head(5), width="stretch")
        elif art is Transformationsart.FEHLWERTE_BEHANDELN:
            st.info(
                f"{name}: {fehlwerte['echte_fehlwerte']} echte Fehlwerte "
                f"({fehlwerte['anteil_echter_fehlwerte']:.1%}) · "
                f"Profiltyp {spalte['profiltyp']} · Pandas {spalte['originaldatentyp']}"
            )
            if fehlwerte["echte_fehlwerte"]:
                st.dataframe(daten.loc[daten[name].isna()].head(5), width="stretch")
        elif art is Transformationsart.PLATZHALTER_BEHANDELN:
            klassen = [
                f"{wert['bezeichnung']}: {wert['anzahl']}"
                for wert in fehlwerte["platzhalterklassen"]
                if wert["anzahl"]
            ]
            st.info(f"{name}: {', '.join(klassen) or 'keine erkannten Platzhalter'}")
            maske = (
                daten[name]
                .astype("string")
                .str.strip()
                .str.upper()
                .isin(("", "NULL", "N/A", "NA", "NAN", "-"))
            )
            if maske.any():
                st.dataframe(daten.loc[maske].head(5), width="stretch")
        elif art is Transformationsart.DATENTYP_KONVERTIEREN:
            zieltyp = parameter["zieltyp"]
            if zieltyp in {"Ganzzahl", "Fließkommazahl"}:
                probe = pd.to_numeric(daten[name], errors="coerce")
            elif zieltyp in {"Datum", "Datum und Uhrzeit"}:
                probe = pd.to_datetime(daten[name], errors="coerce")
            else:
                probe = daten[name].astype("string")
            problematisch = daten[name].notna() & pd.Series(probe).isna()
            st.info(
                f"{name}: Pandas-Typ {spalte['originaldatentyp']} · "
                f"Profiltyp {spalte['profiltyp']} · "
                f"{int((~problematisch & daten[name].notna()).sum())} potenziell "
                f"konvertierbar · {int(problematisch.sum())} problematisch"
            )
            if problematisch.any():
                st.dataframe(daten.loc[problematisch].head(5), width="stretch")
    if art is Transformationsart.DUPLIKATE_BEHANDELN:
        maske = daten.duplicated(subset=betroffene or None, keep=False)
        st.info(
            f"{int(maske.sum())} betroffene Zeilen bei der aktuellen "
            f"Schlüsselauswahl; {max(len(daten) - int(maske.sum()), 0)} nicht betroffen."
        )
        if maske.any():
            st.dataframe(daten.loc[maske].head(5), width="stretch")


def _spaltenoptionen(
    art: Transformationsart, profil: dict[str, Any], alle_spalten: list[str]
) -> list[str]:
    profile = _profil_spalten(profil)
    if art is Transformationsart.AUSREISSER_BEHANDELN:
        return [name for name in alle_spalten if profile[name].get("numerisch")]
    if art is Transformationsart.PLATZHALTER_BEHANDELN and not st.checkbox(
        "Auch Spalten ohne erkannte Platzhalter anzeigen"
    ):
        return [name for name in alle_spalten if int(profile[name]["fehlwerte"]["platzhalter"]) > 0]
    return alle_spalten


def _parameterformular(
    art: Transformationsart,
    betroffene: list[str],
    profil: dict[str, Any],
) -> dict[str, Any]:
    """Erfasst häufige Qualitätsbehandlungen über fachlich begrenzte Optionen."""
    if art is Transformationsart.FEHLWERTE_BEHANDELN:
        strategie = st.selectbox(
            "Fehlwertstrategie",
            fachlich_zulaessige_fehlwertstrategien(profil, tuple(betroffene)),
        )
        parameter: dict[str, Any] = {"strategie": strategie}
        if strategie == "Festen Wert einsetzen":
            parameter["wert"] = st.text_input("Einzusetzender Wert")
        return parameter
    if art is Transformationsart.PLATZHALTER_BEHANDELN:
        strategie = st.selectbox(
            "Platzhalterstrategie",
            (
                "Unverändert lassen",
                "Als echten Fehlwert interpretieren",
                "Durch Wert ersetzen",
            ),
        )
        parameter = {"strategie": strategie}
        if strategie == "Durch Wert ersetzen":
            parameter["wert"] = st.text_input("Ersatzwert")
        return parameter
    if art is Transformationsart.AUSREISSER_BEHANDELN:
        methode = st.selectbox("Erkennungsmethode", ("IQR", "Manuelle Grenzen"))
        parameter = {
            "methode": methode,
            "strategie": st.selectbox(
                "Ausreißerstrategie",
                (
                    "Unverändert lassen",
                    "Markieren",
                    "Zeilen entfernen",
                    "Auf Grenzwerte begrenzen",
                    "Als fehlend markieren",
                ),
            ),
        }
        if methode == "Manuelle Grenzen":
            parameter["untere_grenze"] = st.number_input("Untere Grenze")
            parameter["obere_grenze"] = st.number_input("Obere Grenze")
        return parameter
    if art is Transformationsart.DUPLIKATE_BEHANDELN:
        return {
            "strategie": st.selectbox(
                "Duplikatstrategie",
                ("Unverändert lassen", "Markieren", "Entfernen"),
            ),
            "behalten": st.selectbox(
                "Vorkommen behandeln",
                ("Erstes Vorkommen", "Letztes Vorkommen", "Alle"),
            ),
        }
    if art is Transformationsart.DATENTYP_KONVERTIEREN:
        return {
            "zieltyp": st.selectbox(
                "Zieldatentyp",
                ("Text", "Ganzzahl", "Fließkommazahl", "Boolean", "Datum", "Datum und Uhrzeit"),
            ),
            "fehlerverhalten": st.selectbox(
                "Verhalten bei Konvertierungsfehlern",
                (
                    "Vorgang abbrechen",
                    "Wert als fehlend markieren",
                    "Ursprünglichen Wert beibehalten",
                ),
            ),
        }
    standard = _standardparameter(art, betroffene)
    return json.loads(
        st.text_area(
            "Parameter als nachvollziehbares JSON",
            value=json.dumps(standard, ensure_ascii=False, indent=2),
            help="Erst die Schaltfläche unterhalb fügt die Transformation dem Plan hinzu.",
            key=f"transformationsparameter_{art.value}",
        )
    )


def _vorher_nachher(
    service: TransformationsService,
    plan: Transformationsplan,
    ausgangsprofil: dict[str, Any],
    ergebnis: Any,
) -> None:
    """Cached das Ergebnisprofil ausschließlich anhand des vollständigen Plans."""
    schluessel = service.profil_cache_schluessel(plan)
    cache = st.session_state.setdefault("etl_vorschauprofile", {})
    if schluessel not in cache:
        cache.clear()
        cache[schluessel] = service.vorschauprofil_erstellen(ergebnis)
    nachher = asdict(cache[schluessel].profil)
    st.write("**Vorher-Nachher-Profil**")
    st.dataframe(
        pd.DataFrame(vergleiche_profile(ausgangsprofil, nachher)),
        hide_index=True,
        column_config={"Relative Veränderung": st.column_config.NumberColumn(format="%.1%%")},
        width="stretch",
    )
    gemeinsame = sorted(set(_profil_spalten(ausgangsprofil)) & set(_profil_spalten(nachher)))
    if gemeinsame:
        detail = st.selectbox("Detailspalte vergleichen", gemeinsame)
        vorher = _profil_spalten(ausgangsprofil)[detail]
        nach = _profil_spalten(nachher)[detail]
        vorher_detail = (
            vorher["numerisch"]["median"]
            if vorher.get("numerisch")
            else (
                vorher["kategorial"]["haeufigste_werte"][0]["bezeichnung"]
                if vorher.get("kategorial") and vorher["kategorial"]["haeufigste_werte"]
                else None
            )
        )
        nachher_detail = (
            nach["numerisch"]["median"]
            if nach.get("numerisch")
            else (
                nach["kategorial"]["haeufigste_werte"][0]["bezeichnung"]
                if nach.get("kategorial") and nach["kategorial"]["haeufigste_werte"]
                else None
            )
        )
        st.dataframe(
            bereite_gemischte_anzeigetabelle(
                (
                    ("Datentyp", vorher["originaldatentyp"], nach["originaldatentyp"]),
                    (
                        "Gültige Werte",
                        vorher["fehlwerte"]["gueltige_regulaere_werte"],
                        nach["fehlwerte"]["gueltige_regulaere_werte"],
                    ),
                    (
                        "Fehlwerte",
                        vorher["fehlwerte"]["echte_fehlwerte"],
                        nach["fehlwerte"]["echte_fehlwerte"],
                    ),
                    (
                        "Platzhalter",
                        vorher["fehlwerte"]["platzhalter"],
                        nach["fehlwerte"]["platzhalter"],
                    ),
                    ("Eindeutige Werte", vorher["eindeutige_werte"], nach["eindeutige_werte"]),
                    ("Median/häufigster Wert", vorher_detail, nachher_detail),
                )
            ),
            hide_index=True,
        )


def zeige_transformationseditor(
    service: TransformationsService,
    plan: Transformationsplan,
    daten: pd.DataFrame,
    ausgangsprofil: dict[str, Any],
) -> Transformationsplan:
    """Zeigt Profil, Editor, Historie und separates Vorschauprofil."""
    st.subheader("Daten transformieren")
    _qualitaetsuebersicht(ausgangsprofil)
    _auffaelligkeiten(ausgangsprofil, daten)
    st.caption(
        "Profilinformationen sind Entscheidungshilfen. Keine Transformation wird "
        "automatisch hinzugefügt oder ausgeführt."
    )
    arten = [wert for wert in Transformationsart if wert is not Transformationsart.TABELLEN_JOIN]
    vorauswahl = st.session_state.pop("transformations_vorauswahl", None)
    art_index = arten.index(vorauswahl[0]) if vorauswahl else 0
    art = st.selectbox(
        "Transformationsart",
        arten,
        index=art_index,
        format_func=lambda wert: wert.value.replace("_", " ").capitalize(),
    )
    alle_spalten = [str(wert) for wert in daten.columns]
    optionen = _spaltenoptionen(art, ausgangsprofil, alle_spalten)
    standard_spalten = [vorauswahl[1]] if vorauswahl and vorauswahl[1] in optionen else []
    betroffene = st.multiselect("Betroffene Spalten", optionen, default=standard_spalten)
    parameter = _parameterformular(art, betroffene, ausgangsprofil)
    _kontexthinweise(art, betroffene, ausgangsprofil, daten, parameter)
    st.caption(f"Persistierte Parameter: {json.dumps(parameter, ensure_ascii=False)}")
    begruendung = st.text_input("Fachliche Begründung (optional)")
    if st.button("Transformationsschritt hinzufügen", type="primary"):
        schritt = Transformationsschritt.neu(
            typ=art,
            betroffene_spalten=tuple(betroffene),
            parameter=parameter,
            reihenfolge=len(plan.schritte) + 1,
            beschreibung=art.value.replace("_", " ").capitalize(),
            fachliche_begruendung=begruendung,
        )
        plan = service.schritt_hinzufuegen(plan, schritt)
        service.plan_speichern(plan)
        st.session_state.etl_transformationsplan = plan
        st.rerun()

    for schritt in sorted(plan.schritte, key=lambda wert: wert.reihenfolge):
        with st.expander(f"{schritt.reihenfolge}. {schritt.beschreibung}"):
            st.code(schritt.parameter_json, language="json")
            aktiv, hoch, runter, entfernen = st.columns(4)
            if aktiv.button(
                "Deaktivieren" if schritt.aktiviert else "Aktivieren",
                key=f"aktiv_{schritt.transformationsschritt_id}",
            ):
                plan = service.schritt_aktivieren(
                    plan, schritt.transformationsschritt_id, not schritt.aktiviert
                )
                service.plan_speichern(plan)
                st.session_state.etl_transformationsplan = plan
                st.rerun()
            if hoch.button(
                "Nach oben",
                disabled=schritt.reihenfolge == 1,
                key=f"hoch_{schritt.transformationsschritt_id}",
            ):
                plan = service.schritt_verschieben(
                    plan, schritt.transformationsschritt_id, schritt.reihenfolge - 1
                )
                service.plan_speichern(plan)
                st.session_state.etl_transformationsplan = plan
                st.rerun()
            if runter.button(
                "Nach unten",
                disabled=schritt.reihenfolge == len(plan.schritte),
                key=f"runter_{schritt.transformationsschritt_id}",
            ):
                plan = service.schritt_verschieben(
                    plan, schritt.transformationsschritt_id, schritt.reihenfolge + 1
                )
                service.plan_speichern(plan)
                st.session_state.etl_transformationsplan = plan
                st.rerun()
            if entfernen.button("Entfernen", key=f"entfernen_{schritt.transformationsschritt_id}"):
                plan = service.schritt_entfernen(plan, schritt.transformationsschritt_id)
                service.plan_speichern(plan)
                st.session_state.etl_transformationsplan = plan
                st.rerun()

    ergebnis = service.vorschau(plan)
    st.write("**Transformierte Vorschau**")
    st.dataframe(ergebnis.vorschau, width="stretch")
    st.dataframe(
        pd.DataFrame([asdict(wert) for wert in ergebnis.historie]),
        hide_index=True,
        width="stretch",
    )
    _vorher_nachher(service, plan, ausgangsprofil, ergebnis)
    st.session_state.etl_transformationsergebnis = ergebnis
    return plan
