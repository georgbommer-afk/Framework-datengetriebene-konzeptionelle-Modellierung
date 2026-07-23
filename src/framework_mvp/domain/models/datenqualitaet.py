"""Unveränderliche Modelle regelbasierter Event-Log-Qualität."""

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
