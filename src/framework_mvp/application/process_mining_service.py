"""Algorithmus 6: vollständiger DFG sowie reproduzierbare Prozessentdeckung aus E*."""

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

from framework_mvp.application.aktive_lineage_service import AktiveLineageService, LineageEndpunkt
from framework_mvp.application.datenqualitaet_service import DatenqualitaetService
from framework_mvp.application.ports.process_mining_repository import ProcessMiningRepository
from framework_mvp.application.process_mining import (
    GraphvizStatus,
    Pm4pyAdapter,
    berechne_dfg,
    berechne_varianten,
    validiere_svg_bytes,
)
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    DfgErgebnis,
    DiscoveryErgebnisse,
    DiscoveryKonfiguration,
    DiscoveryVerfahren,
    ProcessMiningAnalyse,
    ProcessMiningStatus,
    Prozessnotation,
    Qualitaetsfreigabe,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.infrastructure.importartefakte import ImportartefaktSpeicher

PROCESS_MINING_ARTEFAKTVERSION = 2
PROCESS_MINING_ARTEFAKTART = "discovery_ergebnisse_a_d_und_prozessmodell_p"


@dataclass(frozen=True, slots=True)
class ProcessMiningVorschau:
    """Vorschau aus exakt einem unveränderten, erneut validierten E*."""

    freigabe_id: UUID
    projekt_id: UUID
    event_log_id: UUID
    event_log_sha256: str
    konfiguration: DiscoveryKonfiguration
    dfg: DfgErgebnis
    discovery: DiscoveryErgebnisse
    dfg_svg: bytes | None
    pm4py_version: str
    cache_schluessel: str


