"""Composition Root für Anwendungsservices und lokale Adapter."""

import os
from pathlib import Path

from framework_mvp.application.datenimport_service import DatenimportService
from framework_mvp.application.datenqualitaet_service import DatenqualitaetService
from framework_mvp.application.datenquelle_service import DatenquelleService
from framework_mvp.application.event_log_service import EventLogService
from framework_mvp.application.importvorgang_service import ImportvorgangService
from framework_mvp.application.mapping_service import MappingService
from framework_mvp.application.process_mining_service import ProcessMiningService
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.application.transformations_service import TransformationsService
from framework_mvp.infrastructure.importartefakte import ImportartefaktSpeicher
from framework_mvp.infrastructure.persistence.sqlite_datenquelle_repository import (
    SQLiteDatenquelleRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_etl_repository import SQLiteETLRepository
from framework_mvp.infrastructure.persistence.sqlite_event_log_repository import (
    SQLiteEventLogRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_importvorgang_repository import (
    SQLiteImportvorgangRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_mapping_repository import (
    SQLiteMappingRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_process_mining_repository import (
    SQLiteProcessMiningRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    SQLiteProjektRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_qualitaet_repository import (
    SQLiteQualitaetRepository,
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


def erstelle_datenimport_service() -> DatenimportService:
    """Erzeugt den zustandslosen Service für temporäre Dateiimporte."""
    return DatenimportService()


def erstelle_importvorgang_service(
    datenbankpfad: Path | str | None = None,
    workspace: WorkspaceKonfiguration | None = None,
) -> ImportvorgangService:
    """Erzeugt den Service für bestätigte Importmetadaten und Artefakte."""
    pfad = ermittle_datenbankpfad(datenbankpfad)
    workspace_konfiguration = workspace or WorkspaceKonfiguration.ermitteln()
    return ImportvorgangService(
        SQLiteImportvorgangRepository(pfad),
        SQLiteProjektRepository(pfad),
        SQLiteDatenquelleRepository(pfad),
        ImportartefaktSpeicher(workspace_konfiguration),
    )


def erstelle_transformations_service(
    datenbankpfad: Path | str | None = None,
    workspace: WorkspaceKonfiguration | None = None,
) -> TransformationsService:
    """Erzeugt den Service für Transformationspläne und Zwischendatensätze."""
    pfad = ermittle_datenbankpfad(datenbankpfad)
    workspace_konfiguration = workspace or WorkspaceKonfiguration.ermitteln()
    return TransformationsService(
        SQLiteETLRepository(pfad),
        erstelle_importvorgang_service(pfad, workspace_konfiguration),
        erstelle_datenimport_service(),
        ImportartefaktSpeicher(workspace_konfiguration),
    )


def erstelle_mapping_service(
    datenbankpfad: Path | str | None = None,
    workspace: WorkspaceKonfiguration | None = None,
) -> MappingService:
    """Erzeugt den Service für persistierte semantische Mappings."""
    pfad = ermittle_datenbankpfad(datenbankpfad)
    workspace_konfiguration = workspace or WorkspaceKonfiguration.ermitteln()
    transformations_service = erstelle_transformations_service(pfad, workspace_konfiguration)
    return MappingService(
        SQLiteMappingRepository(pfad),
        transformations_service,
        ImportartefaktSpeicher(workspace_konfiguration),
    )


def erstelle_event_log_service(
    datenbankpfad: Path | str | None = None,
    workspace: WorkspaceKonfiguration | None = None,
) -> EventLogService:
    """Erzeugt den Service für kanonische Event Logs."""
    pfad = ermittle_datenbankpfad(datenbankpfad)
    workspace_konfiguration = workspace or WorkspaceKonfiguration.ermitteln()
    transformation = erstelle_transformations_service(pfad, workspace_konfiguration)
    mapping = MappingService(
        SQLiteMappingRepository(pfad),
        transformation,
        ImportartefaktSpeicher(workspace_konfiguration),
    )
    return EventLogService(
        SQLiteEventLogRepository(pfad),
        mapping,
        transformation,
        ImportartefaktSpeicher(workspace_konfiguration),
    )


def erstelle_datenqualitaet_service(
    datenbankpfad: Path | str | None = None,
    workspace: WorkspaceKonfiguration | None = None,
) -> DatenqualitaetService:
    """Erzeugt den Service für Qualitätsprüfungen und Maßnahmen."""
    pfad = ermittle_datenbankpfad(datenbankpfad)
    workspace_konfiguration = workspace or WorkspaceKonfiguration.ermitteln()
    return DatenqualitaetService(
        SQLiteQualitaetRepository(pfad),
        erstelle_event_log_service(pfad, workspace_konfiguration),
        ImportartefaktSpeicher(workspace_konfiguration),
    )


def erstelle_process_mining_service(
    datenbankpfad: Path | str | None = None,
    workspace: WorkspaceKonfiguration | None = None,
) -> ProcessMiningService:
    """Erzeugt den Service für Process Discovery mit PM4Py."""
    pfad = ermittle_datenbankpfad(datenbankpfad)
    workspace_konfiguration = workspace or WorkspaceKonfiguration.ermitteln()
    return ProcessMiningService(
        SQLiteProcessMiningRepository(pfad),
        erstelle_datenqualitaet_service(pfad, workspace_konfiguration),
        ImportartefaktSpeicher(workspace_konfiguration),
    )
