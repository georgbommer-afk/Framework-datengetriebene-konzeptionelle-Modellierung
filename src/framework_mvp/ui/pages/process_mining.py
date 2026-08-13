"""Framework-Schritt 6: DFG und Inductive-Miner-Prozessmodell aus aktivem E*."""

import json
import logging
from dataclasses import asdict
from typing import Any
from uuid import UUID, uuid4

import pandas as pd
import streamlit as st

from framework_mvp.application.datenqualitaet_service import DatenqualitaetService
from framework_mvp.application.process_mining.svg import (
    UngueltigesSvg,
    validiere_svg_bytes,
    validiere_svg_text,
)
from framework_mvp.application.process_mining_service import (
    ProcessMiningService,
    ProcessMiningVorschau,
)
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import DiscoveryKonfiguration, Prozessnotation
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.ui.components.kompakter_wizard import zeige_kompakten_fortschritt
from framework_mvp.ui.navigation import framework_bereich_oeffnen, schritt_abschliessen_und_weiter
from framework_mvp.ui.pages.semantisches_mapping import _projektkontext

LOGGER = logging.getLogger(__name__)
SCHRITTE = (
    "Freigegebenen Event Log übernehmen",
    "Schwellwert und Prozessnotation festlegen",
    "P und Discovery-Ergebnisse speichern",
)
KURZ = ("E*", "k und Notation", "P und A_D")


def _zustand(projekt_id: UUID, freigabe_id: UUID) -> dict[str, Any]:
    zustaende = st.session_state.setdefault("process_mining_zustaende", {})
    zustand = zustaende.setdefault(str(projekt_id), {})
    if zustand.get("freigabe_id") != str(freigabe_id):
        zustand.clear()
        zustand.update(
            {
                "schritt": 1,
                "freigabe_id": str(freigabe_id),
                "analyse_id": uuid4(),
            }
        )
    return zustand


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


def _aktive_freigabe(projekt_id: UUID, service: DatenqualitaetService) -> UUID | None:
    try:
        freigabe_id = UUID(str(st.session_state.get("aktuelle_freigabe_id")))
    except (TypeError, ValueError):
        st.warning("Bitte geben Sie zuerst in Schritt 5 einen Event Log E unverändert als E* frei.")
        if st.button("Zu Schritt 5: Datenqualität prüfen", type="primary"):
            framework_bereich_oeffnen(schritt=5, projekt_id=projekt_id)
        return None
    try:
        freigabe, _ = service.freigabe_laden(freigabe_id)
    except (Domaenenfehler, Importintegritaetsfehler) as fehler:
        st.error(f"Die aktive E*-Freigabe ist nicht mehr gültig: {fehler}")
        if st.button("Zu Schritt 5 zurück"):
            framework_bereich_oeffnen(schritt=5, projekt_id=projekt_id)
        return None
    if freigabe.projekt_id != projekt_id:
        st.error("Die aktive E*-Freigabe gehört nicht zum aktuellen Projekt.")
        if st.button("Zu Schritt 5 zurück"):
            framework_bereich_oeffnen(schritt=5, projekt_id=projekt_id)
        return None
    return freigabe_id


def _zeige_svg(svg: bytes | str, beschriftung: str) -> bool:
    """Übergibt ausschließlich validierten SVG-Text an Streamlit."""
    try:
        svg_text = validiere_svg_bytes(svg) if isinstance(svg, bytes) else validiere_svg_text(svg)
        st.image(svg_text, caption=beschriftung, width="stretch")
        return True
    except (UngueltigesSvg, OSError, RuntimeError) as fehler:
        LOGGER.exception("SVG-Darstellung für %s fehlgeschlagen.", beschriftung)
        st.warning(
            f"{beschriftung} kann nicht grafisch angezeigt werden. "
            f"Die strukturierten Ergebnisse bleiben verfügbar: {fehler}"
        )
        return False


