# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
# pyright: reportCallIssue=false, reportGeneralTypeIssues=false
"""Streamlit-Seite für Schritt 7: Ergebnisse aggregieren."""

import hashlib
from dataclasses import asdict
from datetime import date
from uuid import UUID, uuid5

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from framework_mvp.application.ergebnisaggregation import kpi_definition
from framework_mvp.application.ergebnisaggregation.sollprozess import (
    aktivitaetsreferenz_csv,
    erstelle_aktivitaetsmapping,
    erzeuge_lineares_sollmodell,
    validiere_pnml_sollmodell,
)
from framework_mvp.application.ergebnisaggregation.zeitvergleich import (
    lese_externe_sollzeitdaten,
)
from framework_mvp.application.ergebnisaggregation_service import (
    Aggregationsvorschau,
    ErgebnisaggregationService,
)
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    Datenartefakt,
    KpiKonfiguration,
    KpiStatus,
    Operandentyp,
    OperandZuordnung,
    SollmodellEntscheidung,
    Vergleichsebene,
    Vorkommensregel,
    ZeitvergleichKonfiguration,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler

WOPED_NEXT_URL = "https://taminofischer.github.io/woped-next/"
PETRI_GRUNDLAGEN_URL = "https://doi.org/10.1007/978-94-009-0649-5_6"
WOPED_DESKTOP_URL = "https://woped.dhbw-karlsruhe.de/"
PNML_TOOLS_URL = "https://www.pnml.org/tools.php"
_PLATZHALTER = "— bitte ausdrücklich wählen —"


def _uuid_aus_session(name: str) -> UUID:
    wert = st.session_state.get(name)
    if not wert:
        raise Domaenenfehler(f"Der zentrale Sessionwert {name} fehlt.")
    try:
        return UUID(str(wert))
    except ValueError as fehler:
        raise Domaenenfehler(f"Der zentrale Sessionwert {name} ist ungültig.") from fehler


def _navigation_zurueck() -> None:
    if st.button("Zurück zu Schritt 6: Process Mining durchführen"):
        st.session_state.naechster_framework_bereich = "6 Process Mining durchführen"
        st.rerun()


def _eingangsartefakte(basis: object) -> None:
    st.subheader("1. Validierte Eingangsartefakte")
    spalten = st.columns(3)
    spalten[0].metric("Ereignisse", len(basis.event_log))
    spalten[1].metric("Fälle", basis.event_log["case_id"].nunique())
    spalten[2].metric("Aktivitäten", basis.event_log["activity"].nunique())
    st.write(f"**Aktives Projekt:** {basis.projekt.bezeichnung} (`{basis.projekt.projekt_id}`)")
    st.write(
        f"**Freigabe:** `{basis.freigabe.freigabe_id}` · "
        f"**Event Log:** `{basis.freigabe.event_log_id}`"
    )
    von = basis.event_log["timestamp"].min()
    bis = basis.event_log["timestamp"].max()
    st.write(f"**Zeitraum:** {von} bis {bis}")
    st.code(basis.freigabe.event_log_sha256, language=None)
    st.write(f"**Process-Mining-Analyse:** `{basis.analyse.analyse_id}`")
    st.write(
        f"**Notation von P:** {basis.discovery_ergebnisse['prozessnotation']} · "
        f"**P-Prüfsumme:** `{basis.prozessmodell_sha256}`"
    )
    st.write(f"**A_D-Prüfsumme:** `{basis.discovery_ergebnisse_sha256}`")


def _auswahl(
    bezeichnung: str,
    werte: list[str],
    *,
    key: str,
) -> str:
    return str(st.selectbox(bezeichnung, [_PLATZHALTER, *werte], key=key))