class ProcessMiningService:
    """Erzeugt ausschließlich den DFG sowie P und A_D aus einer gültigen E*-Freigabe."""

    def __init__(
        self,
        repository: ProcessMiningRepository,
        qualitaet_service: DatenqualitaetService,
        artefakte: ImportartefaktSpeicher,
        adapter: Pm4pyAdapter | None = None,
        aktive_lineage: AktiveLineageService | None = None,
    ) -> None:
        self._repository = repository
        self._qualitaet = qualitaet_service
        self._artefakte = artefakte
        self._adapter = adapter or Pm4pyAdapter()
        self._aktive_lineage = aktive_lineage

    def grundlage_laden(
        self, freigabe_id: UUID, projekt_id: UUID | None = None
    ) -> tuple[Qualitaetsfreigabe, pd.DataFrame]:
        """Lädt ausschließlich ein aktuell gültiges E* und prüft optional das aktive Projekt."""
        freigabe, daten = self._qualitaet.freigabe_laden(freigabe_id)
        if projekt_id is not None and freigabe.projekt_id != projekt_id:
            raise Domaenenfehler("Die aktive E*-Freigabe gehört nicht zum aktuellen Projekt.")
        self._adapter.arbeitskopie(daten)
        return freigabe, daten.copy(deep=True)

    def vorschau(
        self,
        freigabe_id: UUID,
        konfiguration: DiscoveryKonfiguration,
    ) -> ProcessMiningVorschau:
        """Berechnet DFG stets vollständig; k wirkt nur auf die Prozessentdeckung."""
        freigabe, daten = self.grundlage_laden(freigabe_id)
        unveraendert = daten.copy(deep=True)
        dfg = berechne_dfg(daten)
        discovery = self._adapter.entdecken(daten.copy(deep=True), konfiguration).ergebnisse
        dfg_svg, dfg_warnung = self._adapter.dfg_visualisieren(dfg)
        if dfg_warnung is not None:
            discovery = replace(discovery, warnungen=(*discovery.warnungen, dfg_warnung))
        pd.testing.assert_frame_equal(daten, unveraendert, check_dtype=True)
        schluessel = self.cache_schluessel(
            freigabe.event_log_sha256,
            freigabe_id,
            konfiguration,
            self._adapter.version,
        )
        return ProcessMiningVorschau(
            freigabe_id,
            freigabe.projekt_id,
            freigabe.event_log_id,
            freigabe.event_log_sha256,
            konfiguration,
            dfg,
            discovery,
            dfg_svg,
            self._adapter.version,
            schluessel,
        )

    def graphviz_status(self) -> GraphvizStatus:
        """Liefert den technischen Visualisierungsstatus ohne Discovery."""
        return self._adapter.graphviz_status()

    @staticmethod
    def cache_schluessel(
        event_log_sha256: str,
        freigabe_id: UUID,
        konfiguration: DiscoveryKonfiguration,
        pm4py_version: str,
    ) -> str:
        """Bindet eine ungespeicherte Vorschau an E*, k, Notation und PM4Py-Version."""
        basis = json.dumps(
            {
                "event_log_sha256": event_log_sha256,
                "freigabe_id": str(freigabe_id),
                "schwellwert_k": konfiguration.schwellwert_k,
                "miner_variante": konfiguration.miner_variante.value,
                "prozessnotation": konfiguration.prozessnotation.value,
                "pm4py_version": pm4py_version,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(basis).hexdigest()

    def speichern(
        self,
        analyse_id: UUID,
        freigabe_id: UUID,
        konfiguration: DiscoveryKonfiguration,
        vorschau: ProcessMiningVorschau,
    ) -> ProcessMiningAnalyse:
        """Speichert P und A_D atomar, idempotent und ohne Event-Log-Arbeitskopie."""
        vorhanden = self._repository.laden(analyse_id)
        if vorhanden is not None:
            analyse, ergebnis = self.laden(analyse_id)
            if (
                analyse.qualitaetspruefung_id != freigabe_id
                or ergebnis.get("schwellwert_k") != konfiguration.schwellwert_k
                or ergebnis.get("prozessnotation") != konfiguration.prozessnotation.value
            ):
                raise Domaenenfehler("Die Analyse-ID gehört bereits zu einer anderen Analyse.")
            return analyse

        freigabe, daten = self.grundlage_laden(freigabe_id)
        erwartet = self.cache_schluessel(
            freigabe.event_log_sha256,
            freigabe_id,
            konfiguration,
            vorschau.pm4py_version,
        )
        if (
            vorschau.freigabe_id != freigabe_id
            or vorschau.projekt_id != freigabe.projekt_id
            or vorschau.event_log_id != freigabe.event_log_id
            or vorschau.event_log_sha256 != freigabe.event_log_sha256
            or vorschau.konfiguration != konfiguration
            or vorschau.cache_schluessel != erwartet
        ):
            raise Domaenenfehler(
                "Die Vorschau gehört nicht mehr zur aktiven E*-Freigabe oder Konfiguration."
            )
        original = daten.copy(deep=True)
        jetzt = datetime.now(UTC)
        basis = PurePosixPath("projects") / str(freigabe.projekt_id) / "process_mining"
        endung = konfiguration.prozessnotation.dateiendung
        p_pfad = (basis / f"{analyse_id}.model.{endung}").as_posix()
        pt_pfad = (
            p_pfad
            if konfiguration.prozessnotation is Prozessnotation.PROZESSBAUM
            else (basis / f"{analyse_id}.process-tree.ptml").as_posix()
        )
        pfade = {
            "a_d": (basis / f"{analyse_id}.discovery.json").as_posix(),
            "dfg": (basis / f"{analyse_id}.dfg.json").as_posix(),
            "p": p_pfad,
            "pt": pt_pfad,
            "dfg_svg": (basis / f"{analyse_id}.dfg.svg").as_posix(),
            "modell_svg": (basis / f"{analyse_id}.model.svg").as_posix(),
            "prozessbaum_svg": (basis / f"{analyse_id}.process-tree.svg").as_posix(),
        }
        dfg_struktur = self._dfg_struktur(vorschau.dfg)
        dfg_bytes = json.dumps(dfg_struktur, ensure_ascii=False, sort_keys=True, indent=2).encode()
        inhalte: dict[str, bytes] = {
            pfade["dfg"]: dfg_bytes,
            pfade["p"]: vorschau.discovery.prozessmodell,
        }
        if pfade["pt"] != pfade["p"]:
            inhalte[pfade["pt"]] = vorschau.discovery.prozessbaum_ptml
        if vorschau.dfg_svg is not None:
            inhalte[pfade["dfg_svg"]] = vorschau.dfg_svg
        if vorschau.discovery.modell_svg is not None:
            inhalte[pfade["modell_svg"]] = vorschau.discovery.modell_svg
        if (
            vorschau.discovery.prozessbaum_svg is not None
            and pfade["prozessbaum_svg"] != pfade["modell_svg"]
        ):
            inhalte[pfade["prozessbaum_svg"]] = vorschau.discovery.prozessbaum_svg
        for pfad, inhalt in inhalte.items():
            if pfad.endswith(".svg"):
                validiere_svg_bytes(inhalt)
        pruefsummen = {pfad: hashlib.sha256(inhalt).hexdigest() for pfad, inhalt in inhalte.items()}
        a_d = {
            "artefaktversion": PROCESS_MINING_ARTEFAKTVERSION,
            "artefaktart": PROCESS_MINING_ARTEFAKTART,
            "analyse_id": str(analyse_id),
            "projekt_id": str(freigabe.projekt_id),
            "freigabe_id": str(freigabe_id),
            "event_log_id": str(freigabe.event_log_id),
            "event_log_sha256": freigabe.event_log_sha256,
            "schwellwert_k": konfiguration.schwellwert_k,
            "miner_variante": konfiguration.miner_variante.value,
            "prozessnotation": konfiguration.prozessnotation.value,
            "pm4py_version": vorschau.pm4py_version,
            "dfg": {
                "relativer_pfad": pfade["dfg"],
                "sha256": pruefsummen[pfade["dfg"]],
                "daten": dfg_struktur,
            },
            "prozessmodell_p": {
                "relativer_pfad": pfade["p"],
                "sha256": pruefsummen[pfade["p"]],
                "mime_type": konfiguration.prozessnotation.mime_type,
            },
            "interner_prozessbaum": {
                "relativer_pfad": pfade["pt"],
                "sha256": pruefsummen[pfade["pt"]],
            },
            "modellstatistik": asdict(vorschau.discovery.statistik),
            "warnungen": [asdict(wert) for wert in vorschau.discovery.warnungen],
            "visualisierungsartefakte": {
                "dfg_svg": pfade["dfg_svg"] if vorschau.dfg_svg else "",
                "modell_svg": pfade["modell_svg"] if vorschau.discovery.modell_svg else "",
                "prozessbaum_svg": (
                    pfade["prozessbaum_svg"]
                    if vorschau.discovery.prozessbaum_svg is not None
                    else ""
                ),
            },
            "pruefsummen": pruefsummen,
            "erstellt_am": jetzt.isoformat(),
        }
        a_d_bytes = json.dumps(
            a_d, ensure_ascii=False, sort_keys=True, indent=2, default=str
        ).encode()
        a_d_sha256 = hashlib.sha256(a_d_bytes).hexdigest()
        analyse = self._analyse(
            analyse_id,
            freigabe,
            konfiguration,
            vorschau,
            pfade,
            a_d_sha256,
            daten,
            jetzt,
        )
        erzeugt = []
        try:
            for pfad, inhalt in inhalte.items():
                gespeichert = self._artefakte.artefakt_speichern(pfad, inhalt)
                erzeugt.append(gespeichert)
                if hashlib.sha256(self._artefakte.lesen(pfad)).hexdigest() != pruefsummen[pfad]:
                    raise Importintegritaetsfehler(
                        "Eine Process-Mining-Artefaktprüfsumme ist ungültig."
                    )
            erzeugt.append(self._artefakte.artefakt_speichern(pfade["a_d"], a_d_bytes))
            self._repository.speichern(analyse)
        except Exception:
            for artefakt in reversed(erzeugt):
                self._artefakte.neu_erstelltes_artefakt_entfernen(artefakt)
            raise
        pd.testing.assert_frame_equal(daten, original, check_dtype=True)
        if self._aktive_lineage is not None:
            self._aktive_lineage.aktivieren(
                analyse.projekt_id,
                LineageEndpunkt.P_A_D,
                {
                    "aktuelle_freigabe_id": analyse.qualitaetspruefung_id,
                    "freigegebenes_event_log_id": analyse.event_log_id,
                    "aktuelles_event_log_id": analyse.event_log_id,
                    "event_log_id": analyse.event_log_id,
                    "aktuelle_analyse_id": analyse.analyse_id,
                    "aktuelles_prozessmodell_id": analyse.analyse_id,
                    "aktuelle_discovery_ergebnisse_id": analyse.analyse_id,
                },
            )
        return analyse

    def laden(self, analyse_id: UUID) -> tuple[ProcessMiningAnalyse, dict[str, Any]]:
        """Lädt neue Analysen streng; alte Analysen bleiben getrennt kontrolliert lesbar."""
        analyse = self._repository.laden(analyse_id)
        if analyse is None:
            raise Importintegritaetsfehler("Die Process-Mining-Analyse wurde nicht gefunden.")
        parameter = self._json_objekt(analyse.parameter_json, "Analyseparameter")
        if parameter.get("artefaktversion") == PROCESS_MINING_ARTEFAKTVERSION:
            return analyse, self._regulaer_laden(analyse, parameter)
        return analyse, self._legacy_laden(analyse)

    def analysen_fuer_freigabe(
        self, projekt_id: UUID, freigabe_id: UUID
    ) -> list[ProcessMiningAnalyse]:
        """Bietet nur neue, gültige Analysen exakt derselben Freigabe zur Wiederaufnahme an."""
        freigabe, _ = self.grundlage_laden(freigabe_id, projekt_id)
        ergebnis = []
        for analyse in self._repository.fuer_projekt(projekt_id):
            if analyse.qualitaetspruefung_id != freigabe.freigabe_id:
                continue
            try:
                geladen, _ = self.laden(analyse.analyse_id)
                parameter = self._json_objekt(geladen.parameter_json, "Analyseparameter")
                if parameter.get("artefaktversion") == PROCESS_MINING_ARTEFAKTVERSION:
                    ergebnis.append(geladen)
            except (Domaenenfehler, Importintegritaetsfehler):
                continue
        return ergebnis

    def uebergabe_laden(
        self, analyse_id: UUID, projekt_id: UUID, freigabe_id: UUID
    ) -> tuple[ProcessMiningAnalyse, dict[str, Any], bytes]:
        """Übergibt Schritt 7 ausschließlich ein erneut validiertes Paar aus P und A_D."""
        analyse, a_d = self.laden(analyse_id)
        if analyse.projekt_id != projekt_id or analyse.qualitaetspruefung_id != freigabe_id:
            raise Domaenenfehler("P und A_D gehören nicht zum aktiven Projekt und E*.")
        modell = a_d.get("prozessmodell_bytes")
        if not isinstance(modell, bytes):
            raise Importintegritaetsfehler("Die Analyse ist kein reguläres Prozessmodell P.")
        return analyse, a_d, modell

    def fuer_projekt(self, projekt_id: UUID) -> list[ProcessMiningAnalyse]:
        """Listet für technische Legacy-Zugriffe weiterhin alle gespeicherten Analysen."""
        return self._repository.fuer_projekt(projekt_id)

    def _regulaer_laden(
        self, analyse: ProcessMiningAnalyse, parameter: dict[str, Any]
    ) -> dict[str, Any]:
        if analyse.status is not ProcessMiningStatus.AUSGEFUEHRT:
            raise Importintegritaetsfehler("Die Process-Mining-Analyse ist nicht ausgeführt.")
        a_d_bytes = self._artefakte.lesen(analyse.relativer_ergebnis_pfad)
        if hashlib.sha256(a_d_bytes).hexdigest() != parameter.get("a_d_sha256"):
            raise Importintegritaetsfehler("Die Prüfsumme der Discovery-Ergebnisse A_D ist falsch.")
        try:
            a_d = json.loads(a_d_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError) as fehler:
            raise Importintegritaetsfehler(
                "Die Discovery-Ergebnisse A_D sind ungültig."
            ) from fehler
        if (
            a_d.get("artefaktversion") != PROCESS_MINING_ARTEFAKTVERSION
            or a_d.get("artefaktart") != PROCESS_MINING_ARTEFAKTART
            or a_d.get("analyse_id") != str(analyse.analyse_id)
            or a_d.get("projekt_id") != str(analyse.projekt_id)
            or a_d.get("freigabe_id") != str(analyse.qualitaetspruefung_id)
            or a_d.get("event_log_id") != str(analyse.event_log_id)
            or a_d.get("prozessnotation") != parameter.get("prozessnotation")
            or a_d.get("schwellwert_k") != parameter.get("schwellwert_k")
            or a_d.get("miner_variante") != parameter.get("miner_variante")
        ):
            raise Importintegritaetsfehler("Metadaten von P und A_D sind inkonsistent.")
        freigabe, _ = self.grundlage_laden(analyse.qualitaetspruefung_id, analyse.projekt_id)
        if freigabe.event_log_id != analyse.event_log_id or freigabe.event_log_sha256 != a_d.get(
            "event_log_sha256"
        ):
            raise Importintegritaetsfehler(
                "E* und die gespeicherte Analyse gehören nicht zusammen."
            )
        for pfad, erwartet in a_d.get("pruefsummen", {}).items():
            inhalt = self._artefakte.lesen(str(pfad))
            if hashlib.sha256(inhalt).hexdigest() != erwartet:
                raise Importintegritaetsfehler(
                    "Die Prüfsumme eines Process-Mining-Artefakts stimmt nicht."
                )
            if str(pfad).endswith(".svg"):
                validiere_svg_bytes(inhalt)
        p = a_d["prozessmodell_p"]
        pt = a_d["interner_prozessbaum"]
        if p["relativer_pfad"] != analyse.relativer_modell_pfad:
            raise Importintegritaetsfehler("Die Referenz des Prozessmodells P ist inkonsistent.")
        a_d["dfg_daten"] = json.loads(self._artefakte.lesen(a_d["dfg"]["relativer_pfad"]))
        a_d["prozessmodell_bytes"] = self._artefakte.lesen(p["relativer_pfad"])
        a_d["prozessbaum_bytes"] = self._artefakte.lesen(pt["relativer_pfad"])
        a_d["svg_texte"] = {
            name: validiere_svg_bytes(self._artefakte.lesen(pfad))
            for name, pfad in a_d.get("visualisierungsartefakte", {}).items()
            if pfad
        }
        a_d["legacy"] = False
        return a_d

    def _legacy_laden(self, analyse: ProcessMiningAnalyse) -> dict[str, Any]:
        """Bewahrt alte Filter-/Heuristics-Artefakte lesbar, ohne sie als P/A_D fortzusetzen."""
        summary = json.loads(self._artefakte.lesen(analyse.relativer_ergebnis_pfad))
        if summary.get("analyse_id") != str(analyse.analyse_id):
            raise Importintegritaetsfehler("Das Legacy-Artefakt gehört zu einer anderen Analyse.")
        for pfad, erwartet in summary.get("pruefsummen", {}).items():
            inhalt = self._artefakte.lesen(pfad)
            if hashlib.sha256(inhalt).hexdigest() != erwartet:
                raise Importintegritaetsfehler(
                    "Die Prüfsumme eines Legacy-Process-Mining-Artefakts stimmt nicht."
                )
            if pfad.endswith(".svg"):
                validiere_svg_bytes(inhalt)
        if analyse.relativer_dfg_pfad:
            summary["dfg_daten"] = json.loads(self._artefakte.lesen(analyse.relativer_dfg_pfad))
        if analyse.relativer_varianten_pfad:
            summary["varianten"] = pd.read_csv(
                BytesIO(gzip.decompress(self._artefakte.lesen(analyse.relativer_varianten_pfad)))
            ).to_dict(orient="records")
        summary["svg_texte"] = {
            name: validiere_svg_bytes(self._artefakte.lesen(pfad))
            for name, pfad in summary.get("visualisierungsartefakte", {}).items()
            if pfad
        }
        summary["legacy"] = True
        return summary

    @staticmethod
    def _dfg_struktur(dfg: DfgErgebnis) -> dict[str, Any]:
        return {
            "aktivitaeten": dfg.aktivitaeten,
            "aktivitaetshaeufigkeiten": dfg.aktivitaetshaeufigkeiten,
            "kanten": [asdict(wert) for wert in dfg.kanten],
            "startaktivitaeten": dfg.startaktivitaeten,
            "endaktivitaeten": dfg.endaktivitaeten,
        }

    @staticmethod
    def _json_objekt(text: str, bezeichnung: str) -> dict[str, Any]:
        try:
            wert = json.loads(text)
        except json.JSONDecodeError as fehler:
            raise Importintegritaetsfehler(f"{bezeichnung} sind ungültig.") from fehler
        if not isinstance(wert, dict):
            raise Importintegritaetsfehler(f"{bezeichnung} sind ungültig.")
        return wert

    @staticmethod
    def _analyse(
        analyse_id: UUID,
        freigabe: Qualitaetsfreigabe,
        konfiguration: DiscoveryKonfiguration,
        vorschau: ProcessMiningVorschau,
        pfade: dict[str, str],
        a_d_sha256: str,
        daten: pd.DataFrame,
        jetzt: datetime,
    ) -> ProcessMiningAnalyse:
        kennzahlen = berechne_varianten(daten)
        parameter = {
            "artefaktversion": PROCESS_MINING_ARTEFAKTVERSION,
            "a_d_sha256": a_d_sha256,
            "schwellwert_k": konfiguration.schwellwert_k,
            "miner_variante": konfiguration.miner_variante.value,
            "prozessnotation": konfiguration.prozessnotation.value,
        }
        return ProcessMiningAnalyse(
            analyse_id,
            freigabe.projekt_id,
            freigabe.freigabe_id,
            freigabe.event_log_id,
            json.dumps(asdict(konfiguration), ensure_ascii=False, default=str),
            "[]",
            DiscoveryVerfahren.INDUCTIVE_MINER,
            json.dumps(parameter, ensure_ascii=False, sort_keys=True),
            kennzahlen.ereignisanzahl,
            kennzahlen.fallanzahl,
            kennzahlen.aktivitaetsanzahl,
            kennzahlen.variantenanzahl,
            kennzahlen.ereignisanzahl,
            kennzahlen.fallanzahl,
            kennzahlen.aktivitaetsanzahl,
            kennzahlen.variantenanzahl,
            json.dumps(asdict(vorschau.discovery.statistik)),
            json.dumps([asdict(wert) for wert in vorschau.discovery.warnungen]),
            vorschau.pm4py_version,
            pfade["a_d"],
            "",
            pfade["dfg"],
            pfade["p"],
            pfade["modell_svg"] if vorschau.discovery.modell_svg else "",
            ProcessMiningStatus.AUSGEFUEHRT,
            jetzt,
            jetzt,
        )
