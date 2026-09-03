"""Streamlit-Darstellung bereits berechneter Profil- und Diagrammdaten."""

from dataclasses import asdict, dataclass

import pandas as pd
import streamlit as st

from framework_mvp.application.datenimport_service import Profilierungsergebnis
from framework_mvp.application.profiling import zulaessige_indikatoroperatoren
from framework_mvp.domain.models import (
    Indikatorbedingung,
    Indikatoroperator,
    Profiltyp,
    SpaltenDiagrammdaten,
    Spaltenprofil,
    TechnischerDatentyp,
)


@dataclass(frozen=True, slots=True)
class IndikatorUiAktion:
    """Vom Profiling-Formular ausgelöste, noch nicht bestätigte UI-Aktion."""

    hinzufuegen: Indikatorbedingung | None = None
    entfernen: Indikatorbedingung | None = None


def _zahl(wert: float | None) -> str:
    return "–" if wert is None else f"{wert:,.4g}"


def _spaltendiagramm(ergebnis: Profilierungsergebnis, spaltenname: str) -> SpaltenDiagrammdaten:
    return next(wert for wert in ergebnis.diagramme.spalten if wert.spaltenname == spaltenname)


def _gesamtuebersicht(ergebnis: Profilierungsergebnis) -> None:
    profil = ergebnis.profil
    ausreisser = sum(
        wert.numerisch.potenzielle_ausreisser
        for wert in profil.spaltenprofile
        if wert.numerisch is not None
    )
    kennzahlen = st.columns(4)
    werte = (
        ("Zeilen", profil.zeilen),
        ("Spalten", profil.spalten),
        ("Vollständig leere Spalten", profil.vollstaendig_leere_spalten),
        ("Echte Fehlwerte", profil.echte_fehlwerte),
        ("Textuelle Platzhalter", profil.textuelle_platzhalter),
        ("Exakte Duplikate", profil.exakte_duplikate),
        ("Mögliche Ausreißer", ausreisser),
        ("Erkannte Zeitspalten", profil.zeitbezogene_spalten),
    )
    for index, (name, wert) in enumerate(werte):
        spalte = kennzahlen[index % len(kennzahlen)]
        spalte.metric(name, str(wert))
    st.caption(
        f"Die Kennzahlen basieren auf {profil.zeilen:,} Zeilen. "
        f"Speicherbedarf des DataFrames: {profil.speicherbedarf_bytes:,} Bytes."
    )


def _verstaendlicher_datentyp(profil: Spaltenprofil) -> str:
    """Gibt den fachlichen technischen Datentyp aus Tabelle 3.8 aus."""
    return profil.technischer_datentyp.value


def _spaltenuebersicht(ergebnis: Profilierungsergebnis, daten: pd.DataFrame | None) -> None:
    """Zeigt jede Spalte einmal mit verständlichem Typ und interpretierten Befunden."""
    profil = ergebnis.profil
    st.subheader("Spaltenübersicht")
    zeilen = []
    for wert in profil.spaltenprofile:
        befunde: list[str] = []
        if wert.fehlwerte.echte_fehlwerte:
            befunde.append(f"{wert.fehlwerte.echte_fehlwerte} leere Werte")
        if wert.fehlwerte.platzhalter:
            befunde.append(f"{wert.fehlwerte.platzhalter} mögliche Platzhalter")
        if wert.numerisch is not None and wert.numerisch.potenzielle_ausreisser:
            befunde.append(f"{wert.numerisch.potenzielle_ausreisser} mögliche Ausreißer")
        if wert.zeitbezogen is not None and wert.zeitbezogen.nicht_interpretierbare_werte:
            befunde.append(
                f"{wert.zeitbezogen.nicht_interpretierbare_werte} nicht lesbare Zeitwerte"
            )
        beispiele = "–"
        if daten is not None and wert.spaltenname in daten.columns:
            regulaer = daten[wert.spaltenname].dropna().astype("string").drop_duplicates()
            beispiele = ", ".join(regulaer.head(3)) or "–"
        zeilen.append(
            {
                "Spaltenname": wert.spaltenname,
                "Datentyp": _verstaendlicher_datentyp(wert),
                "Ausgefüllte Werte": wert.fehlwerte.gueltige_regulaere_werte,
                "Leere Werte": wert.fehlwerte.echte_fehlwerte,
                "Anteil leerer Werte": f"{wert.fehlwerte.anteil_echter_fehlwerte:.1%}",
                "Unterschiedliche Werte": wert.eindeutige_werte,
                "Beispielwerte": beispiele,
                "Erkannte Auffälligkeiten": " · ".join(befunde) or "Keine",
            }
        )
    st.dataframe(
        pd.DataFrame(zeilen),
        hide_index=True,
        width="stretch",
    )
    auffaellig = [zeile for zeile in zeilen if zeile["Erkannte Auffälligkeiten"] != "Keine"]
    if auffaellig:
        st.write("**Auffällige Spalten**")
        for zeile in auffaellig:
            st.info(f"**{zeile['Spaltenname']}:** {zeile['Erkannte Auffälligkeiten']}")


