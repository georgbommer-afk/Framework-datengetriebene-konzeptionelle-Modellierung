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


class StrukturiertesErgebnisStatus(StrEnum):
    """Ableitbarkeit eines in Schritt 7 strukturiert ermittelten Ergebnisses."""

    ABLEITBAR = "ableitbar"
    NICHT_MOEGLICH = "nicht_moeglich"


class Ressourcenzuordnungsmodus(StrEnum):
    """Dokumentierter Ursprung einer Aktivität-Ressourcen-Zuordnung."""

    AUTOMATISCH = "automatisch"
    MANUELL = "manuell"
    GEMISCHT = "gemischt"
    NICHT_MOEGLICH = "nicht_moeglich"


class Zuordnungsherkunft(StrEnum):
    """Nachvollziehbare Herkunft einer einzelnen fachlichen Zuordnung."""

    AUTOMATISCH_BEOBACHTET = "automatisch_beobachtet"
    MANUELL_BESTAETIGT = "manuell_bestaetigt"
    OFFEN = "offen"


class Attributstatus(StrEnum):
    """Zulässige Verdichtung eines bestätigten Ressourcen-/Entitätsattributs."""

    STABIL = "stabil"
    ZEITABHAENGIG_NICHT_EINDEUTIG = "zeitabhaengig_nicht_eindeutig"


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


class Profilkennzahltyp(StrEnum):
    """Semantik einer in R bereits gespeicherten, direkt referenzierbaren Kennzahl."""

    ZEILENANZAHL = "zeilenanzahl"
    GUELTIGE_BEOBACHTUNGEN = "gueltige_beobachtungen"
    ARITHMETISCHES_MITTEL = "arithmetisches_mittel"
    SUMME = "summe"
    ABSOLUTE_HAEUFIGKEIT_INDIKATOR = "absolute_haeufigkeit_indikator"
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
    formel_latex: str = ""


@dataclass(frozen=True, slots=True)
class ProfilkennzahlReferenz:
    """Strukturierte Referenz auf genau eine gespeicherte Profilkennzahl aus R."""

    referenz_id: str
    import_id: str
    datenquellen_id: str
    datenquelle_bezeichnung: str
    originaldateiname: str
    tabellenbezeichnung: str
    spaltenname: str
    kennzahltyp: Profilkennzahltyp
    wert: float
    operator: str = ""
    vergleichswert: str = ""
    auswertbare_beobachtungen: int = 0
    grundgesamtheit: int = 0
    profilversion: int = 1
    profil_sha256: str = ""

    @property
    def anzeigetext(self) -> str:
        """Fachlich lesbare Auswahlbezeichnung ohne technische ID als Primärtext."""
        datensatz = (
            self.datenquelle_bezeichnung
            or self.originaldateiname
            or self.tabellenbezeichnung
            or f"Import {self.import_id}"
        )
        tabelle = (
            f" · Tabelle: {self.tabellenbezeichnung}"
            if self.tabellenbezeichnung and self.tabellenbezeichnung != datensatz
            else ""
        )
        spalte = f" · Spalte: {self.spaltenname}" if self.spaltenname else ""
        typ = {
            Profilkennzahltyp.ZEILENANZAHL: "Zeilenanzahl",
            Profilkennzahltyp.GUELTIGE_BEOBACHTUNGEN: "Anzahl gültiger Beobachtungen",
            Profilkennzahltyp.ARITHMETISCHES_MITTEL: "Arithmetisches Mittel",
            Profilkennzahltyp.SUMME: "Summe",
            Profilkennzahltyp.ABSOLUTE_HAEUFIGKEIT_INDIKATOR: (
                "Absolute Häufigkeit eines Indikators"
            ),
            Profilkennzahltyp.ZEITDIFFERENZ_SUMME: "Summe von Zeitdifferenzen",
        }[self.kennzahltyp]
        operator = {"gleich": "=", "ungleich": "!="}.get(self.operator, self.operator)
        bedingung = (
            f" · Bedingung: {self.spaltenname} {operator} {self.vergleichswert}" if operator else ""
        )
        wert = f"{self.wert:g}".replace(".", ",")
        return (
            f"Datensatz: {datensatz}{tabelle}{spalte} · Kennzahl: {typ}{bedingung} · Wert: {wert}"
        )


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
    profilkennzahl: ProfilkennzahlReferenz | None = None

    def __post_init__(self) -> None:
        if self.bedingungsoperator not in {"", "gleich", "ungleich"}:
            raise Domaenenfehler("Der Wertevergleich einer KPI-Zuordnung ist ungültig.")
        if self.profilreferenz and self.profilkennzahl is not None:
            raise Domaenenfehler(
                "Eine KPI-Rechengröße darf nicht gleichzeitig eine alte und eine strukturierte "
                "Profilreferenz verwenden."
            )
        if self.quelle is not Datenartefakt.DATENPROFIL_R and (
            self.profilreferenz or self.profilkennzahl is not None
        ):
            raise Domaenenfehler(
                "Profilkennzahlen dürfen ausschließlich der Quelle R zugeordnet sein."
            )


