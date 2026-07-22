"""Sichere und atomare Ablage sowie Prüfung von Importartefakten."""

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import UUID

from framework_mvp.infrastructure.exceptions import Importintegritaetsfehler
from framework_mvp.workspace import WorkspaceKonfiguration


@dataclass(frozen=True, slots=True)
class GespeichertesArtefakt:
    """Relativer Artefaktpfad mit Information zur Wiederverwendung."""

    relativer_pfad: str
    neu_erstellt: bool


class ImportartefaktSpeicher:
    """Speichert Importartefakte ausschließlich innerhalb des konfigurierten Workspace."""

    def __init__(self, workspace: WorkspaceKonfiguration) -> None:
        """Bindet den Adapter an eine explizite Workspace-Konfiguration."""
        self._workspace = workspace

    def _sicherer_absoluter_pfad(self, relativer_pfad: str) -> Path:
        relativ = PurePosixPath(relativer_pfad.replace("\\", "/"))
        if relativ.is_absolute() or ".." in relativ.parts:
            raise Importintegritaetsfehler("Der Artefaktpfad verlässt den Workspace.")
        basis = self._workspace.basisverzeichnis.resolve()
        ziel = (basis / Path(*relativ.parts)).resolve()
        if not ziel.is_relative_to(basis):
            raise Importintegritaetsfehler("Der Artefaktpfad verlässt den Workspace.")
        return ziel

    @staticmethod
    def _atomar_schreiben(ziel: Path, inhalt: bytes) -> None:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        dateideskriptor, temporaerer_name = tempfile.mkstemp(prefix=".import-", dir=ziel.parent)
        temporaer = Path(temporaerer_name)
        try:
            with os.fdopen(dateideskriptor, "wb") as datei:
                datei.write(inhalt)
                datei.flush()
                os.fsync(datei.fileno())
            os.replace(temporaer, ziel)
        finally:
            if temporaer.exists():
                temporaer.unlink()

    def raw_speichern(
        self, projekt_id: UUID, sha256: str, sicherer_dateiname: str, inhalt: bytes
    ) -> GespeichertesArtefakt:
        """Speichert oder verwendet eine inhaltsadressierte unveränderte Raw-Datei."""
        relativer_pfad = (
            PurePosixPath("projects")
            / str(projekt_id)
            / "raw"
            / sha256
            / PurePosixPath(sicherer_dateiname).name
        ).as_posix()
        ziel = self._sicherer_absoluter_pfad(relativer_pfad)
        if ziel.exists():
            if hashlib.sha256(ziel.read_bytes()).hexdigest() != sha256:
                raise Importintegritaetsfehler(
                    "Eine vorhandene Raw-Datei besitzt eine abweichende Prüfsumme."
                )
            return GespeichertesArtefakt(relativer_pfad, False)
        self._atomar_schreiben(ziel, inhalt)
        if hashlib.sha256(ziel.read_bytes()).hexdigest() != sha256:
            ziel.unlink(missing_ok=True)
            raise Importintegritaetsfehler(
                "Die Prüfsumme der gespeicherten Raw-Datei stimmt nicht überein."
            )
        return GespeichertesArtefakt(relativer_pfad, True)

    def profil_speichern(
        self, projekt_id: UUID, import_id: UUID, inhalt: bytes
    ) -> GespeichertesArtefakt:
        """Speichert ein versioniertes Profil atomar unter seiner Import-ID."""
        relativer_pfad = (
            PurePosixPath("projects") / str(projekt_id) / "profiles" / f"{import_id}.json"
        ).as_posix()
        ziel = self._sicherer_absoluter_pfad(relativer_pfad)
        if ziel.exists():
            if ziel.read_bytes() != inhalt:
                raise Importintegritaetsfehler(
                    "Für die Import-ID existiert bereits ein abweichendes Profil."
                )
            return GespeichertesArtefakt(relativer_pfad, False)
        self._atomar_schreiben(ziel, inhalt)
        return GespeichertesArtefakt(relativer_pfad, True)

    def lesen(self, relativer_pfad: str) -> bytes:
        """Liest ein vorhandenes Artefakt nach erneuter Pfadprüfung."""
        pfad = self._sicherer_absoluter_pfad(relativer_pfad)
        if not pfad.is_file():
            raise Importintegritaetsfehler("Das gespeicherte Importartefakt ist nicht vorhanden.")
        return pfad.read_bytes()

    def pfad(self, relativer_pfad: str) -> Path:
        """Liefert einen geprüften absoluten Pfad innerhalb des Workspace."""
        return self._sicherer_absoluter_pfad(relativer_pfad)

    def neu_erstelltes_artefakt_entfernen(self, artefakt: GespeichertesArtefakt) -> None:
        """Entfernt ausschließlich ein in diesem Ablauf neu erzeugtes Artefakt."""
        if artefakt.neu_erstellt:
            self._sicherer_absoluter_pfad(artefakt.relativer_pfad).unlink(missing_ok=True)
