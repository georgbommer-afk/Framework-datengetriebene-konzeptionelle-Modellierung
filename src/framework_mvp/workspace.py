"""Zentrale, vom Arbeitsverzeichnis unabhängige Workspace-Konfiguration."""

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

WORKSPACE_UMGEBUNGSVARIABLE = "FRAMEWORK_MVP_WORKSPACE_PATH"
STANDARD_WORKSPACE_PFAD = Path(__file__).resolve().parents[2] / "workspace"


@dataclass(frozen=True, slots=True)
class ProjektWorkspace:
    """Pfade der vorbereiteten Arbeitsbereiche eines Projekts."""

    projekt: Path
    raw: Path
    profiles: Path
    interim: Path
    mappings: Path


@dataclass(frozen=True, slots=True)
class WorkspaceKonfiguration:
    """Konfiguration und kontrollierte Anlage lokaler Arbeitsverzeichnisse."""

    basisverzeichnis: Path

    @classmethod
    def ermitteln(cls, expliziter_pfad: Path | str | None = None) -> "WorkspaceKonfiguration":
        """Ermittelt den Workspace mit Vorrang für einen expliziten Pfad."""
        if expliziter_pfad is not None:
            pfad = Path(expliziter_pfad)
        elif umgebungspfad := os.getenv(WORKSPACE_UMGEBUNGSVARIABLE):
            pfad = Path(umgebungspfad)
        else:
            pfad = STANDARD_WORKSPACE_PFAD
        return cls(pfad.expanduser().resolve())

    def fuer_projekt_anlegen(self, projekt_id: UUID) -> ProjektWorkspace:
        """Legt die vier vorgesehenen projektbezogenen Unterverzeichnisse an."""
        projektpfad = self.basisverzeichnis / "projects" / str(projekt_id)
        raw = projektpfad / "raw"
        profiles = projektpfad / "profiles"
        interim = projektpfad / "interim"
        mappings = projektpfad / "mappings"
        for verzeichnis in (raw, profiles, interim, mappings):
            verzeichnis.mkdir(parents=True, exist_ok=True)
        return ProjektWorkspace(projektpfad, raw, profiles, interim, mappings)