def _fehlwertdiagramm(ergebnis: Profilierungsergebnis) -> None:
    st.subheader("Leere und auffällige Werte")
    st.caption(
        "Leere Zellen sind echte fehlende Werte. Einträge wie NULL, N/A oder - "
        "können textuelle Platzhalter für fehlende Angaben sein."
    )
    daten = [asdict(wert) for wert in ergebnis.diagramme.fehlwerte if wert.anzahl > 0]
    if not daten:
        st.info("Keine entsprechenden Werte vorhanden.")
        return
    st.vega_lite_chart(
        {"values": daten},
        {
            "mark": "bar",
            "encoding": {
                "y": {
                    "field": "spaltenname",
                    "type": "nominal",
                    "sort": None,
                    "title": None,
                },
                "x": {
                    "field": "anteil",
                    "type": "quantitative",
                    "stack": "zero",
                    "axis": {"format": ".1%"},
                    "title": None,
                },
                "color": {"field": "art", "type": "nominal", "title": "Art"},
                "tooltip": [
                    {"field": "spaltenname", "title": "Spalte"},
                    {"field": "art", "title": "Art"},
                    {"field": "anzahl", "title": "Anzahl"},
                    {"field": "anteil", "title": "Anteil", "format": ".2%"},
                ],
            },
        },
        width="stretch",
    )


def histogramm_spezifikation(
    profil: Spaltenprofil, diagramm: SpaltenDiagrammdaten
) -> dict[str, object]:
    """Bindet alle Layer an den vollständigen numerischen Wertebereich."""
    assert profil.numerisch is not None and diagramm.numerisch is not None
    numerisch = profil.numerisch
    histogramm = diagramm.numerisch.histogramm
    domain = [numerisch.minimum, numerisch.maximum]
    return {
        "layer": [
            {
                "mark": "bar",
                "encoding": {
                    "x": {
                        "field": "untergrenze",
                        "type": "quantitative",
                        "title": "Wert",
                        "scale": {"domain": domain},
                    },
                    "x2": {"field": "obergrenze"},
                    "y": {"field": "anzahl", "type": "quantitative", "title": "Häufigkeit"},
                },
            },
            {
                "data": {"values": [{"median": histogramm.median}]},
                "mark": {"type": "rule", "color": "#d62728", "strokeWidth": 3},
                "encoding": {
                    "x": {
                        "field": "median",
                        "type": "quantitative",
                        "scale": {"domain": domain},
                    }
                },
            },
        ]
    }