def _kpi_konfigurationen(basis: object) -> tuple[KpiKonfiguration, ...]:
    st.subheader("2. Ausgewählte Kennzahlen")
    kpi_ids = basis.projekt.untersuchungsauftrag.ausgewaehlte_kpi_ids
    if not kpi_ids:
        st.info("In U wurden keine KPI-Kandidaten ausgewählt. A_G kann dennoch A_D enthalten.")
        return ()
    st.caption(
        "Es werden ausschließlich die in U gespeicherten KPI-IDs angeboten. Spalten, Werte und "
        "Einheiten werden nicht semantisch erraten."
    )
    t_spalten = [str(wert) for wert in basis.zwischendaten.columns]
    e_spalten = [str(wert) for wert in basis.event_log.columns]
    aktivitaeten = sorted(basis.event_log["activity"].astype("string").unique())
    profilwerte = sorted(basis.profilwerte)
    konfigurationen: list[KpiKonfiguration] = []
    for kpi_id in kpi_ids:
        definition = kpi_definition(kpi_id)
        with st.expander(f"{definition.bezeichnung} · {definition.formel}"):
            st.caption(
                f"Bezugsmenge: {definition.bezugsmenge} · Ergebnis: {definition.einheit} · "
                f"Definitionsversion {definition.definitionsversion}"
            )
            direktes_profil = ""
            if kpi_id in {
                "mittlere_dlz_warenausgang",
                "mittlere_dlz_wareneingang",
                "mittlere_transportzeit_je_warensendung",
                "mittlere_reaktionszeit",
                "mittlere_kosten_produktionslogistik_pro_produktionsauftrag",
            } and st.checkbox(
                "Diese KPI entspricht exakt einem in R gespeicherten arithmetischen Mittelwert",
                key=f"ag_{kpi_id}_direkt_r",
            ):
                auswahl = _auswahl(
                    "Exakt passende Mittelwert-Profilkennzahl aus R",
                    [wert for wert in profilwerte if wert.endswith(":mittelwert")],
                    key=f"ag_{kpi_id}_direkt_r_referenz",
                )
                if auswahl != _PLATZHALTER:
                    direktes_profil = auswahl
            zuordnungen = []
            if direktes_profil:
                st.info(
                    "Die weiterführende Berechnung aus T oder E* wird für diese KPI übersprungen."
                )
            for operand in definition.operanden:
                if direktes_profil:
                    break
                st.write(f"**{operand.bezeichnung}** ({operand.operandentyp.value})")
                quellen = [wert.value for wert in operand.zulaessige_quellen]
                quelle_roh = st.selectbox(
                    "Zulässige Datenquelle",
                    quellen,
                    key=f"ag_{kpi_id}_{operand.operand_id}_quelle",
                )
                quelle = Datenartefakt(quelle_roh)
                if quelle is Datenartefakt.DATENPROFIL_R:
                    profil = _auswahl(
                        "Exakte Profilkennzahl aus R",
                        profilwerte,
                        key=f"ag_{kpi_id}_{operand.operand_id}_profil",
                    )
                    if profil != _PLATZHALTER:
                        zuordnungen.append(
                            OperandZuordnung(operand.operand_id, quelle, profilreferenz=profil)
                        )
                    continue
                spalten = t_spalten if quelle is Datenartefakt.ZWISCHENDATENSATZ_T else e_spalten
                if operand.operandentyp is Operandentyp.ZEITDIFFERENZ_SUMME:
                    modus = st.radio(
                        "Zeitbezug",
                        ["zwei Zeitstempelspalten", "Start- und Endaktivität in E*"],
                        horizontal=True,
                        key=f"ag_{kpi_id}_{operand.operand_id}_zeitmodus",
                    )
                    if modus == "Start- und Endaktivität in E*":
                        start = _auswahl(
                            "Startaktivität",
                            aktivitaeten,
                            key=f"ag_{kpi_id}_{operand.operand_id}_start",
                        )
                        ende = _auswahl(
                            "Endaktivität",
                            aktivitaeten,
                            key=f"ag_{kpi_id}_{operand.operand_id}_ende",
                        )
                        regel = Vorkommensregel(
                            st.selectbox(
                                "Vorkommensregel der Endaktivität",
                                [Vorkommensregel.ERSTES.value, Vorkommensregel.LETZTES.value],
                                key=f"ag_{kpi_id}_{operand.operand_id}_regel",
                            )
                        )
                        if start != _PLATZHALTER and ende != _PLATZHALTER:
                            zuordnungen.append(
                                OperandZuordnung(
                                    operand.operand_id,
                                    Datenartefakt.EVENT_LOG_E_STERN,
                                    startaktivitaet=start,
                                    endaktivitaet=ende,
                                    vorkommensregel=regel,
                                )
                            )
                    else:
                        start = _auswahl(
                            "Auslösender Zeitstempel",
                            spalten,
                            key=f"ag_{kpi_id}_{operand.operand_id}_spalte1",
                        )
                        ende = _auswahl(
                            "Zeitstempel der ersten Reaktion",
                            spalten,
                            key=f"ag_{kpi_id}_{operand.operand_id}_spalte2",
                        )
                        if start != _PLATZHALTER and ende != _PLATZHALTER:
                            zuordnungen.append(
                                OperandZuordnung(
                                    operand.operand_id,
                                    quelle,
                                    spalte=start,
                                    zweite_spalte=ende,
                                )
                            )
                    continue
                spalte = _auswahl(
                    "Spalte",
                    spalten,
                    key=f"ag_{kpi_id}_{operand.operand_id}_spalte",
                )
                operator = ""
                bedingungswert = ""
                if operand.operandentyp is Operandentyp.ANZAHL and st.checkbox(
                    "Nur Werte zählen, die eine explizite Bedingung erfüllen",
                    key=f"ag_{kpi_id}_{operand.operand_id}_bedingt",
                ):
                    operator = str(
                        st.selectbox(
                            "Wertevergleich",
                            ["gleich", "ungleich"],
                            key=f"ag_{kpi_id}_{operand.operand_id}_operator",
                        )
                    )
                    bedingungswert = st.text_input(
                        "Exakter Attributwert",
                        key=f"ag_{kpi_id}_{operand.operand_id}_wert",
                    )
                if spalte != _PLATZHALTER:
                    zuordnungen.append(
                        OperandZuordnung(
                            operand.operand_id,
                            quelle,
                            spalte=spalte,
                            bedingungsoperator=operator,
                            bedingungswert=bedingungswert,
                        )
                    )
            einheit = (
                st.text_input("Fachlich bestätigte Einheit", key=f"ag_{kpi_id}_einheit")
                if definition.einheiteneingabe_erforderlich
                else definition.einheit
            )
            bezugsmenge = st.text_input(
                "Bestätigte Bezugsmenge",
                value=definition.bezugsmenge,
                key=f"ag_{kpi_id}_bezugsmenge",
            )
            konfigurationen.append(
                KpiKonfiguration(
                    kpi_id,
                    tuple(zuordnungen),
                    einheit,
                    bezugsmenge,
                    direktes_profil,
                )
            )
    return tuple(konfigurationen)


