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

from framework_mvp.application.aktive_lineage_service import AktiveLineageService, LineageEndpunkt
from framework_mvp.application.datenprofil_service import DatenprofilService
from framework_mvp.application.datenqualitaet_service import DatenqualitaetService
from framework_mvp.application.ergebnisaggregation.kpi import (
    KpiDatenbasis,
    berechne_ausgewaehlte_kpis,
    kpi_definition,
)
from framework_mvp.application.ergebnisaggregation.performance import (
    busy_ratio_berechnen,
    performance_zeitvergleich_berechnen,
)
from framework_mvp.application.ergebnisaggregation.sollprozess import token_replay
from framework_mvp.application.ergebnisaggregation.strukturierte_ergebnisse import (
    analysiere_entitaeten,
    analysiere_ressourcen,
    analysiere_warteschlangen,
    analysiere_zeitbezogene_datenauswahl,
)
from framework_mvp.application.ergebnisaggregation.zeitvergleich import (
    lese_externe_sollzeitdaten,
    zeitvergleich_berechnen,
)
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
    AnkunftsstromDefinition,
    Attributzuordnung,
    BestaetigteWarteschlangeninformation,
    BusyRatioErgebnis,
    BusyRatioKonfiguration,
    ConformanceErgebnis,
    Datenartefakt,
    EntitaetsanalyseErgebnis,
    Ergebnisaggregation,
    KpiBehandlungsart,
    KpiErgebnis,
    KpiKonfiguration,
    OperandZuordnung,
    PerformanceZeitvergleichErgebnis,
    PerformanceZeitvergleichKonfiguration,
    ProcessMiningAnalyse,
    ProfilkennzahlReferenz,
    Profilkennzahltyp,
    Projekt,
    Qualitaetsfreigabe,
    RessourcenanalyseErgebnis,
    Ressourcenzuordnungsmodus,
    SollmodellEntscheidung,
    SollmodellErstellungsart,
    SollmodellMetadaten,
    SollmodellVorschau,
    Sollzeitdaten,
    Vorkommensregel,
    WarteschlangenanalyseErgebnis,
    ZeitbezogeneDatenauswahlErgebnis,
    ZeitvergleichErgebnis,
    ZeitvergleichKonfiguration,
)
from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.infrastructure.importartefakte import ImportartefaktSpeicher

AG_ARTEFAKTVERSION = 7
AG_LESBARE_ARTEFAKTVERSIONEN = frozenset({1, 2, 3, 4, 5, 6, AG_ARTEFAKTVERSION})
AG_ARTEFAKTART = "aggregierte_analyseergebnisse_a_g"
STRUKTURIERTE_ERGEBNISVERSION = 4


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
    datenquellen_ids: tuple[str, ...] = ()
    profilkennzahlen: tuple[ProfilkennzahlReferenz, ...] = ()


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
    ressourcenanalyse: RessourcenanalyseErgebnis | None = None
    warteschlangenanalyse: WarteschlangenanalyseErgebnis | None = None
    zeitbezogene_datenauswahl: ZeitbezogeneDatenauswahlErgebnis | None = None
    entitaetsanalyse: EntitaetsanalyseErgebnis | None = None
    ressourcenattributzuordnungen: tuple[Attributzuordnung, ...] = ()
    entitaetsattributzuordnungen: tuple[Attributzuordnung, ...] = ()
    entitaetstyp: str = ""
    bestaetigte_warteschlangen: tuple[BestaetigteWarteschlangeninformation, ...] = ()
    ankunftsstroeme: tuple[AnkunftsstromDefinition, ...] = ()
    performance_zeitvergleich_konfiguration: PerformanceZeitvergleichKonfiguration | None = None
    performance_zeitvergleich_ergebnis: PerformanceZeitvergleichErgebnis | None = None
    busy_ratio_konfiguration: BusyRatioKonfiguration | None = None
    busy_ratio_ergebnis: BusyRatioErgebnis | None = None
    conformance_ausfuehren: bool = False
    zeitvergleich_ausfuehren: bool = False
    performance_zeitvergleich_ausfuehren: bool = False
    busy_ratio_ausfuehren: bool = False
    vereinfachte_zeitspannen_bestaetigt: bool = False