def _numerische_details(profil: Spaltenprofil, diagramm: SpaltenDiagrammdaten) -> None:
    numerisch = profil.numerisch
    assert numerisch is not None and diagramm.numerisch is not None
    if numerisch.gueltige_werte == 0:
        st.info("Diese Spalte enthält keine endlichen numerischen Werte für eine Detailanalyse.")
        return
    kennzahlen = st.columns(4)
    for index, (name, wert) in enumerate(
        (
            ("Minimum", numerisch.minimum),
            ("Q1", numerisch.q1),
            ("Median", numerisch.median),
            ("Q3", numerisch.q3),
            ("Maximum", numerisch.maximum),
            ("IQR", numerisch.interquartilsabstand),
            ("Mittelwert", numerisch.mittelwert),
        )
    ):
        kennzahlen[index % len(kennzahlen)].metric(name, _zahl(wert))
    st.write(
        f"Gültige endliche Werte: **{numerisch.gueltige_werte:,}** · "
        f"Unendliche Werte: **{numerisch.unendliche_werte:,}** · "
        f"Potenzielle Ausreißer: **{numerisch.potenzielle_ausreisser:,}**"
    )
    st.caption(
        "IQR-Regel: ["
        f"{_zahl(numerisch.untere_ausreissergrenze)}, "
        f"{_zahl(numerisch.obere_ausreissergrenze)}]"
    )
    histogramm = diagramm.numerisch.histogramm
    histogrammdaten = [asdict(wert) for wert in histogramm.klassen]
    st.subheader("Histogramm")
    st.caption("Das Diagramm verwendet aggregierte Histogrammklassen.")
    st.vega_lite_chart(
        {"values": histogrammdaten},
        histogramm_spezifikation(profil, diagramm),
        width="stretch",
    )
    box = diagramm.numerisch.boxplot
    st.subheader("Kompakter Boxplot")
    st.vega_lite_chart(
        {"values": [asdict(box)]},
        {
            "layer": [
                {
                    "mark": {"type": "rule", "strokeWidth": 2},
                    "encoding": {
                        "x": {"field": "unterer_whisker", "type": "quantitative"},
                        "x2": {"field": "oberer_whisker"},
                    },
                },
                {
                    "mark": {"type": "bar", "size": 35},
                    "encoding": {
                        "x": {"field": "q1", "type": "quantitative"},
                        "x2": {"field": "q3"},
                    },
                },
                {
                    "mark": {"type": "tick", "color": "white", "thickness": 3, "size": 35},
                    "encoding": {"x": {"field": "median", "type": "quantitative"}},
                },
            ]
        },
        width="stretch",
    )


def _kategoriale_details(profil: Spaltenprofil, diagramm: SpaltenDiagrammdaten) -> None:
    kategorial = profil.kategorial
    assert kategorial is not None
    st.subheader("Häufigkeitsverteilung")
    kennzahlen = st.columns(3)
    kennzahlen[0].metric("Gültige reguläre Werte", kategorial.gueltige_werte)
    kennzahlen[1].metric(
        "Eindeutige reguläre Ausprägungen", kategorial.eindeutige_auspraegungen
    )
    kennzahlen[2].metric("Häufigster Wert (Modus)", kategorial.haeufigster_wert or "–")
    st.write(
        f"Gültige reguläre Werte: **{kategorial.gueltige_werte:,}** · "
        f"Seltene Werte unter 1 %: **{kategorial.seltene_werte:,}**"
    )
    if profil.fehlwerte.platzhalter:
        st.warning(f"Textuelle Fehlwertplatzhalter: {profil.fehlwerte.platzhalter:,}")
    if not diagramm.kategorien:
        st.info("Diese Spalte enthält keine regulären kategorialen Werte.")
        return
    daten = [asdict(wert) for wert in diagramm.kategorien]
    st.dataframe(
        pd.DataFrame(
            {
                "Ausprägung": [wert["bezeichnung"] for wert in daten],
                "Absolute Häufigkeit": [wert["anzahl"] for wert in daten],
                "Relative Häufigkeit": [wert["anteil"] for wert in daten],
            }
        ),
        hide_index=True,
        width="stretch",
        column_config={"Relative Häufigkeit": st.column_config.NumberColumn(format="percent")},
    )
    st.vega_lite_chart(
        {"values": daten},
        {
            "mark": "bar",
            "encoding": {
                "y": {"field": "bezeichnung", "type": "nominal", "sort": "-x", "title": None},
                "x": {"field": "anzahl", "type": "quantitative", "title": None},
                "tooltip": ["bezeichnung", "anzahl", {"field": "anteil", "format": ".2%"}],
            },
        },
        width="stretch",
    )