@dataclass(frozen=True, slots=True)
class KpiKonfiguration:
    """Bestätigte Zuordnungen für genau eine in U ausgewählte KPI-ID."""

    kpi_id: str
    zuordnungen: tuple[OperandZuordnung, ...]
    einheit: str = ""
    bezugsmenge: str = ""
    direkte_profilreferenz: str = ""
    direkte_profilkennzahl: ProfilkennzahlReferenz | None = None

    def __post_init__(self) -> None:
        if self.direkte_profilreferenz and self.direkte_profilkennzahl is not None:
            raise Domaenenfehler(
                "Eine KPI darf nicht gleichzeitig eine alte und eine strukturierte direkte "
                "Profilreferenz verwenden."
            )


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
    definitionsversion: int = 1


@dataclass(frozen=True, slots=True)
class AktivitaetRessourcenZuordnung:
    """Eindeutige Zuordnung einer Aktivität zu beobachteten oder bestätigten Ressourcen."""

    aktivitaet: str
    ressourcen: tuple[str, ...]
    automatisch_beobachtete_ressourcen: tuple[str, ...] = ()
    manuell_bestaetigte_ressourcen: tuple[str, ...] = ()
    offen: bool = False


@dataclass(frozen=True, slots=True)
class Attributzuordnung:
    """Vom Menschen bestätigte Spalten- und Schlüsselzuordnung aus E* oder T."""

    quelle: Datenartefakt
    attributspalte: str
    schluesselspalte: str
    zeitspalte: str = ""


@dataclass(frozen=True, slots=True)
class Attributbeobachtung:
    """Unverdichtete Attributbeobachtung mit optionalem Zeitbezug."""

    wert: str
    zeitpunkt: str = ""


@dataclass(frozen=True, slots=True)
class Attributauswertung:
    """Eindeutiges statisches Attribut oder erhaltene zeitbezogene Beobachtungen."""

    instanz_id: str
    attribut: str
    status: Attributstatus
    quelle: Datenartefakt
    schluesselspalte: str
    attributspalte: str
    zeitspalte: str
    stabiler_wert: str = ""
    beobachtungen: tuple[Attributbeobachtung, ...] = ()


@dataclass(frozen=True, slots=True)
class RessourcenanalyseErgebnis:
    """In Schritt 7 abgeschlossene Ressourcenentscheidung für A_G."""

    modus: Ressourcenzuordnungsmodus
    herkunft: str
    zuordnungen: tuple[AktivitaetRessourcenZuordnung, ...]
    begruendung: str = ""
    quellspalte: str = ""
    attribute: tuple[Attributauswertung, ...] = ()
    ergebnisversion: int = 2


