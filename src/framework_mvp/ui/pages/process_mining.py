"""Framework-Schritt 6: Process Discovery mit PM4Py."""

import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime
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
from framework_mvp.domain.models import (
    DiscoveryKonfiguration,
    DiscoveryVerfahren,
    ProcessMiningFilter,
    ProcessMiningFiltertyp,
    ProcessMiningKonfiguration,
)
from framework_mvp.ui.components.kompakter_wizard import zeige_kompakten_fortschritt

LOGGER = logging.getLogger(__name__)
SCHRITTE = (
    "Datengrundlage",
    "Varianten und Filter",
    "Discovery",
    "Ergebnis speichern",
)
KURZ = ("Datengrundlage", "Verhalten", "Discovery", "Ergebnis")


def _zustand(projekt_id: UUID) -> dict[str, Any]:
    return st.session_state.setdefault("process_mining_zustaende", {}).setdefault(
        str(projekt_id), {"schritt": 1}
    )


def _navigation(zustand: dict[str, Any], weiter: bool) -> None:
    links, rechts = st.columns(2)
    if links.button("Zurück", disabled=zustand["schritt"] == 1, width="content"):
        zustand["schritt"] -= 1
        st.rerun()
    if rechts.button(
        "Weiter",
        disabled=zustand["schritt"] == len(SCHRITTE) or not weiter,
        type="primary",
        width="content",
    ):
        zustand["schritt"] += 1
        st.rerun()


def _kennzahlen(ergebnis: Any) -> None:
    spalten = st.columns(4)
    spalten[0].metric("Ereignisse", ergebnis.ereignisanzahl)
    spalten[1].metric("Fälle", ergebnis.fallanzahl)
    spalten[2].metric("Aktivitäten", ergebnis.aktivitaetsanzahl)
    spalten[3].metric("Varianten", ergebnis.variantenanzahl)


def _varianten(ergebnis: Any, *, begrenzen: bool = True) -> None:
    werte = ergebnis.varianten[:20] if begrenzen else ergebnis.varianten
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Rang": wert.rang,
                    "Aktivitätsfolge": " → ".join(wert.aktivitaetsfolge),
                    "Fälle": wert.fallanzahl,
                    "Anteil": wert.anteil,
                    "Kumuliert": wert.kumulierter_anteil,
                    "Aktivitäten": wert.aktivitaetsanzahl,
                }
                for wert in werte
            ]
        ),
        hide_index=True,
        width="stretch",
    )


def _dfg(vorschau: ProcessMiningVorschau) -> None:
    st.subheader("Frequenzbasierter Directly-Follows-Graph")
    if vorschau.dfg_svg:
        _zeige_svg(vorschau.dfg_svg, "Directly-Follows-Graph")
    else:
        st.info("Die grafische Darstellung ist nicht verfügbar. Alle DFG-Daten bleiben erhalten.")
    st.dataframe(
        pd.DataFrame([asdict(wert) for wert in vorschau.dfg_darstellung.kanten]),
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
    st.bar_chart(
        pd.DataFrame(
            vorschau.dfg.aktivitaetshaeufigkeiten, columns=["Aktivität", "Häufigkeit"]
        ).set_index("Aktivität")
    )


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
            f"Die Analyseergebnisse bleiben verfügbar: {fehler}"
        )
        return False


def _technik(
    process_mining_service: ProcessMiningService,
    *,
    pm4py_version: str,
    artefakte: dict[str, str] | None = None,
) -> None:
    """Zeigt technische Visualisierungsdiagnose kompakt im Expander."""
    status = process_mining_service.graphviz_status()
    with st.expander("Technische Visualisierungsinformationen"):
        st.write(f"PM4Py-Version: {pm4py_version}")
        st.write(f"Graphviz verfügbar: {'Ja' if status.verfuegbar else 'Nein'}")
        st.write(f"dot-Pfad: {status.dot_pfad or 'nicht gefunden'}")
        st.write(f"Graphviz-Version: {status.version or 'nicht verfügbar'}")
        st.write(
            "Python-pipe(format='svg'): "
            + ("gültig" if status.pipe_svg_gueltig else "nicht verfügbar")
        )
        st.json(artefakte or {})