def _sollmodell_metadaten(praefix: str) -> dict[str, object]:
    return {
        "bezeichnung": st.text_input("Bezeichnung des Sollmodells", key=f"{praefix}_name"),
        "fachliche_grundlage": st.text_area(
            "Fachliche Grundlage beziehungsweise Quelle", key=f"{praefix}_grundlage"
        ),
        "modellversion": st.text_input("Version", value="1.0", key=f"{praefix}_version"),
        "person": st.text_input("Erstellende oder prüfende Person", key=f"{praefix}_person"),
        "freigabedatum": st.date_input(
            "Freigabedatum", value=date.today(), key=f"{praefix}_freigabe"
        ),
    }


def _woped_hilfe() -> None:
    with st.expander("Sollmodell mit WoPeD Next erstellen"):
        st.warning(
            "Der fachliche Sollprozess wird nicht automatisch aus E* abgeleitet. Die "
            "Aktivitätsliste dient ausschließlich der konsistenten Benennung sichtbarer "
            "Transitionen."
        )
        schritte = [
            "Lade die bereitgestellte CSV-Datei mit den Aktivitätsbezeichnungen und "
            "Häufigkeiten herunter.",
            "Lege den fachlich erwarteten Sollprozess anhand von Prozessdokumentationen, "
            "Arbeitsanweisungen oder validiertem Domänenwissen fest.",
            "Erstelle in WoPeD Next ein neues Workflow-Petrinetz.",
            "Verwende Stellen für Zustände beziehungsweise Bedingungen, Transitionen für "
            "Aktivitäten und gerichtete Kanten für die Flussbeziehungen.",
            "Beginne mit genau einer Startstelle und beende das Netz mit genau einer Endstelle.",
            "Stelle sicher, dass alle Knoten Bestandteil eines Pfades zwischen Start- und "
            "Endstelle sind.",
            "Benenne sichtbare Transitionen möglichst exakt entsprechend den "
            "Aktivitätsbezeichnungen aus E*.",
            "Modelliere Sequenzen durch eine abwechselnde Verbindung von Stellen und Transitionen.",
            "Modelliere exklusive Alternativen durch mehrere aus einer Stelle ausgehende "
            "Transitionen.",
            "Modelliere Zusammenführungen alternativer Pfade durch mehrere Transitionen, "
            "die in dieselbe Stelle führen.",
            "Modelliere Parallelisierungen durch eine Transition mit mehreren "
            "nachfolgenden Stellen.",
            "Modelliere Synchronisationen durch eine Transition mit mehreren eingehenden Stellen.",
            "Verwende Schleifen nur als geschlossene Rückpfade, welche die ordnungsgemäße "
            "Beendigung weiterhin ermöglichen.",
            "Prüfe typische Abläufe mit dem Token-Game.",
            "Führe die Struktur- und Soundness-Analyse aus und behebe insbesondere "
            "Deadlocks, nicht erreichbare Transitionen und eine nicht ordnungsgemäße Beendigung.",
            "Exportiere das geprüfte Modell als PNML.",
            "Lade die PNML-Datei über das unmittelbar unterhalb des Modellierers angezeigte "
            "Uploadfeld in Schritt 7 hoch.",
        ]
        for nummer, schritt in enumerate(schritte, 1):
            st.markdown(f"{nummer}. {schritt}")
        st.link_button(
            "Petri-Netz-Grundlagen und Modellierungsmuster (fachliche Vertiefung)",
            PETRI_GRUNDLAGEN_URL,
        )
        st.markdown(
            f"[Desktop-Alternative und weiterführende Informationen]({WOPED_DESKTOP_URL}) · "
            f"[Alternative PNML-Werkzeuge]({PNML_TOOLS_URL})"
        )
        st.link_button("WoPeD Next in neuem Tab öffnen", WOPED_NEXT_URL)
        components.iframe(WOPED_NEXT_URL, height=900, scrolling=True)


