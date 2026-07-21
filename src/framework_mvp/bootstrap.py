"""Zusammensetzung der Anwendung mit ihren technischen Adaptern."""

import os
from pathlib import Path

from framework_mvp.application.projekt_service import ProjektService
from framework_mvp.infrastructure.persistence.sqlite_projekt_repository import (
    STANDARD_DATENBANKPFAD,
    SQLiteProjektRepository,
)

DATENBANKPFAD_UMGEBUNGSVARIABLE = "FRAMEWORK_MVP_DB_PATH"


def erstelle_projekt_service(datenbankpfad: Path | str | None = None) -> ProjektService:
    """Erzeugt einen Projektservice mit einem neu angelegten SQLite-Adapter."""
    if datenbankpfad is not None:
        verwendeter_pfad = Path(datenbankpfad)
    elif pfad_aus_umgebung := os.getenv(DATENBANKPFAD_UMGEBUNGSVARIABLE):
        verwendeter_pfad = Path(pfad_aus_umgebung)
    else:
        verwendeter_pfad = STANDARD_DATENBANKPFAD
    return ProjektService(SQLiteProjektRepository(verwendeter_pfad))
