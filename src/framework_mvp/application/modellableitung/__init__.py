"""Deterministische Zuordnung der Ergebnisse zu den Bestandteilen von K und O."""

from framework_mvp.application.modellableitung.ableitung import (
    MAPPINGVERSION,
    MODELLBESTANDTEILE,
    extrahiere_sichtbare_aktivitaeten,
    leite_modellbestandteile_ab,
    validiere_quellenzuordnung,
    wende_fachliche_entscheidungen_an,
)

__all__ = [
    "MAPPINGVERSION",
    "MODELLBESTANDTEILE",
    "extrahiere_sichtbare_aktivitaeten",
    "leite_modellbestandteile_ab",
    "validiere_quellenzuordnung",
    "wende_fachliche_entscheidungen_an",
]