def _sollmodell_und_mapping(basis: object) -> tuple[object | None, object | None, bool]:
    st.subheader("3. Optionales Soll-Prozessmodell und Conformance Checking")
    st.download_button(
        "Aktivitätsreferenz aus E* als CSV herunterladen",
        aktivitaetsreferenz_csv(basis.event_log.copy(deep=True)),
        file_name="aktivitaetsreferenz_e_stern.csv",
        mime="text/csv",
    )
    entscheidung = SollmodellEntscheidung(
        st.radio(
            "Sollmodellpfad",
            [wert.value for wert in SollmodellEntscheidung],
            format_func=lambda wert: {
                SollmodellEntscheidung.KEIN_SOLLMODELL.value: "Kein Sollmodell verwenden",
                SollmodellEntscheidung.LINEARER_ASSISTENT.value: (
                    "Einfachen linearen Sollprozess erstellen"
                ),
                SollmodellEntscheidung.KOMPLEXES_PNML.value: (
                    "Komplexes Sollmodell als PNML verwenden"
                ),
            }[wert],
            key="ag_sollmodell_entscheidung",
        )
    )
    if entscheidung is SollmodellEntscheidung.KEIN_SOLLMODELL:
        st.info(
            "Conformance Checking wird übersprungen; KPI-Berechnung und A_V bleiben unabhängig."
        )
        return None, None, False
    aktivitaeten = sorted(basis.event_log["activity"].astype("string").unique())
    if entscheidung is SollmodellEntscheidung.LINEARER_ASSISTENT:
        st.warning(
            "Der lineare Assistent bildet ausschließlich eine Sequenz ab. Verzweigungen, "
            "Parallelität, Synchronisation und Schleifen erfordern ein extern modelliertes "
            "PNML-Netz."
        )
        reihenfolge = list(st.session_state.get("ag_lineare_reihenfolge", []))
        verfuegbar = [wert for wert in aktivitaeten if wert not in reihenfolge]
        neue_aktivitaet = st.selectbox(
            "Aktivität aus E* hinzufügen", [_PLATZHALTER, *verfuegbar], key="ag_linear_neu"
        )
        if st.button("Zur Sollreihenfolge hinzufügen", disabled=neue_aktivitaet == _PLATZHALTER):
            reihenfolge.append(neue_aktivitaet)
            st.session_state.ag_lineare_reihenfolge = reihenfolge
            st.rerun()
        for index, aktivitaet in enumerate(reihenfolge):
            cols = st.columns([6, 1, 1, 1])
            cols[0].write(f"{index + 1}. {aktivitaet}")
            if cols[1].button("↑", key=f"ag_linear_hoch_{index}", disabled=index == 0):
                reihenfolge[index - 1], reihenfolge[index] = (
                    reihenfolge[index],
                    reihenfolge[index - 1],
                )
                st.session_state.ag_lineare_reihenfolge = reihenfolge
                st.rerun()
            if cols[2].button(
                "↓", key=f"ag_linear_runter_{index}", disabled=index == len(reihenfolge) - 1
            ):
                reihenfolge[index + 1], reihenfolge[index] = (
                    reihenfolge[index],
                    reihenfolge[index + 1],
                )
                st.session_state.ag_lineare_reihenfolge = reihenfolge
                st.rerun()
            if cols[3].button("×", key=f"ag_linear_loeschen_{index}"):
                reihenfolge.pop(index)
                st.session_state.ag_lineare_reihenfolge = reihenfolge
                st.rerun()
        meta = _sollmodell_metadaten("ag_linear")
        bestaetigt = st.checkbox(
            "Ich bestätige diese Reihenfolge als menschlich festgelegten fachlichen Sollablauf.",
            key="ag_linear_bestaetigt",
        )
        if st.button("Lineares P_Soll erzeugen", type="primary"):
            try:
                st.session_state.ag_sollmodell = erzeuge_lineares_sollmodell(
                    projekt_id=basis.projekt.projekt_id,
                    aktivitaeten=reihenfolge,
                    menschlich_bestaetigt=bestaetigt,
                    **meta,
                )
                st.session_state.pop("ag_aktivitaetsmapping", None)
            except (Domaenenfehler, TypeError) as fehler:
                st.error(str(fehler))
    else:
        status = st.radio(
            "Status des komplexen Sollmodells",
            [
                "Fertiges PNML-Sollmodell liegt bereits vor",
                "Sollmodell muss zunächst erstellt werden",
            ],
            key="ag_pnml_status",
        )
        if status == "Sollmodell muss zunächst erstellt werden":
            _woped_hilfe()
        upload = st.file_uploader(
            "Geprüfte PNML-Datei hochladen",
            type=["pnml"],
            key="ag_pnml_upload",
        )
        meta = _sollmodell_metadaten("ag_pnml")
        markierung = st.checkbox(
            "Falls Markierungen fehlen: Ableitung aus genau einem Quell- und Senkenplatz "
            "bestätigen",
            key="ag_pnml_markierung",
        )
        bestaetigt = st.checkbox(
            "Ich bestätige dieses Modell als unabhängige menschliche Sollvorgabe.",
            key="ag_pnml_bestaetigt",
        )
        if st.button("PNML sicher validieren", disabled=upload is None, type="primary"):
            try:
                assert upload is not None
                st.session_state.ag_sollmodell = validiere_pnml_sollmodell(
                    projekt_id=basis.projekt.projekt_id,
                    dateiname=upload.name,
                    originalbytes=upload.getvalue(),
                    menschlich_bestaetigt=bestaetigt,
                    markierungsableitung_bestaetigt=markierung,
                    **meta,
                )
                st.session_state.pop("ag_aktivitaetsmapping", None)
            except (Domaenenfehler, TypeError) as fehler:
                st.error(str(fehler))
    sollmodell = st.session_state.get("ag_sollmodell")
    if sollmodell is None or sollmodell.metadaten.projekt_id != basis.projekt.projekt_id:
        return None, None, False
    st.success(f"P_Soll ist validiert: {sollmodell.metadaten.bezeichnung}")
    st.download_button(
        "Generierte beziehungsweise normalisierte PNML-Datei herunterladen",
        sollmodell.replay_pnml,
        file_name=f"{sollmodell.metadaten.sollmodell_id}.pnml",
        mime="application/xml",
    )
    event_set = set(aktivitaeten)
    modell_set = set(sollmodell.sichtbare_transitionen)
    exakt = sorted(event_set & modell_set)
    nur_event = sorted(event_set - modell_set)
    nur_modell = sorted(modell_set - event_set)
    st.write("**Exakte Übereinstimmungen:**", exakt or "keine")
    st.write("**Nur in E*:**", nur_event or "keine")
    st.write("**Nur in P_Soll:**", nur_modell or "keine")
    manuell = {}
    for aktivitaet in nur_event:
        ziel = st.selectbox(
            f"Manuelle Zuordnung für '{aktivitaet}'",
            [_PLATZHALTER, *nur_modell],
            key=f"ag_mapping_{aktivitaet}",
        )
        if ziel != _PLATZHALTER:
            manuell[aktivitaet] = ziel
    mapping_bestaetigt = st.checkbox(
        "Ich bestätige die exakten und manuellen Aktivitätszuordnungen.",
        key="ag_mapping_bestaetigt",
    )
    if st.button("Aktivitätsmapping bestätigen"):
        try:
            st.session_state.ag_aktivitaetsmapping = erstelle_aktivitaetsmapping(
                projekt_id=basis.projekt.projekt_id,
                sollmodell_id=sollmodell.metadaten.sollmodell_id,
                event_aktivitaeten=aktivitaeten,
                modell_transitionen=sollmodell.sichtbare_transitionen,
                manuelle_zuordnungen=manuell,
                menschlich_bestaetigt=mapping_bestaetigt,
            )
        except Domaenenfehler as fehler:
            st.error(str(fehler))
    mapping = st.session_state.get("ag_aktivitaetsmapping")
    if mapping is not None and mapping.sollmodell_id != sollmodell.metadaten.sollmodell_id:
        mapping = None
    conformance = st.checkbox(
        "Token-Based Replay des vollständigen E* gegen P_Soll durchführen",
        key="ag_conformance_aktiv",
    )
    return sollmodell, mapping, conformance


