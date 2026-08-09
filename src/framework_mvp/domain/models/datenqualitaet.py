"""Modelle des Quality-Gates sowie kontrolliert lesbarer Legacy-Qualität."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from framework_mvp.domain.exceptions import Domaenenfehler


class Qualitaetsdimension(StrEnum):
    """Unterstützte Qualitätsdimensionen."""

    VOLLSTAENDIGKEIT = "Vollständigkeit"
    VALIDITAET = "Validität"
    KONSISTENZ = "Konsistenz"
    EINDEUTIGKEIT = "Eindeutigkeit"
    ZEITLICHE_PLAUSIBILITAET = "Zeitliche Plausibilität"


class Schweregrad(StrEnum):
    """Schweregrad eines Qualitätsbefunds."""

    INFORMATION = "Information"
    WARNUNG = "Warnung"
    FEHLER = "Fehler"
    BLOCKIEREND = "Blockierend"


class Massnahmenaktion(StrEnum):
    """Explizite, fachlich bestätigbare Reaktionen auf Befunde."""

    AKZEPTIEREN = "Unverändert akzeptieren"
    EREIGNISSE_MARKIEREN = "Ereignisse markieren"
    EREIGNISSE_AUSSCHLIESSEN = "Betroffene Ereignisse ausschließen"
    FAELLE_AUSSCHLIESSEN = "Betroffene Fälle ausschließen"
    DUPLIKATE_ENTFERNEN = "Exakte Duplikate entfernen"
    FESTEN_WERT_SETZEN = "Wert durch expliziten festen Wert ersetzen"
    ZURUECK_ZU_ETL = "An ETL-Schritt zurückverweisen"
    ZURUECK_ZU_MAPPING = "An semantisches Mapping zurückverweisen"
    FACHLICHE_PRUEFUNG = "Fachliche Prüfung erforderlich"


@dataclass(frozen=True, slots=True)
class Qualitaetsregel:
    """Konfigurierbare, nachvollziehbare Qualitätsregel."""

    regel_id: str
    bezeichnung: str
    dimension: Qualitaetsdimension
    schweregrad: Schweregrad
    aktiviert: bool
    parameter_json: str
    beschreibung: str
    empfohlene_reaktion: str

    @property
    def parameter(self) -> dict[str, object]:
        """Liefert eine unabhängige Parameterstruktur."""
        return dict(json.loads(self.parameter_json))


@dataclass(frozen=True, slots=True)
class Qualitaetsbefund:
    """Ergebnis genau einer ausgeführten Regel."""

    regel_id: str
    bezeichnung: str
    dimension: Qualitaetsdimension
    schweregrad: Schweregrad
    betroffene_ereignisse: int
    betroffene_faelle: int
    anteil: float
    beispielindizes: tuple[int, ...]
    betroffene_spalten: tuple[str, ...]
    technische_erlaeuterung: str
    fachliche_empfehlung: str


@dataclass(frozen=True, slots=True)
class Qualitaetsmassnahme:
    """Geordnete explizite Maßnahme für genau einen Regelbefund."""

    massnahme_id: UUID
    regel_id: str
    aktion: Massnahmenaktion
    parameter_json: str
    fachliche_begruendung: str
    betroffene_anzahl: int
    erstellt_am: datetime
    reihenfolge: int

    def __post_init__(self) -> None:
        if self.reihenfolge < 1:
            raise Domaenenfehler("Die Maßnahmenreihenfolge beginnt bei eins.")
        if self.erstellt_am.utcoffset() is None:
            raise Domaenenfehler("Der Maßnahmenzeitpunkt muss zeitzonenbewusst sein.")
        object.__setattr__(self, "erstellt_am", self.erstellt_am.astimezone(UTC))

    @property
    def parameter(self) -> dict[str, object]:
        """Liefert eine unabhängige Parameterstruktur."""
        return dict(json.loads(self.parameter_json))


@dataclass(frozen=True, slots=True)
class Qualitaetsmassnahmenplan:
    """Unveränderlicher geordneter Plan bestätigter Maßnahmen."""

    massnahmen: tuple[Qualitaetsmassnahme, ...]


@dataclass(frozen=True, slots=True)
class QualitaetspruefungArtefakt:
    """Metadaten einer gespeicherten Qualitätsprüfung."""

    quality_run_id: UUID
    projekt_id: UUID
    event_log_id: UUID
    relativer_report_pfad: str
    relativer_massnahmen_pfad: str
    relativer_csv_pfad: str
    sha256: str
    erstellt_am: datetime


class QualityGateBereich(StrEnum):
    """Die vier verbindlichen Prüfbereiche aus Tabelle 3.14."""

    DATENQUELLENKATALOG = "Q"
    ZWISCHENDATENSATZ = "T"
    MAPPINGTABELLE = "M"
    EVENT_LOG = "E"


class QualityGateStatus(StrEnum):
    """Automatischer oder fachlich bestätigter Status eines Prüfkriteriums."""

    AUTOMATISCH_BESTANDEN = "automatisch bestanden"
    AUTOMATISCHER_MANGEL = "automatisch festgestellter Mangel"
    FACHLICHE_BESTAETIGUNG_ERFORDERLICH = "fachliche Bestätigung erforderlich"
    FACHLICH_ALS_MANGEL_BEWERTET = "fachlich als Mangel bewertet"
    FACHLICH_BEGRUENDET_KEIN_MANGEL = "fachlich begründet kein Mangel"
    NICHT_ANWENDBAR = "nicht anwendbar"


class Mappingzustand(StrEnum):
    """Zulässige Zustände der optionalen Mappingtabelle M."""

    NICHT_VORHANDEN = "nicht vorhanden"
    BESTAETIGT_LEER = "bestätigt leer"
    BEFUELLT = "befüllt"


class Freigabestatus(StrEnum):
    """Status einer unveränderten E*-Referenz."""

    FREIGEGEBEN = "freigegeben"


@dataclass(frozen=True, slots=True)
class FachlicheEntscheidung:
    """Begründete menschliche Bewertung genau eines Quality-Gate-Kriteriums."""

    kriterium_id: str
    ist_mangel: bool
    begruendung: str
    ruecksprung_schritt: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kriterium_id", self.kriterium_id.strip())
        object.__setattr__(self, "begruendung", self.begruendung.strip())
        if not self.kriterium_id or not self.begruendung:
            raise Domaenenfehler(
                "Eine fachliche Bewertung benötigt Kriterium und kurze Begründung."
            )
        if self.ruecksprung_schritt is not None and not 1 <= self.ruecksprung_schritt <= 4:
            raise Domaenenfehler("Eine fachliche Bewertung kann nur zu Schritt 1 bis 4 führen.")


@dataclass(frozen=True, slots=True)
class QualityGateBefund:
    """Transparentes Ergebnis eines verbindlichen Kriteriums aus Tabelle 3.14."""

    kriterium_id: str
    bereich: QualityGateBereich
    kriterium: str
    status: QualityGateStatus
    meldung: str
    nicht_uebersteuerbar: bool
    ruecksprung_schritt: int | None = None
    betroffene_ereignisse: int = 0
    betroffene_faelle: int = 0
    anteil: float = 0.0
    technische_quellen: tuple[str, ...] = ()
    beispiele_json: str = "[]"
    begruendung: str = ""

    def __post_init__(self) -> None:
        if self.ruecksprung_schritt is not None and not 1 <= self.ruecksprung_schritt <= 4:
            raise Domaenenfehler("Ein Quality-Gate-Rücksprung muss zu Schritt 1 bis 4 führen.")
        if self.betroffene_ereignisse < 0 or self.betroffene_faelle < 0:
            raise Domaenenfehler("Betroffenenzahlen eines Quality-Gate-Befunds sind ungültig.")
        if not 0.0 <= self.anteil <= 1.0:
            raise Domaenenfehler("Der Anteil eines Quality-Gate-Befunds ist ungültig.")
        try:
            json.loads(self.beispiele_json)
        except json.JSONDecodeError as fehler:
            raise Domaenenfehler("Beispiele eines Quality-Gate-Befunds sind ungültig.") from fehler

    @property
    def blockiert(self) -> bool:
        return self.status in {
            QualityGateStatus.AUTOMATISCHER_MANGEL,
            QualityGateStatus.FACHLICHE_BESTAETIGUNG_ERFORDERLICH,
            QualityGateStatus.FACHLICH_ALS_MANGEL_BEWERTET,
        }


@dataclass(frozen=True, slots=True)
class ErforderlicheSpaltenpruefung:
    """Nachvollziehbare Vollständigkeitsprüfung genau einer verwendeten T-Spalte."""

    technische_bezeichnung: str
    fachliche_bezeichnung: str
    verwendung: str
    technischer_datentyp: str
    fehlende_werte: int
    leere_zeichenketten: int
    nicht_interpretierbare_zeitwerte: int
    beispiele_json: str
    verpflichtender_mindestbestandteil: bool


@dataclass(frozen=True, slots=True)
class QualityGateErgebnis:
    """Vollständige vierteilige Gate-Entscheidungsgrundlage ohne Datenmutation."""

    projekt_id: UUID
    event_log_id: UUID
    zwischendatensatz_id: UUID
    mapping_id: UUID
    mappingtabelle_id: UUID | None
    mappingzustand: Mappingzustand
    datenquellen_ids: tuple[UUID, ...]
    datenquellen_snapshot_json: str
    strukturart: str
    event_log_sha256: str
    zwischendatensatz_sha256: str
    mappingtabelle_sha256: str
    konfiguration_sha256: str
    datenquellen_snapshot_sha256: str
    kettenfingerabdruck: str
    ereignisanzahl: int
    fallanzahl: int
    aktivitaetsanzahl: int
    zeitraum_von: datetime | None
    zeitraum_bis: datetime | None
    befunde: tuple[QualityGateBefund, ...]
    spaltenpruefungen: tuple[ErforderlicheSpaltenpruefung, ...]
    entscheidungen: tuple[FachlicheEntscheidung, ...]

    @property
    def freigabe_moeglich(self) -> bool:
        """Erlaubt E* nur nach allen automatischen und menschlichen Prüfungen."""
        return self.ereignisanzahl > 0 and not any(wert.blockiert for wert in self.befunde)

    @property
    def rueckspruenge(self) -> tuple[int, ...]:
        """Liefert alle ursächlichen vorherigen Schritte ohne Duplikate."""
        return tuple(
            sorted(
                {
                    wert.ruecksprung_schritt
                    for wert in self.befunde
                    if wert.blockiert and wert.ruecksprung_schritt is not None
                }
            )
        )


@dataclass(frozen=True, slots=True)
class Qualitaetsfreigabe:
    """Persistierte Referenz E* auf exakt den unveränderten Event Log E."""

    freigabe_id: UUID
    projekt_id: UUID
    event_log_id: UUID
    event_log_sha256: str
    zwischendatensatz_id: UUID
    zwischendatensatz_sha256: str
    mapping_id: UUID
    mappingtabelle_id: UUID | None
    mappingtabelle_sha256: str
    mappingzustand: Mappingzustand
    datenquellen_ids: tuple[UUID, ...]
    datenquellen_snapshot_sha256: str
    konfiguration_sha256: str
    kettenfingerabdruck: str
    relativer_report_pfad: str
    report_sha256: str
    status: Freigabestatus
    erstellt_am: datetime

    def __post_init__(self) -> None:
        for wert in (
            self.event_log_sha256,
            self.zwischendatensatz_sha256,
            self.datenquellen_snapshot_sha256,
            self.konfiguration_sha256,
            self.kettenfingerabdruck,
            self.report_sha256,
        ):
            if len(wert) != 64:
                raise Domaenenfehler("Eine Prüfsumme der Qualitätsfreigabe ist ungültig.")
        if self.mappingtabelle_sha256 and len(self.mappingtabelle_sha256) != 64:
            raise Domaenenfehler("Die Prüfsumme der Mappingtabelle ist ungültig.")
        if self.erstellt_am.utcoffset() is None:
            raise Domaenenfehler("Der Freigabezeitpunkt muss zeitzonenbewusst sein.")
        object.__setattr__(self, "erstellt_am", self.erstellt_am.astimezone(UTC))

    @property
    def quality_run_id(self) -> UUID:
        """Kompatibler technischer Schlüssel für die bestehende Schritt-6-Persistenz."""
        return self.freigabe_id

    @property
    def sha256(self) -> str:
        """Schritt 6 erhält weiterhin die Prüfsumme des unveränderten E."""
        return self.event_log_sha256
