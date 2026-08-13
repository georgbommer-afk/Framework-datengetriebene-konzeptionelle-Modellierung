"""Composition Root für Anwendungsservices und lokale Adapter."""

import os
from datetime import timedelta
from pathlib import Path

from framework_mvp.application.autorisierung import AutorisierungsService
from framework_mvp.application.datenimport_service import DatenimportService
from framework_mvp.application.datenqualitaet_service import DatenqualitaetService
from framework_mvp.application.datenquelle_service import DatenquelleService
from framework_mvp.application.ergebnisaggregation_service import ErgebnisaggregationService
from framework_mvp.application.event_log_service import EventLogService
from framework_mvp.application.fortschritt_service import FortschrittService
from framework_mvp.application.gast_service import BereinigungsService
from framework_mvp.application.identitaet_service import IdentitaetsService
from framework_mvp.application.importvorgang_service import ImportvorgangService
from framework_mvp.application.kursarchiv_service import KursarchivService
from framework_mvp.application.kursgruppen_service import EinladungsService, KursgruppenService
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
from framework_mvp.application.projektarchiv_service import ArchivGrenzen, ProjektArchivService
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
from framework_mvp.infrastructure.persistence.sqlite_fortschritt_repository import (
    SQLiteFortschrittRepository,
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
from framework_mvp.infrastructure.persistence.sqlite_zugriffs_repository import (
    SQLiteZugriffsRepository,
)
from framework_mvp.workspace import WorkspaceKonfiguration

DATENBANKPFAD_UMGEBUNGSVARIABLE = "FRAMEWORK_MVP_DB_PATH"
GAST_TTL_STUNDEN_UMGEBUNGSVARIABLE = "FRAMEWORK_MVP_GUEST_TTL_HOURS"


def ermittle_gast_ttl() -> timedelta:
    """Liest die Gast-TTL; ungültige Konfiguration fällt nicht still auf unendlich zurück."""
    rohwert = os.getenv(GAST_TTL_STUNDEN_UMGEBUNGSVARIABLE, "24")
    try:
        stunden = int(rohwert)
    except ValueError as fehler:
        raise ValueError(f"{GAST_TTL_STUNDEN_UMGEBUNGSVARIABLE} muss ganzzahlig sein.") from fehler
    if not 1 <= stunden <= 24 * 30:
        raise ValueError(f"{GAST_TTL_STUNDEN_UMGEBUNGSVARIABLE} muss zwischen 1 und 720 liegen.")
    return timedelta(hours=stunden)


def ermittle_archivgrenzen() -> ArchivGrenzen:
    """Liest optionale Projektarchivgrenzen aus der Deployment-Umgebung."""

    def positiv(name: str, standard: int) -> int:
        try:
            wert = int(os.getenv(name, str(standard)))
        except ValueError as fehler:
            raise ValueError(f"{name} muss ganzzahlig sein.") from fehler
        if wert <= 0:
            raise ValueError(f"{name} muss positiv sein.")
        return wert

    ratio_name = "FRAMEWORK_MVP_ARCHIVE_MAX_RATIO"
    try:
        ratio = float(os.getenv(ratio_name, "100"))
    except ValueError as fehler:
        raise ValueError(f"{ratio_name} muss numerisch sein.") from fehler
    if ratio < 1:
        raise ValueError(f"{ratio_name} muss mindestens 1 sein.")

    return ArchivGrenzen(
        maximale_archivgroesse_bytes=positiv("FRAMEWORK_MVP_ARCHIVE_MAX_COMPRESSED_MB", 250)
        * 1024
        * 1024,
        maximale_dateien=positiv("FRAMEWORK_MVP_ARCHIVE_MAX_FILES", 5_000),
        maximale_einzeldatei_bytes=positiv("FRAMEWORK_MVP_ARCHIVE_MAX_FILE_MB", 250) * 1024 * 1024,
        maximale_entpackte_groesse_bytes=positiv("FRAMEWORK_MVP_ARCHIVE_MAX_UNCOMPRESSED_MB", 1_024)
        * 1024
        * 1024,
        maximales_kompressionsverhaeltnis=ratio,
        maximale_pfadlaenge=positiv("FRAMEWORK_MVP_ARCHIVE_MAX_PATH_BYTES", 512),
    )


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


def erstelle_zugriffs_repository(
    datenbankpfad: Path | str | None = None,
) -> SQLiteZugriffsRepository:
    return SQLiteZugriffsRepository(ermittle_datenbankpfad(datenbankpfad))


def erstelle_autorisierungs_service(
    datenbankpfad: Path | str | None = None,
) -> AutorisierungsService:
    return AutorisierungsService(erstelle_zugriffs_repository(datenbankpfad))


def erstelle_identitaets_service(
    datenbankpfad: Path | str | None = None,
) -> IdentitaetsService:
    return IdentitaetsService(erstelle_zugriffs_repository(datenbankpfad))


def erstelle_kursgruppen_service(
    datenbankpfad: Path | str | None = None,
) -> KursgruppenService:
    repository = erstelle_zugriffs_repository(datenbankpfad)
    return KursgruppenService(repository, AutorisierungsService(repository))


def erstelle_einladungs_service(
    datenbankpfad: Path | str | None = None,
) -> EinladungsService:
    repository = erstelle_zugriffs_repository(datenbankpfad)
    return EinladungsService(repository, AutorisierungsService(repository))


def erstelle_fortschritt_service(
    datenbankpfad: Path | str | None = None,
) -> FortschrittService:
    pfad = ermittle_datenbankpfad(datenbankpfad)
    repository = SQLiteZugriffsRepository(pfad)
    return FortschrittService(
        repository, SQLiteFortschrittRepository(pfad), AutorisierungsService(repository)
    )


def erstelle_projektarchiv_service(
    datenbankpfad: Path | str | None = None,
    workspace: WorkspaceKonfiguration | None = None,
) -> ProjektArchivService:
    pfad = ermittle_datenbankpfad(datenbankpfad)
    workspace_konfiguration = workspace or WorkspaceKonfiguration.ermitteln()
    repository = SQLiteZugriffsRepository(pfad)
    return ProjektArchivService(
        pfad,
        workspace_konfiguration,
        repository,
        AutorisierungsService(repository),
        grenzen=ermittle_archivgrenzen(),
        gast_ttl=ermittle_gast_ttl(),
    )


def erstelle_kursarchiv_service(
    datenbankpfad: Path | str | None = None,
    workspace: WorkspaceKonfiguration | None = None,
) -> KursarchivService:
    pfad = ermittle_datenbankpfad(datenbankpfad)
    workspace_konfiguration = workspace or WorkspaceKonfiguration.ermitteln()
    repository = SQLiteZugriffsRepository(pfad)
    autorisierung = AutorisierungsService(repository)
    return KursarchivService(
        repository,
        autorisierung,
        ProjektArchivService(
            pfad,
            workspace_konfiguration,
            repository,
            autorisierung,
            grenzen=ermittle_archivgrenzen(),
            gast_ttl=ermittle_gast_ttl(),
        ),
        erstelle_projekt_service(pfad),
        erstelle_loesch_service(pfad, workspace_konfiguration),
    )


def erstelle_bereinigungs_service(
    datenbankpfad: Path | str | None = None,
    workspace: WorkspaceKonfiguration | None = None,
) -> BereinigungsService:
    workspace_konfiguration = workspace or WorkspaceKonfiguration.ermitteln()
    return BereinigungsService(
        erstelle_zugriffs_repository(datenbankpfad),
        erstelle_loesch_service(datenbankpfad, workspace_konfiguration),
        workspace_konfiguration,
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
