"""Persistente Navigation und fachlich gewichteter Projektfortschritt."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from framework_mvp.application.aktive_lineage_service import AktiveLineageService
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
        "Semantische Rollen und Attribute auswählen",
        "Event Log erzeugen und prüfen",
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
    7: ("Ergebnisse fachlich aggregieren",),
    8: ("Modellbestandteile ableiten",),
    9: ("Modell ergänzen und validieren",),
    10: ("Konzeptionelles Modell ausgeben",),
}

PHASENSCHRITTE: dict[int, tuple[int, ...]] = {
    1: (1, 2, 3, 4, 5),
    2: (6, 7),
    3: (8, 9, 10),
}
LEERER_ABSCHLUSS = (0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
VOLLSTAENDIGER_ABSCHLUSS = tuple(len(FACHLICHE_UNTERSCHRITTE[schritt]) for schritt in range(1, 11))


def _normalisiere_abschluesse(werte: tuple[int, ...]) -> tuple[int, ...]:
    if len(werte) != 10:
        return LEERER_ABSCHLUSS
    return tuple(
        min(max(int(werte[schritt - 1]), 0), len(FACHLICHE_UNTERSCHRITTE[schritt]))
        for schritt in range(1, 11)
    )


def berechne_fortschritt(abschluesse: tuple[int, ...]) -> float:
    """Berechnet 10 Prozentpunkte je Schritt, intern gleichmäßig geteilt."""
    normalisiert = _normalisiere_abschluesse(abschluesse)
    return sum(
        10.0 * normalisiert[schritt - 1] / len(FACHLICHE_UNTERSCHRITTE[schritt])
        for schritt in range(1, 11)
    )


def berechne_phasenfortschritt(abschluesse: tuple[int, ...]) -> tuple[float, float, float]:
    """Normalisiert jede der drei Phasen unabhängig auf 0 bis 100 Prozent."""
    normalisiert = _normalisiere_abschluesse(abschluesse)
    ergebnis: list[float] = []
    for phase in range(1, 4):
        schritte = PHASENSCHRITTE[phase]
        anteile = [
            normalisiert[schritt - 1] / len(FACHLICHE_UNTERSCHRITTE[schritt])
            for schritt in schritte
        ]
        ergebnis.append(100.0 * sum(anteile) / len(schritte))
    return (ergebnis[0], ergebnis[1], ergebnis[2])


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
    phasenprozente: tuple[int, int, int]
    abgeschlossene_unterschritte: tuple[int, ...]
    status: str
    gespeichert_am: datetime
    letzte_aktivitaet: datetime
    revision: int


class FortschrittService:
    """Ändert Abschlussstände nur über ausdrücklich benannte Erfolgsereignisse."""

    def __init__(
        self,
        zugriffs_repository: ZugriffsRepository,
        artefakt_repository: FortschrittRepository,
        autorisierung: AutorisierungsService,
        aktive_lineage: AktiveLineageService | None = None,
    ) -> None:
        self._zugriff = zugriffs_repository
        self._artefakte = artefakt_repository
        self._autorisierung = autorisierung
        self._aktive_lineage = aktive_lineage

    def position_aktualisieren(
        self,
        kontext: Zugriffskontext,
        projekt_id: UUID,
        *,
        schritt: int,
        unterschritt: str,
    ) -> Fortschrittsanzeige:
        """Persistiert ausschließlich die aktuelle Navigation, niemals Abschluss."""
        self._autorisierung.projekt_zugriff_pruefen(kontext, projekt_id, Projektaktion.BEARBEITEN)
        schritt = min(max(schritt, 1), 10)
        if unterschritt not in FACHLICHE_UNTERSCHRITTE[schritt]:
            unterschritt = FACHLICHE_UNTERSCHRITTE[schritt][0]
        alt = self._zugriff.fortschritt_laden(projekt_id)
        abschluesse = (
            LEERER_ABSCHLUSS
            if alt is None
            else _normalisiere_abschluesse(alt.abgeschlossene_unterschritte)
        )
        if (
            alt is not None
            and alt.framework_schritt == schritt
            and alt.fachlicher_unterschritt == unterschritt
            and alt.phase == phase_fuer_schritt(schritt)
        ):
            return self._anzeige(alt)
        self._speichern(
            projekt_id=projekt_id,
            schritt=schritt,
            unterschritt=unterschritt,
            abschluesse=abschluesse,
            status=alt.status if alt is not None else "in_bearbeitung",
            alt=alt,
        )
        return self.laden(kontext, projekt_id)

    def unterschritt_abschliessen(
        self,
        kontext: Zugriffskontext,
        projekt_id: UUID,
        *,
        schritt: int,
        unterschritt: int,
    ) -> Fortschrittsanzeige:
        """Markiert nach einem erfolgreichen Fachereignis einen Unterpunkt als erledigt."""
        self._autorisierung.projekt_zugriff_pruefen(kontext, projekt_id, Projektaktion.BEARBEITEN)
        if schritt not in FACHLICHE_UNTERSCHRITTE:
            raise ValueError("Der Framework-Schritt ist ungültig.")
        maximum = len(FACHLICHE_UNTERSCHRITTE[schritt])
        if not 1 <= unterschritt <= maximum:
            raise ValueError("Der fachliche Unterschritt ist ungültig.")
        alt = self._zugriff.fortschritt_laden(projekt_id)
        abschluesse = list(
            LEERER_ABSCHLUSS
            if alt is None
            else _normalisiere_abschluesse(alt.abgeschlossene_unterschritte)
        )
        if abschluesse[schritt - 1] >= unterschritt:
            return self._anzeige(alt) if alt is not None else self.laden(kontext, projekt_id)
        abschluesse[schritt - 1] = unterschritt
        normalisiert = tuple(abschluesse)
        status = "abgeschlossen" if normalisiert == VOLLSTAENDIGER_ABSCHLUSS else "in_bearbeitung"
        self._speichern(
            projekt_id=projekt_id,
            schritt=alt.framework_schritt if alt is not None else schritt,
            unterschritt=(
                alt.fachlicher_unterschritt
                if alt is not None
                else FACHLICHE_UNTERSCHRITTE[schritt][unterschritt - 1]
            ),
            abschluesse=normalisiert,
            status=status,
            alt=alt,
        )
        return self.laden(kontext, projekt_id)

    def schritt_abschliessen(
        self, kontext: Zugriffskontext, projekt_id: UUID, *, schritt: int
    ) -> Fortschrittsanzeige:
        return self.unterschritt_abschliessen(
            kontext,
            projekt_id,
            schritt=schritt,
            unterschritt=len(FACHLICHE_UNTERSCHRITTE[schritt]),
        )

    def projekt_abschliessen(
        self, kontext: Zugriffskontext, projekt_id: UUID
    ) -> Fortschrittsanzeige:
        """Persistiert einen nachweislich vollständig erzeugten Projektstand atomar."""
        self._autorisierung.projekt_zugriff_pruefen(kontext, projekt_id, Projektaktion.BEARBEITEN)
        alt = self._zugriff.fortschritt_laden(projekt_id)
        if (
            alt is not None
            and alt.framework_schritt == 10
            and alt.fachlicher_unterschritt == FACHLICHE_UNTERSCHRITTE[10][-1]
            and alt.abgeschlossene_unterschritte == VOLLSTAENDIGER_ABSCHLUSS
            and alt.status == "abgeschlossen"
        ):
            return self._anzeige(alt)
        self._speichern(
            projekt_id=projekt_id,
            schritt=10,
            unterschritt=FACHLICHE_UNTERSCHRITTE[10][-1],
            abschluesse=VOLLSTAENDIGER_ABSCHLUSS,
            status="abgeschlossen",
            alt=alt,
        )
        return self.laden(kontext, projekt_id)

    def auf_datenbasis_zuruecksetzen(
        self,
        kontext: Zugriffskontext,
        projekt_id: UUID,
        *,
        unterschritt: str,
    ) -> None:
        """Verwirft nach neuer ETL-Basis die Abschlüsse ab Schritt 2."""
        self._autorisierung.projekt_zugriff_pruefen(kontext, projekt_id, Projektaktion.BEARBEITEN)
        alt = self._zugriff.fortschritt_laden(projekt_id)
        abschluesse = list(
            LEERER_ABSCHLUSS
            if alt is None
            else _normalisiere_abschluesse(alt.abgeschlossene_unterschritte)
        )
        abschluesse[1:] = [0] * 9
        neuer_stand = tuple(abschluesse)
        if (
            alt is not None
            and alt.framework_schritt == 2
            and alt.fachlicher_unterschritt == unterschritt
            and alt.abgeschlossene_unterschritte == neuer_stand
            and alt.status == "in_bearbeitung"
        ):
            return
        self._speichern(
            projekt_id=projekt_id,
            schritt=2,
            unterschritt=unterschritt,
            abschluesse=neuer_stand,
            status="in_bearbeitung",
            alt=alt,
        )

    def laden(
        self, kontext: Zugriffskontext, projekt_id: UUID, *, dashboard: bool = False
    ) -> Fortschrittsanzeige:
        """Lädt rein lesend; weder Artefakte noch Position werden als Abschluss gewertet."""
        aktion = Projektaktion.FORTSCHRITT_ANSEHEN if dashboard else Projektaktion.ANSEHEN
        self._autorisierung.projekt_zugriff_pruefen(kontext, projekt_id, aktion)
        gespeichert = self._zugriff.fortschritt_laden(projekt_id)
        if gespeichert is None:
            zuordnung = self._zugriff.projektzugehoerigkeit_laden(projekt_id)
            assert zuordnung is not None
            gespeichert = Projektfortschritt(
                projekt_id=projekt_id,
                framework_schritt=1,
                fachlicher_unterschritt=FACHLICHE_UNTERSCHRITTE[1][0],
                fortschritt_zaehler=0,
                fortschritt_nenner=sum(map(len, FACHLICHE_UNTERSCHRITTE.values())),
                phase=1,
                status="in_bearbeitung",
                gespeichert_am=zuordnung.zuletzt_aktiv_am,
                revision=0,
                abgeschlossene_unterschritte=LEERER_ABSCHLUSS,
            )
        return self._anzeige(gespeichert)

    def _speichern(
        self,
        *,
        projekt_id: UUID,
        schritt: int,
        unterschritt: str,
        abschluesse: tuple[int, ...],
        status: str,
        alt: Projektfortschritt | None,
    ) -> None:
        self._zugriff.fortschritt_speichern(
            Projektfortschritt(
                projekt_id=projekt_id,
                framework_schritt=schritt,
                fachlicher_unterschritt=unterschritt,
                fortschritt_zaehler=sum(abschluesse),
                fortschritt_nenner=sum(map(len, FACHLICHE_UNTERSCHRITTE.values())),
                phase=phase_fuer_schritt(schritt),
                status=status,
                gespeichert_am=datetime.now(UTC),
                revision=1 if alt is None else alt.revision + 1,
                abgeschlossene_unterschritte=abschluesse,
            )
        )

    def _anzeige(self, gespeichert: Projektfortschritt) -> Fortschrittsanzeige:
        zuordnung = self._zugriff.projektzugehoerigkeit_laden(gespeichert.projekt_id)
        assert zuordnung is not None
        abschluesse = _normalisiere_abschluesse(gespeichert.abgeschlossene_unterschritte)
        phasenwerte = berechne_phasenfortschritt(abschluesse)
        return Fortschrittsanzeige(
            projekt_id=gespeichert.projekt_id,
            schritt=gespeichert.framework_schritt,
            unterschritt=gespeichert.fachlicher_unterschritt,
            phase=gespeichert.phase,
            phasenname=PHASENNAMEN[gespeichert.phase],
            zaehler=gespeichert.fortschritt_zaehler,
            nenner=gespeichert.fortschritt_nenner,
            prozent=round(berechne_fortschritt(abschluesse)),
            phasenprozente=(round(phasenwerte[0]), round(phasenwerte[1]), round(phasenwerte[2])),
            abgeschlossene_unterschritte=abschluesse,
            status=gespeichert.status,
            gespeichert_am=gespeichert.gespeichert_am,
            letzte_aktivitaet=zuordnung.zuletzt_aktiv_am,
            revision=gespeichert.revision,
        )