def _zeit_details(profil: Spaltenprofil, diagramm: SpaltenDiagrammdaten) -> None:
    zeit = profil.zeitbezogen
    assert zeit is not None
    links, rechts = st.columns(2)
    links.metric("Frühester Zeitpunkt", str(zeit.fruehester_zeitpunkt or "–"))
    rechts.metric("Spätester Zeitpunkt", str(zeit.spaetester_zeitpunkt or "–"))
    st.write(
        f"Interpretierbare Werte: **{zeit.interpretierbare_werte:,}** · "
        f"Nicht interpretierbare Werte: **{zeit.nicht_interpretierbare_werte:,}** · "
        f"Erfolgsquote: **{zeit.erfolgsquote:.1%}**"
    )
    if zeit.interpretierbare_werte and zeit.fruehester_zeitpunkt is None:
        st.warning(
            "Die Zeitinterpretation enthält eine uneindeutige Mischung aus "
            "zeitzonenlosen und zeitzonenbewussten Werten."
        )
        return
    if zeit.granularitaet is None or not diagramm.zeitintervalle:
        st.info("Es sind keine interpretierbaren Zeitwerte für eine Verteilung vorhanden.")
        return
    st.caption(f"Die Zeitwerte wurden nach {zeit.granularitaet.value.lower()} aggregiert.")
    daten = [asdict(wert) for wert in diagramm.zeitintervalle]
    st.vega_lite_chart(
        {"values": daten},
        {
            "mark": "line",
            "encoding": {
                "x": {"field": "intervallbeginn", "type": "temporal", "title": "Intervall"},
                "y": {"field": "anzahl", "type": "quantitative", "title": "Datensätze"},
                "tooltip": ["intervallbeginn", "anzahl"],
            },
        },
        width="stretch",
    )


def _operatorbezeichnung(operator: Indikatoroperator) -> str:
    return {
        Indikatoroperator.GLEICH: "gleich (=)",
        Indikatoroperator.UNGLEICH: "ungleich (≠)",
        Indikatoroperator.KLEINER: "kleiner als (<)",
        Indikatoroperator.KLEINER_GLEICH: "kleiner oder gleich (<=)",
        Indikatoroperator.GROESSER: "größer als (>)",
        Indikatoroperator.GROESSER_GLEICH: "größer oder gleich (>=)",
    }[operator]


def _indikatorbereich(
    profil: Spaltenprofil,
    *,
    session_key: str,
    bearbeitbar: bool,
) -> IndikatorUiAktion | None:
    st.subheader("Absolute Häufigkeit eines Indikators")
    st.caption(
        "Zählt die Beobachtungen dieser Spalte, welche die definierte Bedingung erfüllen. "
        "Fehlwerte und bestätigte Fehlwertplatzhalter werden nicht ausgewertet."
    )
    for index, auswertung in enumerate(profil.indikatorauswertungen):
        with st.container(border=True):
            inhalt, aktion = st.columns((5, 1))
            inhalt.write(
                f"**Bedingung:** {auswertung.spaltenname} "
                f"{_operatorbezeichnung(auswertung.operator)} "
                f"{auswertung.vergleichswert}"
            )
            inhalt.write(f"**Ergebnis:** {auswertung.absolute_haeufigkeit:,} Beobachtungen")
            inhalt.caption(
                f"Auswertbare reguläre Beobachtungen: {auswertung.auswertbare_beobachtungen:,}"
            )
            if bearbeitbar and aktion.button(
                "Entfernen",
                key=f"{session_key}_indikator_entfernen_{index}",
                width="stretch",
            ):
                return IndikatorUiAktion(
                    entfernen=Indikatorbedingung(
                        spaltenname=auswertung.spaltenname,
                        operator=auswertung.operator,
                        vergleichswert=auswertung.vergleichswert,
                    )
                )
    if not bearbeitbar:
        st.caption(
            "Das bestätigte Datenprofil ist unveränderlich. Zusätzliche Bedingungen "
            "werden als neue Profilversion gespeichert."
        )
        return None
    with st.form(f"{session_key}_indikator_neu", clear_on_submit=True, border=True):
        st.markdown("**Neue Bedingung**")
        operator = st.selectbox(
            "Operator",
            zulaessige_indikatoroperatoren(profil.technischer_datentyp),
            format_func=_operatorbezeichnung,
        )
        if profil.technischer_datentyp is TechnischerDatentyp.BOOLEAN:
            vergleichswert = st.selectbox(
                "Vergleichswert",
                ("true", "false"),
                format_func=lambda wert: "Wahr" if wert == "true" else "Falsch",
            )
        else:
            vergleichswert = st.text_input(
                "Vergleichswert",
                help=(
                    "Der Wert wird gemäß dem erkannten technischen Datentyp interpretiert. "
                    "Textvergleiche unterscheiden Groß- und Kleinschreibung."
                ),
            )
        hinzufuegen = st.form_submit_button("Bedingung hinzufügen", type="primary")
    if hinzufuegen:
        return IndikatorUiAktion(
            hinzufuegen=Indikatorbedingung(
                spaltenname=profil.spaltenname,
                operator=operator,
                vergleichswert=vergleichswert,
            )
        )
    return None