def _filterkonfiguration(zustand: dict[str, Any], grundlage: pd.DataFrame) -> None:
    from framework_mvp.application.process_mining import berechne_varianten

    basis = berechne_varianten(grundlage)
    _kennzahlen(basis)
    st.subheader("Häufigste Varianten")
    _varianten(basis)
    with st.expander("Vollständige Variantenübersicht"):
        _varianten(basis, begrenzen=False)
    filter: list[ProcessMiningFilter] = []
    modus = st.radio(
        "Variantenfilter",
        ("Keine Variantenfilterung", "Top-k Varianten", "Kumulierte Fallabdeckung"),
    )
    jetzt = datetime.now(UTC)
    if modus == "Top-k Varianten":
        k = st.number_input(
            "Anzahl Varianten", 1, basis.variantenanzahl, min(20, basis.variantenanzahl)
        )
        filter.append(
            ProcessMiningFilter(
                ProcessMiningFiltertyp.VARIANTEN_TOP_K,
                json.dumps({"k": int(k)}),
                "{}",
                st.text_input("Fachliche Begründung für den Variantenfilter"),
                jetzt,
            )
        )
    elif modus == "Kumulierte Fallabdeckung":
        abdeckung = st.select_slider(
            "Gewünschte Fallabdeckung", options=(80, 90, 95, 100), value=100
        )
        filter.append(
            ProcessMiningFilter(
                ProcessMiningFiltertyp.VARIANTEN_ABDECKUNG,
                json.dumps({"abdeckung": abdeckung / 100}),
                "{}",
                st.text_input("Fachliche Begründung für die Abdeckung"),
                jetzt,
            )
        )
    else:
        filter.append(
            ProcessMiningFilter(
                ProcessMiningFiltertyp.KEIN_FILTER,
                "{}",
                "{}",
                "Keine Variantenfilterung gewählt.",
                jetzt,
            )
        )
    alle_aktivitaeten = sorted(grundlage["activity"].dropna().astype(str).unique())
    aktivitaeten = st.multiselect(
        "Aktivitäten der Analysesicht",
        alle_aktivitaeten,
        default=alle_aktivitaeten,
    )
    ausgeschlossen = sorted(set(alle_aktivitaeten) - set(aktivitaeten))
    if ausgeschlossen:
        st.warning(
            "Ausgeschlossene Aktivitäten verändern Spuren und Varianten: "
            + ", ".join(ausgeschlossen)
        )
    filter.append(
        ProcessMiningFilter(
            ProcessMiningFiltertyp.AKTIVITAETEN,
            json.dumps({"aktivitaeten": aktivitaeten}, ensure_ascii=False),
            "{}",
            "",
            jetzt,
        )
    )
    mindest = int(st.number_input("Minimale dargestellte Kantenhäufigkeit", 0, value=0))
    anteil = float(
        st.number_input(
            "Minimaler Anteil dargestellter DFG-Beziehungen",
            0.0,
            1.0,
            value=0.0,
            step=0.01,
        )
    )
    st.caption("Dieser Wert reduziert nur die dargestellten Kanten.")
    filter.append(
        ProcessMiningFilter(
            ProcessMiningFiltertyp.DFG_DARSTELLUNG,
            json.dumps({"mindesthaeufigkeit": mindest, "mindestanteil": anteil}),
            "{}",
            "",
            jetzt,
        )
    )
    zustand["filter"] = tuple(filter)
    zustand["dfg_mindesthaeufigkeit"] = mindest
    zustand["dfg_mindestanteil"] = anteil