def _dfg(vorschau: ProcessMiningVorschau) -> None:
    st.subheader("Vollständiger frequenzbasierter Directly-Follows-Graph")
    st.caption(
        "Der DFG wird immer aus dem vollständigen unveränderten E* gebildet. "
        "Der Schwellwert k verändert ihn nicht."
    )
    if vorschau.dfg_svg is not None:
        _zeige_svg(vorschau.dfg_svg, "Directly-Follows-Graph mit Häufigkeiten")
        st.download_button(
            "DFG-SVG herunterladen",
            vorschau.dfg_svg,
            "directly-follows-graph.svg",
            "image/svg+xml",
        )
    else:
        st.info(
            "Graphviz ist nicht verfügbar; sämtliche strukturierten DFG-Daten bleiben erhalten."
        )
    st.dataframe(
        pd.DataFrame([asdict(wert) for wert in vorschau.dfg.kanten]),
        hide_index=True,
        width="stretch",
    )
    links, rechts = st.columns(2)
    links.dataframe(
        pd.DataFrame(vorschau.dfg.startaktivitaeten, columns=["Startaktivität", "Häufigkeit"]),
        hide_index=True,
        width="stretch",
    )
    rechts.dataframe(
        pd.DataFrame(vorschau.dfg.endaktivitaeten, columns=["Endaktivität", "Häufigkeit"]),
        hide_index=True,
        width="stretch",
    )


def _prozessmodell(vorschau: ProcessMiningVorschau) -> None:
    notation = vorschau.konfiguration.prozessnotation
    st.subheader(f"Gewähltes Prozessmodell P: {notation.bezeichnung}")
    if vorschau.discovery.modell_svg is not None:
        _zeige_svg(vorschau.discovery.modell_svg, notation.bezeichnung)
        st.download_button(
            "Darstellung von P als SVG herunterladen",
            vorschau.discovery.modell_svg,
            f"process-model-{notation.value}.svg",
            "image/svg+xml",
        )
    else:
        st.info(
            "Die grafische Darstellung ist lokal nicht verfügbar; das gewählte strukturierte "
            "Prozessmodell P bleibt speicher- und herunterladbar."
        )
    st.download_button(
        f"{notation.bezeichnung} herunterladen",
        vorschau.discovery.prozessmodell,
        f"process-model.{notation.dateiendung}",
        notation.mime_type,
    )
    if notation is not Prozessnotation.PROZESSBAUM:
        with st.expander("Intern erzeugten Prozessbaum anzeigen"):
            st.caption(
                "Der Prozessbaum ist das Reproduzierbarkeitsartefakt der Entdeckung, "
                "nicht das gewählte Prozessmodell P."
            )
            if vorschau.discovery.prozessbaum_svg is not None:
                _zeige_svg(vorschau.discovery.prozessbaum_svg, "Interner Prozessbaum")


def _technik(service: ProcessMiningService, vorschau: ProcessMiningVorschau) -> None:
    status = service.graphviz_status()
    with st.expander("Technische Reproduzierbarkeitsinformationen"):
        st.write(f"PM4Py-Version: {vorschau.pm4py_version}")
        st.write(f"Miner-Variante: {vorschau.konfiguration.miner_variante.value}")
        st.write(f"Graphviz verfügbar: {'Ja' if status.verfuegbar else 'Nein'}")
        st.write(f"Graphviz-Version: {status.version or 'nicht verfügbar'}")
        st.json(asdict(vorschau.discovery.statistik))


def _gespeichertes_ergebnis(a_d: dict[str, Any]) -> None:
    """Stellt erneut geladene P- und A_D-Artefakte ohne Neuberechnung identisch dar."""
    svg = a_d.get("svg_texte", {})
    st.subheader("Gespeicherter vollständiger Directly-Follows-Graph")
    if svg.get("dfg_svg"):
        _zeige_svg(svg["dfg_svg"], "Gespeicherter Directly-Follows-Graph")
    else:
        st.info("Keine DFG-Grafik gespeichert; die vollständigen DFG-Daten sind verfügbar.")
    st.dataframe(
        pd.DataFrame(a_d["dfg_daten"]["kanten"]),
        hide_index=True,
        width="stretch",
    )
    notation = Prozessnotation(a_d["prozessnotation"])
    st.subheader(f"Gespeichertes Prozessmodell P: {notation.bezeichnung}")
    if svg.get("modell_svg"):
        _zeige_svg(svg["modell_svg"], f"Gespeichertes {notation.bezeichnung}")
    else:
        st.info("Keine Modellgrafik gespeichert; das strukturierte Prozessmodell P ist gültig.")
    st.download_button(
        "Gespeichertes Prozessmodell P herunterladen",
        a_d["prozessmodell_bytes"],
        f"process-model.{notation.dateiendung}",
        a_d["prozessmodell_p"]["mime_type"],
    )


