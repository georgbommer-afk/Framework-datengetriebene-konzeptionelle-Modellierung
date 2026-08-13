"""Gezielte Bereinigung abhängiger Streamlit-Zustände nach Löschungen."""

from collections.abc import MutableMapping
from typing import Any
from uuid import UUID

ABHAENGIGE_ID_SCHLUESSEL = (
    "aktuelle_mapping_id",
    "aktuelle_mappingtabelle_id",
    "aktuelle_event_log_konfiguration_id",
    "aktuelles_event_log_id",
    "aktuelle_freigabe_id",
    "aktuelle_analyse_id",
    "aktuelles_prozessmodell_id",
    "aktuelle_discovery_ergebnisse_id",
    "aktuelle_aggregations_id",
    "aktuelle_modellableitungs_id",
    "aktuelle_k_id",
    "aktuelle_o_id",
    "aktuelle_validierungslauf_id",
    "aktuelle_k_stern_id",
    "schritt9_arbeitsfassung_signatur",
)


def zwischendatensatz_zustand_bereinigen(
    zustand: MutableMapping[str, Any], projekt_id: UUID, zwischendatensatz_id: UUID
) -> None:
    """Entfernt die Auswahl von T und sämtliche davon abhängigen Schrittzustände."""
    ist_aktiv = str(zustand.get("aktueller_zwischendatensatz_id")) == str(zwischendatensatz_id)
    if ist_aktiv:
        zustand.pop("aktueller_zwischendatensatz_id", None)
        for schluessel in ABHAENGIGE_ID_SCHLUESSEL:
            zustand.pop(schluessel, None)
        for sammlung in (
            "etl_wizard_zustaende",
            "mapping_wizard_zustaende",
            "mappingtabelle_zustaende",
            "event_log_zustaende",
            "quality_gate_zustaende",
            "process_mining_zustaende",
        ):
            werte = zustand.get(sammlung)
            if isinstance(werte, dict):
                werte.pop(str(projekt_id), None)
    for schluessel in tuple(zustand):
        if str(zwischendatensatz_id) in str(schluessel):
            zustand.pop(schluessel, None)
    zustand["framework_bereich"] = "2 ETL durchführen"


def projekt_zustand_bereinigen(zustand: MutableMapping[str, Any], projekt_id: UUID) -> None:
    """Entfernt den vollständigen Navigations- und Arbeitszustand eines Projekts."""
    zwischendatensatz_zustand_bereinigen(zustand, projekt_id, UUID(int=0))
    for schluessel in ABHAENGIGE_ID_SCHLUESSEL:
        zustand.pop(schluessel, None)
    for sammlung in (
        "etl_wizard_zustaende",
        "mapping_wizard_zustaende",
        "mappingtabelle_zustaende",
        "event_log_zustaende",
        "quality_gate_zustaende",
        "process_mining_zustaende",
    ):
        werte = zustand.get(sammlung)
        if isinstance(werte, dict):
            werte.pop(str(projekt_id), None)
    for schluessel in (
        "aktuelles_projekt_id",
        "ausgewaehlte_projekt_id",
        "aktuelle_datenquellen_id",
        "aktueller_zwischendatensatz_id",
        "wizard_entwurf",
        "wizard_schritt",
    ):
        zustand.pop(schluessel, None)
    for schluessel in tuple(zustand):
        if str(projekt_id) in str(schluessel):
            zustand.pop(schluessel, None)
    zustand["framework_bereich"] = "Schritt 1: Projektrahmen definieren"
