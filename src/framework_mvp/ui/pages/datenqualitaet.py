"""Framework-Schritt 5: Quality-Gate für Q, T, optional M und E."""

import json
from dataclasses import asdict
from typing import Any
from uuid import UUID, uuid4

import pandas as pd
import streamlit as st

from framework_mvp.application.datenqualitaet_service import DatenqualitaetService
from framework_mvp.application.event_log_service import EventLogKontext, EventLogService
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    FachlicheEntscheidung,
    QualityGateBefund,
    QualityGateErgebnis,
    QualityGateStatus,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.ui.components.kompakter_wizard import zeige_kompakten_fortschritt
from framework_mvp.ui.helpers import fachliche_auswahl
from framework_mvp.ui.navigation import framework_bereich_oeffnen, schritt_abschliessen_und_weiter
from framework_mvp.ui.pages.semantisches_mapping import _projektkontext

SCHRITTE = (
    "Artefaktkette übernehmen",
    "Automatische Pflichtprüfungen",
    "Fachlich bewerten",
    "Freigeben oder zurückspringen",
)
KURZ = ("Q · T · M · E", "Automatisch", "Menschlich", "E* / Rücksprung")


def _zustand(projekt_id: UUID, event_log_id: UUID) -> dict[str, Any]:
    zustaende = st.session_state.setdefault("quality_gate_zustaende", {})
    zustand = zustaende.setdefault(str(projekt_id), {})
    if zustand.get("event_log_id") != str(event_log_id):
        zustand.clear()
        zustand.update(
            {
                "schritt": 1,
                "event_log_id": str(event_log_id),
                "freigabe_id": uuid4(),
                "entscheidungen": (),
            }
        )
    return zustand


def _aktives_event_log(projekt_id: UUID, service: EventLogService) -> UUID | None:
    try:
        event_log_id = UUID(str(st.session_state.get("aktuelles_event_log_id")))
    except (TypeError, ValueError):
        st.warning("Bitte erzeugen und speichern Sie zuerst in Schritt 4 einen Event Log E.")
        if st.button("Zu Schritt 4: Event Log aufbauen", type="primary"):
            framework_bereich_oeffnen(schritt=4, projekt_id=projekt_id)
        return None
    artefakte = {wert.event_log_id: wert for wert in service.fuer_projekt(projekt_id)}
    if event_log_id not in artefakte:
        st.error("Der aktive Event Log gehört nicht zum aktuellen Projekt oder existiert nicht.")
        if st.button("Zu Schritt 4 zurück"):
            framework_bereich_oeffnen(schritt=4, projekt_id=projekt_id)
        return None
    return event_log_id


def _navigation(zustand: dict[str, Any], weiter: bool) -> None:
    links, rechts = st.columns(2)
    if links.button("Zurück", disabled=zustand["schritt"] == 1, width="stretch"):
        zustand["schritt"] -= 1
        st.rerun()
    if zustand["schritt"] == len(SCHRITTE):
        return
    if rechts.button(
        "Weiter",
        disabled=not weiter,
        type="primary",
        width="stretch",
    ):
        zustand["schritt"] += 1
        st.rerun()


def _befundtabelle(befunde: tuple[QualityGateBefund, ...]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Artefakt": wert.bereich.value,
                "Prüfkriterium": wert.kriterium,
                "Ergebnis": wert.status.value,
                "Feststellung": wert.meldung,
                "Ereignisse": wert.betroffene_ereignisse,
                "Fälle": wert.betroffene_faelle,
                "Anteil": wert.anteil,
                "Technische Quelle": ", ".join(wert.technische_quellen),
                "Rücksprung": (
                    f"Schritt {wert.ruecksprung_schritt}"
                    if wert.ruecksprung_schritt is not None
                    else "–"
                ),
                "Begründung": wert.begruendung,
            }
            for wert in befunde
        ]
    )


