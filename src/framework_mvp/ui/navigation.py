"""Zentrale Navigation zwischen Unterabschnitten und Framework-Schritten."""

from collections.abc import Callable
from uuid import UUID

import streamlit as st

FRAMEWORK_BEREICHE = (
    "1 Projektrahmen definieren",
    "2 ETL durchführen",
    "3 Semantisches Mapping",
    "4 Event Log aufbauen",
    "5 Datenqualität prüfen",
    "6 Process Mining durchführen",
    "7 Ergebnisse aggregieren",
    "8 Modellbestandteile ableiten",
    "9 Modell ergänzen und validieren",
    "10 Konzeptionelles Modell ausgeben",
)


def zeige_unterschritt_navigation(
    *,
    aktueller_unterschritt: int,
    anzahl_unterschritte: int,
    weiter_erlaubt: bool,
    zurueck_callback: Callable[[], None],
    weiter_callback: Callable[[], None],
    weiter_label: str = "Weiter",
    schluessel: str | None = None,
) -> None:
    """Rendert das einheitliche zweispaltige Navigationsmuster der Schritte 1–9."""
    if not 1 <= aktueller_unterschritt <= anzahl_unterschritte:
        raise ValueError("Der aktuelle Unterschritt liegt außerhalb des Ablaufs.")
    links, rechts = st.columns(2)
    if links.button(
        "Zurück",
        disabled=aktueller_unterschritt == 1,
        width="stretch",
        key=f"{schluessel}_zurueck" if schluessel else None,
    ):
        zurueck_callback()
        st.rerun()
    if rechts.button(
        weiter_label,
        disabled=not weiter_erlaubt,
        type="primary",
        width="stretch",
        key=f"{schluessel}_weiter" if schluessel else None,
    ):
        weiter_callback()
        st.rerun()


def naechster_framework_bereich(aktueller_schritt: int) -> str:
    """Bestimmt den unmittelbar folgenden vorhandenen Framework-Bereich."""
    if not 1 <= aktueller_schritt < len(FRAMEWORK_BEREICHE):
        raise ValueError("Für diesen Framework-Schritt ist kein Folgeschritt definiert.")
    return FRAMEWORK_BEREICHE[aktueller_schritt]


def framework_bereich_oeffnen(*, schritt: int, projekt_id: UUID | None = None) -> None:
    """Öffnet einen vorhandenen Framework-Bereich und bewahrt optional das Projekt."""
    if not 1 <= schritt <= len(FRAMEWORK_BEREICHE):
        raise ValueError("Der angeforderte Framework-Schritt ist nicht vorhanden.")
    if projekt_id is not None:
        st.session_state.aktuelles_projekt_id = str(projekt_id)
        st.session_state.ausgewaehlte_projekt_id = str(projekt_id)
    st.session_state.naechster_framework_bereich = FRAMEWORK_BEREICHE[schritt - 1]
    st.rerun()


def schritt_abschliessen_und_weiter(
    *,
    aktueller_schritt: int,
    projekt_id: UUID,
) -> None:
    """Bewahrt den Projektbezug, öffnet den Folgeschritt und startet einen Rerun."""
    framework_bereich_oeffnen(schritt=aktueller_schritt + 1, projekt_id=projekt_id)
