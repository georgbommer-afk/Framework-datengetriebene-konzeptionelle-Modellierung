"""Algorithmus 7: validierte Aggregation von A_D, KPIs, optional A_C und A_V."""

import hashlib
import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, cast
from uuid import UUID

import pandas as pd

from framework_mvp.application.datenqualitaet_service import DatenqualitaetService
from framework_mvp.application.ergebnisaggregation.kpi import (
    KpiDatenbasis,
    berechne_ausgewaehlte_kpis,
    kpi_definition,
)
from framework_mvp.application.ergebnisaggregation.sollprozess import token_replay
from framework_mvp.application.ergebnisaggregation.zeitvergleich import zeitvergleich_berechnen
from framework_mvp.application.ports.ergebnisaggregation_repository import (
    ErgebnisaggregationRepository,
)
from framework_mvp.application.process_mining_service import ProcessMiningService
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.application.transformations_service import TransformationsService
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.domain.models import (
    Aggregationsstatus,
    Aktivitaetsmapping,
    ConformanceErgebnis,
    Datenartefakt,
    Ergebnisaggregation,
    KpiErgebnis,
    KpiKonfiguration,
    ProcessMiningAnalyse,
    Projekt,
    Qualitaetsfreigabe,
    SollmodellVorschau,
    Sollzeitdaten,
    ZeitvergleichErgebnis,
    ZeitvergleichKonfiguration,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.infrastructure.importartefakte import ImportartefaktSpeicher

AG_ARTEFAKTVERSION = 1
AG_ARTEFAKTART = "aggregierte_analyseergebnisse_a_g"


def _normalisieren(wert: Any) -> Any:
    if isinstance(wert, bytes):
        return {"sha256": hashlib.sha256(wert).hexdigest(), "bytes": len(wert)}
    if isinstance(wert, (UUID, datetime, date, Enum)):
        return str(wert.value if isinstance(wert, Enum) else wert)
    if is_dataclass(wert):
        return _normalisieren(asdict(cast(Any, wert)))
    if isinstance(wert, dict):
        return {str(name): _normalisieren(inhalt) for name, inhalt in wert.items()}
    if isinstance(wert, (tuple, list)):
        return [_normalisieren(inhalt) for inhalt in wert]
    return wert


def _json_bytes(wert: Any, *, eingerueckt: bool = True) -> bytes:
    return json.dumps(
        _normalisieren(wert),
        ensure_ascii=False,
        sort_keys=True,
        indent=2 if eingerueckt else None,
        separators=None if eingerueckt else (",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(wert: Any) -> str:
    return hashlib.sha256(_json_bytes(wert, eingerueckt=False)).hexdigest()


@dataclass(frozen=True, slots=True)
class Aggregationsgrundlage:
    """Erneut validierte, zusammengehörige und tief kopierte Eingangsartefakte."""

    projekt: Projekt
    untersuchungsauftrag_sha256: str
    datenprofil_sha256: str
    profilreferenzen: tuple[dict[str, Any], ...]
    profilwerte: dict[str, float]
    freigabe: Qualitaetsfreigabe
    zwischendatensatz: Any
    zwischendaten: pd.DataFrame
    event_log: pd.DataFrame
    analyse: ProcessMiningAnalyse
    discovery_ergebnisse: dict[str, Any]
    prozessmodell: bytes
    prozessmodell_sha256: str
    discovery_ergebnisse_sha256: str
    eingabefingerabdruck: str


@dataclass(frozen=True, slots=True)
class Aggregationsvorschau:
    """Ungespeichertes A_G, gebunden an Eingaben und alle bestätigten Konfigurationen."""

    grundlage: Aggregationsgrundlage
    kpi_konfigurationen: tuple[KpiKonfiguration, ...]
    kpi_ergebnisse: tuple[KpiErgebnis, ...]
    sollmodell: SollmodellVorschau | None
    aktivitaetsmapping: Aktivitaetsmapping | None
    conformance_ergebnis: ConformanceErgebnis | None
    sollzeitdaten: Sollzeitdaten | None
    zeitvergleich_konfiguration: ZeitvergleichKonfiguration | None
    zeitvergleich_ergebnis: ZeitvergleichErgebnis | None
    warnungen: tuple[str, ...]
    konfigurationsfingerabdruck: str


class ErgebnisaggregationService:
    """Aggregiert ausschließlich die aktive, vollständig validierte Artefaktkette."""

    def __init__(
        self,
        repository: ErgebnisaggregationRepository,
        projekt_service: ProjektService,
        transformations_service: TransformationsService,
        qualitaet_service: DatenqualitaetService,
        process_mining_service: ProcessMiningService,
        artefakte: ImportartefaktSpeicher,
    ) -> None:
        self._repository = repository
        self._projekte = projekt_service
        self._transformationen = transformations_service
        self._qualitaet = qualitaet_service
        self._process_mining = process_mining_service
        self._artefakte = artefakte

    def grundlage_laden(
        self,
        projekt_id: UUID,
        freigabe_id: UUID,
        analyse_id: UUID,
    ) -> Aggregationsgrundlage:
        """Leitet U, R, T und E* aus der aktiven Kette ab und validiert P sowie A_D neu."""
        projekt = self._projekte.projekt_laden(projekt_id)
        if projekt is None:
            raise Domaenenfehler("Das aktive Projekt wurde nicht gefunden.")
        for kpi_id in projekt.untersuchungsauftrag.ausgewaehlte_kpi_ids:
            try:
                kpi_definition(kpi_id)
            except KeyError as fehler:
                raise Importintegritaetsfehler(
                    "U enthält eine nicht in A.7 bis A.10 definierte KPI-ID."
                ) from fehler
        freigabe, event_log = self._qualitaet.freigabe_laden(freigabe_id)
        if freigabe.projekt_id != projekt_id:
            raise Domaenenfehler("Die aktive E*-Freigabe gehört nicht zum aktiven Projekt.")
        analyse, a_d, prozessmodell = self._process_mining.uebergabe_laden(
            analyse_id, projekt_id, freigabe_id
        )
        if analyse.event_log_id != freigabe.event_log_id:
            raise Importintegritaetsfehler("P und A_D gehören nicht zum freigegebenen E*.")
        try:
            parameter = json.loads(analyse.parameter_json)
            a_d_sha256 = str(parameter["a_d_sha256"])
            p_referenz = a_d["prozessmodell_p"]
            p_sha256 = str(p_referenz["sha256"])
        except (json.JSONDecodeError, KeyError, TypeError) as fehler:
            raise Importintegritaetsfehler(
                "Die Prüfsummenreferenzen von P und A_D fehlen."
            ) from fehler
        if hashlib.sha256(prozessmodell).hexdigest() != p_sha256:
            raise Importintegritaetsfehler("Die erneut geladene Prüfsumme von P ist ungültig.")
        datensatz, zwischendaten = self._transformationen.zwischendatensatz_laden(
            freigabe.zwischendatensatz_id
        )
        if (
            datensatz.projekt_id != projekt_id
            or datensatz.sha256 != freigabe.zwischendatensatz_sha256
        ):
            raise Importintegritaetsfehler("T und E* besitzen keine übereinstimmende Lineage.")
        profil_snapshot: list[dict[str, Any]] = []
        profilwerte: dict[str, float] = {}
        for import_id in datensatz.import_ids:
            geladen = self._transformationen.import_laden(import_id)
            if geladen is None or geladen.importvorgang.projekt_id != projekt_id:
                raise Importintegritaetsfehler("Ein in T referenziertes Datenprofil R fehlt.")
            profil = geladen.profil
            snapshot = {
                "import_id": str(import_id),
                "raw_sha256": geladen.importvorgang.sha256,
                "profil_version": profil.profil_version,
                "datei_pruefsumme": profil.datei_pruefsumme,
                "gesamtprofil": profil.gesamtprofil,
            }
            snapshot["profil_sha256"] = _sha(snapshot)
            profil_snapshot.append(snapshot)
            gesamt = profil.gesamtprofil
            profilwerte[f"{import_id}:__gesamt__:zeilen"] = float(gesamt.get("zeilen", 0))
            for spalte in gesamt.get("spaltenprofile", []):
                numerisch = spalte.get("numerisch")
                if not isinstance(numerisch, dict):
                    continue
                for kennzahl, wert in numerisch.items():
                    if isinstance(wert, (int, float)):
                        profilwerte[f"{import_id}:{spalte['spaltenname']}:{kennzahl}"] = float(wert)
        u_sha256 = _sha(projekt.untersuchungsauftrag)
        r_sha256 = _sha(profil_snapshot)
        fingerabdruck = _sha(
            {
                "projekt_id": projekt_id,
                "spezifikations_id": projekt_id,
                "untersuchungsauftrag_sha256": u_sha256,
                "projekt_geaendert_am": projekt.geaendert_am,
                "datenprofil_sha256": r_sha256,
                "zwischendatensatz_id": datensatz.zwischendatensatz_id,
                "zwischendatensatz_sha256": datensatz.sha256,
                "freigabe_id": freigabe.freigabe_id,
                "freigabe_report_sha256": freigabe.report_sha256,
                "kettenfingerabdruck": freigabe.kettenfingerabdruck,
                "event_log_id": freigabe.event_log_id,
                "event_log_sha256": freigabe.event_log_sha256,
                "analyse_id": analyse.analyse_id,
                "prozessmodell_pfad": p_referenz["relativer_pfad"],
                "prozessmodell_sha256": p_sha256,
                "discovery_ergebnisse_pfad": analyse.relativer_ergebnis_pfad,
                "discovery_ergebnisse_sha256": a_d_sha256,
            }
        )
        return Aggregationsgrundlage(
            projekt,
            u_sha256,
            r_sha256,
            tuple(profil_snapshot),
            profilwerte,
            freigabe,
            datensatz,
            zwischendaten.copy(deep=True),
            event_log.copy(deep=True),
            analyse,
            a_d,
            bytes(prozessmodell),
            p_sha256,
            a_d_sha256,
            fingerabdruck,
        )

    @staticmethod
    def _konfigurationsfingerabdruck(
        kpi_konfigurationen: tuple[KpiKonfiguration, ...],
        sollmodell: SollmodellVorschau | None,
        aktivitaetsmapping: Aktivitaetsmapping | None,
        conformance_ausfuehren: bool,
        sollzeitdaten: Sollzeitdaten | None,
        zeitvergleich_konfiguration: ZeitvergleichKonfiguration | None,
        zeitvergleich_ausfuehren: bool,
    ) -> str:
        return _sha(
            {
                "kpi_konfigurationen": kpi_konfigurationen,
                "sollmodell": sollmodell,
                "aktivitaetsmapping": aktivitaetsmapping,
                "conformance_ausfuehren": conformance_ausfuehren,
                "sollzeitdaten": sollzeitdaten,
                "zeitvergleich_konfiguration": zeitvergleich_konfiguration,
                "zeitvergleich_ausfuehren": zeitvergleich_ausfuehren,
            }
        )

    def konfigurationsfingerabdruck(
        self,
        *,
        kpi_konfigurationen: tuple[KpiKonfiguration, ...],
        sollmodell: SollmodellVorschau | None,
        aktivitaetsmapping: Aktivitaetsmapping | None,
        conformance_ausfuehren: bool,
        sollzeitdaten: Sollzeitdaten | None,
        zeitvergleich_konfiguration: ZeitvergleichKonfiguration | None,
        zeitvergleich_ausfuehren: bool,
    ) -> str:
        """Erlaubt der UI, geänderte Entscheidungen vor dem Speichern zu erkennen."""
        return self._konfigurationsfingerabdruck(
            kpi_konfigurationen,
            sollmodell,
            aktivitaetsmapping,
            conformance_ausfuehren,
            sollzeitdaten,
            zeitvergleich_konfiguration,
            zeitvergleich_ausfuehren,
        )

    def vorschau(
        self,
        *,
        projekt_id: UUID,
        freigabe_id: UUID,
        analyse_id: UUID,
        kpi_konfigurationen: tuple[KpiKonfiguration, ...] = (),
        sollmodell: SollmodellVorschau | None = None,
        aktivitaetsmapping: Aktivitaetsmapping | None = None,
        conformance_ausfuehren: bool = False,
        sollzeitdaten: Sollzeitdaten | None = None,
        sollzeit_tabelle: pd.DataFrame | None = None,
        zeitvergleich_konfiguration: ZeitvergleichKonfiguration | None = None,
        zeitvergleich_ausfuehren: bool = False,
    ) -> Aggregationsvorschau:
        """Berechnet die drei unabhängigen Bestandteile auf tiefen Arbeitskopien."""
        basis = self.grundlage_laden(projekt_id, freigabe_id, analyse_id)
        t_original = basis.zwischendaten.copy(deep=True)
        e_original = basis.event_log.copy(deep=True)
        ausgewaehlt = basis.projekt.untersuchungsauftrag.ausgewaehlte_kpi_ids
        fremde_kpis = {wert.kpi_id for wert in kpi_konfigurationen} - set(ausgewaehlt)
        if fremde_kpis:
            raise Domaenenfehler(
                "Schritt 7 darf die in U gespeicherte KPI-Auswahl nicht erweitern."
            )
        kpi_basis = KpiDatenbasis(
            basis.zwischendaten.copy(deep=True),
            basis.event_log.copy(deep=True),
            dict(basis.profilwerte),
            {
                Datenartefakt.DATENPROFIL_R: {
                    "sha256": basis.datenprofil_sha256,
                },
                Datenartefakt.ZWISCHENDATENSATZ_T: {
                    "id": str(basis.zwischendatensatz.zwischendatensatz_id),
                    "sha256": basis.zwischendatensatz.sha256,
                },
                Datenartefakt.EVENT_LOG_E_STERN: {
                    "id": str(basis.freigabe.event_log_id),
                    "sha256": basis.freigabe.event_log_sha256,
                },
            },
        )
        kpis = berechne_ausgewaehlte_kpis(ausgewaehlt, kpi_konfigurationen, kpi_basis)
        warnungen: list[str] = []
        conformance = None
        if conformance_ausfuehren:
            if sollmodell is None or aktivitaetsmapping is None:
                warnungen.append(
                    "Conformance Checking wurde nicht berechnet: bestätigtes P_Soll "
                    "oder Aktivitätsmapping fehlt."
                )
            elif (
                sollmodell.metadaten.projekt_id != projekt_id
                or aktivitaetsmapping.projekt_id != projekt_id
            ):
                warnungen.append(
                    "Conformance Checking wurde nicht berechnet: P_Soll oder Mapping "
                    "gehört zu einem anderen Projekt."
                )
            else:
                try:
                    conformance = token_replay(
                        event_log=basis.event_log.copy(deep=True),
                        sollmodell=sollmodell,
                        mapping=aktivitaetsmapping,
                    )
                except Domaenenfehler as fehler:
                    warnungen.append(f"Conformance Checking wurde nicht berechnet: {fehler}")
        zeitvergleich = None
        if zeitvergleich_ausfuehren:
            if zeitvergleich_konfiguration is None:
                warnungen.append(
                    "Soll-Ist-Zeitauswertung wurde nicht berechnet: bestätigte "
                    "Spaltenrollen fehlen."
                )
            else:
                if zeitvergleich_konfiguration.sollquelle == "T":
                    soll_tabelle = basis.zwischendaten.copy(deep=True)
                elif zeitvergleich_konfiguration.sollquelle == "E*":
                    soll_tabelle = basis.event_log.copy(deep=True)
                elif (
                    sollzeitdaten is not None
                    and sollzeit_tabelle is not None
                    and sollzeitdaten.projekt_id == projekt_id
                ):
                    soll_tabelle = sollzeit_tabelle.copy(deep=True)
                else:
                    soll_tabelle = None
                if soll_tabelle is None:
                    warnungen.append(
                        "Soll-Ist-Zeitauswertung wurde nicht berechnet: Die bestätigte "
                        "Sollzeitquelle fehlt."
                    )
                else:
                    try:
                        zeitvergleich = zeitvergleich_berechnen(
                            soll_daten=soll_tabelle,
                            event_log=basis.event_log.copy(deep=True),
                            konfiguration=zeitvergleich_konfiguration,
                        )
                    except Domaenenfehler as fehler:
                        warnungen.append(f"Soll-Ist-Zeitauswertung wurde nicht berechnet: {fehler}")
        fingerabdruck = self._konfigurationsfingerabdruck(
            kpi_konfigurationen,
            sollmodell,
            aktivitaetsmapping,
            conformance_ausfuehren,
            sollzeitdaten,
            zeitvergleich_konfiguration,
            zeitvergleich_ausfuehren,
        )
        pd.testing.assert_frame_equal(basis.zwischendaten, t_original, check_dtype=True)
        pd.testing.assert_frame_equal(basis.event_log, e_original, check_dtype=True)
        return Aggregationsvorschau(
            basis,
            kpi_konfigurationen,
            kpis,
            sollmodell,
            aktivitaetsmapping,
            conformance,
            sollzeitdaten,
            zeitvergleich_konfiguration,
            zeitvergleich,
            tuple(warnungen),
            fingerabdruck,
        )

    def speichern(
        self,
        aggregations_id: UUID,
        vorschau: Aggregationsvorschau,
        *,
        menschlich_bestaetigt: bool,
    ) -> Ergebnisaggregation:
        """Speichert A_G und Detailartefakte atomar, idempotent und bestätigungspflichtig."""
        if not menschlich_bestaetigt:
            raise Domaenenfehler(
                "A_G darf erst nach bewusster menschlicher Bestätigung gespeichert werden."
            )
        vorhanden = self._repository.laden(aggregations_id)
        if vorhanden is not None:
            if (
                vorhanden.eingabefingerabdruck != vorschau.grundlage.eingabefingerabdruck
                or vorhanden.konfigurationsfingerabdruck != vorschau.konfigurationsfingerabdruck
            ):
                raise Domaenenfehler("Die Aggregations-ID gehört bereits zu einem anderen Lauf.")
            return self.laden(aggregations_id)[0]
        basis = self.grundlage_laden(
            vorschau.grundlage.projekt.projekt_id,
            vorschau.grundlage.freigabe.freigabe_id,
            vorschau.grundlage.analyse.analyse_id,
        )
        if basis.eingabefingerabdruck != vorschau.grundlage.eingabefingerabdruck:
            raise Domaenenfehler(
                "U, R, T, E*, P oder A_D wurde seit der Vorschau verändert; eine "
                "Neuberechnung ist erforderlich."
            )
        projekt_id = basis.projekt.projekt_id
        basis_pfad = PurePosixPath("projects") / str(projekt_id) / "aggregation"
        a_g_pfad = (basis_pfad / f"{aggregations_id}.aggregation.json").as_posix()
        artefakte: dict[str, bytes] = {}
        referenzen: dict[str, Any] = {}
        if vorschau.sollmodell is not None:
            modell_id = vorschau.sollmodell.metadaten.sollmodell_id
            original_pfad = (basis_pfad / f"{modell_id}.target.original.pnml").as_posix()
            replay_pfad = (basis_pfad / f"{modell_id}.target.replay.pnml").as_posix()
            meta_pfad = (basis_pfad / f"{modell_id}.target.json").as_posix()
            artefakte[original_pfad] = vorschau.sollmodell.original_pnml
            artefakte[replay_pfad] = vorschau.sollmodell.replay_pnml
            meta = {
                "metadaten": vorschau.sollmodell.metadaten,
                "original": {
                    "relativer_pfad": original_pfad,
                    "sha256": vorschau.sollmodell.metadaten.sha256,
                },
                "normalisiertes_replay_artefakt": {
                    "relativer_pfad": replay_pfad,
                    "sha256": vorschau.sollmodell.replay_sha256,
                },
                "markierungen": {
                    "startplatz": vorschau.sollmodell.startplatz,
                    "endplatz": vorschau.sollmodell.endplatz,
                    "abgeleitet": vorschau.sollmodell.markierungen_abgeleitet,
                    "ableitung_menschlich_bestaetigt": (
                        vorschau.sollmodell.markierungsableitung_bestaetigt
                    ),
                },
                "workflow_netz": vorschau.sollmodell.workflow_netz,
                "sound": vorschau.sollmodell.sound,
                "sichtbare_transitionen": vorschau.sollmodell.sichtbare_transitionen,
                "warnungen": vorschau.sollmodell.warnungen,
            }
            artefakte[meta_pfad] = _json_bytes(meta)
            referenzen["prozessmodell_p_soll"] = {
                "sollmodell_id": str(modell_id),
                "relativer_metadaten_pfad": meta_pfad,
                "original_pnml_pfad": original_pfad,
                "original_sha256": vorschau.sollmodell.metadaten.sha256,
                "replay_pnml_pfad": replay_pfad,
                "replay_sha256": vorschau.sollmodell.replay_sha256,
            }
        if vorschau.aktivitaetsmapping is not None:
            mapping_pfad = (
                basis_pfad / f"{vorschau.aktivitaetsmapping.mapping_id}.activity-mapping.json"
            ).as_posix()
            artefakte[mapping_pfad] = _json_bytes(vorschau.aktivitaetsmapping)
            referenzen["aktivitaetsmapping"] = {
                "mapping_id": str(vorschau.aktivitaetsmapping.mapping_id),
                "relativer_pfad": mapping_pfad,
            }
        if vorschau.conformance_ergebnis is not None:
            ac = vorschau.conformance_ergebnis
            ac_json_pfad = (basis_pfad / f"{ac.conformance_id}.conformance.json").as_posix()
            ac_csv_pfad = (basis_pfad / f"{ac.conformance_id}.conformance-cases.csv").as_posix()
            ac_struktur = {
                "artefaktart": "conformance_ergebnisse_a_c",
                "event_log_referenz": {
                    "freigabe_id": str(basis.freigabe.freigabe_id),
                    "event_log_id": str(basis.freigabe.event_log_id),
                    "sha256": basis.freigabe.event_log_sha256,
                },
                "sollmodell_referenz": referenzen.get("prozessmodell_p_soll"),
                "aktivitaetsmapping_referenz": referenzen.get("aktivitaetsmapping"),
                "ergebnis": ac,
            }
            artefakte[ac_json_pfad] = _json_bytes(ac_struktur)
            artefakte[ac_csv_pfad] = (
                pd.DataFrame([asdict(wert) for wert in ac.fallbezogene_diagnosen])
                .to_csv(index=False)
                .encode("utf-8")
            )
            referenzen["conformance_ergebnisse_a_c"] = {
                "conformance_id": str(ac.conformance_id),
                "relativer_pfad": ac_json_pfad,
                "detail_csv_pfad": ac_csv_pfad,
            }
        if vorschau.sollzeitdaten is not None:
            endung = vorschau.sollzeitdaten.dateityp.lower()
            sollzeit_pfad = (
                basis_pfad / f"{vorschau.sollzeitdaten.sollzeitdaten_id}.target-times.{endung}"
            ).as_posix()
            artefakte[sollzeit_pfad] = vorschau.sollzeitdaten.originalbytes
            referenzen["sollzeitdaten"] = {
                "sollzeitdaten_id": str(vorschau.sollzeitdaten.sollzeitdaten_id),
                "originaldateiname": vorschau.sollzeitdaten.originaldateiname,
                "relativer_pfad": sollzeit_pfad,
                "sha256": vorschau.sollzeitdaten.sha256,
            }
        if vorschau.zeitvergleich_ergebnis is not None:
            av = vorschau.zeitvergleich_ergebnis
            av_json_pfad = (basis_pfad / f"{av.auswertungs_id}.deviations.json").as_posix()
            av_csv_pfad = (basis_pfad / f"{av.auswertungs_id}.deviations.csv").as_posix()
            av_struktur = {
                "artefaktart": "potenzielle_verbesserungspotenziale_a_v",
                "quellreferenzen": {
                    "event_log_id": str(basis.freigabe.event_log_id),
                    "event_log_sha256": basis.freigabe.event_log_sha256,
                    "zwischendatensatz_id": str(basis.zwischendatensatz.zwischendatensatz_id),
                    "zwischendatensatz_sha256": basis.zwischendatensatz.sha256,
                    "sollzeitdaten": referenzen.get("sollzeitdaten"),
                },
                "ergebnis": av,
                "hinweis": (
                    "Direkte Abweichungen ohne automatische fachliche, kausale oder "
                    "maßnahmenbezogene Bewertung."
                ),
            }
            artefakte[av_json_pfad] = _json_bytes(av_struktur)
            artefakte[av_csv_pfad] = (
                pd.DataFrame([asdict(wert) for wert in av.abweichungen])
                .to_csv(index=False)
                .encode("utf-8")
            )
            referenzen["potenzielle_verbesserungspotenziale_a_v"] = {
                "auswertungs_id": str(av.auswertungs_id),
                "relativer_pfad": av_json_pfad,
                "detail_csv_pfad": av_csv_pfad,
            }
        pruefsummen = {
            pfad: hashlib.sha256(inhalt).hexdigest() for pfad, inhalt in artefakte.items()
        }
        for referenz in referenzen.values():
            if isinstance(referenz, dict):
                hauptpfad = referenz.get("relativer_pfad")
                if hauptpfad in pruefsummen:
                    referenz["sha256"] = pruefsummen[hauptpfad]
                detailpfad = referenz.get("detail_csv_pfad")
                if detailpfad in pruefsummen:
                    referenz["detail_csv_sha256"] = pruefsummen[detailpfad]
                metadatenpfad = referenz.get("relativer_metadaten_pfad")
                if metadatenpfad in pruefsummen:
                    referenz["metadaten_sha256"] = pruefsummen[metadatenpfad]
                for schluessel in ("relativer_pfad", "relativer_metadaten_pfad", "detail_csv_pfad"):
                    pfad = referenz.get(schluessel)
                    if pfad in pruefsummen:
                        referenz[f"{schluessel}_sha256"] = pruefsummen[pfad]
        a_g = self._a_g_struktur(aggregations_id, vorschau, referenzen, pruefsummen)
        a_g["gesamtpruefsumme"] = _sha(a_g)
        a_g_bytes = _json_bytes(a_g)
        a_g_sha256 = hashlib.sha256(a_g_bytes).hexdigest()
        jetzt = datetime.now(UTC)
        aggregation = Ergebnisaggregation(
            aggregations_id,
            projekt_id,
            projekt_id,
            basis.freigabe.freigabe_id,
            basis.freigabe.event_log_id,
            basis.analyse.analyse_id,
            basis.eingabefingerabdruck,
            vorschau.konfigurationsfingerabdruck,
            a_g_pfad,
            a_g_sha256,
            Aggregationsstatus.GESPEICHERT,
            jetzt,
        )
        erzeugt = []
        try:
            for pfad, inhalt in artefakte.items():
                erzeugt.append(self._artefakte.artefakt_speichern(pfad, inhalt))
            erzeugt.append(self._artefakte.artefakt_speichern(a_g_pfad, a_g_bytes))
            self._repository.speichern(aggregation)
        except Exception:
            for artefakt in reversed(erzeugt):
                self._artefakte.neu_erstelltes_artefakt_entfernen(artefakt)
            raise
        self.laden(aggregations_id)
        return aggregation

    def _a_g_struktur(
        self,
        aggregations_id: UUID,
        vorschau: Aggregationsvorschau,
        referenzen: dict[str, Any],
        pruefsummen: dict[str, str],
    ) -> dict[str, Any]:
        basis = vorschau.grundlage
        p = basis.discovery_ergebnisse["prozessmodell_p"]
        return {
            "artefaktversion": AG_ARTEFAKTVERSION,
            "artefaktart": AG_ARTEFAKTART,
            "aggregations_id": str(aggregations_id),
            "projekt_id": str(basis.projekt.projekt_id),
            "spezifikations_id": str(basis.projekt.projekt_id),
            "freigabe_id": str(basis.freigabe.freigabe_id),
            "event_log_id": str(basis.freigabe.event_log_id),
            "event_log_sha256": basis.freigabe.event_log_sha256,
            "process_mining_analyse_id": str(basis.analyse.analyse_id),
            "prozessmodell_p": {
                "relativer_pfad": p["relativer_pfad"],
                "sha256": basis.prozessmodell_sha256,
                "prozessnotation": basis.discovery_ergebnisse["prozessnotation"],
            },
            "discovery_ergebnisse_a_d": {
                "analyse_id": str(basis.analyse.analyse_id),
                "relativer_pfad": basis.analyse.relativer_ergebnis_pfad,
                "sha256": basis.discovery_ergebnisse_sha256,
                "bedeutung": "Unveränderte Referenz; A_D wurde weder kopiert noch verändert.",
            },
            "ausgewaehlte_kpi_ids": list(basis.projekt.untersuchungsauftrag.ausgewaehlte_kpi_ids),
            "kpi_definitionen_version": 1,
            "kpi_konfigurationen": vorschau.kpi_konfigurationen,
            "kpi_ergebnisse": vorschau.kpi_ergebnisse,
            "optionale_artefakte": referenzen,
            "pm4py_version": basis.analyse.pm4py_version,
            "lineage": {
                "untersuchungsauftrag_u": {
                    "spezifikations_id": str(basis.projekt.projekt_id),
                    "sha256": basis.untersuchungsauftrag_sha256,
                    "projekt_geaendert_am": basis.projekt.geaendert_am,
                },
                "datenprofil_r": {
                    "sha256": basis.datenprofil_sha256,
                    "profile": basis.profilreferenzen,
                },
                "zwischendatensatz_t": {
                    "id": str(basis.zwischendatensatz.zwischendatensatz_id),
                    "sha256": basis.zwischendatensatz.sha256,
                },
                "event_log_e_stern": {
                    "freigabe_id": str(basis.freigabe.freigabe_id),
                    "freigabe_report_sha256": basis.freigabe.report_sha256,
                    "kettenfingerabdruck": basis.freigabe.kettenfingerabdruck,
                    "event_log_id": str(basis.freigabe.event_log_id),
                    "sha256": basis.freigabe.event_log_sha256,
                },
                "prozessmodell_p": {
                    "pfad": p["relativer_pfad"],
                    "sha256": basis.prozessmodell_sha256,
                },
                "discovery_ergebnisse_a_d": {
                    "pfad": basis.analyse.relativer_ergebnis_pfad,
                    "sha256": basis.discovery_ergebnisse_sha256,
                },
                "eingabefingerabdruck": basis.eingabefingerabdruck,
                "konfigurationsfingerabdruck": vorschau.konfigurationsfingerabdruck,
            },
            "warnungen": vorschau.warnungen,
            "artefakt_pruefsummen": pruefsummen,
            "erstellt_am": datetime.now(UTC),
        }

    def laden(self, aggregations_id: UUID) -> tuple[Ergebnisaggregation, dict[str, Any]]:
        """Lädt A_G erst nach erneuter Prüfung aller Referenzen, Dateien und Prüfsummen."""
        aggregation = self._repository.laden(aggregations_id)
        if aggregation is None:
            raise Importintegritaetsfehler("Die Ergebnisaggregation wurde nicht gefunden.")
        inhalt = self._artefakte.lesen(aggregation.relativer_aggregations_pfad)
        if hashlib.sha256(inhalt).hexdigest() != aggregation.aggregations_sha256:
            raise Importintegritaetsfehler("Die Dateiprüfsumme von A_G ist ungültig.")
        try:
            a_g = json.loads(inhalt)
            gesamtpruefsumme = a_g.pop("gesamtpruefsumme")
        except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError) as fehler:
            raise Importintegritaetsfehler(
                "A_G ist kein gültiges Aggregationsartefakt."
            ) from fehler
        if (
            a_g.get("artefaktversion") != AG_ARTEFAKTVERSION
            or a_g.get("artefaktart") != AG_ARTEFAKTART
            or a_g.get("aggregations_id") != str(aggregation.aggregations_id)
            or a_g.get("projekt_id") != str(aggregation.projekt_id)
            or a_g.get("freigabe_id") != str(aggregation.freigabe_id)
            or a_g.get("event_log_id") != str(aggregation.event_log_id)
            or a_g.get("process_mining_analyse_id") != str(aggregation.analyse_id)
            or _sha(a_g) != gesamtpruefsumme
        ):
            raise Importintegritaetsfehler("Metadaten oder Gesamtprüfsumme von A_G sind ungültig.")
        basis = self.grundlage_laden(
            aggregation.projekt_id,
            aggregation.freigabe_id,
            aggregation.analyse_id,
        )
        lineage = a_g.get("lineage", {})
        if (
            basis.eingabefingerabdruck != aggregation.eingabefingerabdruck
            or lineage.get("eingabefingerabdruck") != aggregation.eingabefingerabdruck
            or lineage.get("konfigurationsfingerabdruck") != aggregation.konfigurationsfingerabdruck
            or a_g["prozessmodell_p"].get("sha256") != basis.prozessmodell_sha256
            or a_g["discovery_ergebnisse_a_d"].get("sha256") != basis.discovery_ergebnisse_sha256
        ):
            raise Importintegritaetsfehler(
                "Die vollständige Lineage von A_G stimmt nicht mehr mit U, R, T, E*, "
                "P und A_D überein."
            )
        for pfad, erwartet in a_g.get("artefakt_pruefsummen", {}).items():
            if hashlib.sha256(self._artefakte.lesen(str(pfad))).hexdigest() != erwartet:
                raise Importintegritaetsfehler(
                    "Die Prüfsumme eines von A_G referenzierten Detailartefakts ist ungültig."
                )
        a_g["gesamtpruefsumme"] = gesamtpruefsumme
        return aggregation, a_g

    def a_g_download_laden(self, aggregations_id: UUID) -> bytes:
        """Liefert nach vollständiger Validierung exakt die gespeicherten A_G-Bytes."""
        aggregation, _ = self.laden(aggregations_id)
        return self._artefakte.lesen(aggregation.relativer_aggregations_pfad)

    def aggregationen_fuer_aktive_analyse(
        self, projekt_id: UUID, freigabe_id: UUID, analyse_id: UUID
    ) -> list[Ergebnisaggregation]:
        """Bietet nur aktuell erneut validierbare A_G derselben Kette an."""
        self.grundlage_laden(projekt_id, freigabe_id, analyse_id)
        ergebnis = []
        for wert in self._repository.fuer_analyse(projekt_id, analyse_id):
            if wert.freigabe_id != freigabe_id:
                continue
            try:
                geladen, _ = self.laden(wert.aggregations_id)
            except (Domaenenfehler, Importintegritaetsfehler):
                continue
            ergebnis.append(geladen)
        return ergebnis

    def uebergabe_schritt8(
        self,
        aggregations_id: UUID,
        projekt_id: UUID,
        freigabe_id: UUID,
        analyse_id: UUID,
    ) -> tuple[bytes, dict[str, Any]]:
        """Übergibt ausschließlich das unveränderte P aus Schritt 6 und validiertes A_G."""
        aggregation, a_g = self.laden(aggregations_id)
        if (
            aggregation.projekt_id != projekt_id
            or aggregation.freigabe_id != freigabe_id
            or aggregation.analyse_id != analyse_id
        ):
            raise Domaenenfehler("P und A_G gehören nicht zur aktiven zentralen Artefaktkette.")
        basis = self.grundlage_laden(projekt_id, freigabe_id, analyse_id)
        return bytes(basis.prozessmodell), a_g