def _artefaktkette(ergebnis: QualityGateErgebnis, kontext: EventLogKontext) -> None:
    st.write("### Verwendete Artefaktkette")
    snapshot = json.loads(ergebnis.datenquellen_snapshot_json)
    q_zeilen = []
    for wert in snapshot:
        quelle = wert["datenquelle"]
        q_zeilen.append(
            {
                "Datenquelle": quelle["bezeichnung"],
                "Konkrete Quelle": quelle["konkretes_quellsystem"],
                "Quellenart": quelle["quellenart"],
                "Datei/Tabelle/Arbeitsblatt": wert["tabellenbezeichnung"],
                "Datengrundlage": quelle["fachliche_beschreibung"],
                "Herkunft/Verantwortung": quelle["herkunft_oder_verantwortungsbereich"],
                "Datenquellen-ID": quelle["datenquellen_id"],
                "Import-ID": wert["import_id"],
            }
        )
    st.write("**Datenquellenkatalog (Q) – tatsächlich verwendete Quellen**")
    st.dataframe(pd.DataFrame(q_zeilen), hide_index=True, width="stretch")
    st.write(
        f"**Zwischendatensatz (T):** {ergebnis.zwischendatensatz_id} · "
        f"{kontext.zwischendatensatz.zeilenanzahl:,} Zeilen · "
        f"{kontext.zwischendatensatz.spaltenanzahl:,} Spalten · "
        f"Prüfsumme `{ergebnis.zwischendatensatz_sha256}`  \n"
        f"**Mappingtabelle (M):** {ergebnis.mappingzustand.value}"
        + (
            f" · {ergebnis.mappingtabelle_id} · Prüfsumme `{ergebnis.mappingtabelle_sha256}`"
            if ergebnis.mappingtabelle_id is not None
            else ""
        )
        + f"  \n**Event-Log-Konfiguration:** {ergebnis.mapping_id} · "
        f"Strukturart {ergebnis.strukturart}  \n"
        f"**Event Log (E):** {ergebnis.event_log_id} · Prüfsumme "
        f"`{ergebnis.event_log_sha256}`"
    )
    spalten = st.columns(4)
    spalten[0].metric("Ereignisse", ergebnis.ereignisanzahl)
    spalten[1].metric("Fälle", ergebnis.fallanzahl)
    spalten[2].metric("Aktivitäten", ergebnis.aktivitaetsanzahl)
    spalten[3].metric(
        "Zeitraum",
        (
            f"{ergebnis.zeitraum_von} – {ergebnis.zeitraum_bis}"
            if ergebnis.zeitraum_von is not None
            else "nicht bestimmbar"
        ),
    )
    with st.expander("Technische Herkunft von E"):
        st.json(kontext.lineage)


def _automatische_pruefung(ergebnis: QualityGateErgebnis) -> None:
    st.write("### Datenqualitätsprüfung der erzeugten Artefakte")
    st.dataframe(_befundtabelle(ergebnis.befunde), hide_index=True, width="stretch")
    st.write("### Erforderliche und ausgewählte Quellspalten in T")
    st.dataframe(
        pd.DataFrame([asdict(wert) for wert in ergebnis.spaltenpruefungen]),
        hide_index=True,
        width="stretch",
    )
    for befund in ergebnis.befunde:
        if befund.status is not QualityGateStatus.AUTOMATISCHER_MANGEL:
            continue
        st.error(befund.meldung)
        beispiele = json.loads(befund.beispiele_json)
        if beispiele:
            st.dataframe(pd.DataFrame(beispiele), hide_index=True, width="stretch")
    st.info(
        "Schritt 5 berechnet keinen Gesamtscore und verändert weder Q, T, M noch E. "
        "Technische Mängel können nicht fachlich übersteuert werden."
    )


