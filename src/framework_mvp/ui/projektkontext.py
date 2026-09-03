"""Einziger UI-Übergang zwischen Projekten und persistierter Artefaktlineage."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from framework_mvp.application.projektkontext_service import Projektkontext

PROJEKTREFERENZ_SCHLUESSEL = (
    "aktuelle_datenquellen_id",
    "aktueller_zwischendatensatz_id",
    "aktuelle_mappingtabelle_id",
    "aktuelle_mapping_id",
    "mapping_id",
    "aktuelle_event_log_konfiguration_id",
    "aktuelles_event_log_id",
    "event_log_id",
    "aktuelle_freigabe_id",
    "freigegebenes_event_log_id",
    "aktuelle_analyse_id",
    "aktuelles_prozessmodell_id",
    "aktuelle_discovery_ergebnisse_id",
    "aktuelle_aggregations_id",
    "aktuelle_modellableitungs_id",
    "aktuelle_k_id",
    "aktuelle_o_id",
    "aktuelle_validierungslauf_id",
    "aktuelle_k_stern_id",
)

PROJEKTARBEITSZUSTAENDE = (
    "etl_wizard_zustaende",
    "mapping_wizard_zustaende",
    "mappingtabelle_zustaende",
    "event_log_zustaende",
    "quality_gate_zustaende",
    "process_mining_zustaende",
)

PROJEKT_WIDGET_PRAEFIXE = (
    "projektauswahl_",
    "projektrahmen_",
    "etl_",
    "mappingtabelle_",
    "event_",
    "gate_",
    "process_mining_",
    "ag_",
    "schritt8_",
    "schritt9_",
    "schritt10_",
)


def projektkontext_bereinigen(zustand: MutableMapping[str, Any]) -> None:
    """Entfernt Projekt- und Artefaktbezüge vor jedem Kontextwechsel vollständig."""
    for schluessel in (
        "aktuelles_projekt_id",
        "ausgewaehlte_projekt_id",
        "wizard_entwurf",
        "wizard_entwurf_projekt_id",
        "wizard_schritt",
        "folgeartefakte_veraltet",
        "projektkontext_rehydriert",
        "schritt9_arbeitsfassung_signatur",
        "schritt9_arbeitsfassung",
        "ag_vorschau",
        "modellableitung_vorschau",
        "schritt10_ausgabe",
        "schritt10_ausgabe_signatur",
        *PROJEKTREFERENZ_SCHLUESSEL,
    ):
        zustand.pop(schluessel, None)
    for sammlung in PROJEKTARBEITSZUSTAENDE:
        zustand.pop(sammlung, None)
    for schluessel in tuple(zustand):
        if str(schluessel).startswith(PROJEKT_WIDGET_PRAEFIXE):
            zustand.pop(schluessel, None)


def projektkontext_setzen(zustand: MutableMapping[str, Any], kontext: Projektkontext) -> None:
    """Aktiviert genau die zentral rekonstruierte Projektgeneration."""
    projektkontext_bereinigen(zustand)
    projekt_id = str(kontext.projekt_id)
    zustand["aktuelles_projekt_id"] = projekt_id
    zustand["ausgewaehlte_projekt_id"] = projekt_id
    zustand.update(kontext.referenzen)
