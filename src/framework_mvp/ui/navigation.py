"""Zentrale Navigation zwischen abgeschlossenen Framework-Schritten."""

from uuid import UUID

import streamlit as st

FRAMEWORK_BEREICHE = (
    "Schritt 1: Projektrahmen definieren",
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
        st.session_state.ausgewaehlte_projekt_id = projekt_id
    st.session_state.naechster_framework_bereich = FRAMEWORK_BEREICHE[schritt - 1]
    st.rerun()


def schritt_abschliessen_und_weiter(
    *,
    aktueller_schritt: int,
    projekt_id: UUID,
) -> None:
    """Bewahrt den Projektbezug, öffnet den Folgeschritt und startet einen Rerun."""
    framework_bereich_oeffnen(schritt=aktueller_schritt + 1, projekt_id=projekt_id)
