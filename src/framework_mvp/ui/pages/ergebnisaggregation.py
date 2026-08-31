# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
# pyright: reportCallIssue=false, reportGeneralTypeIssues=false
"""Streamlit-Seite für Schritt 7: Ergebnisse aggregieren."""

import hashlib
from dataclasses import asdict
from datetime import UTC, date, datetime, time
from uuid import UUID, uuid5

import pandas as pd
import streamlit as st

from framework_mvp.application.ergebnisaggregation import (
    KpiDatenbasis,
    berechne_ausgewaehlte_kpis,
    kompatible_tabellenspalten,
    kpi_definition,
    profilkennzahlen_fuer_operand,
    zulaessige_quellen_fuer_operand,
)
from framework_mvp.application.ergebnisaggregation.sollprozess import (
    aktivitaetsreferenz_csv,
    erstelle_aktivitaetsmapping,
    erzeuge_lineares_sollmodell,
    validiere_pnml_sollmodell,
)
from framework_mvp.application.ergebnisaggregation.strukturierte_ergebnisse import (
    analysiere_ressourcen,
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
    AnkunftsstromDefinition,
    Attributzuordnung,
    BestaetigteWarteschlangeninformation,
    BusyRatioKonfiguration,
    Datenartefakt,
    KpiKonfiguration,
    KpiStatus,
    Operandentyp,
    OperandZuordnung,
    PerformanceZeitvergleichKonfiguration,
    ProfilkennzahlReferenz,
    Profilkennzahltyp,
    RessourcenanalyseErgebnis,
    Ressourcenzuordnungsmodus,
    SollmodellEntscheidung,
    Vorkommensregel,
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
    st.write(f"**Aktives Projekt:** {basis.projekt.bezeichnung}")
    von = basis.event_log["timestamp"].min()
    bis = basis.event_log["timestamp"].max()
    st.write(f"**Zeitraum:** {von} bis {bis}")
    st.write(f"**Notation von P:** {basis.discovery_ergebnisse['prozessnotation']}")


def _auswahl(
    bezeichnung: str,
    werte: list[str],
    *,
    key: str,
) -> str:
    return str(st.selectbox(bezeichnung, [_PLATZHALTER, *werte], key=key))


def _profilkennzahl_auswahl(
    bezeichnung: str,
    werte: tuple[ProfilkennzahlReferenz, ...],
    *,
    key: str,
) -> ProfilkennzahlReferenz | None:
    nach_id = {wert.referenz_id: wert for wert in werte}
    auswahl = str(
        st.selectbox(
            bezeichnung,
            [_PLATZHALTER, *nach_id],
            format_func=lambda referenz: (
                nach_id[str(referenz)].anzeigetext if str(referenz) in nach_id else str(referenz)
            ),
            key=key,
        )
    )
    return nach_id.get(auswahl)


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
    aktivitaeten = sorted(basis.event_log["activity"].astype("string").unique())
    profilkennzahlen = tuple(getattr(basis, "profilkennzahlen", ()))
    kpi_basis = KpiDatenbasis(
        basis.zwischendaten.copy(deep=True),
        basis.event_log.copy(deep=True),
        dict(basis.profilwerte),
        {},
        profilkennzahlen,
    )
    konfigurationen: list[KpiKonfiguration] = []
    for kpi_id in kpi_ids:
        definition = kpi_definition(kpi_id)
        with st.expander(f"{definition.bezeichnung} · {definition.formel}"):
            st.markdown(f"**Feste Formel:** {definition.formel}")
            st.caption(
                f"Bezugsmenge: {definition.bezugsmenge} · Ergebnis: {definition.einheit} · "
                f"Definitionsversion {definition.definitionsversion}"
            )
            direktes_profil = ""
            direkte_profilkennzahl = None
            mittelwerte = tuple(
                wert
                for wert in profilkennzahlen
                if wert.kennzahltyp is Profilkennzahltyp.ARITHMETISCHES_MITTEL
            )
            if (
                kpi_id
                in {
                    "mittlere_dlz_warenausgang",
                    "mittlere_dlz_wareneingang",
                    "mittlere_transportzeit_je_warensendung",
                    "mittlere_reaktionszeit",
                    "mittlere_kosten_produktionslogistik_pro_produktionsauftrag",
                }
                and mittelwerte
                and st.checkbox(
                    "Diese KPI entspricht exakt einem in R gespeicherten arithmetischen Mittelwert",
                    key=f"ag_{kpi_id}_direkt_r",
                )
            ):
                direkte_profilkennzahl = _profilkennzahl_auswahl(
                    "Exakt passende Mittelwert-Profilkennzahl aus R",
                    mittelwerte,
                    key=f"ag_{kpi_id}_direkt_r_referenz",
                )
                if direkte_profilkennzahl is not None:
                    st.caption(direkte_profilkennzahl.anzeigetext)
            zuordnungen = []
            if direkte_profilkennzahl is not None:
                st.info(
                    "Die weiterführende Berechnung aus T oder E* wird für diese KPI übersprungen."
                )
            for operand in definition.operanden:
                if direkte_profilkennzahl is not None:
                    break
                st.write(f"**{operand.bezeichnung}** ({operand.operandentyp.value})")
                quellen = [
                    wert.value for wert in zulaessige_quellen_fuer_operand(operand, kpi_basis)
                ]
                if not quellen:
                    st.warning(
                        "Für diese Rechengröße ist in R, T oder E* aktuell keine mathematisch "
                        "geeignete Datengrundlage vorhanden."
                    )
                    continue
                quelle_roh = st.selectbox(
                    "Zulässige Datenquelle",
                    quellen,
                    key=f"ag_{kpi_id}_{operand.operand_id}_quelle",
                )
                quelle = Datenartefakt(quelle_roh)
                if quelle is Datenartefakt.DATENPROFIL_R:
                    profil = _profilkennzahl_auswahl(
                        "Exakte Profilkennzahl aus R",
                        profilkennzahlen_fuer_operand(operand, kpi_basis),
                        key=f"ag_{kpi_id}_{operand.operand_id}_profil",
                    )
                    if profil is not None:
                        st.caption(profil.anzeigetext)
                        zuordnungen.append(
                            OperandZuordnung(
                                operand.operand_id,
                                quelle,
                                profilkennzahl=profil,
                            )
                        )
                    continue
                tabelle = (
                    basis.zwischendaten
                    if quelle is Datenartefakt.ZWISCHENDATENSATZ_T
                    else basis.event_log
                )
                spalten = list(kompatible_tabellenspalten(operand.operandentyp, tabelle))
                if operand.operandentyp is Operandentyp.ZEITDIFFERENZ_SUMME:
                    zeitmodi = ["zwei ausdrücklich gewählte Zeitstempelspalten"]
                    if quelle is Datenartefakt.EVENT_LOG_E_STERN:
                        zeitmodi.append("Start- und Endaktivität in E*")
                    modus = st.radio(
                        "Zeitbezug",
                        zeitmodi,
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
            konfiguration = KpiKonfiguration(
                kpi_id,
                tuple(zuordnungen),
                einheit,
                bezugsmenge,
                direktes_profil,
                direkte_profilkennzahl,
            )
            konfigurationen.append(konfiguration)
            (vorschau,) = berechne_ausgewaehlte_kpis((kpi_id,), (konfiguration,), kpi_basis)
            if vorschau.status is KpiStatus.BERECHNET:
                for operand in vorschau.zugeordnete_operanden:
                    st.caption(
                        f"Rechengröße {operand.get('bezeichnung', '')}: verwendeter Wert "
                        f"{operand.get('ermittelter_wert', '—')}"
                    )
                st.success(f"Vorschau des KPI-Ergebnisses: {vorschau.ergebnis} {vorschau.einheit}")
            else:
                st.caption(
                    "Noch nicht berechenbar: " + "; ".join(vorschau.fehlende_voraussetzungen)
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
        # Das frühere components.iframe(WOPED_NEXT_URL, height=900, scrolling=True) schlug fehl.
        st.iframe(WOPED_NEXT_URL, height=900, scrolling=True)


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
        if st.button("Lineares P_Soll erzeugen", type="primary"):
            try:
                st.session_state.ag_sollmodell = erzeuge_lineares_sollmodell(
                    projekt_id=basis.projekt.projekt_id,
                    aktivitaeten=reihenfolge,
                    menschlich_bestaetigt=True,
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
        markierung = st.radio(
            "Umgang mit fehlenden Anfangs- oder Endmarkierungen",
            (
                "Import abbrechen",
                "Aus eindeutigem Quell- und Senkenplatz ableiten",
            ),
            key="ag_pnml_markierung",
        )
        if st.button("PNML sicher validieren", disabled=upload is None, type="primary"):
            try:
                assert upload is not None
                st.session_state.ag_sollmodell = validiere_pnml_sollmodell(
                    projekt_id=basis.projekt.projekt_id,
                    dateiname=upload.name,
                    originalbytes=upload.getvalue(),
                    menschlich_bestaetigt=True,
                    markierungsableitung_bestaetigt=(
                        markierung == "Aus eindeutigem Quell- und Senkenplatz ableiten"
                    ),
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
    st.markdown("**A. Exakte automatische Treffer**")
    st.dataframe(
        pd.DataFrame(
            [{"Aktivität in E*": wert, "Sichtbare Transition in P_Soll": wert} for wert in exakt]
        ),
        hide_index=True,
        width="stretch",
    )
    st.markdown("**B. Manuell zuzuordnende Aktivitäten**")
    if not nur_event:
        st.caption("Alle Aktivitäten aus E* besitzen eine exakte Zuordnung.")
    manuell = {}
    for aktivitaet in nur_event:
        ziel = st.selectbox(
            f"Manuelle Zuordnung für '{aktivitaet}'",
            [_PLATZHALTER, *nur_modell],
            key=f"ag_mapping_{aktivitaet}",
        )
        if ziel != _PLATZHALTER:
            manuell[aktivitaet] = ziel
    st.markdown("**C. Nicht zugeordnete Bezeichnungen**")
    st.write("Nur in E*:", nur_event or "keine")
    st.write(
        "Nur in P_Soll (darf ohne Beobachtung bestehen bleiben):",
        nur_modell or "keine",
    )
    mapping_bestaetigt = st.checkbox(
        "Ich bestätige die Zuordnung zwischen den Aktivitäten des Event Logs und den "
        "Transitionen des Sollprozesses.",
        key="ag_mapping_bestaetigt",
    )
    if st.button("Aktivitätsmapping übernehmen", disabled=not mapping_bestaetigt):
        try:
            st.session_state.ag_aktivitaetsmapping = erstelle_aktivitaetsmapping(
                projekt_id=basis.projekt.projekt_id,
                sollmodell_id=sollmodell.metadaten.sollmodell_id,
                event_aktivitaeten=aktivitaeten,
                modell_transitionen=sollmodell.sichtbare_transitionen,
                manuelle_zuordnungen=manuell,
                menschlich_bestaetigt=True,
            )
        except Domaenenfehler as fehler:
            st.error(str(fehler))
    mapping = st.session_state.get("ag_aktivitaetsmapping")
    if mapping is not None and mapping.sollmodell_id != sollmodell.metadaten.sollmodell_id:
        mapping = None
    conformance = st.checkbox(
        "Token-Based Replay des vollständigen E* gegen P_Soll durchführen",
        key="ag_conformance_aktiv",
        disabled=mapping is None or bool(mapping.nur_event_log),
    )
    if mapping is None:
        st.info("Token-Based Replay benötigt zuerst ein ausdrücklich bestätigtes Mapping.")
    elif mapping.nur_event_log:
        st.warning(
            "Token-Based Replay ist blockiert, solange Aktivitäten nur in E* vorkommen: "
            + ", ".join(mapping.nur_event_log)
        )
    return sollmodell, mapping, conformance


def _ressourcenzuordnung(basis: object) -> RessourcenanalyseErgebnis | None:
    st.markdown("#### A. Ressourcen")
    automatisch = analysiere_ressourcen(basis.event_log.copy(deep=True))
    if automatisch.modus is Ressourcenzuordnungsmodus.AUTOMATISCH:
        st.success(
            "Die beobachteten Aktivität-Ressource-Paare aus der kanonischen Spalte resource "
            "werden automatisch übernommen."
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Aktivität": wert.aktivitaet,
                        "Ressourcen": ", ".join(wert.ressourcen),
                        "Ursprung": "automatisch aus E*.resource",
                    }
                    for wert in automatisch.zuordnungen
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        return automatisch

    st.info(
        "Beobachtete Paare bleiben erhalten. Entscheiden Sie nur für Aktivitäten ohne "
        "beobachtete Ressource: manuell ergänzen oder ausdrücklich offen lassen."
    )
    beobachtete = [wert for wert in automatisch.zuordnungen if wert.ressourcen]
    if beobachtete:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Aktivität": wert.aktivitaet,
                        "Beobachtete Ressourcen": ", ".join(wert.ressourcen),
                        "Herkunft": "automatisch aus E*.resource",
                    }
                    for wert in beobachtete
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    luecken = [wert for wert in automatisch.zuordnungen if wert.offen]
    tabelle = st.data_editor(
        pd.DataFrame(
            {
                "Aktivität": [wert.aktivitaet for wert in luecken],
                "Manuelle Ressourcen (kommagetrennt)": ["" for _ in luecken],
                "Offen / nicht bekannt": [True for _ in luecken],
            }
        ),
        hide_index=True,
        width="stretch",
        disabled=["Aktivität"],
        key="ag_ressourcen_tabelle",
    )
    zuordnungen = {
        str(zeile["Aktivität"]): tuple(
            wert.strip()
            for wert in str(zeile["Manuelle Ressourcen (kommagetrennt)"]).split(",")
            if wert.strip()
        )
        for _, zeile in tabelle.iterrows()
    }
    offene = tuple(
        str(zeile["Aktivität"])
        for _, zeile in tabelle.iterrows()
        if bool(zeile["Offen / nicht bekannt"])
    )
    doppelt = sorted(
        name for name, ressourcen in zuordnungen.items() if ressourcen and name in offene
    )
    if doppelt:
        st.warning(
            "Eine Aktivität kann nicht zugleich manuell zugeordnet und offen sein: "
            + ", ".join(doppelt)
            + "."
        )
        return None
    try:
        return analysiere_ressourcen(
            basis.event_log.copy(deep=True),
            manuelle_zuordnungen=zuordnungen,
            offene_aktivitaeten=offene,
        )
    except Domaenenfehler as fehler:
        st.warning(str(fehler))
        return None


def _attributzuordnungen(basis: object, *, art: str) -> tuple[Attributzuordnung, ...]:
    st.caption(
        f"{art} werden nur über ausdrücklich bestätigte Schlüssel und Spalten aus E* oder T "
        "übernommen; Spaltennamen werden nicht semantisch interpretiert."
    )
    ergebnisse: list[Attributzuordnung] = []
    for quelle, tabelle, fester_schluessel, key in (
        (
            Datenartefakt.EVENT_LOG_E_STERN,
            basis.event_log,
            "resource" if art == "Ressourcenattribute" else "case_id",
            "e",
        ),
        (Datenartefakt.ZWISCHENDATENSATZ_T, basis.zwischendaten, "", "t"),
    ):
        if not st.checkbox(f"{art} aus {quelle.value} zuordnen", key=f"ag_{art}_{key}_aktiv"):
            continue
        spalten = [str(wert) for wert in tabelle.columns]
        schluessel = fester_schluessel or str(
            st.selectbox("Bestätigte ID-/Schlüsselspalte", spalten, key=f"ag_{art}_{key}_id")
        )
        attribute = st.multiselect(
            "Bestätigte Attributspalten",
            [wert for wert in spalten if wert != schluessel],
            key=f"ag_{art}_{key}_attribute",
        )
        zeit = str(
            st.selectbox(
                "Zeitbezug (optional)",
                ["— kein Zeitbezug —", *[wert for wert in spalten if wert != schluessel]],
                key=f"ag_{art}_{key}_zeit",
            )
        )
        ergebnisse.extend(
            Attributzuordnung(
                quelle,
                str(attribut),
                schluessel,
                "" if zeit == "— kein Zeitbezug —" else zeit,
            )
            for attribut in attribute
        )
    return tuple(ergebnisse)


def _warteschlangeninformation(basis: object) -> tuple[BestaetigteWarteschlangeninformation, ...]:
    st.markdown("#### C. Warteschlangen und potenzielle Wartezeiten")
    st.caption(
        "Start(B) − Ende(A) ist nur eine potenzielle Wartezeit. Eine Warteschlange wird "
        "ausschließlich aus einer ausdrücklich bestätigten Information übernommen."
    )
    if not st.checkbox(
        "Explizite Warteschlangen-/Pufferinformation bestätigen", key="ag_queue_aktiv"
    ):
        return ()
    quelle = Datenartefakt(
        st.radio("Quelle der Warteschlangeninformation", ["E*", "T"], key="ag_queue_quelle")
    )
    tabelle = basis.event_log if quelle is Datenartefakt.EVENT_LOG_E_STERN else basis.zwischendaten
    aktivitaeten = sorted(str(wert) for wert in basis.event_log["activity"].dropna().unique())
    bezeichnung = st.text_input("Fachliche Bezeichnung", key="ag_queue_name")
    von = str(st.selectbox("Vorgängeraktivität", aktivitaeten, key="ag_queue_von"))
    zu = str(st.selectbox("Folgeaktivität", aktivitaeten, key="ag_queue_zu"))
    informationsspalte = str(
        st.selectbox("Bestätigte Informationsspalte", list(tabelle.columns), key="ag_queue_spalte")
    )
    filterwert = st.text_input("Optionaler exakter Filterwert", key="ag_queue_filter")
    if not bezeichnung.strip():
        st.warning("Die bestätigte Warteschlangeninformation benötigt eine Bezeichnung.")
        return ()
    return (
        BestaetigteWarteschlangeninformation(
            bezeichnung.strip(), von, zu, quelle, informationsspalte, filterwert
        ),
    )


def _ankunftsstroeme(basis: object) -> tuple[AnkunftsstromDefinition, ...]:
    st.markdown("#### E. Zwischenankunftszeiten (IAT)")
    st.caption(
        "Ohne explizit definierten Ankunftsstrom q wird keine IAT berechnet. Auch der erste "
        "Zeitstempel je Fall gilt nur nach ausdrücklicher Bestätigung als Systemeintritt."
    )
    anzahl = int(
        st.number_input("Anzahl bestätigter Ankunftsströme q", 0, 10, 0, key="ag_iat_anzahl")
    )
    ergebnisse: list[AnkunftsstromDefinition] = []
    for index in range(anzahl):
        with st.expander(f"Ankunftsstrom q{index + 1}", expanded=True):
            name = st.text_input("Fachliche Bezeichnung q", key=f"ag_iat_{index}_name")
            quelle = Datenartefakt(st.radio("Quelle", ["E*", "T"], key=f"ag_iat_{index}_quelle"))
            tabelle = (
                basis.event_log
                if quelle is Datenartefakt.EVENT_LOG_E_STERN
                else basis.zwischendaten
            )
            spalten = [str(wert) for wert in tabelle.columns]
            entitaet = (
                "case_id"
                if quelle is Datenartefakt.EVENT_LOG_E_STERN
                else str(st.selectbox("Entitäts-ID-Spalte", spalten, key=f"ag_iat_{index}_id"))
            )
            zeit = str(
                st.selectbox("Bestätigte Ankunftszeitspalte", spalten, key=f"ag_iat_{index}_zeit")
            )
            aktivitaet = ""
            if quelle is Datenartefakt.EVENT_LOG_E_STERN:
                aktivitaet = str(
                    st.selectbox(
                        "Ankunftsaktivität (optional)",
                        [
                            "— keine —",
                            *sorted(
                                str(wert) for wert in basis.event_log["activity"].dropna().unique()
                            ),
                        ],
                        key=f"ag_iat_{index}_aktivitaet",
                    )
                )
                if aktivitaet == "— keine —":
                    aktivitaet = ""
            filterspalte = ""
            filterwert = ""
            if st.checkbox("Exakten zusätzlichen Filter verwenden", key=f"ag_iat_{index}_filter"):
                filterspalte = str(
                    st.selectbox("Filterspalte", spalten, key=f"ag_iat_{index}_filterspalte")
                )
                filterwert = st.text_input("Exakter Filterwert", key=f"ag_iat_{index}_filterwert")
            regel_roh = str(
                st.selectbox(
                    "Vorkommensregel",
                    [
                        "— keine; Mehrdeutige ausschließen —",
                        Vorkommensregel.ERSTES.value,
                        Vorkommensregel.LETZTES.value,
                    ],
                    key=f"ag_iat_{index}_regel",
                )
            )
            regel = None if regel_roh.startswith("—") else Vorkommensregel(regel_roh)
            if name.strip():
                ergebnisse.append(
                    AnkunftsstromDefinition(
                        name.strip(),
                        quelle,
                        entitaet,
                        zeit,
                        aktivitaet=aktivitaet,
                        filterspalte=filterspalte,
                        filterwert=filterwert,
                        vorkommensregel=regel,
                    )
                )
            else:
                st.warning(f"Ankunftsstrom q{index + 1} benötigt eine fachliche Bezeichnung.")
    return tuple(ergebnisse)


def _performance_und_engpassanalyse(
    basis: object,
) -> tuple[
    object | None,
    pd.DataFrame | None,
    PerformanceZeitvergleichKonfiguration | None,
    bool,
    BusyRatioKonfiguration | None,
    bool,
]:
    st.subheader("5. Performance- und Engpassanalyse")
    st.caption(
        "Terminabweichung dT, Bearbeitungszeitabweichung dB und ressourcenbezogene Busy Ratio "
        "sind getrennte optionale Analysen. Es werden keine Ursachen oder Maßnahmen abgeleitet."
    )
    dt_aktiv = st.checkbox(
        "A. Termin-/Fertigstellungsabweichung dT – Gleichung 3.1",
        key="ag_performance_dt",
    )
    db_aktiv = st.checkbox(
        "B. Bearbeitungszeitabweichung dB – Gleichung 3.2",
        key="ag_performance_db",
    )
    busy_aktiv = st.checkbox(
        "C. Ressourcenbezogene Busy Ratio – Gleichungen 3.3 bis 3.5",
        key="ag_performance_busy",
    )
    sollartefakt = None
    solltabelle = None
    performance_konfiguration = None
    if dt_aktiv or db_aktiv:
        quelle = st.radio(
            "Soll-Zeitdatenquelle für dT/dB",
            ["T", "E*", "Externe CSV-/XLSX-Datei"],
            key="ag_performance_quelle",
        )
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
                key="ag_performance_upload",
            )
            trennzeichen = st.text_input("CSV-Trennzeichen", value=",", key="ag_performance_sep")
            tabellenblatt = st.text_input(
                "XLSX-Tabellenblatt (optional)", key="ag_performance_sheet"
            )
            if upload is not None:
                datei = upload.getvalue()
                fingerprint = hashlib.sha256(datei).hexdigest()
                if st.session_state.get("ag_performance_upload_sha") != fingerprint:
                    try:
                        artefakt, tabelle = lese_externe_sollzeitdaten(
                            projekt_id=basis.projekt.projekt_id,
                            dateiname=upload.name,
                            originalbytes=datei,
                            tabellenblatt=tabellenblatt or None,
                            trennzeichen=trennzeichen,
                            sollzeitdaten_id=uuid5(basis.projekt.projekt_id, fingerprint),
                        )
                        st.session_state.ag_sollzeitdaten = artefakt
                        st.session_state.ag_sollzeit_tabelle = tabelle
                        st.session_state.ag_performance_upload_sha = fingerprint
                    except Domaenenfehler as fehler:
                        st.error(str(fehler))
            sollartefakt = st.session_state.get("ag_sollzeitdaten")
            solltabelle = st.session_state.get("ag_sollzeit_tabelle")
            sollquelle = "extern"
        if solltabelle is None:
            st.warning("dT/dB nicht berechenbar: Die bestätigte Sollzeitquelle fehlt.")
        else:
            soll_spalten = [str(wert) for wert in solltabelle.columns]
            ist_spalten = [str(wert) for wert in basis.event_log.columns]

            def bevorzugt(spalten: list[str], *namen: str) -> list[str]:
                return [wert for wert in namen if wert in spalten] + [
                    wert for wert in spalten if wert not in namen
                ]

            soll_case = _auswahl(
                "Fall-ID in den Soll-Daten", soll_spalten, key="ag_performance_soll_case"
            )
            soll_activity = _auswahl(
                "Aktivität in den Soll-Daten",
                soll_spalten,
                key="ag_performance_soll_activity",
            )
            plan_ende = _auswahl(
                "Plan-Ende t_Plan,Ende",
                soll_spalten,
                key="ag_performance_plan_ende",
            )
            ist_case = _auswahl(
                "Fall-ID in E*",
                bevorzugt(ist_spalten, "case_id"),
                key="ag_performance_ist_case",
            )
            ist_activity = _auswahl(
                "Aktivität in E*",
                bevorzugt(ist_spalten, "activity"),
                key="ag_performance_ist_activity",
            )
            ist_ende = _auswahl(
                "Ist-Ende t_Ist,Ende",
                bevorzugt(ist_spalten, "end_timestamp", "timestamp"),
                key="ag_performance_ist_ende",
            )
            plan_start = ""
            ist_start = ""
            if db_aktiv:
                plan_start = _auswahl(
                    "Plan-Start t_Plan,Start",
                    soll_spalten,
                    key="ag_performance_plan_start",
                )
                ist_start = _auswahl(
                    "Ist-Start t_Ist,Start",
                    bevorzugt(ist_spalten, "start_timestamp", "timestamp"),
                    key="ag_performance_ist_start",
                )
            regel = Vorkommensregel(
                st.selectbox(
                    "Explizite Regel bei wiederholten Aktivitäten",
                    [
                        Vorkommensregel.ERSTES.value,
                        Vorkommensregel.LETZTES.value,
                        Vorkommensregel.AUFTRETENSNUMMER.value,
                    ],
                    key="ag_performance_regel",
                )
            )
            vorkommensspalte = ""
            if regel is Vorkommensregel.AUFTRETENSNUMMER:
                vorkommensspalte = _auswahl(
                    "Auftretensnummer in den Soll-Daten",
                    soll_spalten,
                    key="ag_performance_vorkommen",
                )

            def bereinigt(wert: str) -> str:
                return "" if wert == _PLATZHALTER else wert

            performance_konfiguration = PerformanceZeitvergleichKonfiguration(
                sollquelle,
                bereinigt(soll_case),
                bereinigt(soll_activity),
                bereinigt(ist_case),
                bereinigt(ist_activity),
                bereinigt(plan_ende),
                bereinigt(ist_ende),
                bereinigt(plan_start),
                bereinigt(ist_start),
                bereinigt(vorkommensspalte),
                regel,
                dt_aktiv,
                db_aktiv,
            )
    busy_konfiguration = None
    if busy_aktiv:
        ist_spalten = [str(wert) for wert in basis.event_log.columns]
        resource = _auswahl(
            "Bestätigte Ressourcenspalte",
            (["resource"] if "resource" in ist_spalten else [])
            + [wert for wert in ist_spalten if wert != "resource"],
            key="ag_busy_resource",
        )
        start = _auswahl(
            "Ist-Start der Ausführung",
            (["start_timestamp"] if "start_timestamp" in ist_spalten else [])
            + [wert for wert in ist_spalten if wert != "start_timestamp"],
            key="ag_busy_start",
        )
        ende = _auswahl(
            "Ist-Ende derselben Ausführung",
            (["end_timestamp"] if "end_timestamp" in ist_spalten else [])
            + [wert for wert in ist_spalten if wert != "end_timestamp"],
            key="ag_busy_ende",
        )
        start_bereinigt = "" if start == _PLATZHALTER else start
        ende_bereinigt = "" if ende == _PLATZHALTER else ende
        resource_bereinigt = "" if resource == _PLATZHALTER else resource
        if start_bereinigt and start_bereinigt in basis.event_log:
            zeitwerte = pd.to_datetime(
                basis.event_log[start_bereinigt], errors="coerce", utc=True
            ).dropna()
        else:
            zeitwerte = pd.Series(dtype="datetime64[ns, UTC]")
        if zeitwerte.empty:
            st.warning("Busy Ratio nicht berechenbar: Kein gültiger Ist-Start wurde zugeordnet.")
        else:
            aktive_zeitwerte = (
                pd.to_datetime(basis.event_log["timestamp"], errors="coerce", utc=True).dropna()
                if "timestamp" in basis.event_log.columns
                else zeitwerte
            )
            if aktive_zeitwerte.empty:
                aktive_zeitwerte = zeitwerte
            bereich_von = aktive_zeitwerte.min().date()
            bereich_bis = aktive_zeitwerte.max().date()
            zeitraum_von = st.date_input(
                "Betrachtungszeitraum von",
                value=bereich_von,
                min_value=bereich_von,
                max_value=bereich_bis,
                key="ag_busy_von",
            )
            zeitraum_bis = st.date_input(
                "Betrachtungszeitraum bis",
                value=bereich_bis,
                min_value=bereich_von,
                max_value=bereich_bis,
                key="ag_busy_bis",
            )
            busy_konfiguration = BusyRatioKonfiguration(
                resource_bereinigt,
                start_bereinigt,
                ende_bereinigt,
                datetime.combine(zeitraum_von, time.min, tzinfo=UTC),
                datetime.combine(zeitraum_bis, time.max, tzinfo=UTC),
            )
    return (
        sollartefakt,
        solltabelle,
        performance_konfiguration,
        dt_aktiv or db_aktiv,
        busy_konfiguration,
        busy_aktiv,
    )


def _vorschau_anzeigen(vorschau: Aggregationsvorschau) -> None:
    st.subheader("6. Ergebnisübersicht A_G und Speicherung")
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
        + (
            "A_V enthalten"
            if (
                vorschau.zeitvergleich_ergebnis is not None
                or getattr(vorschau, "performance_zeitvergleich_ergebnis", None) is not None
                or getattr(vorschau, "busy_ratio_ergebnis", None) is not None
            )
            else "nicht enthalten"
        )
    )
    st.write("**Immer enthalten:** unveränderte Referenz auf A_D")
    if vorschau.conformance_ergebnis is not None:
        conformance = vorschau.conformance_ergebnis
        st.markdown("#### Sollprozess und Conformance Checking")
        st.metric("Fitness nach Gleichung 3.13", conformance.fitness)
        token_spalten = st.columns(4)
        token_spalten[0].metric("pT · produzierte Tokens", conformance.produzierte_tokens)
        token_spalten[1].metric("cT · konsumierte Tokens", conformance.konsumierte_tokens)
        token_spalten[2].metric("mT · fehlende Tokens", conformance.fehlende_tokens)
        token_spalten[3].metric("rT · verbleibende Tokens", conformance.verbleibende_tokens)
        fall_spalten = st.columns(3)
        fall_spalten[0].metric(
            "Ausgewertete Fälle", conformance.konforme_faelle + conformance.abweichende_faelle
        )
        fall_spalten[1].metric("Konforme Fälle", conformance.konforme_faelle)
        fall_spalten[2].metric("Abweichende Fälle", conformance.abweichende_faelle)
        if conformance.fitness_plausibilisierung_pm4py is not None:
            st.caption(f"PM4Py-Plausibilisierung: {conformance.fitness_plausibilisierung_pm4py}")
            if (
                conformance.fitness is not None
                and abs(conformance.fitness - conformance.fitness_plausibilisierung_pm4py) > 0.01
            ):
                st.warning(
                    "Fitness nach Gleichung 3.13 und PM4Py-Plausibilisierung weichen "
                    "numerisch um mehr als 0,01 voneinander ab; der fachliche Hauptwert "
                    "wird nicht automatisch korrigiert."
                )
        with st.expander("Erläuterung der Tokenmengen und fallbezogene Diagnosen"):
            st.markdown(
                "- **Produzierte Tokens pT:** vom Sollmodell während des Replay erzeugt\n"
                "- **Konsumierte Tokens cT:** für die beobachtete Ausführung verbraucht\n"
                "- **Fehlende Tokens mT:** für die Spur benötigt, laut Modell nicht vorhanden\n"
                "- **Verbleibende Tokens rT:** nach Abschluss der Spur im Modell verblieben"
            )
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Fall-ID": wert.fall_id,
                            "pT": wert.produzierte_tokens,
                            "cT": wert.konsumierte_tokens,
                            "mT": wert.fehlende_tokens,
                            "rT": wert.verbleibende_tokens,
                            "Ergebnis": "konform" if wert.konform else "abweichend",
                        }
                        for wert in conformance.fallbezogene_diagnosen
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
    performance = getattr(vorschau, "performance_zeitvergleich_ergebnis", None)
    busy = getattr(vorschau, "busy_ratio_ergebnis", None)
    if performance is not None or busy is not None:
        st.markdown("#### Performance- und Engpassanalyse")
    if performance is not None:
        if performance.dt_statistik is not None:
            wert = performance.dt_statistik
            st.write(
                "**dT · Fertigstellungsabweichung (Gl. 3.1):** "
                f"n={wert.anzahl}, verspätet={wert.verspaetet}, "
                f"planmäßig={wert.planmaessig}, vorzeitig={wert.vorzeitig}, "
                f"Mittelwert={wert.mittelwert_sekunden} s, Median={wert.median_sekunden} s"
            )
        if performance.db_statistik is not None:
            wert = performance.db_statistik
            st.write(
                "**dB · Bearbeitungszeitabweichung (Gl. 3.2):** "
                f"n={wert.anzahl}, länger={wert.laenger_als_geplant}, "
                f"gleich={wert.gleich_geplant}, kürzer={wert.kuerzer_als_geplant}, "
                f"Mittelwert={wert.mittelwert_sekunden} s, Median={wert.median_sekunden} s"
            )
        with st.expander("Einzelwerte dT und dB"):
            st.dataframe(
                pd.DataFrame([asdict(wert) for wert in performance.einzelwerte]),
                hide_index=True,
                width="stretch",
            )
    if busy is not None:
        st.write(
            "**Ressourcenbezogene Busy Ratio (Gl. 3.3–3.5):** BR < 1 bedeutet eine "
            "niedrigere Eingangs- als Bearbeitungsrate, BR = 1 gleiche Raten und BR > 1 "
            "einen Hinweis auf potenziellen Rückstau; keine Warteschlange wird bewiesen."
        )
        st.dataframe(
            pd.DataFrame([asdict(wert) for wert in busy.ressourcenstatistiken]),
            hide_index=True,
            width="stretch",
        )
        if busy.potenzieller_engpass:
            st.warning(
                f"{busy.potenzieller_engpass} besitzt den höchsten mittleren Busy-Ratio-Wert "
                "und ist damit potenzieller Engpass im betrachteten Zeitraum."
            )
        elif sum(wert.anzahl_gueltige_busy_ratios > 0 for wert in busy.ressourcenstatistiken) == 1:
            st.info(
                "Nur eine Ressource besitzt gültige Busy-Ratio-Werte; ein Vergleich mit "
                "übrigen Ressourcen wird nicht behauptet."
            )
    ressourcenanalyse = getattr(vorschau, "ressourcenanalyse", None)
    if ressourcenanalyse is not None:
        st.write(
            "**Ressourcenzuordnung:** "
            f"{ressourcenanalyse.modus.value} · {ressourcenanalyse.herkunft}"
        )
        if ressourcenanalyse.attribute:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Ressource": wert.instanz_id,
                            "Attribut": wert.attribut,
                            "Status": wert.status.value,
                            "Stabiler Wert": wert.stabiler_wert or "—",
                            "Beobachtungen": len(wert.beobachtungen),
                        }
                        for wert in ressourcenanalyse.attribute
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
    entitaeten = getattr(vorschau, "entitaetsanalyse", None)
    if entitaeten is not None:
        st.write(
            f"**Entitätsinstanzen:** {len(entitaeten.instanzen)} aus E*.case_id · "
            f"{len(entitaeten.attribute)} bestätigte Attributauswertungen"
        )
    warteschlangenanalyse = getattr(vorschau, "warteschlangenanalyse", None)
    if warteschlangenanalyse is not None:
        st.write(
            "**Potenzielle Wartezeiten:** "
            f"{warteschlangenanalyse.status.value} · "
            f"{len(warteschlangenanalyse.potenzielle_wartezeiten)} Übergänge · "
            f"{len(warteschlangenanalyse.bestaetigte_warteschlangen)} ausdrücklich "
            "bestätigte Warteschlangeninformationen"
        )
    datenauswahl = getattr(vorschau, "zeitbezogene_datenauswahl", None)
    if datenauswahl is not None:
        st.write(
            "**Zeitbezogene Datenauswahl:** "
            + datenauswahl.status.value
            + f" · {len(datenauswahl.zwischenankunftszeiten)} Ankunftsströme q"
        )
        if datenauswahl.bearbeitungszeiten:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Aktivität": wert.aktivitaet,
                            "Ressource": wert.ressource or "kein Ressourcenbezug",
                            "n": wert.statistik.anzahl,
                            "Mittelwert (s)": wert.statistik.mittelwert_sekunden,
                            "Median (s)": wert.statistik.median_sekunden,
                        }
                        for wert in datenauswahl.bearbeitungszeiten
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        if datenauswahl.zwischenankunftszeiten:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Ankunftsstrom q": wert.definition.bezeichnung,
                            "Quelle": wert.definition.quelle.value,
                            "Status": wert.status.value,
                            "n": wert.statistik.anzahl if wert.statistik else 0,
                            "Ausgeschlossene Entitätsinstanzen": (
                                wert.ausgeschlossene_entitaetsinstanzen
                            ),
                        }
                        for wert in datenauswahl.zwischenankunftszeiten
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
    if vorschau.warnungen:
        for warnung in vorschau.warnungen:
            st.warning(warnung)
    with st.expander("Technische Details", expanded=False):
        st.json(
            {
                "projekt_id": str(vorschau.grundlage.projekt.projekt_id),
                "freigabe_id": str(vorschau.grundlage.freigabe.freigabe_id),
                "event_log_id": str(vorschau.grundlage.freigabe.event_log_id),
                "analyse_id": str(vorschau.grundlage.analyse.analyse_id),
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
    if getattr(vorschau, "performance_zeitvergleich_ergebnis", None) is not None:
        performance = vorschau.performance_zeitvergleich_ergebnis
        assert performance is not None
        st.download_button(
            "Einzelwerte dT und dB als CSV herunterladen",
            pd.DataFrame([asdict(wert) for wert in performance.einzelwerte]).to_csv(index=False),
            file_name="a_v_dt_db.csv",
            mime="text/csv",
        )
    if getattr(vorschau, "busy_ratio_ergebnis", None) is not None:
        busy = vorschau.busy_ratio_ergebnis
        assert busy is not None
        st.download_button(
            "Ressourcenbezogene Busy-Ratio-Einzelwerte als CSV herunterladen",
            pd.DataFrame([asdict(wert) for wert in busy.einzelwerte]).to_csv(index=False),
            file_name="a_v_busy_ratio.csv",
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
    st.subheader("4. Ressourcen, Entitäten, Warteschlangen und Zeitgrößen")
    ressourcenanalyse = _ressourcenzuordnung(basis)
    ressourcenattribute = _attributzuordnungen(basis, art="Ressourcenattribute")
    st.markdown("#### B. Entitätsinformationen")
    st.write(
        f"E*.case_id enthält {basis.event_log['case_id'].nunique()} beobachtete "
        "Entitätsinstanzen. Aus der technischen ID wird kein Entitätstyp geraten."
    )
    entitaetsattribute = _attributzuordnungen(basis, art="Entitätsattribute")
    entitaetstyp = st.text_input(
        "Bestätigter fachlicher Entitätstyp (optional)", key="ag_entitaetstyp"
    )
    warteschlangen = _warteschlangeninformation(basis)
    st.markdown("#### D. Bearbeitungszeiten")
    st.caption(
        "Bearbeitungszeit = end_timestamp − start_timestamp derselben Ausführung. Bei "
        "vorhandener Ressource erfolgt die Statistik je Aktivität + Ressource; sonst nur je "
        "Aktivität ohne Ressourcenbezug."
    )
    ankunftsstroeme = _ankunftsstroeme(basis)
    (
        sollzeitdaten,
        sollzeit_tabelle,
        performance_konfiguration,
        performance_aktiv,
        busy_konfiguration,
        busy_aktiv,
    ) = _performance_und_engpassanalyse(basis)
    aktueller_fingerprint = service.konfigurationsfingerabdruck(
        kpi_konfigurationen=kpi_konfigurationen,
        sollmodell=sollmodell,
        aktivitaetsmapping=mapping,
        conformance_ausfuehren=conformance,
        sollzeitdaten=sollzeitdaten,
        zeitvergleich_konfiguration=None,
        zeitvergleich_ausfuehren=False,
        ressourcenanalyse=ressourcenanalyse,
        ressourcenattributzuordnungen=ressourcenattribute,
        entitaetsattributzuordnungen=entitaetsattribute,
        entitaetstyp=entitaetstyp,
        bestaetigte_warteschlangen=warteschlangen,
        ankunftsstroeme=ankunftsstroeme,
        performance_zeitvergleich_konfiguration=performance_konfiguration,
        performance_zeitvergleich_ausfuehren=performance_aktiv,
        busy_ratio_konfiguration=busy_konfiguration,
        busy_ratio_ausfuehren=busy_aktiv,
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
    st.subheader("6. A_G berechnen")
    if st.button(
        "A_G berechnen und zu Schritt 8",
        type="primary",
        disabled=ressourcenanalyse is None,
    ):
        try:
            vorschau = service.vorschau(
                projekt_id=projekt_id,
                freigabe_id=freigabe_id,
                analyse_id=analyse_id,
                kpi_konfigurationen=kpi_konfigurationen,
                sollmodell=sollmodell,
                aktivitaetsmapping=mapping,
                conformance_ausfuehren=conformance,
                sollzeitdaten=sollzeitdaten,
                sollzeit_tabelle=sollzeit_tabelle,
                zeitvergleich_konfiguration=None,
                zeitvergleich_ausfuehren=False,
                ressourcenanalyse=ressourcenanalyse,
                ressourcenattributzuordnungen=ressourcenattribute,
                entitaetsattributzuordnungen=entitaetsattribute,
                entitaetstyp=entitaetstyp,
                bestaetigte_warteschlangen=warteschlangen,
                ankunftsstroeme=ankunftsstroeme,
                performance_zeitvergleich_konfiguration=performance_konfiguration,
                performance_zeitvergleich_ausfuehren=performance_aktiv,
                busy_ratio_konfiguration=busy_konfiguration,
                busy_ratio_ausfuehren=busy_aktiv,
            )
            st.session_state.ag_vorschau = vorschau
            aggregations_id = (
                UUID(str(st.session_state.get("ag_neue_id")))
                if st.session_state.get("ag_neue_id")
                else uuid5(
                    projekt_id,
                    f"{basis.eingabefingerabdruck}:{vorschau.konfigurationsfingerabdruck}",
                )
            )
            aggregation = service.speichern(aggregations_id, vorschau, menschlich_bestaetigt=True)
            st.session_state.aktuelle_aggregations_id = str(aggregation.aggregations_id)
            for schluessel in (
                "aktuelle_modellableitungs_id",
                "aktuelle_k_id",
                "aktuelle_o_id",
                "aktuelle_validierungslauf_id",
                "aktuelle_k_stern_id",
                "schritt10_ausgabe",
                "schritt10_ausgabe_signatur",
            ):
                st.session_state.pop(schluessel, None)
            service.uebergabe_schritt8(
                aggregation.aggregations_id, projekt_id, freigabe_id, analyse_id
            )
            st.session_state.naechster_framework_bereich = "8 Modellbestandteile ableiten"
            st.success(
                "A_G wurde gespeichert. Die Conformance-, Performance- und "
                "Engpassergebnisse werden unten direkt angezeigt."
            )
        except (
            Domaenenfehler,
            Importintegritaetsfehler,
            KeyError,
            TypeError,
            ValueError,
        ) as fehler:
            st.error(str(fehler))
    if vorschau is not None:
        _vorschau_anzeigen(vorschau)
    aktive_id = st.session_state.get("aktuelle_aggregations_id")
    if aktive_id:
        try:
            aggregation, a_g = service.laden(UUID(str(aktive_id)))
            st.success("A_G ist gespeichert und erneut validiert.")
            st.download_button(
                "A_G als JSON herunterladen",
                service.a_g_download_laden(aggregation.aggregations_id),
                file_name="aggregation-a-g.json",
                mime="application/json",
            )
        except (Domaenenfehler, Importintegritaetsfehler, ValueError) as fehler:
            st.error(f"Das aktive A_G ist nicht mehr gültig: {fehler}")