def _zeitvergleich(basis: object) -> tuple[object | None, pd.DataFrame | None, object | None, bool]:
    st.subheader("4. Optionale Soll-Zeitstempel")
    aktiv = st.checkbox("Direkte zeitbezogene Soll-Ist-Auswertung durchführen", key="ag_zeit_aktiv")
    if not aktiv:
        return None, None, None, False
    quelle = st.radio(
        "Soll-Zeitdatenquelle",
        ["T", "E*", "Externe CSV-/XLSX-Datei"],
        key="ag_zeit_quelle",
    )
    sollartefakt = None
    if quelle == "T":
        solltabelle = basis.zwischendaten
        sollquelle = "T"
    elif quelle == "E*":
        solltabelle = basis.event_log
        sollquelle = "E*"
    else:
        upload = st.file_uploader(
            "Unveränderte Soll-Zeitdatentabelle hochladen",
            type=["csv", "xlsx"],
            key="ag_zeit_upload",
        )
        trennzeichen = st.text_input("CSV-Trennzeichen", value=",", key="ag_zeit_sep")
        tabellenblatt = st.text_input("XLSX-Tabellenblatt (optional)", key="ag_zeit_sheet")
        if upload is not None:
            datei = upload.getvalue()
            fingerprint = hashlib.sha256(datei).hexdigest()
            if st.session_state.get("ag_zeit_upload_sha") != fingerprint:
                try:
                    feste_id = uuid5(basis.projekt.projekt_id, fingerprint)
                    artefakt, tabelle = lese_externe_sollzeitdaten(
                        projekt_id=basis.projekt.projekt_id,
                        dateiname=upload.name,
                        originalbytes=datei,
                        tabellenblatt=tabellenblatt or None,
                        trennzeichen=trennzeichen,
                        sollzeitdaten_id=feste_id,
                    )
                    st.session_state.ag_sollzeitdaten = artefakt
                    st.session_state.ag_sollzeit_tabelle = tabelle
                    st.session_state.ag_zeit_upload_sha = fingerprint
                except Domaenenfehler as fehler:
                    st.error(str(fehler))
        sollartefakt = st.session_state.get("ag_sollzeitdaten")
        solltabelle = st.session_state.get("ag_sollzeit_tabelle")
        sollquelle = "extern"
        if sollartefakt is None or solltabelle is None:
            st.info("Für die Auswertung wird eine gültige externe Soll-Zeitdatentabelle benötigt.")
            return None, None, None, True
    soll_spalten = [str(wert) for wert in solltabelle.columns]
    ist_spalten = [str(wert) for wert in basis.event_log.columns]
    ebene = Vergleichsebene(
        st.radio(
            "Vergleichsebene",
            [Vergleichsebene.FALL.value, Vergleichsebene.EREIGNIS.value],
            key="ag_zeit_ebene",
        )
    )
    soll_case = _auswahl("case_id in den Soll-Daten", soll_spalten, key="ag_zeit_soll_case")
    soll_ts = _auswahl("Soll-Zeitstempel", soll_spalten, key="ag_zeit_soll_ts")
    ist_case = _auswahl("case_id in E*", ist_spalten, key="ag_zeit_ist_case")
    ist_ts = _auswahl("Tatsächlicher Ist-Zeitstempel", ist_spalten, key="ag_zeit_ist_ts")
    aktivitaeten = sorted(basis.event_log["activity"].astype("string").unique())
    if ebene is Vergleichsebene.FALL:
        ist_activity_spalte = _auswahl(
            "Aktivitätsspalte in E*", ist_spalten, key="ag_zeit_ist_activity_spalte"
        )
        ist_aktivitaet = _auswahl(
            "Tatsächliche Start-, End- oder Abschlussaktivität",
            aktivitaeten,
            key="ag_zeit_ist_aktivitaet",
        )
        regel = Vorkommensregel(
            st.selectbox(
                "Regel bei mehrfachem Vorkommen",
                [Vorkommensregel.ERSTES.value, Vorkommensregel.LETZTES.value],
                key="ag_zeit_regel",
            )
        )
        soll_activity = ""
        vorkommen = ""
    else:
        soll_activity = _auswahl(
            "activity in den Soll-Daten", soll_spalten, key="ag_zeit_soll_activity"
        )
        ist_activity_spalte = _auswahl(
            "activity in E*", ist_spalten, key="ag_zeit_ist_activity_spalte"
        )
        vorkommen = _auswahl(
            "Auftretensnummer in den Soll-Daten (bei Wiederholungen)",
            soll_spalten,
            key="ag_zeit_vorkommen",
        )
        if vorkommen == _PLATZHALTER:
            vorkommen = ""
        ist_aktivitaet = ""
        regel = Vorkommensregel.AUFTRETENSNUMMER

    def bereinigt(wert: str) -> str:
        return "" if wert == _PLATZHALTER else wert

    konfiguration = ZeitvergleichKonfiguration(
        ebene,
        sollquelle,
        bereinigt(soll_case),
        bereinigt(soll_ts),
        bereinigt(ist_case),
        bereinigt(ist_ts),
        bereinigt(soll_activity),
        bereinigt(ist_activity_spalte),
        bereinigt(ist_aktivitaet),
        vorkommen,
        regel,
    )
    return sollartefakt, solltabelle, konfiguration, True


