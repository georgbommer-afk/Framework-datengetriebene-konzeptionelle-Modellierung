"""Unveränderliche Modelle reproduzierbarer Transformationspläne."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self
from uuid import UUID, uuid4

from framework_mvp.domain.exceptions import Domaenenfehler


class Transformationsart(StrEnum):
    """Unterstützte, explizit konfigurierbare Transformationsarten."""

    SPALTENAUSWAHL = "spaltenauswahl"
    UMBENENNEN = "umbenennen"
    WERTE_ERSETZEN = "werte_ersetzen"
    DATENTYP_KONVERTIEREN = "datentyp_konvertieren"
    PLATZHALTER_BEHANDELN = "platzhalter_behandeln"
    FEHLWERTE_BEHANDELN = "fehlwerte_behandeln"
    DUPLIKATE_BEHANDELN = "duplikate_behandeln"
    AUSREISSER_BEHANDELN = "ausreisser_behandeln"
    ZEILEN_FILTERN = "zeilen_filtern"
    ABGELEITETE_SPALTE = "abgeleitete_spalte"
    TABELLEN_JOIN = "tabellen_join"


@dataclass(frozen=True, slots=True)
class Transformationsschritt:
    """Ein geordneter, dokumentierter und aktivierbarer Transformationsschritt."""

    transformationsschritt_id: UUID
    typ: Transformationsart
    betroffene_spalten: tuple[str, ...]
    parameter_json: str
    reihenfolge: int
    beschreibung: str
    aktiviert: bool
    erstellt_am: datetime
    fachliche_begruendung: str = ""

    def __post_init__(self) -> None:
        """Prüft Reihenfolge, Spaltennamen, Parameter und Zeitstempel."""
        if self.reihenfolge < 1:
            raise Domaenenfehler("Die Reihenfolge eines Transformationsschritts beginnt bei eins.")
        spalten = tuple(name.strip() for name in self.betroffene_spalten if name.strip())
        object.__setattr__(self, "betroffene_spalten", spalten)
        object.__setattr__(self, "beschreibung", self.beschreibung.strip())
        object.__setattr__(self, "fachliche_begruendung", self.fachliche_begruendung.strip())
        try:
            struktur = json.loads(self.parameter_json)
        except json.JSONDecodeError as fehler:
            raise Domaenenfehler(
                "Die Transformationsparameter sind kein gültiges JSON."
            ) from fehler
        if not isinstance(struktur, dict):
            raise Domaenenfehler("Transformationsparameter müssen ein JSON-Objekt sein.")
        if self.erstellt_am.utcoffset() is None:
            raise Domaenenfehler(
                "Der Erstellungszeitpunkt eines Schritts muss zeitzonenbewusst sein."
            )
        object.__setattr__(self, "erstellt_am", self.erstellt_am.astimezone(UTC))

    @property
    def parameter(self) -> dict[str, Any]:
        """Liefert eine neue Parameterstruktur für die Ausführung."""
        return dict(json.loads(self.parameter_json))

    @classmethod
    def neu(
        cls,
        *,
        typ: Transformationsart,
        betroffene_spalten: tuple[str, ...],
        parameter: dict[str, Any],
        reihenfolge: int,
        beschreibung: str,
        fachliche_begruendung: str = "",
    ) -> Self:
        """Erzeugt einen aktivierten Schritt mit stabil serialisierten Parametern."""
        return cls(
            uuid4(),
            typ,
            betroffene_spalten,
            json.dumps(parameter, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            reihenfolge,
            beschreibung,
            True,
            datetime.now(UTC),
            fachliche_begruendung,
        )


@dataclass(frozen=True, slots=True)
class Transformationsplan:
    """Geordneter Plan auf Basis eines oder mehrerer bestätigter Importe."""

    transformationsplan_id: UUID
    projekt_id: UUID
    import_ids: tuple[UUID, ...]
    schritte: tuple[Transformationsschritt, ...]
    erstellt_am: datetime
    geaendert_am: datetime

    def __post_init__(self) -> None:
        """Prüft Quellen, eindeutige IDs und lückenlose Reihenfolgen."""
        if not self.import_ids:
            raise Domaenenfehler("Ein Transformationsplan benötigt mindestens einen Import.")
        if len({wert.transformationsschritt_id for wert in self.schritte}) != len(self.schritte):
            raise Domaenenfehler("Transformationsschritt-IDs müssen eindeutig sein.")
        reihenfolgen = sorted(wert.reihenfolge for wert in self.schritte)
        if reihenfolgen != list(range(1, len(self.schritte) + 1)):
            raise Domaenenfehler("Transformationsschritte benötigen eine lückenlose Reihenfolge.")
        if self.erstellt_am.utcoffset() is None or self.geaendert_am.utcoffset() is None:
            raise Domaenenfehler(
                "Zeitstempel eines Transformationsplans müssen zeitzonenbewusst sein."
            )

    @classmethod
    def neu(cls, projekt_id: UUID, import_ids: tuple[UUID, ...]) -> Self:
        """Erzeugt einen leeren Plan für bestätigte Importquellen."""
        jetzt = datetime.now(UTC)
        return cls(uuid4(), projekt_id, import_ids, (), jetzt, jetzt)


@dataclass(frozen=True, slots=True)
class Transformationshistorie:
    """Nachvollziehbare Wirkung eines ausgeführten Schritts."""

    schritt: int
    aktion: str
    betroffene_spalten: tuple[str, ...]
    zeilen_vorher: int
    zeilen_nachher: int
    spalten_vorher: int
    spalten_nachher: int
    ergebnis_oder_warnung: str