def zeige_process_mining_seite(
    projekt_service: ProjektService,
    qualitaet_service: DatenqualitaetService,
    process_mining_service: ProcessMiningService,
) -> None:
    """Setzt Algorithmus 6 mit den einzigen Entscheidungen k und Prozessnotation um."""
    st.header("6 Process Mining durchführen")
    projektkontext = _projektkontext(projekt_service)
    if projektkontext is None:
        return
    projekt_id, projektname = projektkontext
    freigabe_id = _aktive_freigabe(projekt_id, qualitaet_service)
    if freigabe_id is None:
        return
    zustand = _zustand(projekt_id, freigabe_id)
    try:
        freigabe, daten = process_mining_service.grundlage_laden(freigabe_id, projekt_id)
        zeige_kompakten_fortschritt(
            schritt=zustand["schritt"], kurze_namen=KURZ, lange_namen=SCHRITTE
        )
        if zustand["schritt"] == 1:
            st.write("### Aktive, erneut validierte Grundlage")
            st.write(
                f"**Projekt:** {projektname}  \n"
                f"**Freigabe-ID:** {freigabe.freigabe_id}  \n"
                f"**Event-Log-ID:** {freigabe.event_log_id}  \n"
                f"**Prüfsumme von E:** `{freigabe.event_log_sha256}`"
            )
            zeit = pd.to_datetime(daten["timestamp"], errors="coerce")
            spalten = st.columns(4)
            spalten[0].metric("Ereignisse", len(daten))
            spalten[1].metric("Fälle", len(set(daten["case_id"].astype(str))))
            spalten[2].metric("Aktivitäten", len(set(daten["activity"].astype(str))))
            spalten[3].metric(
                "Zeitraum",
                f"{zeit.min()} – {zeit.max()}" if not zeit.empty else "nicht bestimmbar",
            )
            st.info(
                "PM4Py erhält ausschließlich eine tiefe interne Arbeitskopie. E*, seine ID, "
                "Prüfsumme, Reihenfolge, Werte, Spalten und Datentypen bleiben unverändert."
            )
            vorhandene = process_mining_service.analysen_fuer_freigabe(projekt_id, freigabe_id)
            if vorhandene:
                with st.expander("Gespeicherte Ergebnisse für exakt dieses E* wiederaufnehmen"):
                    auswahl = st.selectbox(
                        "Gespeicherte Analyse",
                        [wert.analyse_id for wert in vorhandene],
                    )
                    if st.button("P und A_D wiederaufnehmen"):
                        analyse, a_d, _ = process_mining_service.uebergabe_laden(
                            auswahl, projekt_id, freigabe_id
                        )
                        st.session_state.aktuelle_analyse_id = str(analyse.analyse_id)
                        st.session_state.aktuelles_prozessmodell_id = str(analyse.analyse_id)
                        st.session_state.aktuelle_discovery_ergebnisse_id = str(analyse.analyse_id)
                        zustand["gespeicherte_analyse"] = analyse
                        zustand["gespeicherte_a_d"] = a_d
                        zustand["schritt"] = 3
                        st.rerun()
            _navigation(zustand, True)
            return

        if zustand["schritt"] == 2:
            st.write("### Menschliche Entscheidungen für die Prozessentdeckung")
            widget_praefix = f"process_mining_{projekt_id}_{freigabe_id}"
            k_key = f"{widget_praefix}_schwellwert_k"
            notation_key = f"{widget_praefix}_prozessnotation"
            st.session_state.setdefault(k_key, float(zustand.get("schwellwert_k", 0.0)))
            st.session_state.setdefault(
                notation_key, zustand.get("prozessnotation", Prozessnotation.PROZESSBAUM)
            )
            with st.form(f"{widget_praefix}_konfiguration"):
                k = float(
                    st.slider(
                        "Schwellwert k",
                        min_value=0.0,
                        max_value=1.0,
                        step=0.01,
                        key=k_key,
                    )
                )
                notation = st.radio(
                    "Prozessnotation für P",
                    list(Prozessnotation),
                    format_func=lambda wert: wert.bezeichnung,
                    key=notation_key,
                )
                berechnen = st.form_submit_button("Modell berechnen", type="primary")
            if k == 0.0:
                st.info("k = 0: Es wird der reguläre Inductive Miner verwendet.")
            else:
                st.warning(
                    "k > 0: Inductive Miner – infrequent erhöht mit wachsendem k den "
                    "Abstraktionsgrad. Seltenes Verhalten kann aus P ausgeschlossen und die "
                    "Fitness dadurch reduziert werden. Der vollständige DFG bleibt unverändert."
                )
            signatur = json.dumps(
                {
                    "freigabe_id": str(freigabe_id),
                    "event_log_sha256": freigabe.event_log_sha256,
                    "schwellwert_k": k,
                    "prozessnotation": notation.value,
                },
                sort_keys=True,
            )
            if berechnen:
                konfiguration = DiscoveryKonfiguration(k, notation)
                zustand["schwellwert_k"] = k
                zustand["prozessnotation"] = notation
                if zustand.get("vorschau_signatur") != signatur:
                    zustand.pop("gespeicherte_analyse", None)
                    zustand.pop("gespeicherte_a_d", None)
                    zustand["vorschau"] = process_mining_service.vorschau(
                        freigabe_id, konfiguration
                    )
                    zustand["vorschau_signatur"] = signatur
            vorschau = zustand.get("vorschau")
            if vorschau is None:
                st.info("Starten Sie die Prozessentdeckung ausdrücklich mit „Modell berechnen“.")
                _navigation(zustand, False)
                return
            if zustand.get("vorschau_signatur") != signatur:
                st.warning(
                    "Die angezeigte Vorschau gehört zur zuletzt bestätigten Konfiguration. "
                    "Berechnen Sie das Modell mit den geänderten Werten erneut."
                )
                _navigation(zustand, False)
                return
            if not isinstance(vorschau, ProcessMiningVorschau):
                raise Domaenenfehler("Die Process-Mining-Vorschau ist ungültig.")
            _dfg(vorschau)
            _prozessmodell(vorschau)
            _technik(process_mining_service, vorschau)
            _navigation(zustand, True)
            return

        st.write("### Prozessmodell P und Discovery-Ergebnisse A_D")
        analyse = zustand.get("gespeicherte_analyse")
        if analyse is None:
            vorschau = zustand.get("vorschau")
            if vorschau is None:
                zustand["schritt"] = 2
                st.rerun()
            konfiguration = vorschau.konfiguration
            _dfg(vorschau)
            _prozessmodell(vorschau)
            if st.button("P und A_D speichern und zu Schritt 7", type="primary"):
                analyse = process_mining_service.speichern(
                    zustand["analyse_id"], freigabe_id, konfiguration, vorschau
                )
                analyse, a_d, _ = process_mining_service.uebergabe_laden(
                    analyse.analyse_id, projekt_id, freigabe_id
                )
                zustand["gespeicherte_analyse"] = analyse
                zustand["gespeicherte_a_d"] = a_d
                st.session_state.aktuelle_analyse_id = str(analyse.analyse_id)
                st.session_state.aktuelles_prozessmodell_id = str(analyse.analyse_id)
                st.session_state.aktuelle_discovery_ergebnisse_id = str(analyse.analyse_id)
                schritt_abschliessen_und_weiter(aktueller_schritt=6, projekt_id=projekt_id)
        if analyse is None:
            _navigation(zustand, False)
            return
        a_d = zustand["gespeicherte_a_d"]
        st.success(
            "P und A_D wurden gespeichert und vollständig erneut validiert. E* blieb unverändert."
        )
        _gespeichertes_ergebnis(a_d)
        st.write(
            f"**Analyse-ID:** {analyse.analyse_id}  \n"
            f"**Freigabe-ID:** {analyse.qualitaetspruefung_id}  \n"
            f"**Miner-Variante:** {a_d['miner_variante']}  \n"
            f"**k:** {a_d['schwellwert_k']}  \n"
            f"**Prozessnotation:** {a_d['prozessnotation']}  \n"
            f"**Prozessmodell P:** `{a_d['prozessmodell_p']['relativer_pfad']}`  \n"
            f"**Discovery-Ergebnisse A_D:** `{analyse.relativer_ergebnis_pfad}`"
        )
        with st.expander("Gespeicherte Discovery-Ergebnisse A_D"):
            st.json({name: wert for name, wert in a_d.items() if not name.endswith("_bytes")})
        if st.button("Weiter zu Schritt 7: Ergebnisse aggregieren", type="primary"):
            schritt_abschliessen_und_weiter(aktueller_schritt=6, projekt_id=projekt_id)
        _navigation(zustand, False)
    except (Domaenenfehler, Importintegritaetsfehler, KeyError, ValueError) as fehler:
        LOGGER.exception("Process Mining konnte nicht ausgeführt werden.")
        st.error(f"Process Mining konnte nicht ausgeführt werden: {fehler}")
