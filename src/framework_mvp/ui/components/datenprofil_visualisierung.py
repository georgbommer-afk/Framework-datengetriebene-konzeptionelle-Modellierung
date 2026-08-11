"""Streamlit-Darstellung bereits berechneter Profil- und Diagrammdaten."""

from dataclasses import asdict

import pandas as pd
import streamlit as st

from framework_mvp.application.datenimport_service import Profilierungsergebnis
from framework_mvp.domain.models import Profiltyp, SpaltenDiagrammdaten, Spaltenprofil


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


def _numerische_details(profil: Spaltenprofil, diagramm: SpaltenDiagrammdaten) -> None:
    numerisch = profil.numerisch
    assert numerisch is not None and diagramm.numerisch is not None
    if numerisch.gueltige_werte == 0:
        st.info("Diese Spalte enthält keine endlichen numerischen Werte für eine Detailanalyse.")
        return
    kennzahlen = st.columns(6)
    for spalte, (name, wert) in zip(
        kennzahlen,
        (
            ("Minimum", numerisch.minimum),
            ("Maximum", numerisch.maximum),
            ("Mittelwert", numerisch.mittelwert),
            ("Median", numerisch.median),
            ("Q1", numerisch.q1),
            ("Q3", numerisch.q3),
        ),
        strict=True,
    ):
        spalte.metric(name, _zahl(wert))
    st.write(
        f"Gültige endliche Werte: **{numerisch.gueltige_werte:,}** · "
        f"Unendliche Werte: **{numerisch.unendliche_werte:,}** · "
        f"Potenzielle Ausreißer: **{numerisch.potenzielle_ausreisser:,}**"
    )
    histogramm = diagramm.numerisch.histogramm
    histogrammdaten = [asdict(wert) for wert in histogramm.klassen]
    st.subheader("Histogramm")
    st.caption("Das Diagramm verwendet aggregierte Histogrammklassen.")
    st.vega_lite_chart(
        {"values": histogrammdaten},
        {
            "layer": [
                {
                    "mark": "bar",
                    "encoding": {
                        "x": {"field": "untergrenze", "type": "quantitative", "title": "Wert"},
                        "x2": {"field": "obergrenze"},
                        "y": {"field": "anzahl", "type": "quantitative", "title": "Häufigkeit"},
                    },
                },
                {
                    "data": {"values": [{"median": histogramm.median}]},
                    "mark": {"type": "rule", "color": "#d62728", "strokeWidth": 3},
                    "encoding": {"x": {"field": "median", "type": "quantitative"}},
                },
            ]
        },
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
    st.metric("Eindeutige reguläre Ausprägungen", kategorial.eindeutige_auspraegungen)
    st.metric("Häufigster Wert (Modus)", kategorial.haeufigster_wert or "–")
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


def zeige_datenprofil(
    ergebnis: Profilierungsergebnis,
    *,
    session_key: str,
    daten: pd.DataFrame | None = None,
) -> None:
    """Zeigt Gesamtübersicht, Fehlwerte und genau eine Spaltendetailanalyse."""
    profil = ergebnis.profil
    if profil.spalten == 0:
        st.warning("Die Tabelle enthält keine Spalten und kann nicht profiliert werden.")
        return
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
        return
    if spaltenprofil.profiltyp is Profiltyp.NUMERISCH:
        _numerische_details(spaltenprofil, diagramm)
    elif spaltenprofil.profiltyp is Profiltyp.KATEGORIAL:
        _kategoriale_details(spaltenprofil, diagramm)
    elif spaltenprofil.profiltyp is Profiltyp.ZEITBEZOGEN:
        _zeit_details(spaltenprofil, diagramm)
    else:
        st.info("Für den erkannten Datentyp ist keine technische Detailanalyse verfügbar.")


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
    st.dataframe(pd.DataFrame(tabellendaten), hide_index=True)
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
