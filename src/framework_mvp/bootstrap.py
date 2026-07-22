"""Composition Root für Anwendungsservices und lokale Adapter."""

import os
from pathlib import Path

from framework_mvp.application.datenquelle_service import DatenquelleService
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.infrastructure.persistence.sqlite_datenquelle_repository import (
    SQLiteDatenquelleRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    SQLiteProjektRepository,
)
from framework_mvp.workspace import WorkspaceKonfiguration

DATENBANKPFAD_UMGEBUNGSVARIABLE = "FRAMEWORK_MVP_DB_PATH"


def ermittle_datenbankpfad(datenbankpfad: Path | str | None = None) -> Path:
    """Ermittelt den Datenbankpfad nach expliziter, Umgebungs- und Standardkonfiguration."""
    if datenbankpfad is not None:
        return Path(datenbankpfad)
    if umgebungspfad := os.getenv(DATENBANKPFAD_UMGEBUNGSVARIABLE):
        return Path(umgebungspfad)
    return WorkspaceKonfiguration.ermitteln().basisverzeichnis / "framework_mvp.sqlite"


def erstelle_projekt_service(datenbankpfad: Path | str | None = None) -> ProjektService:
    """Erzeugt einen Projektservice ohne globale veränderliche Instanz."""
    return ProjektService(SQLiteProjektRepository(ermittle_datenbankpfad(datenbankpfad)))


def erstelle_datenquelle_service(
    datenbankpfad: Path | str | None = None,
) -> DatenquelleService:
    """Erzeugt einen Datenquellenservice für die gemeinsame Datenbank."""
    return DatenquelleService(SQLiteDatenquelleRepository(ermittle_datenbankpfad(datenbankpfad)))