def _menschliche_bewertung(
    ergebnis: QualityGateErgebnis,
    kontext: EventLogKontext,
    zustand: dict[str, Any],
) -> bool:
    st.write("### Menschliche Bewertung und Domänenwissen")
    st.caption(
        "Bewerten Sie die grundsätzliche Verwendbarkeit. Jede Entscheidung benötigt eine "
        "kurze fachliche Begründung; sie ist keine numerische Qualitätsbewertung."
    )
    if kontext.mappingtabelle is not None and kontext.mappingtabelle.eintraege:
        st.write("**Zuordnungen der Mappingtabelle M**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Art": wert.art.value,
                        "Technische Referenz": wert.technische_bezeichnung,
                        "Quellspalte": wert.technische_quellspalte,
                        "Datentyp": (
                            wert.wertreferenz.technischer_datentyp
                            if wert.wertreferenz is not None
                            else ""
                        ),
                        "Fachliche Bezeichnung": wert.fachliche_bezeichnung,
                    }
                    for wert in kontext.mappingtabelle.eintraege
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    fachliche_befunde = [
        wert
        for wert in ergebnis.befunde
        if wert.status
        in {
            QualityGateStatus.FACHLICHE_BESTAETIGUNG_ERFORDERLICH,
            QualityGateStatus.FACHLICH_ALS_MANGEL_BEWERTET,
            QualityGateStatus.FACHLICH_BEGRUENDET_KEIN_MANGEL,
        }
    ]
    bisher = {wert.kriterium_id: wert for wert in zustand.get("entscheidungen", ())}
    entscheidungen: list[FachlicheEntscheidung] = []
    vollstaendig = True
    for befund in fachliche_befunde:
        st.write(f"**{befund.bereich.value}: {befund.kriterium}**")
        st.write(befund.meldung)
        vorhandene = bisher.get(befund.kriterium_id)
        auswahl = st.radio(
            "Fachliche Entscheidung",
            ("Noch nicht bewertet", "Begründet kein Mangel", "Als Mangel bewertet"),
            index=(0 if vorhandene is None else 2 if vorhandene.ist_mangel else 1),
            key=f"gate_entscheidung_{zustand['event_log_id']}_{befund.kriterium_id}",
            horizontal=True,
        )
        begruendung = st.text_area(
            "Kurze fachliche Begründung",
            value=vorhandene.begruendung if vorhandene is not None else "",
            key=f"gate_begruendung_{zustand['event_log_id']}_{befund.kriterium_id}",
        ).strip()
        if auswahl == "Noch nicht bewertet" or not begruendung:
            vollstaendig = False
            continue
        ruecksprung = vorhandene.ruecksprung_schritt if vorhandene is not None else None
        if auswahl == "Als Mangel bewertet" and befund.kriterium_id == "e_interpretierbar":
            ruecksprung = fachliche_auswahl(
                "Ursächlicher vorheriger Schritt",
                (2, 3, 4),
                wert=ruecksprung if ruecksprung in {2, 3, 4} else None,
                format_func=lambda wert: {
                    2: "Schritt 2 – Ursache in T",
                    3: "Schritt 3 – Ursache in M",
                    4: "Schritt 4 – Konfiguration oder Erzeugung von E",
                }[wert],
                key=f"gate_ursache_{zustand['event_log_id']}_{befund.kriterium_id}",
            )
            if ruecksprung is None:
                vollstaendig = False
                continue
        entscheidungen.append(
            FachlicheEntscheidung(
                befund.kriterium_id,
                auswahl == "Als Mangel bewertet",
                begruendung,
                ruecksprung if auswahl == "Als Mangel bewertet" else None,
            )
        )
    zustand["entscheidungen"] = tuple(entscheidungen)
    if not vollstaendig:
        st.info("Alle fachlichen Bewertungen und Begründungen sind vor der Entscheidung nötig.")
    return vollstaendig


def _abschluss(
    projekt_id: UUID,
    event_log_id: UUID,
    kontext: EventLogKontext,
    service: DatenqualitaetService,
    zustand: dict[str, Any],
) -> None:
    ergebnis = service.quality_gate_pruefen(
        projekt_id, event_log_id, tuple(zustand["entscheidungen"])
    )
    st.write("### Abschlussentscheidung des Quality-Gates")
    _befundansicht = _befundtabelle(ergebnis.befunde)
    st.dataframe(_befundansicht, hide_index=True, width="stretch")
    if not ergebnis.freigabe_moeglich:
        st.error("Gesamtstatus: Rücksprung erforderlich. Es wird kein E* erzeugt.")
        for schritt in ergebnis.rueckspruenge:
            if st.button(
                f"Zu Schritt {schritt} zurückspringen",
                key=f"gate_ruecksprung_{schritt}",
            ):
                framework_bereich_oeffnen(schritt=schritt, projekt_id=projekt_id)
        if st.button("Bewertungen ändern"):
            zustand["schritt"] = 3
            st.rerun()
        return
    st.success("Gesamtstatus: Freigabe möglich.")
    freigabe = zustand.get("freigabe")
    if freigabe is not None:
        freigabe, e_stern = service.freigabe_laden(freigabe.freigabe_id)
        if freigabe.projekt_id != projekt_id or freigabe.event_log_id != event_log_id:
            raise Importintegritaetsfehler(
                "Die gespeicherte Freigabe gehört nicht zum aktiven Projekt und Event Log."
            )
        zustand["freigabe"] = freigabe
        st.session_state.aktuelle_freigabe_id = str(freigabe.freigabe_id)
        st.session_state.freigegebenes_event_log_id = str(event_log_id)
    if freigabe is None and st.button(
        "Event Log E als E* freigeben und zu Schritt 6",
        type="primary",
    ):
        freigabe = service.freigeben(
            zustand["freigabe_id"],
            projekt_id,
            event_log_id,
            tuple(zustand["entscheidungen"]),
        )
        geladen, _ = service.freigabe_laden(freigabe.freigabe_id)
        if geladen.projekt_id != projekt_id or geladen.event_log_id != event_log_id:
            raise Importintegritaetsfehler(
                "Die gespeicherte Freigabe konnte nicht im aktiven Kontext validiert werden."
            )
        zustand["freigabe"] = geladen
        st.session_state.aktuelle_freigabe_id = str(geladen.freigabe_id)
        st.session_state.freigegebenes_event_log_id = str(event_log_id)
        schritt_abschliessen_und_weiter(aktueller_schritt=5, projekt_id=projekt_id)
    if freigabe is None:
        st.info("Geben Sie zuerst E unverändert als E* frei, bevor Sie fortfahren.")
        return
    st.success(
        "E wurde ohne Änderung von Reihenfolge, Werten, Spalten oder Datentypen als E* "
        "freigegeben. Es wurde keine zusätzliche Qualitäts-CSV erzeugt."
    )
    st.write(
        f"**Freigabe-ID:** {freigabe.freigabe_id}  \n"
        f"**Event-Log-ID:** {freigabe.event_log_id}  \n"
        f"**Unveränderte E-Prüfsumme:** `{freigabe.event_log_sha256}`  \n"
        f"**Auditbericht:** `{freigabe.relativer_report_pfad}`  \n"
        f"**Ereignisse:** {ergebnis.ereignisanzahl:,} · **Fälle:** "
        f"{ergebnis.fallanzahl:,} · **Aktivitäten:** {ergebnis.aktivitaetsanzahl:,}  \n"
        f"**Zeitraum:** {ergebnis.zeitraum_von or 'nicht bestimmbar'} – "
        f"{ergebnis.zeitraum_bis or 'nicht bestimmbar'}"
    )
    fachspalten = [
        wert
        for wert in e_stern.columns
        if wert in {"case_id", "activity", "timestamp"}
        or wert in kontext.lineage.get("herkunft_zusaetzliche_attribute", {})
    ]
    st.dataframe(e_stern.loc[:, fachspalten].head(200), width="stretch")
    if st.button("Weiter zu Schritt 6", type="primary"):
        schritt_abschliessen_und_weiter(aktueller_schritt=5, projekt_id=projekt_id)