def zeige_indikatorbedingungen(
    ergebnis: Profilierungsergebnis,
    *,
    session_key: str,
    bearbeitbar: bool,
) -> IndikatorUiAktion | None:
    """Bündelt vorhandene und neue Indikatorbedingungen spaltenübergreifend."""
    profile = ergebnis.profil.spaltenprofile
    auswertungen = [wert for profil in profile for wert in profil.indikatorauswertungen]
    if auswertungen:
        for index, auswertung in enumerate(auswertungen):
            with st.container(border=True):
                inhalt, aktion = st.columns((5, 1))
                inhalt.markdown(
                    f"**{auswertung.spaltenname}** "
                    f"{_operatorbezeichnung(auswertung.operator)} "
                    f"**{auswertung.vergleichswert}**"
                )
                inhalt.markdown(
                    f"Ergebnis: **{auswertung.absolute_haeufigkeit:,} Beobachtungen**"
                )
                inhalt.markdown(f"$n_B = {auswertung.absolute_haeufigkeit:,}$")
                inhalt.caption(
                    "Auswertbare reguläre Beobachtungen: "
                    f"{auswertung.auswertbare_beobachtungen:,}"
                )
                if bearbeitbar and aktion.button(
                    "Entfernen",
                    key=f"{session_key}_indikator_entfernen_{index}",
                    width="stretch",
                ):
                    return IndikatorUiAktion(
                        entfernen=Indikatorbedingung(
                            auswertung.spaltenname,
                            auswertung.operator,
                            auswertung.vergleichswert,
                        )
                    )
    else:
        st.info("Noch keine Indikatorbedingung definiert.")
    if not bearbeitbar:
        st.caption(
            "Das bestätigte Datenprofil ist unveränderlich. Änderungen werden als neue "
            "Profilgeneration gespeichert."
        )
        return None
    namen = [wert.spaltenname for wert in profile]
    with st.form(f"{session_key}_indikator_neu", clear_on_submit=True, border=True):
        st.markdown("**Neue Bedingung**")
        spaltenname = st.selectbox("Spalte", namen)
        profil = next(wert for wert in profile if wert.spaltenname == spaltenname)
        operator = st.selectbox(
            "Operator",
            zulaessige_indikatoroperatoren(profil.technischer_datentyp),
            format_func=_operatorbezeichnung,
        )
        if profil.technischer_datentyp is TechnischerDatentyp.BOOLEAN:
            vergleichswert = st.selectbox(
                "Vergleichswert",
                ("true", "false"),
                format_func=lambda wert: "Wahr" if wert == "true" else "Falsch",
            )
        else:
            vergleichswert = st.text_input("Vergleichswert")
        hinzufuegen = st.form_submit_button("Bedingung hinzufügen", type="primary")
    if hinzufuegen:
        return IndikatorUiAktion(
            hinzufuegen=Indikatorbedingung(spaltenname, operator, vergleichswert)
        )
    return None


def zeige_datenprofil(
    ergebnis: Profilierungsergebnis,
    *,
    session_key: str,
    daten: pd.DataFrame | None = None,
    indikator_bearbeitbar: bool = False,
) -> IndikatorUiAktion | None:
    """Zeigt Gesamtübersicht, Fehlwerte und genau eine Spaltendetailanalyse."""
    profil = ergebnis.profil
    if profil.spalten == 0:
        st.warning("Die Tabelle enthält keine Spalten und kann nicht profiliert werden.")
        return None
    if profil.zeilen == 0:
        st.warning("Die Tabelle enthält keine Datenzeilen; dargestellt wird nur ihre Struktur.")
    _gesamtuebersicht(ergebnis)
    _spaltenuebersicht(ergebnis, daten)
    _fehlwertdiagramm(ergebnis)
    st.subheader("Detailanalyse")
    namen = [wert.spaltenname for wert in profil.spaltenprofile]
    auswahl = st.selectbox("Spalte für Detailanalyse", namen, key=session_key)
    spaltenprofil = next(wert for wert in profil.spaltenprofile if wert.spaltenname == auswahl)
    diagramm = _spaltendiagramm(ergebnis, auswahl)
    if spaltenprofil.fehlwerte.gueltige_regulaere_werte == 0:
        st.info("Diese Spalte ist vollständig leer oder enthält ausschließlich Platzhalter.")
    elif spaltenprofil.profiltyp is Profiltyp.NUMERISCH:
        _numerische_details(spaltenprofil, diagramm)
    elif spaltenprofil.profiltyp is Profiltyp.KATEGORIAL:
        _kategoriale_details(spaltenprofil, diagramm)
    elif spaltenprofil.profiltyp is Profiltyp.ZEITBEZOGEN:
        _zeit_details(spaltenprofil, diagramm)
    else:
        st.info("Für den erkannten Datentyp ist keine technische Detailanalyse verfügbar.")
    return None


