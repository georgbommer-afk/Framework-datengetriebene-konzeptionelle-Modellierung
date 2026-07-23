"""Getrennter Adapter zur öffentlichen PM4Py-API."""

import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pm4py
from pm4py.visualization.dfg import visualizer as dfg_visualizer
from pm4py.visualization.petri_net import visualizer as petri_visualizer
from pm4py.visualization.process_tree import visualizer as process_tree_visualizer

from framework_mvp.application.process_mining.svg import validiere_svg_bytes
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    DfgErgebnis,
    DiscoveryErgebnisse,
    DiscoveryKonfiguration,
    DiscoveryVerfahren,
    ModellStatistik,
    ProcessMiningWarnung,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GraphvizStatus:
    """Technischer Laufzeitstatus der lokalen Graphviz-Ausführung."""

    verfuegbar: bool
    dot_pfad: str
    version: str
    pipe_svg_gueltig: bool


@dataclass(frozen=True, slots=True)
class Pm4pyDiscoveryErgebnis:
    """Discovery-Ergebnis einschließlich nicht persistierbarer Laufzeitobjekte."""

    ergebnisse: DiscoveryErgebnisse
    netz: Any
    initial_marking: Any
    final_marking: Any


class Pm4pyAdapter:
    """Übersetzt kanonische Logs kontrolliert in eine PM4Py-Arbeitskopie."""

    @property
    def version(self) -> str:
        """Liefert die installierte PM4Py-Paketversion."""
        return version("pm4py")

    def graphviz_status(self) -> GraphvizStatus:
        """Prüft dot und einen echten Python-Graphviz-Pipe-Aufruf."""
        dot_pfad = shutil.which("dot") or ""
        if not dot_pfad:
            return GraphvizStatus(False, "", "", False)
        try:
            ausgabe = subprocess.run(
                [dot_pfad, "-V"],
                check=True,
                capture_output=True,
                text=True,
            )
            from graphviz import Digraph

            graph = Digraph()
            graph.edge("A", "B")
            validiere_svg_bytes(graph.pipe(format="svg"))
            return GraphvizStatus(
                True,
                dot_pfad,
                (ausgabe.stderr or ausgabe.stdout).strip(),
                True,
            )
        except (OSError, subprocess.SubprocessError, ValueError) as fehler:
            LOGGER.exception("Graphviz-Statusprüfung fehlgeschlagen.")
            return GraphvizStatus(False, dot_pfad, str(fehler), False)

    def arbeitskopie(self, daten: pd.DataFrame) -> pd.DataFrame:
        """Erzeugt eine PM4Py-kompatible Kopie und bewahrt Zusatzattribute."""
        erforderlich = {"case_id", "activity", "timestamp"}
        fehlend = erforderlich - set(daten)
        if fehlend:
            raise Domaenenfehler(
                "Dem Event Log fehlen Pflichtspalten: " + ", ".join(sorted(fehlend))
            )
        kopie = daten.copy(deep=True)
        for spalte in ("case_id", "activity"):
            serie = cast("pd.Series", kopie[spalte])
            if bool(serie.isna().any()) or bool(serie.astype("string").str.strip().eq("").any()):
                raise Domaenenfehler(f"Die Pflichtspalte {spalte} enthält leere Werte.")
        kopie["timestamp"] = pd.to_datetime(kopie["timestamp"], errors="coerce", utc=True)
        if bool(cast("pd.Series", kopie["timestamp"]).isna().any()):
            raise Domaenenfehler("Die Pflichtspalte timestamp enthält ungültige Zeitwerte.")
        return kopie.rename(
            columns={
                "case_id": "case:concept:name",
                "activity": "concept:name",
                "timestamp": "time:timestamp",
            }
        )

    def entdecken(
        self, daten: pd.DataFrame, konfiguration: DiscoveryKonfiguration
    ) -> Pm4pyDiscoveryErgebnis:
        """Führt eines der zwei explizit unterstützten Discovery-Verfahren aus."""
        log = self.arbeitskopie(daten)
        process_tree = None
        if konfiguration.verfahren is DiscoveryVerfahren.INDUCTIVE_MINER:
            process_tree = pm4py.discover_process_tree_inductive(
                log, noise_threshold=konfiguration.noise_threshold
            )
            netz, initial, final = pm4py.convert_to_petri_net(process_tree)
        else:
            netz, initial, final = pm4py.discover_petri_net_heuristics(
                log,
                dependency_threshold=konfiguration.dependency_threshold,
                and_threshold=konfiguration.and_threshold,
                loop_two_threshold=konfiguration.loop_two_threshold,
            )
        sichtbar = sum(transition.label is not None for transition in netz.transitions)
        statistik = ModellStatistik(
            sichtbar,
            len(netz.transitions) - sichtbar,
            len(netz.places),
            len(netz.arcs),
        )
        warnungen: list[ProcessMiningWarnung] = []
        modell_svg = None
        process_tree_svg = None
        try:
            modell_graph = petri_visualizer.apply(netz, initial, final)
            modell_svg = self._graph_svg(modell_graph)
        except Exception as fehler:
            LOGGER.exception("Die Petri-Netz-Visualisierung ist fehlgeschlagen.")
            warnungen.append(
                ProcessMiningWarnung(
                    "MODELL_VISUALISIERUNG_NICHT_VERFUEGBAR",
                    f"Die Modellvisualisierung ist lokal nicht verfügbar: {fehler}",
                )
            )
        if process_tree is not None:
            try:
                process_tree_graph = process_tree_visualizer.apply(process_tree)
                process_tree_svg = self._graph_svg(process_tree_graph)
            except Exception as fehler:
                LOGGER.exception("Die Process-Tree-Visualisierung ist fehlgeschlagen.")
                warnungen.append(
                    ProcessMiningWarnung(
                        "PROCESS_TREE_VISUALISIERUNG_NICHT_VERFUEGBAR",
                        f"Die Process-Tree-Visualisierung ist lokal nicht verfügbar: {fehler}",
                    )
                )
        with tempfile.TemporaryDirectory(prefix="framework-pm-") as verzeichnis:
            basis = Path(verzeichnis)
            pnml_pfad = basis / "modell.pnml"
            pm4py.write_pnml(netz, initial, final, str(pnml_pfad))
            pnml = pnml_pfad.read_bytes()
            ptml = None
            if process_tree is not None:
                ptml_pfad = basis / "prozessbaum.ptml"
                pm4py.write_ptml(process_tree, str(ptml_pfad))
                ptml = ptml_pfad.read_bytes()
        return Pm4pyDiscoveryErgebnis(
            DiscoveryErgebnisse(
                statistik,
                pnml,
                ptml,
                modell_svg,
                process_tree_svg,
                tuple(warnungen),
            ),
            netz,
            initial,
            final,
        )

    def dfg_visualisieren(
        self, dfg: DfgErgebnis
    ) -> tuple[bytes | None, ProcessMiningWarnung | None]:
        """Visualisiert einen DFG oder liefert einen kontrollierten Graphviz-Fallback."""
        kanten = {(wert.quelle, wert.ziel): float(wert.haeufigkeit) for wert in dfg.kanten}
        start = dict(dfg.startaktivitaeten)
        ende = dict(dfg.endaktivitaeten)
        try:
            graph = dfg_visualizer.apply(
                kanten,
                activities_count=dict(dfg.aktivitaetshaeufigkeiten),
                parameters={
                    "start_activities": start,
                    "end_activities": ende,
                },
            )
            return self._graph_svg(graph), None
        except Exception as fehler:
            LOGGER.exception("Die DFG-Visualisierung ist fehlgeschlagen.")
            return None, ProcessMiningWarnung(
                "DFG_VISUALISIERUNG_NICHT_VERFUEGBAR",
                "Die grafische DFG-Darstellung ist lokal nicht verfügbar; "
                f"die Tabellen bleiben verwendbar: {fehler}",
            )

    @staticmethod
    def _graph_svg(graph: Any) -> bytes:
        """Erzeugt validierte SVG-Bytes direkt aus einem Graphviz-Objekt."""
        svg_bytes = cast("bytes", graph.pipe(format="svg"))
        validiere_svg_bytes(svg_bytes)
        return svg_bytes
