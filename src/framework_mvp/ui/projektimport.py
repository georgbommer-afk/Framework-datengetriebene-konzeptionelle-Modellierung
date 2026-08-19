"""Rerun-stabiles, kleines Zustandsmodell für den Projektimport."""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any
from uuid import UUID

from framework_mvp.application.projektarchiv_service import (
    ArchivStaging,
    GestagterProjektimport,
)

PROJEKTIMPORT_ZUSTAND = "projektimport_zustand"


class ProjektImportPhase(StrEnum):
    """Explizite Phasen zwischen Upload, Prüfung, Bestätigung und Abschluss."""

    UEBERNOMMEN = "archiv_uebernommen"
    VALIDIERT = "archiv_validiert"
    KONFLIKT = "konflikt_erkannt"
    AUSFUEHRUNG = "import_wird_ausgefuehrt"
    FEHLGESCHLAGEN = "fehlgeschlagen"


@dataclass(frozen=True, slots=True)
class ProjektImportZustand:
    """Im Session-State liegen nur Referenz, Hash und nicht-sensitive Metadaten."""

    staging_id: UUID
    archiv_sha256: str
    zielkontext: str
    ziel_gruppen_id: UUID | None
    phase: ProjektImportPhase
    archivversion: int | None = None
    projekt_id: UUID | None = None
    projektname: str = ""
    exportiert_am: str = ""
    bereits_vorhanden: bool | None = None
    fehlermeldung: str = ""

    @classmethod
    def aus_staging(cls, staging: ArchivStaging) -> ProjektImportZustand:
        return cls(
            staging_id=staging.staging_id,
            archiv_sha256=staging.archiv_sha256,
            zielkontext=staging.zielkontext,
            ziel_gruppen_id=staging.ziel_gruppen_id,
            phase=ProjektImportPhase.UEBERNOMMEN,
        )

    def mit_pruefung(self, pruefung: GestagterProjektimport) -> ProjektImportZustand:
        if pruefung.staging_id != self.staging_id or pruefung.archiv_sha256 != self.archiv_sha256:
            raise ValueError("Die Importprüfung gehört nicht zum gestagten Archiv.")
        return replace(
            self,
            phase=(
                ProjektImportPhase.KONFLIKT
                if pruefung.bereits_vorhanden
                else ProjektImportPhase.VALIDIERT
            ),
            archivversion=pruefung.archivversion,
            projekt_id=pruefung.projekt_id,
            projektname=pruefung.projektname,
            exportiert_am=pruefung.exportiert_am,
            bereits_vorhanden=pruefung.bereits_vorhanden,
            ziel_gruppen_id=pruefung.ziel_gruppen_id,
        )

    def in_ausfuehrung(self) -> ProjektImportZustand:
        return replace(self, phase=ProjektImportPhase.AUSFUEHRUNG, fehlermeldung="")

    def fehlgeschlagen(self, meldung: str) -> ProjektImportZustand:
        return replace(
            self,
            phase=ProjektImportPhase.FEHLGESCHLAGEN,
            fehlermeldung=meldung,
        )


def projektimport_widget_key(
    aktion: str,
    projekt_id: UUID | str | None,
    archiv_sha256: str | None = None,
) -> str:
    """Erzeugt fachlich getrennte, über Reruns stabile Import-Widget-Keys."""
    projektkennung = str(projekt_id) if projekt_id is not None else "neues-projekt"
    bestandteile = ["projektimport", aktion, projektkennung]
    if archiv_sha256:
        bestandteile.append(archiv_sha256[:16])
    return "_".join(bestandteile)


def projektimport_session_zuruecksetzen(
    zustand: MutableMapping[str, Any],
    *,
    schliessen: bool = True,
) -> None:
    """Entfernt ausschließlich Import-UI-Zustand und invalidiert den Uploader."""
    zustand.pop(PROJEKTIMPORT_ZUSTAND, None)
    zustand["projektimport_generation"] = int(zustand.get("projektimport_generation", 0)) + 1
    if schliessen:
        zustand["projektimport_offen"] = False