def _vorschau_anzeigen(vorschau: Aggregationsvorschau) -> None:
    st.subheader("5. Vorschau und Speicherung von A_G")
    st.write("**Status der ausgewählten KPIs**")
    for wert in vorschau.kpi_ergebnisse:
        if wert.status is KpiStatus.BERECHNET:
            st.success(f"{wert.bezeichnung}: {wert.ergebnis} {wert.einheit}")
        else:
            st.warning(
                f"{wert.bezeichnung}: nicht berechenbar – "
                + "; ".join(wert.fehlende_voraussetzungen)
            )
    st.write(
        "**Conformance Checking:** "
        + ("A_C enthalten" if vorschau.conformance_ergebnis is not None else "nicht enthalten")
    )
    st.write(
        "**Soll-Ist-Auswertung:** "
        + ("A_V enthalten" if vorschau.zeitvergleich_ergebnis is not None else "nicht enthalten")
    )
    st.write("**Immer enthalten:** unveränderte Referenz auf A_D")
    if vorschau.warnungen:
        for warnung in vorschau.warnungen:
            st.warning(warnung)
    with st.expander("Vollständige Lineage der Vorschau"):
        st.json(
            {
                "U": vorschau.grundlage.untersuchungsauftrag_sha256,
                "R": vorschau.grundlage.datenprofil_sha256,
                "T": vorschau.grundlage.zwischendatensatz.sha256,
                "E*": vorschau.grundlage.freigabe.event_log_sha256,
                "P": vorschau.grundlage.prozessmodell_sha256,
                "A_D": vorschau.grundlage.discovery_ergebnisse_sha256,
                "eingabefingerabdruck": vorschau.grundlage.eingabefingerabdruck,
                "konfigurationsfingerabdruck": vorschau.konfigurationsfingerabdruck,
            }
        )
    if vorschau.conformance_ergebnis is not None:
        st.download_button(
            "Fallbezogene Token-Diagnosen als CSV herunterladen",
            pd.DataFrame(
                [asdict(wert) for wert in vorschau.conformance_ergebnis.fallbezogene_diagnosen]
            ).to_csv(index=False),
            file_name="a_c_token_diagnosen.csv",
            mime="text/csv",
        )
    if vorschau.zeitvergleich_ergebnis is not None:
        st.download_button(
            "Einzelne Soll-Ist-Abweichungen als CSV herunterladen",
            pd.DataFrame(
                [asdict(wert) for wert in vorschau.zeitvergleich_ergebnis.abweichungen]
            ).to_csv(index=False),
            file_name="a_v_zeitabweichungen.csv",
            mime="text/csv",
        )