def zeige_process_mining_seite(
    projekt_service: ProjektService,
    qualitaet_service: DatenqualitaetService,
    process_mining_service: ProcessMiningService,
) -> None:
    """Zeigt den vierstufigen Process-Discovery-Wizard."""
    st.header("6 Process Mining durchführen")
    projekte = projekt_service.projekte_auflisten()
    if not projekte:
        st.warning("Es muss zuerst ein Projekt angelegt werden.")
        return
    projekt_id = st.selectbox(
        "Projekt",
        [wert.projekt_id for wert in projekte],
        format_func=lambda wert: next(
            projekt.bezeichnung for projekt in projekte if projekt.projekt_id == wert
        ),
        key="process_mining_projekt",
    )
    zustand = _zustand(projekt_id)
    zeige_kompakten_fortschritt(schritt=zustand["schritt"], kurze_namen=KURZ, lange_namen=SCHRITTE)
    pruefungen = qualitaet_service.fuer_projekt(projekt_id)
    weiter = False
    try:
        if zustand["schritt"] == 1:
            if not pruefungen:
                st.warning(
                    "Für dieses Projekt ist noch kein qualitätsgeprüftes Event Log vorhanden."
                )
            else:
                quality_run_id = st.selectbox(
                    "Qualitätsgeprüfter Event Log",
                    [wert.quality_run_id for wert in pruefungen],
                )
                zustand["quality_run_id"] = quality_run_id
                artefakt, daten = process_mining_service.grundlage_laden(quality_run_id)
                zustand["grundlage"] = daten
                spalten = st.columns(4)
                spalten[0].metric("Ereignisse", len(daten))
                spalten[1].metric("Fälle", len(set(daten["case_id"].dropna().astype(str))))
                spalten[2].metric("Aktivitäten", len(set(daten["activity"].dropna().astype(str))))
                spalten[3].metric("Optionale Attribute", max(0, len(daten.columns) - 3))
                st.caption(
                    f"Event Log: {artefakt.event_log_id} · Prüfsumme: {artefakt.sha256} · "
                    f"Erstellt: {artefakt.erstellt_am.isoformat()}"
                )
                st.info(
                    "Der qualitätsgeprüfte Event Log wird ausschließlich "
                    "als Arbeitskopie analysiert."
                )
                weiter = True
        elif zustand["schritt"] == 2:
            _filterkonfiguration(zustand, zustand["grundlage"])
            weiter = bool(zustand["filter"])
        elif zustand["schritt"] == 3:
            st.markdown(
                "**Inductive Miner:** strukturierter Standard; der Noise Threshold steuert "
                "seltene Verhaltensweisen.  \n**Heuristics Miner:** berücksichtigt Häufigkeiten "
                "und Abhängigkeiten."
            )
            verfahren = st.radio(
                "Discovery-Verfahren",
                list(DiscoveryVerfahren),
                format_func=lambda wert: (
                    "Inductive Miner"
                    if wert is DiscoveryVerfahren.INDUCTIVE_MINER
                    else "Heuristics Miner"
                ),
            )
            if verfahren is DiscoveryVerfahren.INDUCTIVE_MINER:
                noise = st.slider("Noise Threshold", 0.0, 1.0, 0.0, 0.05)
                discovery = DiscoveryKonfiguration(verfahren, noise_threshold=noise)
            else:
                with st.expander("Erweiterte Parameter", expanded=True):
                    dependency = st.slider("Dependency Threshold", 0.0, 1.0, 0.5, 0.05)
                    and_threshold = st.slider("AND Threshold", 0.0, 1.0, 0.65, 0.05)
                    loop = st.slider("Loop-two Threshold", 0.0, 1.0, 0.5, 0.05)
                discovery = DiscoveryKonfiguration(
                    verfahren,
                    dependency_threshold=dependency,
                    and_threshold=and_threshold,
                    loop_two_threshold=loop,
                )
            konfiguration = ProcessMiningKonfiguration(discovery, zustand["filter"])
            discovery_signatur = json.dumps(
                {
                    "quality_run_id": str(zustand["quality_run_id"]),
                    "discovery": asdict(discovery),
                    "filter": [
                        asdict(wert)
                        for wert in zustand["filter"]
                        if wert.filtertyp is not ProcessMiningFiltertyp.DFG_DARSTELLUNG
                    ],
                },
                sort_keys=True,
                default=str,
            )
            if zustand.get("discovery_signatur") == discovery_signatur and "vorschau" in zustand:
                vorschau = process_mining_service.dfg_darstellung_aktualisieren(
                    zustand["vorschau"],
                    mindesthaeufigkeit=zustand["dfg_mindesthaeufigkeit"],
                    mindestanteil=zustand["dfg_mindestanteil"],
                )
            else:
                vorschau = process_mining_service.vorschau(
                    zustand["quality_run_id"],
                    konfiguration,
                    dfg_mindesthaeufigkeit=zustand["dfg_mindesthaeufigkeit"],
                    dfg_mindestanteil=zustand["dfg_mindestanteil"],
                )
                zustand["discovery_signatur"] = discovery_signatur
            zustand["konfiguration"] = konfiguration
            zustand["vorschau"] = vorschau
            _kennzahlen(vorschau.analysesicht.nachher)
            _dfg(vorschau)
            st.subheader("Entdecktes Prozessmodell")
            if vorschau.discovery.modell_svg:
                _zeige_svg(vorschau.discovery.modell_svg, "Entdecktes Petri-Netz")
                st.download_button(
                    "Modell-SVG herunterladen",
                    vorschau.discovery.modell_svg,
                    "process-model.svg",
                    "image/svg+xml",
                )
            else:
                st.info(
                    "Die Modellvisualisierung ist nicht verfügbar; das PNML bleibt speicherbar."
                )
            if vorschau.discovery.process_tree_svg:
                with st.expander("Process Tree anzeigen"):
                    _zeige_svg(vorschau.discovery.process_tree_svg, "Entdeckter Process Tree")
            st.json(asdict(vorschau.discovery.statistik))
            st.caption(f"PM4Py-Version: {vorschau.pm4py_version}")
            _technik(
                process_mining_service,
                pm4py_version=vorschau.pm4py_version,
                artefakte={
                    "DFG-SVG": "im Arbeitsspeicher" if vorschau.dfg_svg else "",
                    "Modell-SVG": ("im Arbeitsspeicher" if vorschau.discovery.modell_svg else ""),
                    "Process-Tree-SVG": (
                        "im Arbeitsspeicher" if vorschau.discovery.process_tree_svg else ""
                    ),
                },
            )
            weiter = True
        else:
            vorschau = zustand["vorschau"]
            _kennzahlen(vorschau.analysesicht.nachher)
            _varianten(vorschau.analysesicht.nachher)
            _dfg(vorschau)
            st.json(asdict(zustand["konfiguration"].discovery))
            if st.button("Analyse verbindlich speichern", type="primary"):
                analyse = process_mining_service.speichern(
                    zustand.setdefault("analyse_id", uuid4()),
                    zustand["quality_run_id"],
                    zustand["konfiguration"],
                    vorschau,
                )
                st.success(f"Analyse {analyse.analyse_id} wurde gespeichert.")
            gespeicherte = process_mining_service.fuer_projekt(projekt_id)
            if gespeicherte:
                st.subheader("Gespeicherte Analysen")
                auswahl = st.selectbox(
                    "Analyse erneut öffnen",
                    [wert.analyse_id for wert in gespeicherte],
                )
                if st.button("Gespeicherte Analyse öffnen"):
                    analyse, summary = process_mining_service.laden(auswahl)
                    svg_texte = summary["svg_texte"]
                    if svg_texte:
                        if svg_texte.get("dfg_svg"):
                            _zeige_svg(svg_texte["dfg_svg"], "Gespeicherter DFG")
                        if svg_texte.get("modell_svg"):
                            _zeige_svg(svg_texte["modell_svg"], "Gespeichertes Prozessmodell")
                        if svg_texte.get("process_tree_svg"):
                            _zeige_svg(
                                svg_texte["process_tree_svg"],
                                "Gespeicherter Process Tree",
                            )
                    else:
                        st.info(
                            "Diese gespeicherte Analyse besitzt keine SVG-Artefakte. "
                            "Tabellen und Modellartefakte bleiben verfügbar."
                        )
                    st.dataframe(
                        pd.DataFrame(summary["varianten"]), hide_index=True, width="stretch"
                    )
                    st.dataframe(
                        pd.DataFrame(summary["dfg_daten"]["kanten"]),
                        hide_index=True,
                        width="stretch",
                    )
                    with st.expander("Gespeicherte Konfiguration und Parameter"):
                        st.json(summary)
                    _technik(
                        process_mining_service,
                        pm4py_version=analyse.pm4py_version,
                        artefakte=summary.get("visualisierungsartefakte", {}),
                    )
                    st.caption(
                        f"{analyse.discovery_verfahren.value} · "
                        f"{analyse.fallanzahl_nachher} Fälle · "
                        f"{analyse.variantenanzahl_nachher} Varianten"
                    )
    except Exception as fehler:
        fehler_id = str(uuid4())
        LOGGER.exception("Process-Mining-Fehler %s", fehler_id)
        st.error(
            f"Process Mining konnte nicht ausgeführt werden: {fehler}. "
            f"Technische Fehler-ID: {fehler_id}"
        )
        weiter = False
    _navigation(zustand, weiter)
