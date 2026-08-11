"""Unveränderliche Domänenmodelle für Algorithmus 7."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from framework_mvp.domain.exceptions import Domaenenfehler


class Aggregationsstatus(StrEnum):
    """Persistenzstatus eines Aggregationslaufs."""

    GESPEICHERT = "gespeichert"


class KpiStatus(StrEnum):
    """Fachlicher Status einer ausgewählten Kennzahl."""

    BERECHNET = "berechnet"
    NICHT_BERECHENBAR = "nicht_berechenbar"


class Datenartefakt(StrEnum):
    """Zulässige Quellen einer KPI-Rechengröße."""

    DATENPROFIL_R = "R"
    ZWISCHENDATENSATZ_T = "T"
    EVENT_LOG_E_STERN = "E*"


class Operandentyp(StrEnum):
    """Technische Ermittlung einer fachlich definierten Rechengröße."""

    ANZAHL = "anzahl"
    SUMME = "summe"
    MITTELWERT = "mittelwert"
    MESSWERTE = "messwerte"
    ZEITDIFFERENZ_SUMME = "zeitdifferenz_summe"


class SollmodellErstellungsart(StrEnum):
    """Die zwei persistierbaren Erstellungsarten von P_Soll."""

    LINEARER_ASSISTENT = "linearer_assistent"
    PNML_UPLOAD = "pnml_upload"


class SollmodellEntscheidung(StrEnum):
    """Die drei im MVP angebotenen Sollmodellpfade."""

    KEIN_SOLLMODELL = "kein_sollmodell"
    LINEARER_ASSISTENT = "linearer_assistent"
    KOMPLEXES_PNML = "komplexes_pnml"


class Vergleichsebene(StrEnum):
    """Granularität eines direkten Soll-Ist-Zeitvergleichs."""

    FALL = "fallbezogen"
    EREIGNIS = "ereignisbezogen"


class Vorkommensregel(StrEnum):
    """Explizite Auswahl bei wiederholten Aktivitäten."""

    ERSTES = "erstes"
    LETZTES = "letztes"
    AUFTRETENSNUMMER = "auftretensnummer"


@dataclass(frozen=True, slots=True)
class KpiOperandDefinition:
    """Feste Rechengröße innerhalb einer KPI-Gleichung."""

    operand_id: str
    bezeichnung: str
    operandentyp: Operandentyp
    zulaessige_quellen: tuple[Datenartefakt, ...]
    erwarteter_datentyp: str


@dataclass(frozen=True, slots=True)
class KpiDefinition:
    """Versionierte, nicht frei änderbare KPI-Definition aus A.7 bis A.10."""

    kpi_id: str
    bezeichnung: str
    formel: str
    operanden: tuple[KpiOperandDefinition, ...]
    ergebnisdatentyp: str
    einheit: str
    einheiteneingabe_erforderlich: bool
    bezugsmenge: str
    definitionsversion: int = 1


@dataclass(frozen=True, slots=True)
class OperandZuordnung:
    """Explizite menschliche Zuordnung einer Rechengröße, ohne Semantik-Raten."""

    operand_id: str
    quelle: Datenartefakt
    spalte: str = ""
    zweite_spalte: str = ""
    bedingungsoperator: str = ""
    bedingungswert: str = ""
    startaktivitaet: str = ""
    endaktivitaet: str = ""
    vorkommensregel: Vorkommensregel = Vorkommensregel.ERSTES
    profilreferenz: str = ""

    def __post_init__(self) -> None:
        if self.bedingungsoperator not in {"", "gleich", "ungleich"}:
            raise Domaenenfehler("Der Wertevergleich einer KPI-Zuordnung ist ungültig.")


@dataclass(frozen=True, slots=True)
class KpiKonfiguration:
    """Bestätigte Zuordnungen für genau eine in U ausgewählte KPI-ID."""

    kpi_id: str
    zuordnungen: tuple[OperandZuordnung, ...]
    einheit: str = ""
    bezugsmenge: str = ""
    direkte_profilreferenz: str = ""


@dataclass(frozen=True, slots=True)
class KpiErgebnis:
    """Nachvollziehbares Ergebnis oder konkret dokumentierte Nichtberechenbarkeit."""

    kpi_id: str
    bezeichnung: str
    status: KpiStatus
    formel: str
    zugeordnete_operanden: tuple[dict[str, Any], ...]
    quellenreferenzen: tuple[dict[str, Any], ...]
    wertebedingungen: tuple[dict[str, Any], ...]
    bezugsmenge: str
    einheit: str
    ausgeschlossene_werte: int
    rechenweg: str
    zwischensummen: dict[str, Any]
    ergebnis: float | None
    fehlende_voraussetzungen: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SollmodellMetadaten:
    """Human-in-the-Loop-Metadaten eines eigenständigen Sollprozessmodells."""

    sollmodell_id: UUID
    projekt_id: UUID
    bezeichnung: str
    erstellungsart: SollmodellErstellungsart
    fachliche_grundlage: str
    version: str
    erstellende_oder_pruefende_person: str
    freigabedatum: date
    erstellt_am: datetime
    sha256: str
    menschlich_bestaetigt: bool

    def __post_init__(self) -> None:
        for bezeichnung, wert in (
            ("Bezeichnung", self.bezeichnung),
            ("fachliche Grundlage", self.fachliche_grundlage),
            ("Version", self.version),
            ("erstellende oder prüfende Person", self.erstellende_oder_pruefende_person),
        ):
            if not wert.strip():
                raise Domaenenfehler(f"Das Sollmodell benötigt eine {bezeichnung}.")
        if len(self.sha256) != 64:
            raise Domaenenfehler("Die Prüfsumme des Sollmodells ist ungültig.")
        if self.erstellt_am.utcoffset() is None:
            raise Domaenenfehler(
                "Der Erstellungszeitpunkt des Sollmodells muss zeitzonenbewusst sein."
            )
        if not self.menschlich_bestaetigt:
            raise Domaenenfehler(
                "Das Sollmodell muss vor seiner Verwendung menschlich bestätigt werden."
            )
        object.__setattr__(self, "erstellt_am", self.erstellt_am.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class SollmodellVorschau:
    """Validiertes P_Soll mit unverändertem Original und getrennter Replay-Fassung."""

    metadaten: SollmodellMetadaten
    original_pnml: bytes
    replay_pnml: bytes
    replay_sha256: str
    sichtbare_transitionen: tuple[str, ...]
    startplatz: str
    endplatz: str
    markierungen_abgeleitet: bool
    markierungsableitung_bestaetigt: bool
    workflow_netz: bool
    sound: bool
    warnungen: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Aktivitaetsmapping:
    """Exakte und ausdrücklich bestätigte Bezeichnungszuordnung für Replay-Kopien."""

    mapping_id: UUID
    projekt_id: UUID
    sollmodell_id: UUID
    exakte_zuordnungen: tuple[tuple[str, str], ...]
    manuelle_zuordnungen: tuple[tuple[str, str], ...]
    nur_event_log: tuple[str, ...]
    nur_sollmodell: tuple[str, ...]
    menschlich_bestaetigt: bool


@dataclass(frozen=True, slots=True)
class TokenDiagnose:
    """Tokenmengen einer unveränderten vollständigen Spur aus E*."""

    fall_id: str
    produzierte_tokens: int
    konsumierte_tokens: int
    fehlende_tokens: int
    verbleibende_tokens: int
    konform: bool
    auswertbar: bool = True
    begruendung: str = ""


@dataclass(frozen=True, slots=True)
class ConformanceErgebnis:
    """A_C gemäß Token-Based Replay und Gleichung 3.13."""

    conformance_id: UUID
    mapping_id: UUID
    fallbezogene_diagnosen: tuple[TokenDiagnose, ...]
    produzierte_tokens: int
    konsumierte_tokens: int
    fehlende_tokens: int
    verbleibende_tokens: int
    konforme_faelle: int
    abweichende_faelle: int
    fitness: float | None
    fitness_plausibilisierung_pm4py: float | None
    ausgeschlossene_faelle: tuple[dict[str, str], ...]
    pm4py_version: str
    erstellt_am: datetime
    artefaktversion: int = 1


@dataclass(frozen=True, slots=True)
class Sollzeitdaten:
    """Optionales, von T und E* getrenntes Original-Sollzeitdatenartefakt."""

    sollzeitdaten_id: UUID
    projekt_id: UUID
    originaldateiname: str
    dateityp: str
    originalbytes: bytes
    sha256: str
    erstellt_am: datetime


@dataclass(frozen=True, slots=True)
class ZeitvergleichKonfiguration:
    """Menschlich bestätigte Rollen und Verknüpfungsregeln eines Zeitvergleichs."""

    ebene: Vergleichsebene
    sollquelle: str
    soll_case_id_spalte: str
    soll_zeitstempel_spalte: str
    ist_case_id_spalte: str
    ist_zeitstempel_spalte: str
    soll_activity_spalte: str = ""
    ist_activity_spalte: str = "activity"
    ausgewaehlte_ist_aktivitaet: str = ""
    soll_auftretensnummer_spalte: str = ""
    vorkommensregel: Vorkommensregel = Vorkommensregel.ERSTES


@dataclass(frozen=True, slots=True)
class Zeitabweichung:
    """Eine direkte, nicht kausal interpretierte Soll-Ist-Abweichung."""

    vergleichsebene: Vergleichsebene
    fall_id: str
    aktivitaet: str
    auftretensnummer: int | None
    soll_zeitstempel: str
    ist_zeitstempel: str
    abweichung_sekunden: float
    klassifikation: str


@dataclass(frozen=True, slots=True)
class ZeitvergleichErgebnis:
    """A_V mit Einzelwerten und getrennten Zuordnungszuständen."""

    auswertungs_id: UUID
    konfiguration: ZeitvergleichKonfiguration
    abweichungen: tuple[Zeitabweichung, ...]
    aggregierte_anzahlen: dict[str, int]
    fehlende_sollwerte: int
    fehlende_istwerte: int
    mehrdeutige_datensaetze: int
    nicht_zuordenbare_datensaetze: int
    erstellt_am: datetime
    artefaktversion: int = 1


@dataclass(frozen=True, slots=True)
class Ergebnisaggregation:
    """Persistierte SQLite-Metadaten des Artefakts A_G."""

    aggregations_id: UUID
    projekt_id: UUID
    spezifikations_id: UUID
    freigabe_id: UUID
    event_log_id: UUID
    analyse_id: UUID
    eingabefingerabdruck: str
    konfigurationsfingerabdruck: str
    relativer_aggregations_pfad: str
    aggregations_sha256: str
    status: Aggregationsstatus
    erstellt_am: datetime

    def __post_init__(self) -> None:
        for wert in (
            self.eingabefingerabdruck,
            self.konfigurationsfingerabdruck,
            self.aggregations_sha256,
        ):
            if len(wert) != 64:
                raise Domaenenfehler("Eine Prüfsumme der Ergebnisaggregation ist ungültig.")
        if self.erstellt_am.utcoffset() is None:
            raise Domaenenfehler("Der Aggregationszeitpunkt muss zeitzonenbewusst sein.")
        object.__setattr__(self, "erstellt_am", self.erstellt_am.astimezone(UTC))