def zeige_ergebnisaggregation_seite(
    projekt_service: ProjektService,
    service: ErgebnisaggregationService,
) -> None:
    """Zeigt Schritt 7 ohne lokale Auswahl vorgelagerter Artefakte."""
    st.header("7 Ergebnisse aggregieren")
    try:
        projekt_id = _uuid_aus_session("aktuelles_projekt_id")
        freigabe_id = _uuid_aus_session("aktuelle_freigabe_id")
        analyse_id = _uuid_aus_session("aktuelle_analyse_id")
        projekt = projekt_service.projekt_laden(projekt_id)
        if projekt is None:
            raise Domaenenfehler("Das aktive Projekt wurde nicht gefunden.")
        basis = service.grundlage_laden(projekt_id, freigabe_id, analyse_id)
    except (Domaenenfehler, Importintegritaetsfehler, KeyError, TypeError) as fehler:
        st.error(
            "Schritt 7 benötigt die aktive, erneut validierte Kombination aus U, R, T, "
            f"E*, P und A_D. Ursache: {fehler}"
        )
        _navigation_zurueck()
        return
    _eingangsartefakte(basis)
    kpi_konfigurationen = _kpi_konfigurationen(basis)
    sollmodell, mapping, conformance = _sollmodell_und_mapping(basis)
    sollzeitdaten, sollzeit_tabelle, zeitkonfiguration, zeit_aktiv = _zeitvergleich(basis)
    aktueller_fingerprint = service.konfigurationsfingerabdruck(
        kpi_konfigurationen=kpi_konfigurationen,
        sollmodell=sollmodell,
        aktivitaetsmapping=mapping,
        conformance_ausfuehren=conformance,
        sollzeitdaten=sollzeitdaten,
        zeitvergleich_konfiguration=zeitkonfiguration,
        zeitvergleich_ausfuehren=zeit_aktiv,
    )
    vorschau = st.session_state.get("ag_vorschau")
    if vorschau is not None and (
        vorschau.grundlage.eingabefingerabdruck != basis.eingabefingerabdruck
        or vorschau.konfigurationsfingerabdruck != aktueller_fingerprint
    ):
        st.session_state.pop("ag_vorschau", None)
        vorschau = None
        st.warning(
            "Eingaben oder Entscheidungen wurden geändert. Die Vorschau muss neu berechnet werden."
        )
    st.subheader("5. Vorschau und Speicherung von A_G")
    if st.button("A_G vollständig neu berechnen", type="primary"):
        try:
            st.session_state.ag_vorschau = service.vorschau(
                projekt_id=projekt_id,
                freigabe_id=freigabe_id,
                analyse_id=analyse_id,
                kpi_konfigurationen=kpi_konfigurationen,
                sollmodell=sollmodell,
                aktivitaetsmapping=mapping,
                conformance_ausfuehren=conformance,
                sollzeitdaten=sollzeitdaten,
                sollzeit_tabelle=sollzeit_tabelle,
                zeitvergleich_konfiguration=zeitkonfiguration,
                zeitvergleich_ausfuehren=zeit_aktiv,
            )
            vorschau = st.session_state.ag_vorschau
        except (Domaenenfehler, Importintegritaetsfehler, KeyError, TypeError) as fehler:
            st.error(str(fehler))
    if vorschau is not None:
        _vorschau_anzeigen(vorschau)
        bestaetigt = st.checkbox(
            "Ich bestätige die Vorschau, alle Zuordnungen und die vollständige Lineage von A_G.",
            key="ag_speichern_bestaetigt",
        )
        if st.button("A_G reproduzierbar speichern", type="primary"):
            try:
                aggregations_id = (
                    UUID(str(st.session_state.get("ag_neue_id")))
                    if st.session_state.get("ag_neue_id")
                    else uuid5(
                        projekt_id,
                        f"{basis.eingabefingerabdruck}:{vorschau.konfigurationsfingerabdruck}",
                    )
                )
                aggregation = service.speichern(
                    aggregations_id, vorschau, menschlich_bestaetigt=bestaetigt
                )
                st.session_state.aktuelle_aggregations_id = str(aggregation.aggregations_id)
                st.success("A_G wurde atomar gespeichert und vollständig erneut validiert.")
            except (Domaenenfehler, Importintegritaetsfehler, ValueError) as fehler:
                st.error(str(fehler))
    aktive_id = st.session_state.get("aktuelle_aggregations_id")
    if aktive_id:
        try:
            aggregation, a_g = service.laden(UUID(str(aktive_id)))
            st.success(f"Aktives, erneut validiertes A_G: `{aggregation.aggregations_id}`")
            st.download_button(
                "A_G als JSON herunterladen",
                service.a_g_download_laden(aggregation.aggregations_id),
                file_name=f"{aggregation.aggregations_id}.aggregation.json",
                mime="application/json",
            )
            if st.button("Weiter zu Schritt 8: Modellbestandteile ableiten", type="primary"):
                service.uebergabe_schritt8(
                    aggregation.aggregations_id, projekt_id, freigabe_id, analyse_id
                )
                st.session_state.naechster_framework_bereich = "8 Modellbestandteile ableiten"
                st.rerun()
        except (Domaenenfehler, Importintegritaetsfehler, ValueError) as fehler:
            st.error(f"Das aktive A_G ist nicht mehr gültig: {fehler}")