@dataclass(frozen=True, slots=True)
class Aggregationskonfigurationsvorlage:
    """Persistierte manuelle Entscheidungen eines fachlich kompatiblen A_G."""

    aggregations_id: UUID
    kpi_konfigurationen: tuple[KpiKonfiguration, ...] = ()
    sollmodell: SollmodellVorschau | None = None
    aktivitaetsmapping: Aktivitaetsmapping | None = None
    conformance_ausfuehren: bool = False
    ressourcenanalyse: RessourcenanalyseErgebnis | None = None
    ressourcenattributzuordnungen: tuple[Attributzuordnung, ...] = ()
    entitaetsattributzuordnungen: tuple[Attributzuordnung, ...] = ()
    entitaetstyp: str = ""
    bestaetigte_warteschlangen: tuple[BestaetigteWarteschlangeninformation, ...] = ()
    ankunftsstroeme: tuple[AnkunftsstromDefinition, ...] = ()
    performance_zeitvergleich_konfiguration: PerformanceZeitvergleichKonfiguration | None = None
    performance_zeitvergleich_ausfuehren: bool = False
    busy_ratio_konfiguration: BusyRatioKonfiguration | None = None
    busy_ratio_ausfuehren: bool = False
    sollzeitdaten: Sollzeitdaten | None = None
    sollzeit_tabelle: pd.DataFrame | None = None
    vereinfachte_zeitspannen_bestaetigt: bool = False


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
        aktive_lineage: AktiveLineageService | None = None,
        datenprofile: DatenprofilService | None = None,
    ) -> None:
        self._repository = repository
        self._projekte = projekt_service
        self._transformationen = transformations_service
        self._qualitaet = qualitaet_service
        self._process_mining = process_mining_service
        self._artefakte = artefakte
        self._aktive_lineage = aktive_lineage
        self._datenprofile = datenprofile

    def grundlage_laden(
        self,
        projekt_id: UUID,
        freigabe_id: UUID,
        analyse_id: UUID,
        *,
        profilreferenzen: tuple[dict[str, Any], ...] | None = None,
    ) -> Aggregationsgrundlage:
        """Lädt die Grundlage mit aktuellen oder ausdrücklich fixierten R-Generationen."""
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
        profilkennzahlen: list[ProfilkennzahlReferenz] = []
        datenquellen_ids: list[str] = []
        referenzen_nach_import = {
            str(wert.get("import_id")): wert for wert in (profilreferenzen or ())
        }
        if profilreferenzen is not None and set(referenzen_nach_import) != {
            str(wert) for wert in datensatz.import_ids
        }:
            raise Importintegritaetsfehler(
                "Die in der Ergebnisaggregation gespeicherten Profilreferenzen sind unvollständig."
            )
        for import_id in datensatz.import_ids:
            geladen = self._transformationen.import_laden(import_id)
            if geladen is None or geladen.importvorgang.projekt_id != projekt_id:
                raise Importintegritaetsfehler("Ein in T referenziertes Datenprofil R fehlt.")
            gespeicherte_referenz = referenzen_nach_import.get(str(import_id))
            if gespeicherte_referenz is not None:
                if not gespeicherte_referenz.get("profil_id"):
                    raise Importintegritaetsfehler(
                        "Die explizit referenzierte Profilgeneration kann nicht geladen werden."
                    )
                if self._datenprofile is None:
                    if (
                        str(gespeicherte_referenz["profil_id"]) != str(import_id)
                        or int(gespeicherte_referenz.get("fachversion", -1)) != 1
                    ):
                        raise Importintegritaetsfehler(
                            "Die explizit referenzierte Profilgeneration kann nicht geladen werden."
                        )
                    profilgeneration = None
                else:
                    try:
                        profilgeneration = self._datenprofile.laden(
                            UUID(str(gespeicherte_referenz["profil_id"])), import_id=import_id
                        )
                    except (KeyError, TypeError, ValueError) as fehler:
                        raise Importintegritaetsfehler(
                            "Die Profilreferenz der Ergebnisaggregation ist ungültig."
                        ) from fehler
            else:
                profilgeneration = (
                    self._datenprofile.aktuellste(import_id) if self._datenprofile else None
                )
            profil = profilgeneration.profil if profilgeneration is not None else geladen.profil
            fachversion = profilgeneration.fachversion if profilgeneration is not None else 1
            profil_id = profilgeneration.profil_id if profilgeneration is not None else import_id
            importvorgang = geladen.importvorgang
            datenquellen_id = str(getattr(geladen.importvorgang, "datenquellen_id", ""))
            if datenquellen_id:
                datenquellen_ids.append(datenquellen_id)
            originaldateiname = str(getattr(importvorgang, "originaldateiname", ""))
            tabellenbezeichnung = str(
                getattr(importvorgang, "tabellenbezeichnung", "")
                or getattr(profil, "tabellenbezeichnung", "")
            )
            datenquelle = getattr(geladen, "datenquelle", None)
            datenquelle_bezeichnung = str(getattr(datenquelle, "bezeichnung", ""))
            snapshot = {
                "import_id": str(import_id),
                "raw_sha256": geladen.importvorgang.sha256,
                "profil_version": profil.profil_version,
                "profil_id": str(profil_id),
                "fachversion": fachversion,
                "datei_pruefsumme": profil.datei_pruefsumme,
                "datenquellen_id": datenquellen_id,
                "datenquelle_bezeichnung": datenquelle_bezeichnung,
                "originaldateiname": originaldateiname,
                "tabellenbezeichnung": tabellenbezeichnung,
                "gesamtprofil": profil.gesamtprofil,
            }
            snapshot["profil_sha256"] = _sha(snapshot)
            if gespeicherte_referenz is not None:
                if (
                    int(gespeicherte_referenz.get("fachversion", -1)) != fachversion
                    or str(gespeicherte_referenz.get("profil_sha256", ""))
                    != snapshot["profil_sha256"]
                ):
                    raise Importintegritaetsfehler(
                        "Die gespeicherte Profilgeneration oder ihre Prüfsumme ist ungültig."
                    )
            profil_snapshot.append(snapshot)
            gesamt = profil.gesamtprofil
            zeilen = int(gesamt.get("zeilen", 0))
            legacy_zeilen = f"{import_id}:__gesamt__:zeilen"
            profilwerte[legacy_zeilen] = float(zeilen)
            profilkennzahlen.append(
                ProfilkennzahlReferenz(
                    referenz_id="profilkennzahl:"
                    + _sha(
                        {
                            "import_id": str(import_id),
                            "kennzahltyp": Profilkennzahltyp.ZEILENANZAHL,
                        }
                    ),
                    import_id=str(import_id),
                    datenquellen_id=datenquellen_id,
                    datenquelle_bezeichnung=datenquelle_bezeichnung,
                    originaldateiname=originaldateiname,
                    tabellenbezeichnung=tabellenbezeichnung,
                    spaltenname="",
                    kennzahltyp=Profilkennzahltyp.ZEILENANZAHL,
                    wert=float(zeilen),
                    auswertbare_beobachtungen=zeilen,
                    grundgesamtheit=zeilen,
                    profilversion=fachversion,
                    profil_sha256=snapshot["profil_sha256"],
                )
            )
            for spalte in gesamt.get("spaltenprofile", []):
                spaltenname = str(spalte.get("spaltenname", ""))
                for auswertung in spalte.get("indikatorauswertungen", []):
                    if not isinstance(auswertung, dict):
                        continue
                    operator = str(auswertung.get("operator", ""))
                    vergleichswert = str(auswertung.get("vergleichswert", ""))
                    wert = float(auswertung.get("absolute_haeufigkeit", 0))
                    auswertbar = int(auswertung.get("auswertbare_beobachtungen", 0))
                    profilkennzahlen.append(
                        ProfilkennzahlReferenz(
                            referenz_id="profilkennzahl:"
                            + _sha(
                                {
                                    "import_id": str(import_id),
                                    "spaltenname": spaltenname,
                                    "kennzahltyp": (
                                        Profilkennzahltyp.ABSOLUTE_HAEUFIGKEIT_INDIKATOR
                                    ),
                                    "operator": operator,
                                    "vergleichswert": vergleichswert,
                                }
                            ),
                            import_id=str(import_id),
                            datenquellen_id=datenquellen_id,
                            datenquelle_bezeichnung=datenquelle_bezeichnung,
                            originaldateiname=originaldateiname,
                            tabellenbezeichnung=tabellenbezeichnung,
                            spaltenname=spaltenname,
                            kennzahltyp=Profilkennzahltyp.ABSOLUTE_HAEUFIGKEIT_INDIKATOR,
                            wert=wert,
                            operator=operator,
                            vergleichswert=vergleichswert,
                            auswertbare_beobachtungen=auswertbar,
                            grundgesamtheit=zeilen,
                            profilversion=fachversion,
                            profil_sha256=snapshot["profil_sha256"],
                        )
                    )
                numerisch = spalte.get("numerisch")
                if not isinstance(numerisch, dict):
                    continue
                for kennzahl, wert in numerisch.items():
                    if isinstance(wert, (int, float)):
                        profilwerte[f"{import_id}:{spaltenname}:{kennzahl}"] = float(wert)
                profiltypen = {
                    "gueltige_werte": Profilkennzahltyp.GUELTIGE_BEOBACHTUNGEN,
                    "mittelwert": Profilkennzahltyp.ARITHMETISCHES_MITTEL,
                    "summe": Profilkennzahltyp.SUMME,
                }
                for kennzahl, kennzahltyp in profiltypen.items():
                    wert = numerisch.get(kennzahl)
                    if not isinstance(wert, (int, float)):
                        continue
                    auswertbar = int(numerisch.get("gueltige_werte", zeilen))
                    profilkennzahlen.append(
                        ProfilkennzahlReferenz(
                            referenz_id="profilkennzahl:"
                            + _sha(
                                {
                                    "import_id": str(import_id),
                                    "spaltenname": spaltenname,
                                    "kennzahltyp": kennzahltyp,
                                }
                            ),
                            import_id=str(import_id),
                            datenquellen_id=datenquellen_id,
                            datenquelle_bezeichnung=datenquelle_bezeichnung,
                            originaldateiname=originaldateiname,
                            tabellenbezeichnung=tabellenbezeichnung,
                            spaltenname=spaltenname,
                            kennzahltyp=kennzahltyp,
                            wert=float(wert),
                            auswertbare_beobachtungen=auswertbar,
                            grundgesamtheit=zeilen,
                            profilversion=fachversion,
                            profil_sha256=snapshot["profil_sha256"],
                        )
                    )
        u_sha256 = _sha(projekt.untersuchungsauftrag)
        r_sha256 = _sha(profil_snapshot)
        fingerabdruck = _sha(
            {
                "projekt_id": projekt_id,
                "spezifikations_id": projekt_id,
                "untersuchungsauftrag_sha256": u_sha256,
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
            tuple(sorted(set(datenquellen_ids))),
            tuple(profilkennzahlen),
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
        ressourcenanalyse: RessourcenanalyseErgebnis | None = None,
        ressourcenattributzuordnungen: tuple[Attributzuordnung, ...] = (),
        entitaetsattributzuordnungen: tuple[Attributzuordnung, ...] = (),
        entitaetstyp: str = "",
        bestaetigte_warteschlangen: tuple[BestaetigteWarteschlangeninformation, ...] = (),
        ankunftsstroeme: tuple[AnkunftsstromDefinition, ...] = (),
        performance_zeitvergleich_konfiguration: (
            PerformanceZeitvergleichKonfiguration | None
        ) = None,
        performance_zeitvergleich_ausfuehren: bool = False,
        busy_ratio_konfiguration: BusyRatioKonfiguration | None = None,
        busy_ratio_ausfuehren: bool = False,
        vereinfachte_zeitspannen_bestaetigt: bool = False,
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
                "ressourcenanalyse": ressourcenanalyse,
                "ressourcenattributzuordnungen": ressourcenattributzuordnungen,
                "entitaetsattributzuordnungen": entitaetsattributzuordnungen,
                "entitaetstyp": entitaetstyp,
                "bestaetigte_warteschlangen": bestaetigte_warteschlangen,
                "ankunftsstroeme": ankunftsstroeme,
                "performance_zeitvergleich_konfiguration": (
                    performance_zeitvergleich_konfiguration
                ),
                "performance_zeitvergleich_ausfuehren": (performance_zeitvergleich_ausfuehren),
                "busy_ratio_konfiguration": busy_ratio_konfiguration,
                "busy_ratio_ausfuehren": busy_ratio_ausfuehren,
                "vereinfachte_zeitspannen_bestaetigt": (vereinfachte_zeitspannen_bestaetigt),
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
        ressourcenanalyse: RessourcenanalyseErgebnis | None = None,
        ressourcenattributzuordnungen: tuple[Attributzuordnung, ...] = (),
        entitaetsattributzuordnungen: tuple[Attributzuordnung, ...] = (),
        entitaetstyp: str = "",
        bestaetigte_warteschlangen: tuple[BestaetigteWarteschlangeninformation, ...] = (),
        ankunftsstroeme: tuple[AnkunftsstromDefinition, ...] = (),
        performance_zeitvergleich_konfiguration: (
            PerformanceZeitvergleichKonfiguration | None
        ) = None,
        performance_zeitvergleich_ausfuehren: bool = False,
        busy_ratio_konfiguration: BusyRatioKonfiguration | None = None,
        busy_ratio_ausfuehren: bool = False,
        vereinfachte_zeitspannen_bestaetigt: bool = False,
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
            ressourcenanalyse,
            ressourcenattributzuordnungen,
            entitaetsattributzuordnungen,
            entitaetstyp,
            bestaetigte_warteschlangen,
            ankunftsstroeme,
            performance_zeitvergleich_konfiguration,
            performance_zeitvergleich_ausfuehren,
            busy_ratio_konfiguration,
            busy_ratio_ausfuehren,
            vereinfachte_zeitspannen_bestaetigt,
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
        ressourcenanalyse: RessourcenanalyseErgebnis | None = None,
        ressourcenattributzuordnungen: tuple[Attributzuordnung, ...] = (),
        entitaetsattributzuordnungen: tuple[Attributzuordnung, ...] = (),
        entitaetstyp: str = "",
        bestaetigte_warteschlangen: tuple[BestaetigteWarteschlangeninformation, ...] = (),
        ankunftsstroeme: tuple[AnkunftsstromDefinition, ...] = (),
        performance_zeitvergleich_konfiguration: (
            PerformanceZeitvergleichKonfiguration | None
        ) = None,
        performance_zeitvergleich_ausfuehren: bool = False,
        busy_ratio_konfiguration: BusyRatioKonfiguration | None = None,
        busy_ratio_ausfuehren: bool = False,
        vereinfachte_zeitspannen_bestaetigt: bool = False,
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
            basis.profilkennzahlen,
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
        performance_zeitvergleich = None
        if performance_zeitvergleich_ausfuehren:
            if performance_zeitvergleich_konfiguration is None:
                warnungen.append(
                    "dT/dB nicht berechenbar: Die bestätigten Soll-/Ist-Zeitrollen fehlen."
                )
            else:
                if performance_zeitvergleich_konfiguration.sollquelle == "T":
                    performance_soll = basis.zwischendaten.copy(deep=True)
                elif performance_zeitvergleich_konfiguration.sollquelle == "E*":
                    performance_soll = basis.event_log.copy(deep=True)
                elif (
                    sollzeitdaten is not None
                    and sollzeit_tabelle is not None
                    and sollzeitdaten.projekt_id == projekt_id
                ):
                    performance_soll = sollzeit_tabelle.copy(deep=True)
                else:
                    performance_soll = None
                if performance_soll is None:
                    warnungen.append(
                        "dT/dB nicht berechenbar: Die bestätigte Sollzeitquelle fehlt."
                    )
                else:
                    try:
                        performance_zeitvergleich = performance_zeitvergleich_berechnen(
                            soll_daten=performance_soll,
                            event_log=basis.event_log.copy(deep=True),
                            konfiguration=performance_zeitvergleich_konfiguration,
                        )
                    except Domaenenfehler as fehler:
                        warnungen.append(f"dT/dB nicht berechenbar: {fehler}")
        busy_ratio = None
        if busy_ratio_ausfuehren:
            if busy_ratio_konfiguration is None:
                warnungen.append(
                    "Busy Ratio nicht berechenbar: Ressource, Ist-Start, Ist-Ende oder "
                    "Betrachtungszeitraum wurde nicht bestätigt."
                )
            else:
                try:
                    busy_ratio = busy_ratio_berechnen(
                        event_log=basis.event_log.copy(deep=True),
                        konfiguration=busy_ratio_konfiguration,
                    )
                except Domaenenfehler as fehler:
                    warnungen.append(f"Busy Ratio nicht berechenbar: {fehler}")
        bestaetigte_ressourcenentscheidung = ressourcenanalyse
        if ressourcenanalyse is None:
            ressourcenanalyse = analysiere_ressourcen(
                basis.event_log,
                zwischendaten=basis.zwischendaten,
                attributzuordnungen=ressourcenattributzuordnungen,
            )
        else:
            manuell = {
                wert.aktivitaet: (
                    wert.manuell_bestaetigte_ressourcen
                    or (
                        wert.ressourcen
                        if ressourcenanalyse.modus is Ressourcenzuordnungsmodus.MANUELL
                        else ()
                    )
                )
                for wert in ressourcenanalyse.zuordnungen
            }
            ressourcenanalyse = analysiere_ressourcen(
                basis.event_log,
                manuelle_zuordnungen=manuell,
                offene_aktivitaeten=tuple(
                    wert.aktivitaet for wert in ressourcenanalyse.zuordnungen if wert.offen
                ),
                nicht_moeglich_begruendung=ressourcenanalyse.begruendung,
                zwischendaten=basis.zwischendaten,
                attributzuordnungen=ressourcenattributzuordnungen,
            )
        entitaetsanalyse = analysiere_entitaeten(
            basis.zwischendaten,
            basis.event_log,
            attributzuordnungen=entitaetsattributzuordnungen,
            entitaetstyp=entitaetstyp,
        )
        warteschlangenanalyse = analysiere_warteschlangen(
            basis.event_log,
            bestaetigte_warteschlangen=bestaetigte_warteschlangen,
            zwischendaten=basis.zwischendaten,
        )
        zeitbezogene_datenauswahl = analysiere_zeitbezogene_datenauswahl(
            basis.zwischendaten,
            basis.event_log,
            ankunftsstroeme=ankunftsstroeme,
            vereinfachte_zeitspannen_bestaetigt=vereinfachte_zeitspannen_bestaetigt,
            datenbasis_referenzen={
                "Q": {"datenquellen_ids": list(basis.datenquellen_ids)},
                "R": {
                    "profile": [
                        {
                            "import_id": wert.get("import_id"),
                            "profil_sha256": wert.get("profil_sha256"),
                        }
                        for wert in basis.profilreferenzen
                    ]
                },
                "T": {
                    "id": str(basis.zwischendatensatz.zwischendatensatz_id),
                    "sha256": basis.zwischendatensatz.sha256,
                },
                "E*": {
                    "id": str(basis.freigabe.event_log_id),
                    "sha256": basis.freigabe.event_log_sha256,
                },
            },
        )
        fingerabdruck = self._konfigurationsfingerabdruck(
            kpi_konfigurationen,
            sollmodell,
            aktivitaetsmapping,
            conformance_ausfuehren,
            sollzeitdaten,
            zeitvergleich_konfiguration,
            zeitvergleich_ausfuehren,
            bestaetigte_ressourcenentscheidung,
            ressourcenattributzuordnungen,
            entitaetsattributzuordnungen,
            entitaetstyp,
            bestaetigte_warteschlangen,
            ankunftsstroeme,
            performance_zeitvergleich_konfiguration,
            performance_zeitvergleich_ausfuehren,
            busy_ratio_konfiguration,
            busy_ratio_ausfuehren,
            vereinfachte_zeitspannen_bestaetigt,
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
            ressourcenanalyse,
            warteschlangenanalyse,
            zeitbezogene_datenauswahl,
            entitaetsanalyse,
            ressourcenattributzuordnungen,
            entitaetsattributzuordnungen,
            entitaetstyp,
            bestaetigte_warteschlangen,
            ankunftsstroeme,
            performance_zeitvergleich_konfiguration,
            performance_zeitvergleich,
            busy_ratio_konfiguration,
            busy_ratio,
            conformance_ausfuehren,
            zeitvergleich_ausfuehren,
            performance_zeitvergleich_ausfuehren,
            busy_ratio_ausfuehren,
            vereinfachte_zeitspannen_bestaetigt,
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
            gespeichert = self.laden(aggregations_id)[0]
            if self._aktive_lineage is not None:
                self._aktive_lineage.aktivieren(
                    gespeichert.projekt_id,
                    LineageEndpunkt.A_G,
                    {
                        "aktuelle_freigabe_id": gespeichert.freigabe_id,
                        "freigegebenes_event_log_id": gespeichert.event_log_id,
                        "aktuelles_event_log_id": gespeichert.event_log_id,
                        "event_log_id": gespeichert.event_log_id,
                        "aktuelle_analyse_id": gespeichert.analyse_id,
                        "aktuelles_prozessmodell_id": gespeichert.analyse_id,
                        "aktuelle_discovery_ergebnisse_id": gespeichert.analyse_id,
                        "aktuelle_aggregations_id": gespeichert.aggregations_id,
                    },
                )
            return gespeichert
        basis = self.grundlage_laden(
            vorschau.grundlage.projekt.projekt_id,
            vorschau.grundlage.freigabe.freigabe_id,
            vorschau.grundlage.analyse.analyse_id,
            profilreferenzen=vorschau.grundlage.profilreferenzen,
        )
        if basis.eingabefingerabdruck != vorschau.grundlage.eingabefingerabdruck:
            raise Domaenenfehler(
                "U, R, T, E*, P oder A_D wurde seit der Vorschau verändert; eine "
                "Neuberechnung ist erforderlich."
            )
        if vorschau.ressourcenanalyse is None:
            raise Domaenenfehler("Die strukturierte Ressourcenanalyse der Vorschau fehlt.")
        erwartete_ressourcen = analysiere_ressourcen(
            basis.event_log,
            manuelle_zuordnungen={
                wert.aktivitaet: wert.manuell_bestaetigte_ressourcen
                for wert in vorschau.ressourcenanalyse.zuordnungen
            },
            offene_aktivitaeten=tuple(
                wert.aktivitaet for wert in vorschau.ressourcenanalyse.zuordnungen if wert.offen
            ),
            nicht_moeglich_begruendung=vorschau.ressourcenanalyse.begruendung,
            zwischendaten=basis.zwischendaten,
            attributzuordnungen=vorschau.ressourcenattributzuordnungen,
        )
        erwartete_entitaeten = analysiere_entitaeten(
            basis.zwischendaten,
            basis.event_log,
            attributzuordnungen=vorschau.entitaetsattributzuordnungen,
            entitaetstyp=vorschau.entitaetstyp,
        )
        erwartete_warteschlangen = analysiere_warteschlangen(
            basis.event_log,
            bestaetigte_warteschlangen=vorschau.bestaetigte_warteschlangen,
            zwischendaten=basis.zwischendaten,
        )
        erwartete_zeitdaten = analysiere_zeitbezogene_datenauswahl(
            basis.zwischendaten,
            basis.event_log,
            ankunftsstroeme=vorschau.ankunftsstroeme,
            vereinfachte_zeitspannen_bestaetigt=(vorschau.vereinfachte_zeitspannen_bestaetigt),
            datenbasis_referenzen={
                "Q": {"datenquellen_ids": list(basis.datenquellen_ids)},
                "R": {
                    "profile": [
                        {
                            "import_id": wert.get("import_id"),
                            "profil_sha256": wert.get("profil_sha256"),
                        }
                        for wert in basis.profilreferenzen
                    ]
                },
                "T": {
                    "id": str(basis.zwischendatensatz.zwischendatensatz_id),
                    "sha256": basis.zwischendatensatz.sha256,
                },
                "E*": {
                    "id": str(basis.freigabe.event_log_id),
                    "sha256": basis.freigabe.event_log_sha256,
                },
            },
        )
        if (
            vorschau.ressourcenanalyse != erwartete_ressourcen
            or vorschau.entitaetsanalyse != erwartete_entitaeten
            or vorschau.warteschlangenanalyse != erwartete_warteschlangen
            or vorschau.zeitbezogene_datenauswahl != erwartete_zeitdaten
        ):
            raise Domaenenfehler(
                "Die strukturierten Schritt-7-Ergebnisse sind nicht mehr reproduzierbar."
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
        if (
            vorschau.zeitvergleich_ergebnis is not None
            and vorschau.performance_zeitvergleich_ergebnis is None
            and vorschau.busy_ratio_ergebnis is None
        ):
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
        if (
            vorschau.performance_zeitvergleich_ergebnis is not None
            or vorschau.busy_ratio_ergebnis is not None
        ):
            performance = vorschau.performance_zeitvergleich_ergebnis
            busy = vorschau.busy_ratio_ergebnis
            if performance is not None:
                av_id = performance.auswertungs_id
            else:
                assert busy is not None
                av_id = busy.auswertungs_id
            av_json_pfad = (basis_pfad / f"{av_id}.performance-a-v.json").as_posix()
            av_struktur = {
                "artefaktart": "potenzielle_verbesserungspotenziale_a_v",
                "artefaktversion": 2,
                "quellreferenzen": {
                    "event_log_id": str(basis.freigabe.event_log_id),
                    "event_log_sha256": basis.freigabe.event_log_sha256,
                    "zwischendatensatz_id": str(basis.zwischendatensatz.zwischendatensatz_id),
                    "zwischendatensatz_sha256": basis.zwischendatensatz.sha256,
                    "sollzeitdaten": referenzen.get("sollzeitdaten"),
                },
                "fertigstellungs_und_bearbeitungszeitabweichungen": performance,
                "ressourcenbezogene_busy_ratio": busy,
                "hinweis": (
                    "Zeitliche Abweichungen und Busy Ratio sind Hinweise auf potenzielle "
                    "Verbesserungspotenziale; es werden keine Ursachen oder Maßnahmen abgeleitet."
                ),
            }
            artefakte[av_json_pfad] = _json_bytes(av_struktur)
            av_referenz: dict[str, Any] = {
                "auswertungs_id": str(av_id),
                "artefaktversion": 2,
                "relativer_pfad": av_json_pfad,
            }
            if performance is not None:
                performance_csv = (basis_pfad / f"{av_id}.dt-db.csv").as_posix()
                artefakte[performance_csv] = (
                    pd.DataFrame([asdict(wert) for wert in performance.einzelwerte])
                    .to_csv(index=False)
                    .encode("utf-8")
                )
                av_referenz["dt_db_csv_pfad"] = performance_csv
            if busy is not None:
                busy_csv = (basis_pfad / f"{av_id}.busy-ratio.csv").as_posix()
                artefakte[busy_csv] = (
                    pd.DataFrame([asdict(wert) for wert in busy.einzelwerte])
                    .to_csv(index=False)
                    .encode("utf-8")
                )
                av_referenz["busy_ratio_csv_pfad"] = busy_csv
            referenzen["potenzielle_verbesserungspotenziale_a_v"] = av_referenz
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
                for schluessel in (
                    "relativer_pfad",
                    "relativer_metadaten_pfad",
                    "detail_csv_pfad",
                    "dt_db_csv_pfad",
                    "busy_ratio_csv_pfad",
                ):
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
        if self._aktive_lineage is not None:
            self._aktive_lineage.aktivieren(
                projekt_id,
                LineageEndpunkt.A_G,
                {
                    "aktuelle_freigabe_id": basis.freigabe.freigabe_id,
                    "freigegebenes_event_log_id": basis.freigabe.event_log_id,
                    "aktuelles_event_log_id": basis.freigabe.event_log_id,
                    "event_log_id": basis.freigabe.event_log_id,
                    "aktuelle_analyse_id": basis.analyse.analyse_id,
                    "aktuelles_prozessmodell_id": basis.analyse.analyse_id,
                    "aktuelle_discovery_ergebnisse_id": basis.analyse.analyse_id,
                    "aktuelle_aggregations_id": aggregation.aggregations_id,
                },
            )
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
        abstraktionen_laden = getattr(
            self._transformationen, "regelbasierte_abstraktionen_laden", None
        )
        etl_abstraktionen = (
            abstraktionen_laden(basis.zwischendatensatz) if callable(abstraktionen_laden) else ()
        )
        historie_laden = getattr(
            self._transformationen, "fachliche_transformationshistorie_laden", None
        )
        transformationshistorie = (
            historie_laden(basis.zwischendatensatz) if callable(historie_laden) else ()
        )
        ressourcenentscheidung = vorschau.ressourcenanalyse
        sollmodell_entscheidung = SollmodellEntscheidung.KEIN_SOLLMODELL
        if vorschau.sollmodell is not None:
            sollmodell_entscheidung = (
                SollmodellEntscheidung.LINEARER_ASSISTENT
                if vorschau.sollmodell.metadaten.erstellungsart
                is SollmodellErstellungsart.LINEARER_ASSISTENT
                else SollmodellEntscheidung.KOMPLEXES_PNML
            )
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
                "schwellwert_k": basis.discovery_ergebnisse.get("schwellwert_k"),
                "miner_variante": basis.discovery_ergebnisse.get("miner_variante"),
                "bedeutung": "Unveränderte Referenz; A_D wurde weder kopiert noch verändert.",
            },
            "prozessbelege": {
                "ergebnisversion": 1,
                "quelle": "A_D/P",
                "start_und_endaktivitaeten": {
                    "startaktivitaeten": basis.discovery_ergebnisse.get("dfg_daten", {}).get(
                        "startaktivitaeten", []
                    ),
                    "endaktivitaeten": basis.discovery_ergebnisse.get("dfg_daten", {}).get(
                        "endaktivitaeten", []
                    ),
                },
            },
            "ausgewaehlte_kpi_ids": list(basis.projekt.untersuchungsauftrag.ausgewaehlte_kpi_ids),
            "kpi_definitionen_version": 2,
            "kpi_konfigurationsversion": 3,
            "kpi_konfigurationen": vorschau.kpi_konfigurationen,
            "kpi_ergebnisse": vorschau.kpi_ergebnisse,
            "konfiguration": {
                "version": 2,
                "kpi_konfigurationen": vorschau.kpi_konfigurationen,
                "sollmodell_entscheidung": sollmodell_entscheidung,
                "conformance_ausfuehren": vorschau.conformance_ausfuehren,
                "ressourcenzuordnung": {
                    "modus": ressourcenentscheidung.modus if ressourcenentscheidung else None,
                    "manuelle_zuordnungen": {
                        wert.aktivitaet: wert.manuell_bestaetigte_ressourcen
                        for wert in (
                            ressourcenentscheidung.zuordnungen if ressourcenentscheidung else ()
                        )
                        if wert.manuell_bestaetigte_ressourcen
                    },
                    "offene_aktivitaeten": tuple(
                        wert.aktivitaet
                        for wert in (
                            ressourcenentscheidung.zuordnungen if ressourcenentscheidung else ()
                        )
                        if wert.offen
                    ),
                    "begruendung": (
                        ressourcenentscheidung.begruendung if ressourcenentscheidung else ""
                    ),
                },
                "ressourcenattributzuordnungen": vorschau.ressourcenattributzuordnungen,
                "entitaetsattributzuordnungen": vorschau.entitaetsattributzuordnungen,
                "entitaetstyp": vorschau.entitaetstyp,
                "bestaetigte_warteschlangen": vorschau.bestaetigte_warteschlangen,
                "ankunftsstroeme": vorschau.ankunftsstroeme,
                "vereinfachte_zeitspannen_bestaetigt": (
                    vorschau.vereinfachte_zeitspannen_bestaetigt
                ),
                "zeitvergleich_konfiguration": vorschau.zeitvergleich_konfiguration,
                "zeitvergleich_ausfuehren": vorschau.zeitvergleich_ausfuehren,
                "performance_zeitvergleich_konfiguration": (
                    vorschau.performance_zeitvergleich_konfiguration
                ),
                "performance_zeitvergleich_ausfuehren": (
                    vorschau.performance_zeitvergleich_ausfuehren
                ),
                "busy_ratio_konfiguration": vorschau.busy_ratio_konfiguration,
                "busy_ratio_ausfuehren": vorschau.busy_ratio_ausfuehren,
            },
            "conformance_checking": {
                "sollprozess_vorhanden": vorschau.sollmodell is not None,
                "durchgefuehrt": vorschau.conformance_ergebnis is not None,
                "status": (
                    "Token-Based Replay durchgeführt; A_C ist referenziert."
                    if vorschau.conformance_ergebnis is not None
                    else (
                        "Kein Sollprozess vorhanden; Conformance Checking entfällt ohne Fehler."
                        if vorschau.sollmodell is None
                        else "Conformance Checking nicht durchgeführt oder Voraussetzungen fehlen."
                    )
                ),
                "a_c_referenz": referenzen.get("conformance_ergebnisse_a_c"),
                "ergebnis": (
                    {
                        "fitness": vorschau.conformance_ergebnis.fitness,
                        "produzierte_tokens": (vorschau.conformance_ergebnis.produzierte_tokens),
                        "konsumierte_tokens": (vorschau.conformance_ergebnis.konsumierte_tokens),
                        "fehlende_tokens": vorschau.conformance_ergebnis.fehlende_tokens,
                        "verbleibende_tokens": (vorschau.conformance_ergebnis.verbleibende_tokens),
                        "ausgewertete_faelle": (
                            vorschau.conformance_ergebnis.konforme_faelle
                            + vorschau.conformance_ergebnis.abweichende_faelle
                        ),
                        "konforme_faelle": vorschau.conformance_ergebnis.konforme_faelle,
                        "abweichende_faelle": (vorschau.conformance_ergebnis.abweichende_faelle),
                        "ausgeschlossene_faelle": len(
                            vorschau.conformance_ergebnis.ausgeschlossene_faelle
                        ),
                        "artefaktversion": vorschau.conformance_ergebnis.artefaktversion,
                    }
                    if vorschau.conformance_ergebnis is not None
                    else None
                ),
            },
            "strukturierte_ergebnisse": {
                "ergebnisversion": STRUKTURIERTE_ERGEBNISVERSION,
                "datenaufbereitung": {
                    "ausgang": "ursprüngliche Datenquelle D",
                    "transformationshistorie": transformationshistorie,
                    "aktiver_zwischendatensatz_t": {
                        "id": str(basis.zwischendatensatz.zwischendatensatz_id),
                        "zeilenanzahl": basis.zwischendatensatz.zeilenanzahl,
                        "spaltenanzahl": basis.zwischendatensatz.spaltenanzahl,
                        "sha256": basis.zwischendatensatz.sha256,
                    },
                    "fachliche_bedeutung": (
                        "Alle Transformationen bilden eine geordnete Aufbereitungskette; "
                        "fachlich gültig ist genau der aktuelle Zwischendatensatz T."
                    ),
                },
                "vereinfachungen": {
                    "etl_abstraktionen": etl_abstraktionen,
                },
                "ressourcen": vorschau.ressourcenanalyse,
                "entitaetsinstanzen_und_attribute": vorschau.entitaetsanalyse,
                "warteschlangen_und_wartezeiten": vorschau.warteschlangenanalyse,
                "zeitbezogene_datenauswahl": vorschau.zeitbezogene_datenauswahl,
                "performance_und_engpassanalyse": {
                    "ergebnisversion": 1,
                    "dt_db_konfiguration": (vorschau.performance_zeitvergleich_konfiguration),
                    "dt_db_ergebnis": vorschau.performance_zeitvergleich_ergebnis,
                    "busy_ratio_konfiguration": vorschau.busy_ratio_konfiguration,
                    "busy_ratio_ergebnis": vorschau.busy_ratio_ergebnis,
                    "a_v_referenz": referenzen.get("potenzielle_verbesserungspotenziale_a_v"),
                },
            },
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

    def historisch_laden(self, aggregations_id: UUID) -> tuple[Ergebnisaggregation, dict[str, Any]]:
        """Lädt ein unveränderliches A_G samt Eigenintegrität ohne Aktivitätsannahme."""
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
            a_g.get("artefaktversion") not in AG_LESBARE_ARTEFAKTVERSIONEN
            or a_g.get("artefaktart") != AG_ARTEFAKTART
            or a_g.get("aggregations_id") != str(aggregation.aggregations_id)
            or a_g.get("projekt_id") != str(aggregation.projekt_id)
            or a_g.get("freigabe_id") != str(aggregation.freigabe_id)
            or a_g.get("event_log_id") != str(aggregation.event_log_id)
            or a_g.get("process_mining_analyse_id") != str(aggregation.analyse_id)
            or _sha(a_g) != gesamtpruefsumme
        ):
            raise Importintegritaetsfehler("Metadaten oder Gesamtprüfsumme von A_G sind ungültig.")
        for pfad, erwartet in a_g.get("artefakt_pruefsummen", {}).items():
            if hashlib.sha256(self._artefakte.lesen(str(pfad))).hexdigest() != erwartet:
                raise Importintegritaetsfehler(
                    "Die Prüfsumme eines von A_G referenzierten Detailartefakts ist ungültig."
                )
        a_g["gesamtpruefsumme"] = gesamtpruefsumme
        return aggregation, a_g

    def laden(self, aggregations_id: UUID) -> tuple[Ergebnisaggregation, dict[str, Any]]:
        """Lädt A_G erst nach erneuter Prüfung der aktuell gültigen Fachlineage."""
        aggregation, a_g = self.historisch_laden(aggregations_id)
        gespeicherte_profile = tuple(
            wert
            for wert in a_g.get("lineage", {}).get("datenprofil_r", {}).get("profile", ())
            if isinstance(wert, dict)
        )
        basis = self.grundlage_laden(
            aggregation.projekt_id,
            aggregation.freigabe_id,
            aggregation.analyse_id,
            profilreferenzen=gespeicherte_profile or None,
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
        return aggregation, a_g

    @staticmethod
    def _vorlage_ist_fachlich_kompatibel(
        aggregation: Ergebnisaggregation,
        a_g: dict[str, Any],
        basis: Aggregationsgrundlage,
    ) -> bool:
        """Vergleicht die unveränderte Grundlage ohne den absichtlich geänderten U-Hash."""
        lineage = a_g.get("lineage", {})
        profil = lineage.get("datenprofil_r", {})
        datensatz = lineage.get("zwischendatensatz_t", {})
        freigabe = lineage.get("event_log_e_stern", {})
        prozessmodell = lineage.get("prozessmodell_p", {})
        discovery = lineage.get("discovery_ergebnisse_a_d", {})
        return bool(
            aggregation.projekt_id == basis.projekt.projekt_id
            and aggregation.freigabe_id == basis.freigabe.freigabe_id
            and aggregation.event_log_id == basis.freigabe.event_log_id
            and aggregation.analyse_id == basis.analyse.analyse_id
            and profil.get("sha256") == basis.datenprofil_sha256
            and datensatz.get("id") == str(basis.zwischendatensatz.zwischendatensatz_id)
            and datensatz.get("sha256") == basis.zwischendatensatz.sha256
            and freigabe.get("freigabe_id") == str(basis.freigabe.freigabe_id)
            and freigabe.get("freigabe_report_sha256") == basis.freigabe.report_sha256
            and freigabe.get("kettenfingerabdruck") == basis.freigabe.kettenfingerabdruck
            and freigabe.get("event_log_id") == str(basis.freigabe.event_log_id)
            and freigabe.get("sha256") == basis.freigabe.event_log_sha256
            and prozessmodell.get("pfad")
            == basis.discovery_ergebnisse["prozessmodell_p"]["relativer_pfad"]
            and prozessmodell.get("sha256") == basis.prozessmodell_sha256
            and discovery.get("pfad") == basis.analyse.relativer_ergebnis_pfad
            and discovery.get("sha256") == basis.discovery_ergebnisse_sha256
        )

    @staticmethod
    def _profilkennzahl_wiederherstellen(wert: object) -> ProfilkennzahlReferenz | None:
        if not isinstance(wert, dict):
            return None
        try:
            return ProfilkennzahlReferenz(
                referenz_id=str(wert["referenz_id"]),
                import_id=str(wert["import_id"]),
                datenquellen_id=str(wert.get("datenquellen_id", "")),
                datenquelle_bezeichnung=str(wert.get("datenquelle_bezeichnung", "")),
                originaldateiname=str(wert.get("originaldateiname", "")),
                tabellenbezeichnung=str(wert.get("tabellenbezeichnung", "")),
                spaltenname=str(wert.get("spaltenname", "")),
                kennzahltyp=Profilkennzahltyp(str(wert["kennzahltyp"])),
                wert=float(wert["wert"]),
                operator=str(wert.get("operator", "")),
                vergleichswert=str(wert.get("vergleichswert", "")),
                auswertbare_beobachtungen=int(wert.get("auswertbare_beobachtungen", 0)),
                grundgesamtheit=int(wert.get("grundgesamtheit", 0)),
                profilversion=int(wert.get("profilversion", 1)),
                profil_sha256=str(wert.get("profil_sha256", "")),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @classmethod
    def _kpi_konfiguration_wiederherstellen(cls, wert: object) -> KpiKonfiguration | None:
        if not isinstance(wert, dict):
            return None
        zuordnungen: list[OperandZuordnung] = []
        try:
            for roh in wert.get("zuordnungen", ()):
                if not isinstance(roh, dict):
                    return None
                zuordnungen.append(
                    OperandZuordnung(
                        operand_id=str(roh["operand_id"]),
                        quelle=Datenartefakt(str(roh["quelle"])),
                        spalte=str(roh.get("spalte", "")),
                        zweite_spalte=str(roh.get("zweite_spalte", "")),
                        bedingungsoperator=str(roh.get("bedingungsoperator", "")),
                        bedingungswert=str(roh.get("bedingungswert", "")),
                        startaktivitaet=str(roh.get("startaktivitaet", "")),
                        endaktivitaet=str(roh.get("endaktivitaet", "")),
                        vorkommensregel=Vorkommensregel(
                            str(roh.get("vorkommensregel", Vorkommensregel.ERSTES.value))
                        ),
                        profilreferenz=str(roh.get("profilreferenz", "")),
                        profilkennzahl=cls._profilkennzahl_wiederherstellen(
                            roh.get("profilkennzahl")
                        ),
                    )
                )
            return KpiKonfiguration(
                kpi_id=str(wert["kpi_id"]),
                zuordnungen=tuple(zuordnungen),
                einheit=str(wert.get("einheit", "")),
                bezugsmenge=str(wert.get("bezugsmenge", "")),
                direkte_profilreferenz=str(wert.get("direkte_profilreferenz", "")),
                direkte_profilkennzahl=cls._profilkennzahl_wiederherstellen(
                    wert.get("direkte_profilkennzahl")
                ),
                behandlungsart=KpiBehandlungsart(
                    str(
                        wert.get(
                            "behandlungsart",
                            KpiBehandlungsart.AUTOMATISCH_BERECHNEN.value,
                        )
                    )
                ),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _attributzuordnungen_wiederherstellen(
        werte: object,
    ) -> tuple[Attributzuordnung, ...]:
        if not isinstance(werte, list):
            return ()
        ergebnis: list[Attributzuordnung] = []
        for wert in werte:
            if not isinstance(wert, dict):
                continue
            try:
                zuordnung = Attributzuordnung(
                    Datenartefakt(str(wert["quelle"])),
                    str(wert["attributspalte"]),
                    str(wert["schluesselspalte"]),
                    str(wert.get("zeitspalte", "")),
                )
            except (KeyError, ValueError):
                continue
            if zuordnung not in ergebnis:
                ergebnis.append(zuordnung)
        return tuple(ergebnis)

    @staticmethod
    def _warteschlangen_wiederherstellen(
        werte: object,
    ) -> tuple[BestaetigteWarteschlangeninformation, ...]:
        if not isinstance(werte, list):
            return ()
        ergebnis = []
        for wert in werte:
            if not isinstance(wert, dict):
                continue
            try:
                ergebnis.append(
                    BestaetigteWarteschlangeninformation(
                        str(wert["bezeichnung"]),
                        str(wert["von_aktivitaet"]),
                        str(wert["zu_aktivitaet"]),
                        Datenartefakt(str(wert["quelle"])),
                        str(wert["informationsspalte"]),
                        str(wert.get("filterwert", "")),
                    )
                )
            except (KeyError, ValueError):
                continue
        return tuple(ergebnis)

    @staticmethod
    def _ankunftsstroeme_wiederherstellen(
        werte: object,
    ) -> tuple[AnkunftsstromDefinition, ...]:
        if not isinstance(werte, list):
            return ()
        ergebnis = []
        for wert in werte:
            if not isinstance(wert, dict):
                continue
            try:
                regel = wert.get("vorkommensregel")
                ergebnis.append(
                    AnkunftsstromDefinition(
                        str(wert["bezeichnung"]),
                        Datenartefakt(str(wert["quelle"])),
                        str(wert["entitaetsspalte"]),
                        str(wert["zeitspalte"]),
                        aktivitaet=str(wert.get("aktivitaet", "")),
                        filterspalte=str(wert.get("filterspalte", "")),
                        filterwert=str(wert.get("filterwert", "")),
                        vorkommensregel=Vorkommensregel(str(regel)) if regel else None,
                        vorkommensnummer=(
                            int(wert["vorkommensnummer"])
                            if wert.get("vorkommensnummer") is not None
                            else None
                        ),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return tuple(ergebnis)

    @staticmethod
    def _performance_wiederherstellen(
        wert: object,
    ) -> PerformanceZeitvergleichKonfiguration | None:
        if not isinstance(wert, dict):
            return None
        try:
            return PerformanceZeitvergleichKonfiguration(
                sollquelle=str(wert["sollquelle"]),
                soll_case_id_spalte=str(wert["soll_case_id_spalte"]),
                soll_activity_spalte=str(wert["soll_activity_spalte"]),
                ist_case_id_spalte=str(wert["ist_case_id_spalte"]),
                ist_activity_spalte=str(wert["ist_activity_spalte"]),
                plan_ende_spalte=str(wert["plan_ende_spalte"]),
                ist_ende_spalte=str(wert["ist_ende_spalte"]),
                plan_start_spalte=str(wert.get("plan_start_spalte", "")),
                ist_start_spalte=str(wert.get("ist_start_spalte", "")),
                soll_auftretensnummer_spalte=str(wert.get("soll_auftretensnummer_spalte", "")),
                vorkommensregel=Vorkommensregel(
                    str(wert.get("vorkommensregel", Vorkommensregel.ERSTES.value))
                ),
                fertigstellungsabweichung_aktiv=bool(
                    wert.get("fertigstellungsabweichung_aktiv", True)
                ),
                bearbeitungszeitabweichung_aktiv=bool(
                    wert.get("bearbeitungszeitabweichung_aktiv", False)
                ),
            )
        except (KeyError, ValueError):
            return None

    @staticmethod
    def _busy_ratio_wiederherstellen(wert: object) -> BusyRatioKonfiguration | None:
        if not isinstance(wert, dict):
            return None
        try:
            von = wert.get("zeitraum_von")
            bis = wert.get("zeitraum_bis")
            return BusyRatioKonfiguration(
                str(wert["ressourcenspalte"]),
                str(wert["startspalte"]),
                str(wert["endspalte"]),
                datetime.fromisoformat(str(von)) if von else None,
                datetime.fromisoformat(str(bis)) if bis else None,
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _sollmodell_wiederherstellen(self, a_g: dict[str, Any]) -> SollmodellVorschau | None:
        referenz = a_g.get("optionale_artefakte", {}).get("prozessmodell_p_soll")
        if not isinstance(referenz, dict):
            return None
        try:
            meta = json.loads(self._artefakte.lesen(str(referenz["relativer_metadaten_pfad"])))
            metadaten = meta["metadaten"]
            markierungen = meta["markierungen"]
            return SollmodellVorschau(
                metadaten=SollmodellMetadaten(
                    sollmodell_id=UUID(str(metadaten["sollmodell_id"])),
                    projekt_id=UUID(str(metadaten["projekt_id"])),
                    bezeichnung=str(metadaten["bezeichnung"]),
                    erstellungsart=SollmodellErstellungsart(str(metadaten["erstellungsart"])),
                    fachliche_grundlage=str(metadaten["fachliche_grundlage"]),
                    version=str(metadaten["version"]),
                    erstellende_oder_pruefende_person=str(
                        metadaten["erstellende_oder_pruefende_person"]
                    ),
                    freigabedatum=date.fromisoformat(str(metadaten["freigabedatum"])),
                    erstellt_am=datetime.fromisoformat(str(metadaten["erstellt_am"])),
                    sha256=str(metadaten["sha256"]),
                    menschlich_bestaetigt=bool(metadaten["menschlich_bestaetigt"]),
                ),
                original_pnml=self._artefakte.lesen(str(referenz["original_pnml_pfad"])),
                replay_pnml=self._artefakte.lesen(str(referenz["replay_pnml_pfad"])),
                replay_sha256=str(referenz["replay_sha256"]),
                sichtbare_transitionen=tuple(
                    str(wert) for wert in meta.get("sichtbare_transitionen", ())
                ),
                startplatz=str(markierungen["startplatz"]),
                endplatz=str(markierungen["endplatz"]),
                markierungen_abgeleitet=bool(markierungen["abgeleitet"]),
                markierungsableitung_bestaetigt=bool(
                    markierungen["ableitung_menschlich_bestaetigt"]
                ),
                workflow_netz=bool(meta["workflow_netz"]),
                sound=bool(meta["sound"]),
                warnungen=tuple(str(wert) for wert in meta.get("warnungen", ())),
            )
        except (
            Domaenenfehler,
            Importintegritaetsfehler,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            return None

    def _aktivitaetsmapping_wiederherstellen(
        self, a_g: dict[str, Any]
    ) -> Aktivitaetsmapping | None:
        referenz = a_g.get("optionale_artefakte", {}).get("aktivitaetsmapping")
        if not isinstance(referenz, dict):
            return None
        try:
            wert = json.loads(self._artefakte.lesen(str(referenz["relativer_pfad"])))
            return Aktivitaetsmapping(
                mapping_id=UUID(str(wert["mapping_id"])),
                projekt_id=UUID(str(wert["projekt_id"])),
                sollmodell_id=UUID(str(wert["sollmodell_id"])),
                exakte_zuordnungen=tuple(
                    (str(paar[0]), str(paar[1])) for paar in wert.get("exakte_zuordnungen", ())
                ),
                manuelle_zuordnungen=tuple(
                    (str(paar[0]), str(paar[1])) for paar in wert.get("manuelle_zuordnungen", ())
                ),
                nur_event_log=tuple(str(name) for name in wert.get("nur_event_log", ())),
                nur_sollmodell=tuple(str(name) for name in wert.get("nur_sollmodell", ())),
                menschlich_bestaetigt=bool(wert["menschlich_bestaetigt"]),
            )
        except (
            Importintegritaetsfehler,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            return None

    def _sollzeitdaten_wiederherstellen(
        self,
        aggregation: Ergebnisaggregation,
        a_g: dict[str, Any],
        performance: PerformanceZeitvergleichKonfiguration | None,
    ) -> tuple[Sollzeitdaten | None, pd.DataFrame | None]:
        """Lädt das unveränderte externe Sollzeit-Original und rekonstruiert seine Tabelle."""
        referenz = a_g.get("optionale_artefakte", {}).get("sollzeitdaten")
        if not isinstance(referenz, dict):
            return None, None
        try:
            originalbytes = self._artefakte.lesen(str(referenz["relativer_pfad"]))
            erwartet = str(referenz["sha256"])
            if hashlib.sha256(originalbytes).hexdigest() != erwartet:
                return None, None
            originaldateiname = str(referenz["originaldateiname"])
            sollzeitdaten_id = UUID(str(referenz["sollzeitdaten_id"]))
            trennzeichen = ","
            kandidaten = (
                (",", ";", "\t", "|") if originaldateiname.lower().endswith(".csv") else (",",)
            )
            erforderliche_spalten = set()
            if performance is not None and performance.sollquelle == "extern":
                erforderliche_spalten = {
                    performance.soll_case_id_spalte,
                    performance.soll_activity_spalte,
                    performance.plan_ende_spalte,
                    performance.plan_start_spalte,
                    performance.soll_auftretensnummer_spalte,
                } - {""}
            gelesene_tabelle = None
            for kandidat in kandidaten:
                _, tabelle = lese_externe_sollzeitdaten(
                    projekt_id=aggregation.projekt_id,
                    dateiname=originaldateiname,
                    originalbytes=originalbytes,
                    trennzeichen=kandidat,
                    sollzeitdaten_id=sollzeitdaten_id,
                )
                if erforderliche_spalten <= set(tabelle.columns):
                    trennzeichen = kandidat
                    gelesene_tabelle = tabelle
                    break
            if gelesene_tabelle is None:
                _, gelesene_tabelle = lese_externe_sollzeitdaten(
                    projekt_id=aggregation.projekt_id,
                    dateiname=originaldateiname,
                    originalbytes=originalbytes,
                    trennzeichen=trennzeichen,
                    sollzeitdaten_id=sollzeitdaten_id,
                )
            dateityp = PurePosixPath(originaldateiname).suffix.removeprefix(".").lower()
            artefakt = Sollzeitdaten(
                sollzeitdaten_id,
                aggregation.projekt_id,
                originaldateiname,
                dateityp,
                originalbytes,
                erwartet,
                aggregation.erstellt_am,
            )
            return artefakt, gelesene_tabelle
        except (Domaenenfehler, Importintegritaetsfehler, KeyError, TypeError, ValueError):
            return None, None

    @staticmethod
    def _attributentscheidungen_aus_ergebnis(wert: object) -> list[dict[str, Any]]:
        if not isinstance(wert, dict) or not isinstance(wert.get("attribute"), list):
            return []
        return [
            {
                "quelle": attribut.get("quelle"),
                "attributspalte": attribut.get("attributspalte"),
                "schluesselspalte": attribut.get("schluesselspalte"),
                "zeitspalte": attribut.get("zeitspalte", ""),
            }
            for attribut in wert["attribute"]
            if isinstance(attribut, dict)
        ]

    def _vorlage_wiederherstellen(
        self,
        aggregation: Ergebnisaggregation,
        a_g: dict[str, Any],
        basis: Aggregationsgrundlage,
    ) -> Aggregationskonfigurationsvorlage:
        konfiguration = a_g.get("konfiguration")
        if not isinstance(konfiguration, dict):
            konfiguration = {}
        struktur = a_g.get("strukturierte_ergebnisse")
        if not isinstance(struktur, dict):
            struktur = {}

        kpi_roh = konfiguration.get("kpi_konfigurationen", a_g.get("kpi_konfigurationen", ()))
        kpi_nach_id: dict[str, KpiKonfiguration] = {}
        if isinstance(kpi_roh, list):
            for wert in kpi_roh:
                wiederhergestellt = self._kpi_konfiguration_wiederherstellen(wert)
                if wiederhergestellt is not None:
                    kpi_nach_id[wiederhergestellt.kpi_id] = wiederhergestellt
        kpi_konfigurationen = tuple(
            kpi_nach_id[kpi_id]
            for kpi_id in basis.projekt.untersuchungsauftrag.ausgewaehlte_kpi_ids
            if kpi_id in kpi_nach_id
        )

        ressourcen_roh = konfiguration.get("ressourcenzuordnung")
        if not isinstance(ressourcen_roh, dict):
            ressourcen_roh = struktur.get("ressourcen", {})
        manuelle: dict[str, tuple[str, ...]] = {}
        offene: tuple[str, ...] = ()
        begruendung = ""
        if isinstance(ressourcen_roh, dict):
            explizit_manuell = ressourcen_roh.get("manuelle_zuordnungen")
            if isinstance(explizit_manuell, dict):
                manuelle = {
                    str(name): tuple(str(eintrag) for eintrag in werte)
                    for name, werte in explizit_manuell.items()
                    if isinstance(werte, list)
                }
            elif isinstance(ressourcen_roh.get("zuordnungen"), list):
                manuelle = {
                    str(wert["aktivitaet"]): tuple(
                        str(name) for name in wert.get("manuell_bestaetigte_ressourcen", ())
                    )
                    for wert in ressourcen_roh["zuordnungen"]
                    if isinstance(wert, dict) and wert.get("manuell_bestaetigte_ressourcen")
                }
            explizit_offen = ressourcen_roh.get("offene_aktivitaeten")
            if isinstance(explizit_offen, list):
                offene = tuple(str(name) for name in explizit_offen)
            elif isinstance(ressourcen_roh.get("zuordnungen"), list):
                offene = tuple(
                    str(wert["aktivitaet"])
                    for wert in ressourcen_roh["zuordnungen"]
                    if isinstance(wert, dict) and wert.get("offen")
                )
            begruendung = str(ressourcen_roh.get("begruendung", ""))

        ressourcenattribute_roh = konfiguration.get("ressourcenattributzuordnungen")
        if not isinstance(ressourcenattribute_roh, list):
            ressourcenattribute_roh = self._attributentscheidungen_aus_ergebnis(
                struktur.get("ressourcen")
            )
        entitaeten_roh = struktur.get("entitaetsinstanzen_und_attribute")
        entitaetsattribute_roh = konfiguration.get("entitaetsattributzuordnungen")
        if not isinstance(entitaetsattribute_roh, list):
            entitaetsattribute_roh = self._attributentscheidungen_aus_ergebnis(entitaeten_roh)
        ressourcenattribute = self._attributzuordnungen_wiederherstellen(ressourcenattribute_roh)
        entitaetsattribute = self._attributzuordnungen_wiederherstellen(entitaetsattribute_roh)
        ressourcenanalyse = analysiere_ressourcen(
            basis.event_log,
            manuelle_zuordnungen=manuelle,
            offene_aktivitaeten=offene,
            nicht_moeglich_begruendung=begruendung,
        )

        warteschlangen_roh = konfiguration.get("bestaetigte_warteschlangen")
        warteschlangen_ergebnis = struktur.get("warteschlangen_und_wartezeiten")
        if not isinstance(warteschlangen_roh, list) and isinstance(warteschlangen_ergebnis, dict):
            warteschlangen_roh = warteschlangen_ergebnis.get("bestaetigte_warteschlangen")

        ankunftsstroeme_roh = konfiguration.get("ankunftsstroeme")
        datenauswahl = struktur.get("zeitbezogene_datenauswahl")
        if not isinstance(ankunftsstroeme_roh, list) and isinstance(datenauswahl, dict):
            zwischenankuenfte = datenauswahl.get("zwischenankunftszeiten", ())
            if isinstance(zwischenankuenfte, list):
                ankunftsstroeme_roh = [
                    wert.get("definition") for wert in zwischenankuenfte if isinstance(wert, dict)
                ]

        performance_block = struktur.get("performance_und_engpassanalyse")
        if not isinstance(performance_block, dict):
            performance_block = {}
        performance = self._performance_wiederherstellen(
            konfiguration.get(
                "performance_zeitvergleich_konfiguration",
                performance_block.get("dt_db_konfiguration"),
            )
        )
        busy = self._busy_ratio_wiederherstellen(
            konfiguration.get(
                "busy_ratio_konfiguration", performance_block.get("busy_ratio_konfiguration")
            )
        )
        sollzeitdaten, sollzeit_tabelle = self._sollzeitdaten_wiederherstellen(
            aggregation, a_g, performance
        )
        conformance = a_g.get("conformance_checking", {})
        return Aggregationskonfigurationsvorlage(
            aggregations_id=aggregation.aggregations_id,
            kpi_konfigurationen=kpi_konfigurationen,
            sollmodell=self._sollmodell_wiederherstellen(a_g),
            aktivitaetsmapping=self._aktivitaetsmapping_wiederherstellen(a_g),
            conformance_ausfuehren=bool(
                konfiguration.get(
                    "conformance_ausfuehren",
                    conformance.get("durchgefuehrt", False)
                    if isinstance(conformance, dict)
                    else False,
                )
            ),
            ressourcenanalyse=ressourcenanalyse,
            ressourcenattributzuordnungen=ressourcenattribute,
            entitaetsattributzuordnungen=entitaetsattribute,
            entitaetstyp=str(
                konfiguration.get(
                    "entitaetstyp",
                    entitaeten_roh.get("entitaetstyp", "")
                    if isinstance(entitaeten_roh, dict)
                    else "",
                )
            ),
            bestaetigte_warteschlangen=self._warteschlangen_wiederherstellen(warteschlangen_roh),
            ankunftsstroeme=self._ankunftsstroeme_wiederherstellen(ankunftsstroeme_roh),
            performance_zeitvergleich_konfiguration=performance,
            performance_zeitvergleich_ausfuehren=bool(
                konfiguration.get("performance_zeitvergleich_ausfuehren", performance is not None)
            ),
            busy_ratio_konfiguration=busy,
            busy_ratio_ausfuehren=bool(
                konfiguration.get("busy_ratio_ausfuehren", busy is not None)
            ),
            sollzeitdaten=sollzeitdaten,
            sollzeit_tabelle=sollzeit_tabelle,
            vereinfachte_zeitspannen_bestaetigt=bool(
                konfiguration.get(
                    "vereinfachte_zeitspannen_bestaetigt",
                    datenauswahl.get("vereinfachte_zeitspannen_bestaetigt", False)
                    if isinstance(datenauswahl, dict)
                    else False,
                )
            ),
        )

    def kompatible_konfigurationsvorlage_laden(
        self,
        projekt_id: UUID,
        freigabe_id: UUID,
        analyse_id: UUID,
    ) -> Aggregationskonfigurationsvorlage | None:
        """Lädt die jüngste Vorlage mit identischer Grundlage und filtert KPI nach aktueller U."""
        basis = self.grundlage_laden(projekt_id, freigabe_id, analyse_id)
        for kandidat in reversed(self._repository.fuer_analyse(projekt_id, analyse_id)):
            if kandidat.freigabe_id != freigabe_id:
                continue
            try:
                aggregation, a_g = self.historisch_laden(kandidat.aggregations_id)
            except (Domaenenfehler, Importintegritaetsfehler):
                continue
            if self._vorlage_ist_fachlich_kompatibel(aggregation, a_g, basis):
                return self._vorlage_wiederherstellen(aggregation, a_g, basis)
        return None

    def rekonfiguration_vorbereiten(
        self,
        projekt_id: UUID,
        freigabe_id: UUID,
        analyse_id: UUID,
    ) -> None:
        """Validiert P/A_D und entfernt A_G-Folgereferenzen aus der aktiven Lineage."""
        self.grundlage_laden(projekt_id, freigabe_id, analyse_id)
        if self._aktive_lineage is not None:
            self._aktive_lineage.bis_endpunkt_zuruecksetzen(projekt_id, LineageEndpunkt.P_A_D)

    def grundlage_fuer_aggregation(self, aggregations_id: UUID) -> Aggregationsgrundlage:
        """Lädt die in A_G unveränderlich fixierten R-Generationen erneut."""
        aggregation, a_g = self.laden(aggregations_id)
        profile = tuple(
            wert
            for wert in a_g.get("lineage", {}).get("datenprofil_r", {}).get("profile", ())
            if isinstance(wert, dict)
        )
        return self.grundlage_laden(
            aggregation.projekt_id,
            aggregation.freigabe_id,
            aggregation.analyse_id,
            profilreferenzen=profile or None,
        )

    def a_g_download_laden(self, aggregations_id: UUID) -> bytes:
        """Liefert nach vollständiger Validierung exakt die gespeicherten A_G-Bytes."""
        aggregation, _ = self.laden(aggregations_id)
        return self._artefakte.lesen(aggregation.relativer_aggregations_pfad)

    def gespeicherte_ergebnisdetails_laden(self, aggregations_id: UUID) -> dict[str, Any]:
        """Lädt bereits validierte A_C-/A_V-Details, ohne Analysen erneut auszuführen."""
        _, a_g = self.laden(aggregations_id)
        details: dict[str, Any] = {}
        referenzen = a_g.get("optionale_artefakte", {})
        if not isinstance(referenzen, dict):
            return details
        for name, schluessel in (
            ("conformance", "conformance_ergebnisse_a_c"),
            ("performance", "potenzielle_verbesserungspotenziale_a_v"),
        ):
            referenz = referenzen.get(schluessel)
            if not isinstance(referenz, dict) or not referenz.get("relativer_pfad"):
                continue
            try:
                details[name] = json.loads(self._artefakte.lesen(str(referenz["relativer_pfad"])))
            except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as fehler:
                raise Importintegritaetsfehler(
                    f"Das gespeicherte Detailergebnis {schluessel} ist ungültig."
                ) from fehler
        return details

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
