"""Gemeinsame Anzeige für Navigation und fachlichen Abschlussfortschritt."""

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any

import streamlit as st

from framework_mvp.application.fortschritt_service import (
    FACHLICHE_UNTERSCHRITTE,
    LEERER_ABSCHLUSS,
    PHASENNAMEN,
    Fortschrittsanzeige,
    berechne_fortschritt,
    berechne_phasenfortschritt,
)
from framework_mvp.ui.navigation import ENTWURFSABSCHLUESSE, FRAMEWORK_BEREICHE

PHASEN = {phase: f"Phase {phase} – {name}" for phase, name in PHASENNAMEN.items()}

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
    gesamt_prozent: int
    phasenprozente: tuple[int, int, int]
    abgeschlossene_unterschritte: tuple[int, ...]

    @property
    def anteil(self) -> float:
        return self.gesamt_prozent / 100

    @property
    def prozent(self) -> int:
        return self.gesamt_prozent


def unterschritte_fuer(framework_schritt: int) -> tuple[str, ...]:
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
        projekt_id = zustand.get("aktuelles_projekt_id") or zustand.get("ausgewaehlte_projekt_id")
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
    framework_bereich: str,
    zustand: Mapping[Any, Any],
    anzeige: Fortschrittsanzeige | None = None,
) -> Fortschrittsstand:
    """Kombiniert aktuelle UI-Position mit einem separaten Abschlussstand."""
    try:
        framework_schritt = FRAMEWORK_BEREICHE.index(framework_bereich) + 1
    except ValueError as fehler:
        raise ValueError("Unbekannter Framework-Bereich.") from fehler
    unterschritt = _aktueller_unterschritt(framework_schritt, zustand)
    phase = _phase_fuer(framework_schritt)
    abschluesse = (
        anzeige.abgeschlossene_unterschritte
        if anzeige is not None
        else tuple(zustand.get(ENTWURFSABSCHLUESSE, LEERER_ABSCHLUSS))
    )
    phasenwerte = berechne_phasenfortschritt(abschluesse)
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
        gesamt_prozent=round(berechne_fortschritt(abschluesse)),
        phasenprozente=(round(phasenwerte[0]), round(phasenwerte[1]), round(phasenwerte[2])),
        abgeschlossene_unterschritte=abschluesse,
    )


def fortschrittsstand_aus_persistenz(anzeige: Fortschrittsanzeige) -> Fortschrittsstand:
    """Nutzt für eine Nur-Lese-Ansicht auch die persistierte Navigationsposition."""
    framework_schritt = min(max(anzeige.schritt, 1), len(FRAMEWORK_BEREICHE))
    unterschritte = FACHLICHE_UNTERSCHRITTE[framework_schritt]
    try:
        unterschritt = unterschritte.index(anzeige.unterschritt) + 1
    except ValueError:
        unterschritt = 1
    framework_bereich = FRAMEWORK_BEREICHE[framework_schritt - 1]
    return Fortschrittsstand(
        framework_schritt=framework_schritt,
        framework_name=framework_bereich.split(" ", 1)[-1],
        unterschritt=unterschritt,
        unterschritt_gesamt=len(unterschritte),
        unterschritt_name=anzeige.unterschritt or unterschritte[unterschritt - 1],
        phase=anzeige.phase,
        phase_name=PHASEN[anzeige.phase],
        gesamt_prozent=anzeige.prozent,
        phasenprozente=anzeige.phasenprozente,
        abgeschlossene_unterschritte=anzeige.abgeschlossene_unterschritte,
    )


def fortschrittszustand_aus_persistenz_setzen(
    zustand: MutableMapping[str, Any], anzeige: Fortschrittsanzeige
) -> None:
    """Stellt ausschließlich die separat persistierte Navigationsposition wieder her."""
    unterschritte = FACHLICHE_UNTERSCHRITTE[anzeige.schritt]
    try:
        unterschritt = unterschritte.index(anzeige.unterschritt) + 1
    except ValueError:
        unterschritt = 1
    if anzeige.schritt == 1:
        zustand["wizard_schritt"] = unterschritt
        return
    sammlungsname = _ZUSTANDSSAMMLUNG.get(anzeige.schritt)
    if sammlungsname is None:
        return
    sammlung = zustand.setdefault(sammlungsname, {})
    if not isinstance(sammlung, dict):
        sammlung = {}
        zustand[sammlungsname] = sammlung
    sammlung[str(anzeige.projekt_id)] = {"schritt": unterschritt}


def zeige_gesamtfortschritt(stand: Fortschrittsstand) -> None:
    """Zeigt Gesamt-, Phasenfortschritt und Navigation getrennt in der Sidebar."""
    with st.sidebar:
        st.subheader("Fortschritt")
        st.caption(f"Gesamtfortschritt: {stand.gesamt_prozent} %")
        st.progress(stand.gesamt_prozent / 100)
        for phase, prozent in enumerate(stand.phasenprozente, start=1):
            st.caption(f"{PHASEN[phase]}: {prozent} %")
            st.progress(prozent / 100)
        st.write(f"**Aktuell: Schritt {stand.framework_schritt} – {stand.framework_name}**")
        st.caption(
            f"Unterschritt {stand.unterschritt}/{stand.unterschritt_gesamt}: "
            f"{stand.unterschritt_name}"
        )
