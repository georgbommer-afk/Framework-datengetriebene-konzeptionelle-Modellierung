"""Zentrale fachliche Fortschrittsdefinition für das gesamte Framework."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import streamlit as st

from framework_mvp.ui.navigation import FRAMEWORK_BEREICHE

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
    7: ("Ergebnisse fachlich aggregieren",),
    8: ("Modellbestandteile ableiten",),
    9: ("Modell ergänzen und validieren",),
    10: ("Konzeptionelles Modell ausgeben",),
}

PHASEN = {
    1: "Phase 1 – Aufbereitung der Datenbasis",
    2: "Phase 2 – Datengetriebene Analyse des Systems",
    3: "Phase 3 – Überführung in das konzeptionelle Modell",
}

_ZUSTANDSSAMMLUNG = {
    2: "etl_wizard_zustaende",
    3: "mapping_wizard_zustaende",
    4: "event_log_zustaende",
    5: "quality_gate_zustaende",
    6: "process_mining_zustaende",
}


@dataclass(frozen=True)
class Fortschrittsstand:
    framework_schritt: int
    framework_name: str
    unterschritt: int
    unterschritt_gesamt: int
    unterschritt_name: str
    phase: int
    phase_name: str
    gesamt_position: int
    gesamt_anzahl: int

    @property
    def anteil(self) -> float:
        return self.gesamt_position / self.gesamt_anzahl

    @property
    def prozent(self) -> int:
        return round(self.anteil * 100)


def unterschritte_fuer(framework_schritt: int) -> tuple[str, ...]:
    """Liefert ausschließlich fachliche Unterabschnitte eines Framework-Schritts."""
    return FACHLICHE_UNTERSCHRITTE[framework_schritt]


def _phase_fuer(framework_schritt: int) -> int:
    if framework_schritt <= 5:
        return 1
    if framework_schritt <= 7:
        return 2
    return 3


def _aktueller_unterschritt(framework_schritt: int, zustand: Mapping[Any, Any]) -> int:
    if framework_schritt == 1:
        rohwert = zustand.get("wizard_schritt", 1)
    elif framework_schritt in _ZUSTANDSSAMMLUNG:
        projekt_id = zustand.get("aktuelles_projekt_id") or zustand.get(
            "ausgewaehlte_projekt_id"
        )
        sammlung = zustand.get(_ZUSTANDSSAMMLUNG[framework_schritt], {})
        projektzustand = sammlung.get(str(projekt_id), {}) if isinstance(sammlung, Mapping) else {}
        rohwert = projektzustand.get("schritt", 1) if isinstance(projektzustand, Mapping) else 1
    else:
        rohwert = 1
    try:
        nummer = int(rohwert)
    except (TypeError, ValueError):
        nummer = 1
    return min(max(nummer, 1), len(FACHLICHE_UNTERSCHRITTE[framework_schritt]))


def fortschrittsstand(
    framework_bereich: str, zustand: Mapping[Any, Any]
) -> Fortschrittsstand:
    """Berechnet den Gesamtfortschritt deterministisch aus Navigation und Session-State."""
    try:
        framework_schritt = FRAMEWORK_BEREICHE.index(framework_bereich) + 1
    except ValueError as fehler:
        raise ValueError("Unbekannter Framework-Bereich.") from fehler
    unterschritt = _aktueller_unterschritt(framework_schritt, zustand)
    phase = _phase_fuer(framework_schritt)
    vorher = sum(len(FACHLICHE_UNTERSCHRITTE[n]) for n in range(1, framework_schritt))
    gesamt = sum(len(werte) for werte in FACHLICHE_UNTERSCHRITTE.values())
    return Fortschrittsstand(
        framework_schritt=framework_schritt,
        framework_name=framework_bereich.split(":", 1)[-1].strip()
        if ":" in framework_bereich
        else framework_bereich.split(" ", 1)[-1],
        unterschritt=unterschritt,
        unterschritt_gesamt=len(FACHLICHE_UNTERSCHRITTE[framework_schritt]),
        unterschritt_name=FACHLICHE_UNTERSCHRITTE[framework_schritt][unterschritt - 1],
        phase=phase,
        phase_name=PHASEN[phase],
        gesamt_position=vorher + unterschritt,
        gesamt_anzahl=gesamt,
    )


def zeige_gesamtfortschritt(stand: Fortschrittsstand) -> None:
    """Rendert die einzige Fortschrittsanzeige der Anwendung."""
    st.caption(
        f"Gesamtfortschritt: {stand.prozent} % "
        f"({stand.gesamt_position}/{stand.gesamt_anzahl}) · {stand.phase_name}"
    )
    st.progress(stand.anteil)
    st.write(
        f"**Schritt {stand.framework_schritt}: {stand.framework_name} · "
        f"Unterschritt {stand.unterschritt}/{stand.unterschritt_gesamt}:** "
        f"{stand.unterschritt_name}"
    )