def zeige_datenqualitaet_seite(
    projekt_service: ProjektService,
    event_log_service: EventLogService,
    qualitaet_service: DatenqualitaetService,
) -> None:
    """Setzt Tabelle 3.14 und Pseudocode 5 als nicht veränderndes Quality-Gate um."""
    st.header("5 Datenqualität prüfen")
    try:
        projektkontext = _projektkontext(projekt_service)
        if projektkontext is None:
            return
        projekt_id, _ = projektkontext
        event_log_id = _aktives_event_log(projekt_id, event_log_service)
        if event_log_id is None:
            return
        zustand = _zustand(projekt_id, event_log_id)
        kontext = event_log_service.kontext_laden(event_log_id)
        ergebnis = qualitaet_service.quality_gate_pruefen(
            projekt_id,
            event_log_id,
            tuple(zustand.get("entscheidungen", ())),
        )
        zeige_kompakten_fortschritt(
            schritt=zustand["schritt"], kurze_namen=KURZ, lange_namen=SCHRITTE
        )
        if zustand["schritt"] == 1:
            _artefaktkette(ergebnis, kontext)
            vorhandene = qualitaet_service.freigaben_fuer_event_log(projekt_id, event_log_id)
            if vorhandene:
                with st.expander("Gespeicherte Freigabe für exakt dieses E wiederaufnehmen"):
                    auswahl = st.selectbox(
                        "Freigabe E*",
                        [wert.freigabe_id for wert in vorhandene],
                    )
                    if st.button("Freigabe wiederaufnehmen"):
                        zustand["freigabe"] = next(
                            wert for wert in vorhandene if wert.freigabe_id == auswahl
                        )
                        zustand["freigabe_id"] = auswahl
                        zustand["entscheidungen"] = qualitaet_service.entscheidungen_der_freigabe(
                            auswahl
                        )
                        st.session_state.aktuelle_freigabe_id = str(auswahl)
                        st.session_state.freigegebenes_event_log_id = str(event_log_id)
                        zustand["schritt"] = 4
                        st.rerun()
            _navigation(zustand, True)
        elif zustand["schritt"] == 2:
            _automatische_pruefung(ergebnis)
            _navigation(zustand, True)
        elif zustand["schritt"] == 3:
            vollstaendig = _menschliche_bewertung(ergebnis, kontext, zustand)
            _navigation(zustand, vollstaendig)
        else:
            _abschluss(
                projekt_id,
                event_log_id,
                kontext,
                qualitaet_service,
                zustand,
            )
            _navigation(zustand, False)
    except (Domaenenfehler, Importintegritaetsfehler) as fehler:
        st.error(str(fehler))
