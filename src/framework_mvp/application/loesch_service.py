"""Koordination konsistenter Löschungen zwischen Workspace und Datenbank."""

import os
import shutil
from pathlib import Path
from uuid import UUID, uuid4

from framework_mvp.application.ports.loesch_repository import LoeschRepository
from framework_mvp.domain.exceptions import Domaenenfehler
from framework_mvp.workspace import WorkspaceKonfiguration


class LoeschService:
    """Staged Artefakte vor der atomaren, expliziten DB-Löschtransaktion."""

    def __init__(self, repository: LoeschRepository, workspace: WorkspaceKonfiguration) -> None:
        self._repository = repository
        self._workspace = workspace

    @property
    def _basis(self) -> Path:
        return self._workspace.basisverzeichnis.resolve()

    def _sicherer_pfad(
        self, relativer_pfad: str, projekt_id: UUID, *, projektwurzel_erlaubt: bool = False
    ) -> Path:
        roh = Path(relativer_pfad)
        if roh.is_absolute():
            raise Domaenenfehler("Artefaktpfade müssen relativ zum Workspace sein.")
        aufgeloest = (self._basis / roh).resolve()
        try:
            relativ = aufgeloest.relative_to(self._basis)
        except ValueError as fehler:
            raise Domaenenfehler("Ein Artefaktpfad verlässt den Workspace.") from fehler
        mindestlaenge = 2 if projektwurzel_erlaubt else 3
        if (
            len(relativ.parts) < mindestlaenge
            or relativ.parts[0] != "projects"
            or relativ.parts[1] != str(projekt_id)
        ):
            raise Domaenenfehler("Ein Löschpfad ist zu breit oder liegt außerhalb eines Projekts.")
        return aufgeloest

    def _staging_pfad(self) -> Path:
        pfad = self._basis / ".deletion-staging" / str(uuid4())
        pfad.mkdir(parents=True, exist_ok=False)
        return pfad

    @staticmethod
    def _zurueckrollen(verschoben: list[tuple[Path, Path]]) -> None:
        for quelle, ziel in reversed(verschoben):
            if ziel.exists():
                quelle.parent.mkdir(parents=True, exist_ok=True)
                os.replace(ziel, quelle)

    def _artefakte_stagen(
        self, projekt_id: UUID, relative_pfade: tuple[str, ...], staging: Path
    ) -> list[tuple[Path, Path]]:
        verschoben: list[tuple[Path, Path]] = []
        try:
            for relativer_pfad in relative_pfade:
                quelle = self._sicherer_pfad(relativer_pfad, projekt_id)
                relativ = quelle.relative_to(self._basis)
                if relativ.parts[2] in {"raw", "profiles"}:
                    raise Domaenenfehler(
                        "Rohimporte und Importprofile dürfen bei einer T-Löschung nicht "
                        "entfernt werden."
                    )
                if not quelle.exists():
                    continue
                if not quelle.is_file():
                    raise Domaenenfehler("Ein erwarteter Artefaktpfad ist keine Datei.")
                ziel = staging / relativ
                ziel.parent.mkdir(parents=True, exist_ok=True)
                os.replace(quelle, ziel)
                verschoben.append((quelle, ziel))
        except Exception:
            self._zurueckrollen(verschoben)
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return verschoben

    def zwischendatensatz_loeschen(self, projekt_id: UUID, zwischendatensatz_id: UUID) -> None:
        plan = self._repository.zwischendatensatz_loeschplan(projekt_id, zwischendatensatz_id)
        if plan is None:
            raise Domaenenfehler("Der Zwischendatensatz gehört nicht zum gewählten Projekt.")
        staging = self._staging_pfad()
        verschoben = self._artefakte_stagen(projekt_id, plan.relative_artefaktpfade, staging)
        try:
            self._repository.zwischendatensatz_loeschen(
                projekt_id, zwischendatensatz_id, plan.transformationsplan_id
            )
        except Exception:
            self._zurueckrollen(verschoben)
            shutil.rmtree(staging, ignore_errors=True)
            raise
        shutil.rmtree(staging, ignore_errors=True)

    def projekt_loeschen(self, projekt_id: UUID) -> None:
        projektpfad = self._sicherer_pfad(
            f"projects/{projekt_id}", projekt_id, projektwurzel_erlaubt=True
        )
        staging = self._staging_pfad()
        verschoben: list[tuple[Path, Path]] = []
        if projektpfad.exists():
            if not projektpfad.is_dir():
                shutil.rmtree(staging, ignore_errors=True)
                raise Domaenenfehler("Der erwartete Projektpfad ist kein Verzeichnis.")
            ziel = staging / "project"
            os.replace(projektpfad, ziel)
            verschoben.append((projektpfad, ziel))
        try:
            if not self._repository.projekt_loeschen(projekt_id):
                raise Domaenenfehler("Das Projekt wurde nicht gefunden.")
        except Exception:
            self._zurueckrollen(verschoben)
            shutil.rmtree(staging, ignore_errors=True)
            raise
        shutil.rmtree(staging, ignore_errors=True)
