"""Orchestrierung reproduzierbarer Process-Discovery-Analysen."""

import gzip
import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID

import pandas as pd

from framework_mvp.application.datenqualitaet_service import DatenqualitaetService
from framework_mvp.application.ports.process_mining_repository import ProcessMiningRepository
from framework_mvp.application.process_mining import (
    AnalysesichtErgebnis,
    GraphvizStatus,
    Pm4pyAdapter,
    berechne_dfg,
    filtere_analysesicht,
    filtere_dfg_darstellung,
    validiere_svg_bytes,
)
from framework_mvp.domain.models import (
    DfgErgebnis,
    DiscoveryErgebnisse,
    ProcessMiningAnalyse,
    ProcessMiningFiltertyp,
    ProcessMiningKonfiguration,
    ProcessMiningStatus,
    QualitaetspruefungArtefakt,
    VariantenErgebnis,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.infrastructure.importartefakte import ImportartefaktSpeicher

PROCESS_MINING_ARTEFAKTVERSION = 1


@dataclass(frozen=True, slots=True)
class ProcessMiningVorschau:
    """Vollständige Vorschau vor der expliziten Speicherung."""

    analysesicht: AnalysesichtErgebnis
    dfg: DfgErgebnis
    dfg_darstellung: DfgErgebnis
    discovery: DiscoveryErgebnisse
    dfg_svg: bytes | None
    pm4py_version: str
    cache_schluessel: str


class ProcessMiningService:
    """Analysiert ausschließlich qualitätsgeprüfte Event Logs."""

    def __init__(
        self,
        repository: ProcessMiningRepository,
        qualitaet_service: DatenqualitaetService,
        artefakte: ImportartefaktSpeicher,
        adapter: Pm4pyAdapter | None = None,
    ) -> None:
        self._repository = repository
        self._qualitaet = qualitaet_service
        self._artefakte = artefakte
        self._adapter = adapter or Pm4pyAdapter()

    def grundlage_laden(
        self, quality_run_id: UUID
    ) -> tuple[QualitaetspruefungArtefakt, pd.DataFrame]:
        """Lädt und validiert das qualitätsgeprüfte Artefakt vollständig."""
        artefakt, daten = self._qualitaet.laden(quality_run_id)
        self._adapter.arbeitskopie(daten)
        return artefakt, daten

    def vorschau(
        self,
        quality_run_id: UUID,
        konfiguration: ProcessMiningKonfiguration,
        *,
        dfg_mindesthaeufigkeit: int = 0,
        dfg_mindestanteil: float = 0.0,
    ) -> ProcessMiningVorschau:
        """Berechnet Grundauswertung, Analysesicht, DFG und Discovery."""
        artefakt, daten = self._qualitaet.laden(quality_run_id)
        filter_ohne_darstellung = tuple(
            wert
            for wert in konfiguration.filter
            if wert.filtertyp is not ProcessMiningFiltertyp.DFG_DARSTELLUNG
        )
        sicht = filtere_analysesicht(daten, filter_ohne_darstellung)
        dfg = berechne_dfg(sicht.daten)
        darstellung = filtere_dfg_darstellung(
            dfg,
            mindesthaeufigkeit=dfg_mindesthaeufigkeit,
            mindestanteil=dfg_mindestanteil,
        )
        discovery = self._adapter.entdecken(sicht.daten, konfiguration.discovery).ergebnisse
        dfg_svg, dfg_warnung = self._adapter.dfg_visualisieren(darstellung)
        warnungen = discovery.warnungen + ((dfg_warnung,) if dfg_warnung else ())
        discovery = DiscoveryErgebnisse(
            discovery.statistik,
            discovery.pnml,
            discovery.process_tree_ptml,
            discovery.modell_svg,
            discovery.process_tree_svg,
            warnungen,
        )
        schluessel = self.cache_schluessel(
            artefakt.sha256, quality_run_id, konfiguration, self._adapter.version
        )
        return ProcessMiningVorschau(
            sicht,
            dfg,
            darstellung,
            discovery,
            dfg_svg,
            self._adapter.version,
            schluessel,
        )

    def dfg_darstellung_aktualisieren(
        self,
        vorschau: ProcessMiningVorschau,
        *,
        mindesthaeufigkeit: int,
        mindestanteil: float,
    ) -> ProcessMiningVorschau:
        """Aktualisiert ausschließlich die DFG-Darstellung ohne erneute Discovery."""
        darstellung = filtere_dfg_darstellung(
            vorschau.dfg,
            mindesthaeufigkeit=mindesthaeufigkeit,
            mindestanteil=mindestanteil,
        )
        svg, warnung = self._adapter.dfg_visualisieren(darstellung)
        discovery = vorschau.discovery
        if warnung and warnung not in discovery.warnungen:
            discovery = replace(discovery, warnungen=(*discovery.warnungen, warnung))
        return replace(
            vorschau,
            dfg_darstellung=darstellung,
            dfg_svg=svg,
            discovery=discovery,
        )

    def graphviz_status(self) -> GraphvizStatus:
        """Liefert den technischen Visualisierungsstatus ohne Discovery."""
        return self._adapter.graphviz_status()

    @staticmethod
    def cache_schluessel(
        event_log_sha256: str,
        quality_run_id: UUID,
        konfiguration: ProcessMiningKonfiguration,
        pm4py_version: str,
    ) -> str:
        """Erzeugt einen stabilen Cache-Schlüssel ohne reine Darstellungsfilter."""
        filter = [
            asdict(wert)
            for wert in konfiguration.filter
            if wert.filtertyp is not ProcessMiningFiltertyp.DFG_DARSTELLUNG
        ]
        basis = json.dumps(
            {
                "event_log_sha256": event_log_sha256,
                "quality_run_id": str(quality_run_id),
                "filter": filter,
                "discovery": asdict(konfiguration.discovery),
                "pm4py_version": pm4py_version,
            },
            sort_keys=True,
            default=str,
        ).encode()
        return hashlib.sha256(basis).hexdigest()

    def speichern(
        self,
        analyse_id: UUID,
        quality_run_id: UUID,
        konfiguration: ProcessMiningKonfiguration,
        vorschau: ProcessMiningVorschau,
    ) -> ProcessMiningAnalyse:
        """Speichert alle textbasierten Artefakte atomar und idempotent."""
        vorhanden = self._repository.laden(analyse_id)
        if vorhanden is not None:
            self.laden(analyse_id)
            return vorhanden
        qualitaet, _ = self._qualitaet.laden(quality_run_id)
        jetzt = datetime.now(UTC)
        basis = PurePosixPath("projects") / str(qualitaet.projekt_id) / "process_mining"
        pfade = {
            "summary": (basis / f"{analyse_id}.summary.json").as_posix(),
            "varianten": (basis / f"{analyse_id}.variants.csv.gz").as_posix(),
            "dfg": (basis / f"{analyse_id}.dfg.json").as_posix(),
            "modell": (basis / f"{analyse_id}.model.pnml").as_posix(),
            "ptml": (basis / f"{analyse_id}.process-tree.ptml").as_posix(),
            "dfg_svg": (basis / f"{analyse_id}.dfg.svg").as_posix(),
            "modell_svg": (basis / f"{analyse_id}.model.svg").as_posix(),
            "process_tree_svg": (basis / f"{analyse_id}.process-tree.svg").as_posix(),
        }
        varianten_bytes = self._varianten_csv(vorschau.analysesicht.nachher)
        dfg_bytes = json.dumps(
            {
                "aktivitaeten": vorschau.dfg.aktivitaeten,
                "aktivitaetshaeufigkeiten": vorschau.dfg.aktivitaetshaeufigkeiten,
                "kanten": [asdict(wert) for wert in vorschau.dfg.kanten],
                "startaktivitaeten": vorschau.dfg.startaktivitaeten,
                "endaktivitaeten": vorschau.dfg.endaktivitaeten,
                "darstellungsfilter": [
                    asdict(wert)
                    for wert in konfiguration.filter
                    if wert.filtertyp is ProcessMiningFiltertyp.DFG_DARSTELLUNG
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=str,
        ).encode()
        inhalte: dict[str, bytes] = {
            pfade["varianten"]: varianten_bytes,
            pfade["dfg"]: dfg_bytes,
            pfade["modell"]: vorschau.discovery.pnml,
        }
        if vorschau.discovery.process_tree_ptml is not None:
            inhalte[pfade["ptml"]] = vorschau.discovery.process_tree_ptml
        if vorschau.dfg_svg is not None:
            inhalte[pfade["dfg_svg"]] = vorschau.dfg_svg
        if vorschau.discovery.modell_svg is not None:
            inhalte[pfade["modell_svg"]] = vorschau.discovery.modell_svg
        if vorschau.discovery.process_tree_svg is not None:
            inhalte[pfade["process_tree_svg"]] = vorschau.discovery.process_tree_svg
        for pfad, inhalt in inhalte.items():
            if pfad.endswith(".svg"):
                validiere_svg_bytes(inhalt)
        pruefsummen = {pfad: hashlib.sha256(inhalt).hexdigest() for pfad, inhalt in inhalte.items()}
        summary = {
            "artefaktversion": PROCESS_MINING_ARTEFAKTVERSION,
            "analyse_id": str(analyse_id),
            "projekt_id": str(qualitaet.projekt_id),
            "qualitaetspruefung_id": str(quality_run_id),
            "event_log_id": str(qualitaet.event_log_id),
            "pm4py_version": vorschau.pm4py_version,
            "cache_schluessel": vorschau.cache_schluessel,
            "grundkennzahlen": asdict(vorschau.analysesicht.vorher),
            "filter": [asdict(wert) for wert in konfiguration.filter],
            "filterwirkung": asdict(vorschau.analysesicht.nachher),
            "discovery_verfahren": konfiguration.discovery.verfahren.value,
            "parameter": asdict(konfiguration.discovery),
            "modellstatistik": asdict(vorschau.discovery.statistik),
            "warnungen": [asdict(wert) for wert in vorschau.discovery.warnungen],
            "visualisierungsartefakte": {
                "dfg_svg": pfade["dfg_svg"] if vorschau.dfg_svg else "",
                "modell_svg": (pfade["modell_svg"] if vorschau.discovery.modell_svg else ""),
                "process_tree_svg": (
                    pfade["process_tree_svg"] if vorschau.discovery.process_tree_svg else ""
                ),
            },
            "pruefsummen": pruefsummen,
            "erstellt_am": jetzt.isoformat(),
        }
        summary_bytes = json.dumps(
            summary, ensure_ascii=False, sort_keys=True, indent=2, default=str
        ).encode()
        erzeugt = []
        try:
            for pfad, inhalt in inhalte.items():
                gespeichert = self._artefakte.artefakt_speichern(pfad, inhalt)
                erzeugt.append(gespeichert)
                if hashlib.sha256(self._artefakte.lesen(pfad)).hexdigest() != pruefsummen[pfad]:
                    raise Importintegritaetsfehler(
                        "Eine Process-Mining-Artefaktprüfsumme ist ungültig."
                    )
                if pfad.endswith(".svg"):
                    validiere_svg_bytes(self._artefakte.lesen(pfad))
            erzeugt.append(self._artefakte.artefakt_speichern(pfade["summary"], summary_bytes))
            analyse = self._analyse(analyse_id, qualitaet, konfiguration, vorschau, pfade, jetzt)
            self._repository.speichern(analyse)
            return analyse
        except Exception:
            for artefakt in reversed(erzeugt):
                self._artefakte.neu_erstelltes_artefakt_entfernen(artefakt)
            raise

    def laden(self, analyse_id: UUID) -> tuple[ProcessMiningAnalyse, dict[str, Any]]:
        """Öffnet eine Analyse ohne Neuberechnung und prüft alle Artefakte."""
        analyse = self._repository.laden(analyse_id)
        if analyse is None:
            raise Importintegritaetsfehler("Die Process-Mining-Analyse wurde nicht gefunden.")
        summary = json.loads(self._artefakte.lesen(analyse.relativer_ergebnis_pfad))
        if summary["analyse_id"] != str(analyse_id):
            raise Importintegritaetsfehler("Das Analyseartefakt gehört zu einer anderen Analyse.")
        for pfad, erwartet in summary["pruefsummen"].items():
            inhalt = self._artefakte.lesen(pfad)
            if hashlib.sha256(inhalt).hexdigest() != erwartet:
                raise Importintegritaetsfehler(
                    "Die Prüfsumme eines Process-Mining-Artefakts stimmt nicht."
                )
            if pfad.endswith(".svg"):
                validiere_svg_bytes(inhalt)
        summary["dfg_daten"] = json.loads(self._artefakte.lesen(analyse.relativer_dfg_pfad))
        summary["varianten"] = pd.read_csv(
            BytesIO(gzip.decompress(self._artefakte.lesen(analyse.relativer_varianten_pfad)))
        ).to_dict(orient="records")
        summary["svg_texte"] = {
            name: validiere_svg_bytes(self._artefakte.lesen(pfad))
            for name, pfad in summary.get("visualisierungsartefakte", {}).items()
            if pfad
        }
        return analyse, summary

    def fuer_projekt(self, projekt_id: UUID) -> list[ProcessMiningAnalyse]:
        """Listet gespeicherte Analysen eines Projekts."""
        return self._repository.fuer_projekt(projekt_id)

    @staticmethod
    def _varianten_csv(ergebnis: VariantenErgebnis) -> bytes:
        tabelle = pd.DataFrame(
            [
                {
                    "rang": wert.rang,
                    "aktivitaetsfolge": " → ".join(wert.aktivitaetsfolge),
                    "fallanzahl": wert.fallanzahl,
                    "anteil": wert.anteil,
                    "kumulierter_anteil": wert.kumulierter_anteil,
                    "aktivitaetsanzahl": wert.aktivitaetsanzahl,
                }
                for wert in ergebnis.varianten
            ]
        )
        return gzip.compress(tabelle.to_csv(index=False).encode(), mtime=0)

    @staticmethod
    def _analyse(
        analyse_id: UUID,
        qualitaet: QualitaetspruefungArtefakt,
        konfiguration: ProcessMiningKonfiguration,
        vorschau: ProcessMiningVorschau,
        pfade: dict[str, str],
        jetzt: datetime,
    ) -> ProcessMiningAnalyse:
        vorher = vorschau.analysesicht.vorher
        nachher = vorschau.analysesicht.nachher
        return ProcessMiningAnalyse(
            analyse_id,
            qualitaet.projekt_id,
            qualitaet.quality_run_id,
            qualitaet.event_log_id,
            json.dumps(asdict(konfiguration), ensure_ascii=False, default=str),
            json.dumps([asdict(wert) for wert in konfiguration.filter], default=str),
            konfiguration.discovery.verfahren,
            json.dumps(asdict(konfiguration.discovery), default=str),
            vorher.ereignisanzahl,
            vorher.fallanzahl,
            vorher.aktivitaetsanzahl,
            vorher.variantenanzahl,
            nachher.ereignisanzahl,
            nachher.fallanzahl,
            nachher.aktivitaetsanzahl,
            nachher.variantenanzahl,
            json.dumps(asdict(vorschau.discovery.statistik)),
            json.dumps([asdict(wert) for wert in vorschau.discovery.warnungen]),
            vorschau.pm4py_version,
            pfade["summary"],
            pfade["varianten"],
            pfade["dfg"],
            pfade["modell"],
            pfade["modell_svg"] if vorschau.discovery.modell_svg else "",
            ProcessMiningStatus.AUSGEFUEHRT,
            jetzt,
            jetzt,
        )