@dataclass(frozen=True, slots=True)
class Entitaetsinstanz:
    """Eine anhand von E*.case_id beobachtete Entitätsinstanz."""

    instanz_id: str


@dataclass(frozen=True, slots=True)
class EntitaetsanalyseErgebnis:
    """Beobachtete Entitätsinstanzen und nur bestätigt zugeordnete Attribute."""

    instanzen: tuple[Entitaetsinstanz, ...]
    attribute: tuple[Attributauswertung, ...]
    entitaetstyp: str = ""
    herkunft: str = "E*.case_id"
    ergebnisversion: int = 2


@dataclass(frozen=True, slots=True)
class RobusteZeitstatistik:
    """Robuste Zusammenfassung nichtnegativer Zeitdifferenzen in Sekunden."""

    anzahl: int
    mittelwert_sekunden: float
    median_sekunden: float


@dataclass(frozen=True, slots=True)
class PotenzielleWartezeit:
    """Zeitliche Lücke, die allein noch keine Warteschlange belegt."""

    von_aktivitaet: str
    zu_aktivitaet: str
    statistik: RobusteZeitstatistik


@dataclass(frozen=True, slots=True)
class Aktivitaetsbearbeitungszeit:
    """Bearbeitungszeit einer Aktivität aus kanonischem Start und Ende."""

    aktivitaet: str
    statistik: RobusteZeitstatistik
    ressource: str = ""
    ressourcenbezug: bool = False
    gruppierungsbezeichnung: str = "Bearbeitungszeit nach Aktivität; kein Ressourcenbezug verfügbar"


@dataclass(frozen=True, slots=True)
class BestaetigteWarteschlangeninformation:
    """Explizit fachlich bestätigte Warteschlangen-/Pufferinformation."""

    bezeichnung: str
    von_aktivitaet: str
    zu_aktivitaet: str
    quelle: Datenartefakt
    informationsspalte: str
    filterwert: str = ""
    herkunft: Zuordnungsherkunft = Zuordnungsherkunft.MANUELL_BESTAETIGT


@dataclass(frozen=True, slots=True)
class WarteschlangenanalyseErgebnis:
    """Bestätigte Warteschlangen und davon getrennte potenzielle Wartezeiten."""

    status: StrukturiertesErgebnisStatus
    berechnungsregel: str
    potenzielle_wartezeiten: tuple[PotenzielleWartezeit, ...]
    anzahl_ueberlappungen: int
    ausgeschlossene_nicht_auswertbare_werte: int
    begruendung: str = ""
    bestaetigte_warteschlangen: tuple[BestaetigteWarteschlangeninformation, ...] = ()
    ergebnisversion: int = 2

    @property
    def uebergaenge(self) -> tuple[PotenzielleWartezeit, ...]:
        """Kompatibler Lesezugriff für Code vor Ergebnisversion 2."""
        return self.potenzielle_wartezeiten

    @property
    def ausgeschlossene_negative_werte(self) -> int:
        """Kompatibler Lesezugriff; fachlich handelt es sich um Überlappungen."""
        return self.anzahl_ueberlappungen


# Quellcode-Kompatibilität; serialisierte V1-Felder behalten ihre alte Bedeutung.
Uebergangswartezeit = PotenzielleWartezeit


@dataclass(frozen=True, slots=True)
class AnkunftsstromDefinition:
    """Explizit bestätigte fachliche Definition eines Ankunftsstroms q."""

    bezeichnung: str
    quelle: Datenartefakt
    entitaetsspalte: str
    zeitspalte: str
    aktivitaet: str = ""
    filterspalte: str = ""
    filterwert: str = ""
    vorkommensregel: Vorkommensregel | None = None
    vorkommensnummer: int | None = None

    def __post_init__(self) -> None:
        if self.vorkommensregel is Vorkommensregel.AUFTRETENSNUMMER and (
            self.vorkommensnummer is None or self.vorkommensnummer < 1
        ):
            raise Domaenenfehler(
                "Für die Vorkommensregel 'Auftretensnummer' ist eine Nummer ab 1 erforderlich."
            )


