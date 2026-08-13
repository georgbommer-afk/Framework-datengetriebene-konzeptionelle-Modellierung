"""Eine Fortschrittsdefinition für Projektkopf und Lehrenden-Dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from framework_mvp.application.autorisierung import AutorisierungsService
from framework_mvp.application.ports.fortschritt_repository import FortschrittRepository
from framework_mvp.application.ports.zugriffs_repository import ZugriffsRepository
from framework_mvp.domain.models.zugriff import (
    Projektaktion,
    Projektfortschritt,
    Zugriffskontext,
    phase_fuer_schritt,
)

PHASENNAMEN = {
    1: "Aufbereitung der Datenbasis",
    2: "Datengetriebene Analyse des Systems",
    3: "Überführung in das konzeptionelle Modell",
}

FACHLICHE_UNTERSCHRITTE: dict[int, tuple[str, ...]] = {
    1: (
        "Problem und Systemgrenze",
        "Untersuchungszweck und Logistikziele",
        "Systemklassifikation",
        "Auswertungen und KPIs",
        "Untersuchungsauftrag und Systemprofil",
    ),
    2: (
        "Datenquelle und Datei",
        "Tabelle und Vorschau",
        "Datenprofil",
        "Transformieren und verknüpfen",
        "Zwischendatensatz",
    ),
    3: ("Datenstruktur", "Rollen und Aktivität", "Prüfen und speichern"),
    4: (
        "Strukturart festlegen",
        "Mindestbestandteile konfigurieren",
        "Zusätzliche Attribute auswählen",
        "Event Log erzeugen und prüfen",
        "Event Log ausgeben und speichern",
    ),
    5: (
        "Artefaktkette übernehmen",
        "Automatische Pflichtprüfungen",
        "Fachlich bewerten",
        "Freigeben oder zurückspringen",
    ),
    6: (
        "Freigegebenen Event Log übernehmen",
        "Schwellwert und Prozessnotation festlegen",
        "P und Discovery-Ergebnisse speichern",
    ),
    7: ("Ergebnisse", "Sollbezug", "Aggregation speichern"),
    8: ("Eingaben", "Ableitung", "Modellbestandteile speichern"),
    9: ("Offene Punkte", "Ergänzen", "Validieren und speichern"),
    10: ("Modell prüfen", "Ausgabe erzeugen"),
}


@dataclass(frozen=True, slots=True)
class Fortschrittsanzeige:
    projekt_id: UUID
    schritt: int
    unterschritt: str
    phase: int
    phasenname: str
    zaehler: int
    nenner: int
    prozent: int
    status: str
    gespeichert_am: datetime
    letzte_aktivitaet: datetime


def berechne_fortschritt(schritt: int, unterschritt: str = "") -> tuple[int, int]:
    """Berechnet fachliche Teilstände; technische UI-Abschnitte zählen nicht."""
    schritt = min(10, max(1, schritt))
    vorher = sum(len(FACHLICHE_UNTERSCHRITTE[nr]) for nr in range(1, schritt))
    aktuelle = FACHLICHE_UNTERSCHRITTE[schritt]
    try:
        index = aktuelle.index(unterschritt) + 1
    except ValueError:
        index = 0
    return vorher + index, sum(map(len, FACHLICHE_UNTERSCHRITTE.values()))


class FortschrittService:
    """Persistiert und rekonstruiert Fortschritt mit derselben zentralen Berechnung."""

    def __init__(
        self,
        zugriffs_repository: ZugriffsRepository,
        artefakt_repository: FortschrittRepository,
        autorisierung: AutorisierungsService,
    ) -> None:
        self._zugriff = zugriffs_repository
        self._artefakte = artefakt_repository
        self._autorisierung = autorisierung

    def aktualisieren(
        self,
        kontext: Zugriffskontext,
        projekt_id: UUID,
        *,
        schritt: int,
        unterschritt: str,
        status: str = "in_bearbeitung",
    ) -> Fortschrittsanzeige:
        self._autorisierung.projekt_zugriff_pruefen(kontext, projekt_id, Projektaktion.BEARBEITEN)
        gespeicherter_schritt = self._artefakte.hoechster_gespeicherter_schritt(projekt_id)
        effektiver_schritt = max(schritt, gespeicherter_schritt)
        effektiver_unterschritt = unterschritt if effektiver_schritt == schritt else ""
        zaehler, nenner = berechne_fortschritt(effektiver_schritt, effektiver_unterschritt)
        jetzt = datetime.now(UTC)
        alt = self._zugriff.fortschritt_laden(projekt_id)
        self._zugriff.fortschritt_speichern(
            Projektfortschritt(
                projekt_id=projekt_id,
                framework_schritt=effektiver_schritt,
                fachlicher_unterschritt=effektiver_unterschritt,
                fortschritt_zaehler=zaehler,
                fortschritt_nenner=nenner,
                phase=phase_fuer_schritt(effektiver_schritt),
                status=status,
                gespeichert_am=jetzt,
                revision=1 if alt is None else alt.revision + 1,
            )
        )
        return self.laden(kontext, projekt_id)

    def laden(
        self, kontext: Zugriffskontext, projekt_id: UUID, *, dashboard: bool = False
    ) -> Fortschrittsanzeige:
        aktion = Projektaktion.FORTSCHRITT_ANSEHEN if dashboard else Projektaktion.ANSEHEN
        self._autorisierung.projekt_zugriff_pruefen(kontext, projekt_id, aktion)
        gespeichert = self._zugriff.fortschritt_laden(projekt_id)
        artefaktschritt = self._artefakte.hoechster_gespeicherter_schritt(projekt_id)
        if gespeichert is None or artefaktschritt > gespeichert.framework_schritt:
            schritt = max(1, artefaktschritt)
            zaehler, nenner = berechne_fortschritt(schritt)
            gespeichert = Projektfortschritt(
                projekt_id,
                schritt,
                "",
                zaehler,
                nenner,
                phase_fuer_schritt(schritt),
                "in_bearbeitung",
                datetime.now(UTC),
                1,
            )
            self._zugriff.fortschritt_speichern(gespeichert)
        zuordnung = self._zugriff.projektzugehoerigkeit_laden(projekt_id)
        assert zuordnung is not None
        return Fortschrittsanzeige(
            projekt_id=projekt_id,
            schritt=gespeichert.framework_schritt,
            unterschritt=gespeichert.fachlicher_unterschritt,
            phase=gespeichert.phase,
            phasenname=PHASENNAMEN[gespeichert.phase],
            zaehler=gespeichert.fortschritt_zaehler,
            nenner=gespeichert.fortschritt_nenner,
            prozent=round(100 * gespeichert.fortschritt_zaehler / gespeichert.fortschritt_nenner),
            status=gespeichert.status,
            gespeichert_am=gespeichert.gespeichert_am,
            letzte_aktivitaet=zuordnung.zuletzt_aktiv_am,
        )
