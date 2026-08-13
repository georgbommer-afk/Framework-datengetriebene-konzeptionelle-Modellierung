"""Composition Root für Anwendungsservices und lokale Adapter."""

import os
from pathlib import Path

from framework_mvp.application.datenimport_service import DatenimportService
from framework_mvp.application.datenqualitaet_service import DatenqualitaetService
from framework_mvp.application.datenquelle_service import DatenquelleService
from framework_mvp.application.ergebnisaggregation_service import ErgebnisaggregationService
from framework_mvp.application.event_log_service import EventLogService
from framework_mvp.application.importvorgang_service import ImportvorgangService
from framework_mvp.application.loesch_service import LoeschService
from framework_mvp.application.mapping_service import (
    EventLogKonfigurationService,
    MappingService,
)
from framework_mvp.application.mappingtabelle_service import MappingtabelleService
from framework_mvp.application.modellableitung_service import ModellableitungService
from framework_mvp.application.modellausgabe_service import ModellausgabeService
from framework_mvp.application.modellvalidierung_service import ModellvalidierungService
from framework_mvp.application.process_mining_service import ProcessMiningService
from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.application.transformations_service import TransformationsService
from framework_mvp.infrastructure.importartefakte import ImportartefaktSpeicher
from framework_mvp.infrastructure.persistence.sqlite_datenquelle_repository import (
    SQLiteDatenquelleRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_ergebnisaggregation_repository import (
    SQLiteErgebnisaggregationRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_etl_repository import SQLiteETLRepository
from framework_mvp.infrastructure.persistence.sqlite_event_log_repository import (
    SQLiteEventLogRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_importvorgang_repository import (
    SQLiteImportvorgangRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_loesch_repository import (
    SQLiteLoeschRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_mapping_repository import (
    SQLiteMappingRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_mappingtabelle_repository import (
    SQLiteMappingtabelleRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_modellableitung_repository import (
    SQLiteModellableitungRepository,
)
from framework_mvp.infrastructure.persistence.sqlite_modellvalidierung_repository import (
    SQLiteModellvalidierungRepository,
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


def erstelle_loesch_service(
    datenbankpfad: Path | str | None = None,
    workspace: WorkspaceKonfiguration | None = None,
) -> LoeschService:
    """Erzeugt die kontrollierte DB-/Dateisystem-Löschkoordination."""
    return LoeschService(
        SQLiteLoeschRepository(ermittle_datenbankpfad(datenbankpfad)),
        workspace or WorkspaceKonfiguration.ermitteln(),
    )


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


def erstelle_event_log_konfigurations_service(
    datenbankpfad: Path | str | None = None,
    workspace: WorkspaceKonfiguration | None = None,
) -> EventLogKonfigurationService:
    """Erzeugt die Rollen- und Strukturkonfiguration für Schritt 4."""
    pfad = ermittle_datenbankpfad(datenbankpfad)
    workspace_konfiguration = workspace or WorkspaceKonfiguration.ermitteln()
    transformations_service = erstelle_transformations_service(pfad, workspace_konfiguration)
    return EventLogKonfigurationService(
        SQLiteMappingRepository(pfad),
        transformations_service,
        ImportartefaktSpeicher(workspace_konfiguration),
    )


def erstelle_mapping_service(
    datenbankpfad: Path | str | None = None,
    workspace: WorkspaceKonfiguration | None = None,
) -> MappingService:
    """Kompatibler alter Composition-Root-Name für die Schritt-4-Konfiguration."""
    return erstelle_event_log_konfigurations_service(datenbankpfad, workspace)


def erstelle_mappingtabelle_service(
    datenbankpfad: Path | str | None = None,
    workspace: WorkspaceKonfiguration | None = None,
) -> MappingtabelleService:
    """Erzeugt den Service für die eigenständige Mappingtabelle M aus Schritt 3."""
    pfad = ermittle_datenbankpfad(datenbankpfad)
    workspace_konfiguration = workspace or WorkspaceKonfiguration.ermitteln()
    return MappingtabelleService(
        SQLiteMappingtabelleRepository(pfad),
        erstelle_transformations_service(pfad, workspace_konfiguration),
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
        erstelle_mappingtabelle_service(pfad, workspace_konfiguration),
    )


def erstelle_datenqualitaet_service(
    datenbankpfad: Path | str | None = None,
    workspace: WorkspaceKonfiguration | None = None,
) -> DatenqualitaetService:
    """Erzeugt das Quality-Gate mit integritätsgeprüften Q-, T-, M- und E-Services."""
    pfad = ermittle_datenbankpfad(datenbankpfad)
    workspace_konfiguration = workspace or WorkspaceKonfiguration.ermitteln()
    transformationen = erstelle_transformations_service(pfad, workspace_konfiguration)
    return DatenqualitaetService(
        SQLiteQualitaetRepository(pfad),
        erstelle_event_log_service(pfad, workspace_konfiguration),
        ImportartefaktSpeicher(workspace_konfiguration),
        transformationen,
        erstelle_datenquelle_service(pfad),
        erstelle_mappingtabelle_service(pfad, workspace_konfiguration),
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


def erstelle_ergebnisaggregation_service(
    datenbankpfad: Path | str | None = None,
    workspace: WorkspaceKonfiguration | None = None,
) -> ErgebnisaggregationService:
    """Erzeugt Algorithmus 7 mit der bestehenden, validierten Artefaktkette."""
    pfad = ermittle_datenbankpfad(datenbankpfad)
    workspace_konfiguration = workspace or WorkspaceKonfiguration.ermitteln()
    return ErgebnisaggregationService(
        SQLiteErgebnisaggregationRepository(pfad),
        erstelle_projekt_service(pfad),
        erstelle_transformations_service(pfad, workspace_konfiguration),
        erstelle_datenqualitaet_service(pfad, workspace_konfiguration),
        erstelle_process_mining_service(pfad, workspace_konfiguration),
        ImportartefaktSpeicher(workspace_konfiguration),
    )


def erstelle_modellableitung_service(
    datenbankpfad: Path | str | None = None,
    workspace: WorkspaceKonfiguration | None = None,
) -> ModellableitungService:
    """Erzeugt Algorithmus 8 auf der validierten Übergabe von P und A_G."""
    pfad = ermittle_datenbankpfad(datenbankpfad)
    workspace_konfiguration = workspace or WorkspaceKonfiguration.ermitteln()
    return ModellableitungService(
        SQLiteModellableitungRepository(pfad),
        erstelle_ergebnisaggregation_service(pfad, workspace_konfiguration),
        erstelle_transformations_service(pfad, workspace_konfiguration),
        erstelle_datenquelle_service(pfad),
        ImportartefaktSpeicher(workspace_konfiguration),
    )


def erstelle_modellvalidierung_service(
    datenbankpfad: Path | str | None = None,
    workspace: WorkspaceKonfiguration | None = None,
) -> ModellvalidierungService:
    """Erzeugt Algorithmus 9 auf dem validierten K/O-Paar aus Schritt 8."""
    pfad = ermittle_datenbankpfad(datenbankpfad)
    workspace_konfiguration = workspace or WorkspaceKonfiguration.ermitteln()
    return ModellvalidierungService(
        SQLiteModellvalidierungRepository(pfad),
        erstelle_modellableitung_service(pfad, workspace_konfiguration),
        ImportartefaktSpeicher(workspace_konfiguration),
    )


def erstelle_modellausgabe_service(
    datenbankpfad: Path | str | None = None,
    workspace: WorkspaceKonfiguration | None = None,
) -> ModellausgabeService:
    """Erzeugt Algorithmus 10 ohne zusätzliche Exportpersistenz."""
    workspace_konfiguration = workspace or WorkspaceKonfiguration.ermitteln()
    return ModellausgabeService(
        erstelle_modellvalidierung_service(datenbankpfad, workspace_konfiguration),
        workspace_konfiguration,
    )