@dataclass(frozen=True, slots=True)
class ZwischenankunftszeitErgebnis:
    """Getrennte IAT-Auswertung für genau einen bestätigten Ankunftsstrom."""

    definition: AnkunftsstromDefinition
    status: StrukturiertesErgebnisStatus
    statistik: RobusteZeitstatistik | None
    ausgeschlossene_entitaetsinstanzen: int
    ausschlussgruende: dict[str, int]
    lineage: dict[str, Any]
    berechnungsregel: str


@dataclass(frozen=True, slots=True)
class ZeitbezogeneDatenauswahlErgebnis:
    """Bestätigte Datenbasis und daraus in Schritt 7 abgeleitete Zeitgrößen."""

    status: StrukturiertesErgebnisStatus
    bestaetigte_datenbasis: tuple[str, ...]
    datenbasis_referenzen: dict[str, Any]
    schema_t: tuple[dict[str, str], ...]
    schema_e_stern: tuple[dict[str, str], ...]
    umfang_e_stern: dict[str, Any]
    bearbeitungszeiten: tuple[Aktivitaetsbearbeitungszeit, ...]
    potenzielle_wartezeiten: tuple[PotenzielleWartezeit, ...]
    zwischenankunftszeiten: tuple[ZwischenankunftszeitErgebnis, ...]
    lineage_pro_zeitgroesse: dict[str, Any]
    ausgeschlossene_negative_bearbeitungszeiten: int
    ausgeschlossene_nicht_auswertbare_bearbeitungszeiten: int
    begruendung: str = ""
    ergebnisversion: int = 2

    @property
    def uebergangswartezeiten(self) -> tuple[PotenzielleWartezeit, ...]:
        """Kompatibler Lesezugriff mit fachlich korrigiertem Ergebnistyp."""
        return self.potenzielle_wartezeiten

    @property
    def zwischenankunftszeit(self) -> RobusteZeitstatistik | None:
        """Kompatibler Lesezugriff nur bei genau einem definierten Strom."""
        if len(self.zwischenankunftszeiten) != 1:
            return None
        return self.zwischenankunftszeiten[0].statistik

    @property
    def ankunftsregel(self) -> str:
        """Kompatibler Lesezugriff; neue Artefakte speichern Regeln je Strom."""
        if len(self.zwischenankunftszeiten) != 1:
            return "Kein eindeutig einzelner Ankunftsstrom bestätigt."
        return self.zwischenankunftszeiten[0].berechnungsregel

    @property
    def ausgeschlossene_nicht_auswertbare_ankuenfte(self) -> int:
        return sum(wert.ausgeschlossene_entitaetsinstanzen for wert in self.zwischenankunftszeiten)


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
class PerformanceZeitvergleichKonfiguration:
    """Bestätigte Rollen für die getrennten Gleichungen 3.1 und 3.2."""

    sollquelle: str
    soll_case_id_spalte: str
    soll_activity_spalte: str
    ist_case_id_spalte: str
    ist_activity_spalte: str
    plan_ende_spalte: str
    ist_ende_spalte: str
    plan_start_spalte: str = ""
    ist_start_spalte: str = ""
    soll_auftretensnummer_spalte: str = ""
    vorkommensregel: Vorkommensregel = Vorkommensregel.ERSTES
    fertigstellungsabweichung_aktiv: bool = True
    bearbeitungszeitabweichung_aktiv: bool = False


@dataclass(frozen=True, slots=True)
class PerformanceZeitabweichung:
    """Getrennter Einzelwert für dT und dB ohne Ursacheninterpretation."""

    fall_id: str
    aktivitaet: str
    auftretensnummer: int
    plan_start: str
    plan_ende: str
    ist_start: str
    ist_ende: str
    fertigstellungsabweichung_dt_sekunden: float | None
    klassifikation_dt: str
    bearbeitungszeitabweichung_db_sekunden: float | None
    klassifikation_db: str