def zeige_gespeichertes_datenprofil(struktur: dict[str, object]) -> None:
    """Visualisiert ein validiertes Profil-JSON ohne erneute Profilberechnung."""
    kennzahlen = st.columns(6)
    werte = (
        ("Zeilen", struktur["zeilen"]),
        ("Spalten", struktur["spalten"]),
        ("Echte Fehlwerte", struktur["echte_fehlwerte"]),
        ("Textuelle Platzhalter", struktur["textuelle_platzhalter"]),
        ("Exakte Duplikate", struktur["exakte_duplikate"]),
        ("Vollständig leere Spalten", struktur["vollstaendig_leere_spalten"]),
    )
    for spalte, (name, wert) in zip(kennzahlen, werte, strict=True):
        spalte.metric(name, str(wert))
    spaltenprofile = struktur["spaltenprofile"]
    if not isinstance(spaltenprofile, list):
        st.warning("Das gespeicherte Profil enthält keine darstellbaren Spaltenprofile.")
        return
    tabellendaten = []
    diagrammdaten = []
    indikatorzeilen = []
    for spaltenprofil in spaltenprofile:
        if not isinstance(spaltenprofil, dict):
            continue
        fehlwerte = spaltenprofil.get("fehlwerte", {})
        if not isinstance(fehlwerte, dict):
            continue
        name = str(spaltenprofil.get("spaltenname", ""))
        tabellendaten.append(
            {
                "Spaltenname": name,
                "Originaldatentyp": spaltenprofil.get("originaldatentyp"),
                "Technischer Datentyp": spaltenprofil.get("technischer_datentyp"),
                "Profiltyp": spaltenprofil.get("profiltyp"),
                "Gültige Werte": fehlwerte.get("gueltige_regulaere_werte", 0),
                "Echte Fehlwerte": fehlwerte.get("echte_fehlwerte", 0),
                "Textuelle Platzhalter": fehlwerte.get("platzhalter", 0),
                "Eindeutige Werte": spaltenprofil.get("eindeutige_werte", 0),
            }
        )
        diagrammdaten.extend(
            (
                {
                    "spaltenname": name,
                    "art": "Echte Fehlwerte",
                    "anteil": fehlwerte.get("anteil_echter_fehlwerte", 0),
                },
                {
                    "spaltenname": name,
                    "art": "Textuelle Platzhalter",
                    "anteil": fehlwerte.get("anteil_platzhalter", 0),
                },
            )
        )
        for auswertung in spaltenprofil.get("indikatorauswertungen", []):
            if not isinstance(auswertung, dict):
                continue
            indikatorzeilen.append(
                {
                    "Spalte": auswertung.get("spaltenname"),
                    "Operator": auswertung.get("operator"),
                    "Vergleichswert": auswertung.get("vergleichswert"),
                    "Absolute Häufigkeit (n_B)": auswertung.get("absolute_haeufigkeit"),
                    "Auswertbare reguläre Beobachtungen": auswertung.get(
                        "auswertbare_beobachtungen"
                    ),
                }
            )
    st.dataframe(pd.DataFrame(tabellendaten), hide_index=True)
    if indikatorzeilen:
        st.subheader("Absolute Häufigkeit eines Indikators")
        st.dataframe(pd.DataFrame(indikatorzeilen), hide_index=True)
    st.vega_lite_chart(
        {"values": diagrammdaten},
        {
            "mark": "bar",
            "encoding": {
                "y": {"field": "spaltenname", "type": "nominal", "title": "Spalte"},
                "x": {
                    "field": "anteil",
                    "type": "quantitative",
                    "stack": "zero",
                    "axis": {"format": ".1%"},
                    "title": "Anteil",
                },
                "color": {"field": "art", "type": "nominal", "title": "Art"},
            },
        },
        width="stretch",
    )