@dataclass(frozen=True, slots=True)
class Terminabweichungsstatistik:
    """Aggregierte Fertigstellungsabweichung dT gemäß Gleichung 3.1."""

    anzahl: int
    verspaetet: int
    planmaessig: int
    vorzeitig: int
    mittelwert_sekunden: float
    median_sekunden: float


@dataclass(frozen=True, slots=True)
class Bearbeitungszeitabweichungsstatistik:
    """Aggregierte Bearbeitungszeitabweichung dB gemäß Gleichung 3.2."""

    anzahl: int
    laenger_als_geplant: int
    gleich_geplant: int
    kuerzer_als_geplant: int
    mittelwert_sekunden: float
    median_sekunden: float


@dataclass(frozen=True, slots=True)
class PerformanceZeitvergleichErgebnis:
    """A_V-Einzelwerte und getrennte Statistiken für dT und dB."""

    auswertungs_id: UUID
    konfiguration: PerformanceZeitvergleichKonfiguration
    einzelwerte: tuple[PerformanceZeitabweichung, ...]
    dt_statistik: Terminabweichungsstatistik | None
    db_statistik: Bearbeitungszeitabweichungsstatistik | None
    ausschlussgruende: dict[str, int]
    erstellt_am: datetime
    artefaktversion: int = 2


@dataclass(frozen=True, slots=True)
class BusyRatioKonfiguration:
    """Bestätigte Zeitrollen und Zeitraum der ressourcenbezogenen Engpassanalyse."""

    ressourcenspalte: str
    startspalte: str
    endspalte: str
    zeitraum_von: datetime | None = None
    zeitraum_bis: datetime | None = None

    def __post_init__(self) -> None:
        if self.zeitraum_von is not None and self.zeitraum_von.utcoffset() is None:
            raise Domaenenfehler("Der Beginn des Busy-Ratio-Zeitraums benötigt eine Zeitzone.")
        if self.zeitraum_bis is not None and self.zeitraum_bis.utcoffset() is None:
            raise Domaenenfehler("Das Ende des Busy-Ratio-Zeitraums benötigt eine Zeitzone.")
        if (
            self.zeitraum_von is not None
            and self.zeitraum_bis is not None
            and self.zeitraum_von > self.zeitraum_bis
        ):
            raise Domaenenfehler("Der Busy-Ratio-Zeitraum ist chronologisch ungültig.")


@dataclass(frozen=True, slots=True)
class BusyRatioEinzelwert:
    """Gleichungen 3.3 bis 3.5 für eine Ausführung und deren Nachfolger."""

    ressource: str
    fall_id: str
    aktivitaet: str
    ausfuehrungsindex: int
    ist_start: str
    ist_ende: str
    naechster_ist_start: str
    bearbeitungszeit_sekunden: float
    ressourcenbezogene_zwischenankunftszeit_sekunden: float
    busy_ratio: float


@dataclass(frozen=True, slots=True)
class BusyRatioRessourcenstatistik:
    """Busy-Ratio-Aggregation für genau eine Ressource."""

    ressource: str
    anzahl_gueltige_busy_ratios: int
    mittelwert_busy_ratio: float | None
    median_busy_ratio: float | None
    minimum_busy_ratio: float | None
    maximum_busy_ratio: float | None
    ausgeschlossene_beobachtungen: int


@dataclass(frozen=True, slots=True)
class BusyRatioErgebnis:
    """Ressourcenbezogener Engpasshinweis, getrennt von Ankunftsströmen q."""

    auswertungs_id: UUID
    konfiguration: BusyRatioKonfiguration
    einzelwerte: tuple[BusyRatioEinzelwert, ...]
    ressourcenstatistiken: tuple[BusyRatioRessourcenstatistik, ...]
    potenzieller_engpass: str
    ausschlussgruende: dict[str, int]
    berechnungsregel: str
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
